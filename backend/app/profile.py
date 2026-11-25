"""Side-profile analysis from the face silhouette.

MediaPipe's face mesh doesn't work on true 90° profiles, so instead we:
1. segment the person (MediaPipe DeepLab v3) to get a coarse outline,
2. trace the front edge of the silhouette from the top of the head to the neck and
   snap it to the strongest nearby image edge (works even for pale skin on a white wall),
3. locate soft-tissue landmarks as turning points along that edge,
4. measure classic profile angles. Angles between landmark lines are
   rotation-invariant, so slight head tilt doesn't change them.
"""
from __future__ import annotations

import base64
import math
from dataclasses import asdict
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from . import landmarks
from .metrics import Metric, _score

MODELS = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODELS / "deeplab_v3.tflite"
MODNET_PATH = MODELS / "modnet.onnx"
PERSON = 15  # PASCAL VOC class index
WORK_SIZE = 900  # max image side for profile analysis

_segmenter: vision.ImageSegmenter | None = None
_modnet = None


class ProfileError(Exception):
    pass


def _get_segmenter() -> vision.ImageSegmenter:
    global _segmenter
    if _segmenter is None:
        options = vision.ImageSegmenterOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            output_category_mask=True,
        )
        _segmenter = vision.ImageSegmenter.create_from_options(options)
    return _segmenter


def _largest_blob(mask: np.ndarray) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        raise ProfileError("Couldn't find a person in the photo. Use a plain, contrasting background.")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(labels == biggest, 255, 0).astype(np.uint8)


def _deeplab_mask(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    res = _get_segmenter().segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    cat = np.array(res.category_mask.numpy_view()).squeeze()
    if cat.shape[:2] != (h, w):
        cat = cv2.resize(cat, (w, h), interpolation=cv2.INTER_NEAREST)
    return (cat == PERSON).astype(np.uint8) * 255


def _modnet_mask(bgr: np.ndarray, ref: int = 512) -> np.ndarray:
    """Portrait matting (MODNet) - much better hair/skin edges on modern photos."""
    global _modnet
    if _modnet is None:
        import onnxruntime as ort
        _modnet = ort.InferenceSession(str(MODNET_PATH), providers=["CPUExecutionProvider"])
    h, w = bgr.shape[:2]
    sc = ref / max(h, w)
    nh, nw = max(32, int(h * sc) // 32 * 32), max(32, int(w * sc) // 32 * 32)
    x = cv2.resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), (nw, nh), interpolation=cv2.INTER_AREA).astype(np.float32)
    x = ((x / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    matte = _modnet.run(None, {_modnet.get_inputs()[0].name: x})[0][0, 0]
    matte = cv2.resize(matte, (w, h), interpolation=cv2.INTER_LINEAR)
    return (matte >= 0.5).astype(np.uint8) * 255


def _segment(bgr: np.ndarray) -> list[np.ndarray]:
    """Candidate person masks (uint8 0/255), best-guess first."""
    masks = []
    for fn in (_modnet_mask, _deeplab_mask):
        try:
            m = _largest_blob(fn(bgr))
        except ProfileError:
            continue
        if m.mean() >= 255 * 0.03:
            masks.append(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)))
    if not masks:
        raise ProfileError("Couldn't find a person in the photo. Move closer and use a plain background.")
    return masks


def _smooth(a: np.ndarray, k: int) -> np.ndarray:
    k = max(3, k) | 1
    return cv2.GaussianBlur(a.reshape(-1, 1).astype(np.float64), (1, k), 0).ravel()


def _resample(pts: np.ndarray) -> np.ndarray:
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    s = np.arange(0, seg[-1], 1.0)
    return np.stack([np.interp(s, seg, pts[:, 0]), np.interp(s, seg, pts[:, 1])], axis=1)


def _front_chain(person: np.ndarray) -> np.ndarray:
    """Ordered (N,2) points along the front edge of the silhouette (face pointing +x),
    from the top of the head down to the bottom of the mask, ~1px spacing."""
    contours, _ = cv2.findContours(person, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    n = len(c)
    top_ids = np.where(c[:, 1] <= c[:, 1].min() + 1)[0]
    start = int(top_ids[np.argmax(c[top_ids, 0])])
    # Walk in whichever direction heads to the front (+x) of the head.
    look = max(10, n // 6)
    fwd = c[(start + np.arange(look)) % n, 0].mean()
    back = c[(start - np.arange(look)) % n, 0].mean()
    step = 1 if fwd >= back else -1
    bottom = c[:, 1].max() - 2
    pts, i = [], start
    for _ in range(n):
        pts.append(c[i])
        if c[i, 1] >= bottom:
            break
        i = (i + step) % n
    out = _resample(np.array(pts))
    k = int(len(out) * 0.006)
    return np.stack([_smooth(out[:, 0], k), _smooth(out[:, 1], k)], axis=1)


def _snap_to_edges(chain: np.ndarray, bgr: np.ndarray, person: np.ndarray) -> np.ndarray:
    """Move each outline point along its normal to the strongest image edge nearby."""
    lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (0, 0), 1.2), cv2.COLOR_BGR2LAB).astype(np.float32)
    mag = np.zeros(bgr.shape[:2], np.float32)
    for ch in cv2.split(lab):
        gx, gy = cv2.Sobel(ch, cv2.CV_32F, 1, 0), cv2.Sobel(ch, cv2.CV_32F, 0, 1)
        mag = np.maximum(mag, cv2.magnitude(gx, gy))

    tang = np.gradient(chain, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    normal = np.stack([tang[:, 1], -tang[:, 0]], axis=1)
    # Orient normals outwards (away from the person mask).
    probe = (chain + 4 * normal).round().astype(int)
    probe[:, 0] = probe[:, 0].clip(0, person.shape[1] - 1)
    probe[:, 1] = probe[:, 1].clip(0, person.shape[0] - 1)
    if (person[probe[:, 1], probe[:, 0]] > 0).mean() > 0.5:
        normal = -normal

    band = max(6, int(0.018 * max(bgr.shape[:2])))
    offsets = np.arange(-band, band + 1, dtype=np.float32)
    samples = chain[:, None, :] + offsets[None, :, None] * normal[:, None, :]
    mx = samples[..., 0].astype(np.float32)
    my = samples[..., 1].astype(np.float32)
    resp = cv2.remap(mag, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    resp = resp * (1 - 0.3 * np.abs(offsets)[None, :] / band)  # prefer staying close
    best = offsets[np.argmax(resp, axis=1)]
    best = cv2.medianBlur(best.reshape(-1, 1).astype(np.float32), 5).ravel()
    best = _smooth(best, 9)
    snapped = chain + best[:, None] * normal
    return _resample(snapped)


def _extrema(x: np.ndarray, start: int, end: int, prominence: float) -> list[tuple[int, str]]:
    """Alternating local max/min of x in [start, end) with a minimum prominence."""
    out: list[tuple[int, str]] = []
    last_i, last_v, mode = start, x[start], None
    for i in range(start + 1, end):
        v = x[i]
        if mode in (None, "max") and v > last_v:
            last_i, last_v, mode = i, v, "max"
        elif mode in (None, "min") and v < last_v:
            last_i, last_v, mode = i, v, "min"
        elif mode == "max" and last_v - v > prominence:
            out.append((last_i, "max"))
            last_i, last_v, mode = i, v, "min"
        elif mode == "min" and v - last_v > prominence:
            out.append((last_i, "min"))
            last_i, last_v, mode = i, v, "max"
    return out


def _farthest_from_line(chain: np.ndarray, a: int, b: int, sign: int) -> int:
    """Index between a and b farthest from line chain[a]-chain[b] on the given side."""
    p, q = chain[a], chain[b]
    d = q - p
    seg = chain[a:b + 1]
    cross = d[0] * (seg[:, 1] - p[1]) - d[1] * (seg[:, 0] - p[0])
    return a + int(np.argmax(sign * cross))


def _angle(a, b, c) -> float:
    """Angle at b (degrees) between b->a and b->c."""
    v1, v2 = np.asarray(a) - b, np.asarray(c) - b
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    return math.degrees(math.acos(float(np.clip(cos, -1, 1))))


def _line_angle(p1, p2, q1, q2) -> float:
    a = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    b = math.atan2(q2[1] - q1[1], q2[0] - q1[0])
    d = abs(math.degrees(a - b)) % 180
    return min(d, 180 - d)


def _signed_dist(pt, a, b) -> float:
    """Distance of pt from line a-b; positive when pt is in front (+x side) of the line."""
    a, b, pt = map(np.asarray, (a, b, pt))
    d = b - a
    cross = d[0] * (pt[1] - a[1]) - d[1] * (pt[0] - a[0])
    return -cross / np.linalg.norm(d)


def _ref(sex: str) -> dict[str, tuple[float, float]]:
    male = sex.lower().startswith("m")
    return {
        # North-Indian / Kerala soft-tissue norms where published (photo-based studies).
        "nasofrontal": (121.0 if male else 130.0, 9.0),
        "nasolabial": (97.0 if male else 101.0, 8.0),
        "nasofacial": (35.0, 4.0),
        "nasomental": (127.0, 5.0),
        "convexity": (166.5, 4.5),
        "e_line_upper": (-4.0, 2.5),
        "e_line_lower": (-1.2 if male else 0.1, 2.7),
        "mentocervical": (87.0, 7.0),
        "cervicomental": (112.0, 10.0),
        # Wen et al. 2015 meta-analysis: nasal tip ~78-81°, total facial convexity ~141-147° (Asian/Caucasian);
        # mentolabial ~130° (Naini 2017 ideal range 120-140°); submental length 50-75 mm (Naini 2020).
        "nasal_tip": (80.0, 7.0),
        "total_convexity": (143.0, 5.0),
        "mentolabial": (128.0, 10.0),
        "submental_length": (60.0, 10.0),
    }


META = {
    "nasofrontal": ("Nasofrontal angle", "profile", "°", "Angle at the bridge of the nose between forehead and nasal dorsum. 115-135° is typical."),
    "nasolabial": ("Nasolabial angle", "profile", "°", "Angle between the underside of the nose and the upper lip. ~90-105° (men), 95-115° (women)."),
    "nasofacial": ("Nasofacial angle", "profile", "°", "How far the nose projects from the facial plane (forehead to chin). Ideal 30-40°."),
    "nasomental": ("Nasomental angle", "profile", "°", "Angle at the nose tip between the bridge and the chin. Ideal 120-132°."),
    "convexity": ("Facial convexity", "profile", "°", "Angle at the base of the nose between forehead and chin. ~162-171° is typical for Indian faces; lower means a more convex profile or a recessed chin."),
    "e_line_upper": ("Upper lip to E-line", "profile", "mm", "Distance of the upper lip from the line between nose tip and chin. Negative = behind the line. Ideal about -4 mm."),
    "e_line_lower": ("Lower lip to E-line", "profile", "mm", "Distance of the lower lip from the nose-chin line. About -1 mm (men) to 0 mm (women) is typical for Indian faces."),
    "mentocervical": ("Mentocervical angle", "profile", "°", "Angle between the facial plane and the under-chin line. 80-95° is typical."),
    "cervicomental": ("Jaw-neck angle", "profile", "°", "Angle between the under-chin line and the front of the neck. Lower (105-120°) reads as a sharper, more defined jawline."),
    "nasal_tip": ("Nasal tip angle", "profile", "°", "Angle at the nose tip between the bridge and the underside of the nose (columella). About 75-85° is typical."),
    "total_convexity": ("Total facial convexity", "profile", "°", "Angle at the nose tip between the forehead and the chin, nose included. About 138-148° is typical; lower means the nose and chin stand further forward."),
    "mentolabial": ("Lip-chin angle (mentolabial)", "profile", "°", "Angle of the fold between the lower lip and the chin. About 120-140° is typical; a deep fold reads as a sharper chin."),
    "submental_length": ("Under-chin length", "profile", "mm", "Distance from the bottom of the chin to where the under-chin meets the neck. 50-75 mm reads as a defined jaw-neck line (Naini 2020)."),
}


def _find_landmarks(chain: np.ndarray, head_top: int, bottom: int) -> tuple[dict, np.ndarray, np.ndarray, float, bool]:
    """Locate profile landmarks on a front-edge chain (face pointing +x).
    Returns (points, columella_pt, neck_pt, nose_prominence, neck_ok)."""
    x, y = chain[:, 0], chain[:, 1]

    def idx_where(cond):
        ids = np.where(cond)[0]
        if len(ids) == 0:
            raise ProfileError("Couldn't trace your profile clearly. Use a plain background and keep hair off the face.")
        return ids

    # Nose tip = most forward point in the upper part of the silhouette.
    upper = idx_where(y < head_top + 0.6 * (bottom - head_top))
    prn = int(upper[np.argmax(x[upper])])
    S = y[prn] - head_top  # top of head to nose tip; used as the length scale
    if S < 80:
        raise ProfileError("Face is too small in the photo. Move closer so your head fills most of the frame.")
    prom = 0.006 * S

    above = idx_where((np.arange(len(x)) < prn) & (y > y[prn] - 0.5 * S))
    n_ = int(above[np.argmin(x[above])])
    above_n = idx_where((np.arange(len(x)) < n_) & (y > y[n_] - 0.25 * S))
    g = int(above_n[np.argmax(x[above_n])])

    chin_limit = int(idx_where(y <= y[prn] + 0.85 * S)[-1])
    ext = _extrema(x, prn, chin_limit, prom)
    mins = [i for i, k in ext if k == "min"]
    maxs = [i for i, k in ext if k == "max"]
    if not mins or len(maxs) < 2:
        raise ProfileError("Couldn't find lips and chin in the outline. Keep a neutral expression with lips relaxed.")
    sn = mins[0]
    neck_end = int(np.where(y <= y[prn] + 1.4 * S)[0][-1])
    # Chin (pogonion) = first bump after the lips that's followed by a clear step back
    # under the jaw. Falls back to the last bump (e.g. dark neck on dark background).
    after_lips = [i for i in maxs if i > sn][1:] or maxs[-1:]
    pog = after_lips[-1]
    for i in after_lips:
        below = np.arange(i, neck_end + 1)
        below = below[y[below] <= y[i] + 0.35 * S]
        if len(below) and x[i] - x[below].min() > 0.1 * S:
            pog = i
            break
    lip_maxs = [i for i in maxs if sn < i < pog] or [maxs[0]]
    ls, li = lip_maxs[0], lip_maxs[-1]
    # Soft-tissue B point: deepest point of the fold between lower lip and chin.
    b_pt = _farthest_from_line(chain, li, pog, sign=-1) if pog - li > 4 else None

    if neck_end - pog < 10 or y[neck_end] - y[pog] < 0.3 * S:
        raise ProfileError("Neck is not visible. Include your chin and neck in the photo.")
    c_ = _farthest_from_line(chain, pog, neck_end, sign=-1)  # concave point under the chin
    me = _farthest_from_line(chain, pog, c_, sign=1) if c_ - pog > 4 else pog
    neck_pt = chain[min(neck_end, c_ + int(0.3 * S))]
    cm = chain[max(prn, sn - int(0.08 * S))]  # along the columella, back toward the nose tip
    # Only trust neck angles when the chin-neck corner is clearly defined.
    corner_depth = abs(_signed_dist(chain[c_], chain[pog], chain[neck_end])) / S
    neck_ok = corner_depth > 0.05 and x[pog] - x[c_] > 0.1 * S

    P = {k: chain[i] for k, i in dict(glabella=g, nasion=n_, pronasale=prn, subnasale=sn, labrale_superius=ls,
                                         labrale_inferius=li, pogonion=pog, menton=me, cervical=c_).items()}
    order = ["glabella", "nasion", "pronasale", "subnasale", "labrale_superius", "pogonion", "menton", "cervical"]
    if any(P[a][1] > P[b][1] + 2 for a, b in zip(order, order[1:])):
        raise ProfileError("Profile landmarks look inconsistent. Retake the photo exactly side-on with a plain background.")
    if b_pt is not None and li < b_pt < pog:
        P["b_point"] = chain[b_pt]
    nose_prominence = (x[prn] - max(x[n_], x[sn])) / S
    return P, cm, neck_pt, float(nose_prominence), neck_ok


def _plausible(P: dict, cm: np.ndarray) -> bool:
    """Reject traces whose geometry is outside the range of real human profiles."""
    checks = [
        (_angle(P["glabella"], P["nasion"], P["pronasale"]), 100, 165),
        (_angle(cm, P["subnasale"], P["labrale_superius"]), 60, 140),
        (_angle(P["nasion"], P["pronasale"], P["pogonion"]), 105, 150),
        (_angle(P["glabella"], P["subnasale"], P["pogonion"]), 145, 195),
        (_line_angle(P["glabella"], P["pogonion"], P["nasion"], P["pronasale"]), 20, 50),
    ]
    return all(lo <= v <= hi for v, lo, hi in checks)


def analyze(bgr: np.ndarray, sex: str = "unspecified") -> dict:
    scale = WORK_SIZE / max(bgr.shape[:2])
    if scale < 1:
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    # The face mesh only works on faces that are mostly frontal, so a detection with
    # small yaw means the user hasn't turned side-on.
    face = landmarks.detect(bgr)
    if face is not None and abs(face.pose["yaw"]) < 40:
        raise ProfileError("This looks like a front-facing photo. Turn fully side-on (90°) so only one eye is visible.")
    # Try each candidate mask in both facing directions; the real face side has a
    # clear nose peak, while the back of the head or a bad mask does not.
    best, error = None, None
    for person in _segment(bgr):
        rows = np.where(person.any(axis=1))[0]
        head_top, bottom = int(rows.min()), int(rows.max())
        for flipped in (False, True):
            im, mask = (cv2.flip(bgr, 1), cv2.flip(person, 1)) if flipped else (bgr, person)
            try:
                chain = _snap_to_edges(_front_chain(mask), im, mask)
                P, cm, neck_pt, prominence, neck_ok = _find_landmarks(chain, head_top, bottom)
            except ProfileError as e:
                error = e
                continue
            if not _plausible(P, cm):
                error = ProfileError("Couldn't trace your profile clearly. Turn fully side-on, use a plain "
                                     "background that contrasts with your skin, and keep hair off the face.")
                continue
            if best is None or prominence > best[0]:
                best = (prominence, flipped, im, chain, P, cm, neck_pt, neck_ok)
    if best is None:
        raise error
    _, flipped, bgr, chain, P, cm, neck_pt, neck_ok = best

    # Nasion-to-subnasale (midface height) averages ~55 mm in men, ~51 mm in women.
    midface_px = float(np.linalg.norm(P["subnasale"] - P["nasion"]))
    px_per_mm = midface_px / (55.0 if sex.lower().startswith("m") else 51.0)

    raw = {
        "nasofrontal": _angle(P["glabella"], P["nasion"], P["pronasale"]),
        "nasolabial": _angle(cm, P["subnasale"], P["labrale_superius"]),
        "nasofacial": _line_angle(P["glabella"], P["pogonion"], P["nasion"], P["pronasale"]),
        "nasomental": _angle(P["nasion"], P["pronasale"], P["pogonion"]),
        "convexity": _angle(P["glabella"], P["subnasale"], P["pogonion"]),
        "e_line_upper": _signed_dist(P["labrale_superius"], P["pronasale"], P["pogonion"]) / px_per_mm,
    }
    if P["labrale_inferius"][1] - P["labrale_superius"][1] > 2:  # both lips found separately
        raw["e_line_lower"] = _signed_dist(P["labrale_inferius"], P["pronasale"], P["pogonion"]) / px_per_mm
    # Between the dorsum line (nasion -> tip) and the columella tangent (subnasale -> columella).
    raw["nasal_tip"] = _angle(P["pronasale"] - P["nasion"], np.zeros(2), cm - P["subnasale"])
    raw["total_convexity"] = _angle(P["glabella"], P["pronasale"], P["pogonion"])
    if "b_point" in P and P["labrale_inferius"][1] - P["labrale_superius"][1] > 2:
        raw["mentolabial"] = _angle(P["labrale_inferius"], P["b_point"], P["pogonion"])
    if neck_ok:
        raw["mentocervical"] = _line_angle(P["glabella"], P["pogonion"], P["menton"], P["cervical"])
        raw["cervicomental"] = _angle(P["menton"], P["cervical"], neck_pt)
        raw["submental_length"] = float(np.linalg.norm(P["cervical"] - P["menton"])) / px_per_mm
    ref = _ref(sex)
    metrics = []
    for key, value in raw.items():
        ideal, tol = ref[key]
        score, status, direction = _score(value, ideal, tol)
        label, category, unit, desc = META[key]
        metrics.append(asdict(Metric(key, label, category, round(value, 1), unit, ideal, tol, score, status, direction, desc)))

    notes = []
    if not neck_ok:
        notes.append("Chin-neck angle couldn't be measured clearly. Keep your chin level and make sure your neck "
                     "contrasts with the background (no high collars or scarves).")
        P = {k: v for k, v in P.items() if k not in ("menton", "cervical")}
    annotated = _annotate(bgr, chain, P, cm, neck_pt if neck_ok else None, flipped, raw)
    return {
        "metrics": metrics,
        "score": round(sum(m["score"] for m in metrics) / len(metrics), 1),
        "landmarks": {k: [round(float(v[0]), 1), round(float(v[1]), 1)] for k, v in P.items()},
        "facing": "left" if flipped else "right",
        "notes": notes,
        "annotated_image": annotated,
    }


def _arc(img, centre, a, b, r, colour, t):
    """Draw the arc of the angle a-centre-b (the smaller one) with radius r."""
    ang = lambda p: np.degrees(np.arctan2(p[1] - centre[1], p[0] - centre[0]))  # noqa: E731
    s, e = ang(a), ang(b)
    if (e - s) % 360 > 180:
        s, e = e, s
    if e < s:
        e += 360
    cv2.ellipse(img, (int(centre[0]), int(centre[1])), (int(r), int(r)), 0, s, e, colour, t, cv2.LINE_AA)
    mid = np.radians((s + e) / 2)
    return centre[0] + 1.9 * r * np.cos(mid), centre[1] + 1.9 * r * np.sin(mid)


def _annotate(bgr, chain, P, cm, neck_pt, flipped, raw=None) -> str:
    img = bgr.copy()
    t = max(2, int(img.shape[1] / 500))
    ip = lambda p: (int(p[0]), int(p[1]))  # noqa: E731
    gold, cyan, pink, white = (80, 190, 255), (230, 200, 60), (180, 105, 255), (240, 240, 240)

    cv2.polylines(img, [chain.astype(np.int32).reshape(-1, 1, 2)], False, white, max(1, t // 2), cv2.LINE_AA)
    cv2.line(img, ip(P["pronasale"]), ip(P["pogonion"]), pink, t, cv2.LINE_AA)  # E-line
    cv2.line(img, ip(P["glabella"]), ip(P["pogonion"]), cyan, t, cv2.LINE_AA)  # facial plane
    cv2.line(img, ip(P["glabella"]), ip(P["subnasale"]), gold, t, cv2.LINE_AA)
    cv2.line(img, ip(P["subnasale"]), ip(P["pogonion"]), gold, t, cv2.LINE_AA)
    cv2.line(img, ip(P["nasion"]), ip(P["pronasale"]), cyan, t, cv2.LINE_AA)
    cv2.line(img, ip(P["subnasale"]), ip(cm), gold, t, cv2.LINE_AA)
    cv2.line(img, ip(P["subnasale"]), ip(P["labrale_superius"]), gold, t, cv2.LINE_AA)
    if neck_pt is not None:
        cv2.line(img, ip(P["menton"]), ip(P["cervical"]), cyan, t, cv2.LINE_AA)
        cv2.line(img, ip(P["cervical"]), ip(neck_pt), cyan, t, cv2.LINE_AA)
    for p in P.values():
        cv2.circle(img, ip(p), t * 2, pink, -1, cv2.LINE_AA)

    # Angle arcs (Qoves-style); labels are written after the crop is flipped so text isn't mirrored.
    raw = raw or {}
    hgt0 = float(np.ptp(np.array(list(P.values()))[:, 1]))
    r = 0.045 * hgt0
    arcs = [("nasofrontal", P["nasion"], P["glabella"], P["pronasale"]),
            ("nasolabial", P["subnasale"], cm, P["labrale_superius"]),
            ("nasal_tip", P["pronasale"], P["nasion"], cm)]
    if "b_point" in P:
        arcs.append(("mentolabial", P["b_point"], P["labrale_inferius"], P["pogonion"]))
    if neck_pt is not None:
        arcs.append(("cervicomental", P["cervical"], P["menton"], neck_pt))
    labels = []
    for key, c, a, b in arcs:
        if key in raw:
            labels.append((_arc(img, c, a, b, r, white, max(1, t // 2 + 1)), f"{META[key][0].split(' (')[0].replace(' angle', '')} {raw[key]:.0f}"))

    pts = np.array(list(P.values()))
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    hgt = y1 - y0
    x0, x1 = int(max(0, x0 - 0.9 * hgt)), int(min(img.shape[1], x1 + 0.2 * hgt))
    y0, y1 = int(max(0, y0 - 0.35 * hgt)), int(min(img.shape[0], y1 + 0.3 * hgt))
    crop = img[y0:y1, x0:x1]
    if flipped:
        crop = cv2.flip(crop, 1)
    scale = min(1.0, 1000 / max(crop.shape[:2]))
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    fs = max(0.45, crop.shape[1] / 1400)
    for (lx, ly), text in labels:
        cx = (lx - x0) * scale
        if flipped:
            cx = crop.shape[1] - cx
        cy = (ly - y0) * scale
        (tw, th), _ = cv2.getTextSize(text + "°", cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
        org = (int(min(max(cx - tw / 2, 2), crop.shape[1] - tw - 2)), int(cy + th / 2))
        cv2.putText(crop, text + "°", org, cv2.FONT_HERSHEY_SIMPLEX, fs, (20, 20, 20), 3, cv2.LINE_AA)
        cv2.putText(crop, text + "°", org, cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""
