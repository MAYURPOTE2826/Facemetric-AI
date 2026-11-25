"""Simulated before/after previews.

Generated locally from the user's own photo - no external image AI - so photos stay
private and every change is subtle and traceable to a recommendation:
landmark-guided warps (brows, jaw, lips) and skin retouching (texture, redness,
under-eyes). Each preview is only offered when the analysis recommends it.
"""
from __future__ import annotations

import base64

import cv2
import numpy as np

from .landmarks import FaceDetection
from .skin import FACE_OVAL, L_BROW, L_EYE, LIPS, NOSTRILS, R_BROW, R_EYE

MAX_SIDE = 720  # output size of the preview crops

# Brow points from the inner end to the tail, per side.
R_BROW_TAIL, L_BROW_TAIL = [46, 53, 52, 65], [276, 283, 282, 295]
R_BROW_MID, L_BROW_MID = [105, 66, 63], [334, 296, 293]
R_JAW_CORNER, L_JAW_CORNER = [58, 172, 136, 132], [288, 397, 365, 361]
UNDER_CHIN = [148, 176, 149, 150, 377, 400, 378, 379, 152]
LOWER_LIP = [84, 17, 314, 181, 405, 91, 321]
UPPER_LIP = [37, 0, 267, 39, 269, 40, 270]


def _warp(img: np.ndarray, src: np.ndarray, dst: np.ndarray, sigma: float) -> np.ndarray:
    """Local displacement field from control points, inverse-mapped.

    Normalised Gaussian weighting: the shift at a pixel is the weighted average of the control-point
    displacements, damped toward zero away from them. Control points with zero displacement (anchors)
    therefore actively HOLD their surroundings still - the eyes, nose and mouth don't get dragged
    along, and nothing far from the edit moves. (A plain sum of Gaussians drags the whole face.)"""
    h, w = img.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    num_x = np.zeros((h, w), np.float32)
    num_y = np.zeros((h, w), np.float32)
    den = np.full((h, w), 0.12, np.float32)  # background weight: pulls the field to zero far from any control point
    disp = (dst - src).astype(np.float32)
    for (cx, cy), (dx, dy) in zip(src.astype(np.float32), disp):
        wgt = np.exp(-((gx - cx) ** 2 + (gy - cy) ** 2) / (2 * sigma ** 2))
        num_x += dx * wgt
        num_y += dy * wgt
        den += wgt
    return cv2.remap(img, gx - num_x / den, gy - num_y / den, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


MAX_SHIFT = 0.028  # of face width - keeps previews in "routine/grooming" territory, not surgery


def _cap(src: np.ndarray, dst: np.ndarray, face_w: float) -> tuple[np.ndarray, np.ndarray]:
    """Limit every control-point displacement to MAX_SHIFT x face width."""
    d = dst - src
    n = np.linalg.norm(d, axis=1, keepdims=True)
    lim = MAX_SHIFT * face_w
    return src, src + d * np.minimum(1.0, lim / np.maximum(n, 1e-6))


def _hull_mask(shape, pts, grow=0) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(pts.astype(np.int32))], 255)
    if grow:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow)))
    return m


def _clear_skin(img: np.ndarray, p: np.ndarray, face_w: float, skin: dict) -> np.ndarray:
    shape = img.shape[:2]
    mask = _hull_mask(shape, p[FACE_OVAL])
    mask = cv2.erode(mask, np.ones((int(face_w * 0.03) | 1,) * 2, np.uint8))
    for part, grow in ((R_EYE, 0.07), (L_EYE, 0.07), (R_BROW, 0.04), (L_BROW, 0.04), (LIPS, 0.03), (NOSTRILS, 0.03)):
        mask[_hull_mask(shape, p[part], int(face_w * grow) | 1) > 0] = 0
    # Leave beard, glasses frames and shadows alone: only smooth pixels close to the skin's own lightness.
    luma = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if (mask > 0).any():
        skin_l = float(np.median(luma[mask > 0]))
        mask[luma < skin_l * 0.62] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(mask.astype(np.float32) / 255, (0, 0), face_w * 0.02)[..., None]

    d = max(5, int(face_w * 0.025)) | 1
    smooth = cv2.bilateralFilter(img, d, 40, d)
    smooth = cv2.bilateralFilter(smooth, d, 30, d)  # second pass: clearly smoother texture, edges (lashes, lips) stay sharp
    # Keep fine detail so skin doesn't look plastic or painted.
    detail = img.astype(np.float32) - cv2.GaussianBlur(img, (0, 0), 1.2).astype(np.float32)
    out = smooth.astype(np.float32) + 0.3 * detail

    lab = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    a = lab[..., 1]
    a_med = float(np.median(a[mask > 0])) if (mask > 0).any() else 128.0
    lab[..., 1] = np.where(a > a_med, a_med + (a - a_med) * 0.35, a)  # calm redness
    # Even out the tone: pull blotchy colour and shading toward the skin's own average (large-scale only)
    sig = max(3.0, face_w * 0.06)
    for ch, amt in ((1, 0.6), (2, 0.6), (0, 0.35)):
        low = cv2.GaussianBlur(lab[..., ch], (0, 0), sig)
        ref_v = float(np.median(low[mask > 0])) if (mask > 0).any() else float(low.mean())
        lab[..., ch] = lab[..., ch] - amt * (low - ref_v)
    concerns = {c["key"]: c["score"] for c in skin.get("concerns", [])}
    ue = np.zeros(shape, np.float32)
    if concerns.get("dark_circles", 100) < 85:
        for eye in (R_EYE, L_EYE):
            e = p[eye]
            cx, cy = e[:, 0].mean(), e[:, 1].max() + face_w * 0.05
            cv2.ellipse(ue, (int(cx), int(cy)), (int(face_w * 0.11), int(face_w * 0.05)), 0, 0, 360, 1.0, -1)
        ue = cv2.GaussianBlur(ue, (0, 0), face_w * 0.02)
        lab[..., 0] += ue * 16
    # Never change overall skin colour: match the mean lightness and yellowness of the face
    # (outside the under-eyes) to the original, so the preview can't read as "lighter skin".
    orig = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = (mask > 0) & (ue < 0.05)
    if ref.any():
        for ch in (0, 2):
            lab[..., ch] += float(orig[..., ch][ref].mean() - lab[..., ch][ref].mean())
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)
    return np.clip(img * (1 - alpha) + out * alpha, 0, 255).astype(np.uint8)


def _brow_lift(p: np.ndarray, eye_w: float):
    src, dst = [], []
    for tail, mid in ((R_BROW_TAIL, R_BROW_MID), (L_BROW_TAIL, L_BROW_MID)):
        for i, idx in enumerate(tail):
            src.append(p[idx]); dst.append(p[idx] - [0, eye_w * (0.16 - 0.03 * i)])
        for idx in mid:
            src.append(p[idx]); dst.append(p[idx] - [0, eye_w * 0.05])
    # anchor the eyes so they don't move
    for idx in (33, 133, 159, 145, 263, 362, 386, 374):
        src.append(p[idx]); dst.append(p[idx])
    return np.array(src), np.array(dst)


def _jaw_sharpen(p: np.ndarray, face_w: float):
    src, dst = [], []
    for corner, sign in ((R_JAW_CORNER, -1), (L_JAW_CORNER, 1)):
        for idx in corner:
            src.append(p[idx]); dst.append(p[idx] + [sign * face_w * 0.022, -face_w * 0.012])
    for idx in UNDER_CHIN:
        src.append(p[idx]); dst.append(p[idx] - [0, face_w * 0.012])
    for idx in (1, 2, 61, 291, 13, 14):  # keep nose and mouth fixed
        src.append(p[idx]); dst.append(p[idx])
    return np.array(src), np.array(dst)


def _lip_balance(p: np.ndarray, direction: str):
    lip_h = float(np.linalg.norm(p[17] - p[0]))
    src, dst = [], []
    pts, shift = (LOWER_LIP, [0, lip_h * 0.12]) if direction == "low" else (UPPER_LIP, [0, -lip_h * 0.10])
    for idx in pts:
        src.append(p[idx]); dst.append(p[idx] + shift)
    for idx in (61, 291, 2, 152):
        src.append(p[idx]); dst.append(p[idx])
    return np.array(src), np.array(dst)


def _encode(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 93])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def generate(bgr: np.ndarray, face: FaceDetection, metrics: list[dict], skin: dict, glasses: bool = False) -> dict | None:
    pts = face.points[:, :2]
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    mw, mh = (x1 - x0) * 0.25, (y1 - y0) * 0.22
    x0, y0 = int(max(0, x0 - mw)), int(max(0, y0 - mh))
    x1, y1 = int(min(bgr.shape[1], x1 + mw)), int(min(bgr.shape[0], y1 + mh))
    crop = bgr[y0:y1, x0:x1]
    s = MAX_SIDE / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    p = (pts - [x0, y0]) * s
    face_w = float(np.linalg.norm(p[454] - p[234]))
    eye_w = float(np.linalg.norm(p[33] - p[133]))
    by_key = {m["key"]: m for m in metrics}

    def needs(key, *directions):
        m = by_key.get(key)
        return m is not None and m["status"] != "ideal" and m["direction"] in directions

    items = []
    warps = []
    skin_flag = skin.get("available") and any(c["score"] < 80 for c in skin.get("concerns", []))
    if skin_flag:
        items.append(("skin", "Clearer skin", "Smoother texture, calmer redness and brighter under-eyes - what a consistent skincare routine may help with.",
                      _clear_skin(crop, p, face_w, skin)))
    # Glasses can't be reshaped believably: a warp near them bends the frames. Skin-only in that case.
    geometry_ok = not glasses
    if geometry_ok and (needs("canthal_tilt", "low") or needs("nasofrontal", "high")):
        src, dst = _cap(*_brow_lift(p, eye_w), face_w)
        warps.append((src, dst, eye_w * 0.45))
        items.append(("brows", "Lifted brow tails", "Brow shaping or lamination that lifts the tail opens the eye area.", _warp(crop, src, dst, eye_w * 0.45)))
    if (needs("jaw_zygo", "low") or needs("gonial_angle", "high") or needs("cervicomental", "high")):
        src, dst = _cap(*_jaw_sharpen(p, face_w), face_w)
        warps.append((src, dst, face_w * 0.09))
        items.append(("jaw", "Sharper jawline", "Lower body-fat, beard shaping or contouring that defines the jaw corners and under-chin.",
                      _warp(crop, src, dst, face_w * 0.09)))
    for direction in ("low", "high"):
        if needs("lip_ratio", direction):
            src, dst = _cap(*_lip_balance(p, direction), face_w)
            warps.append((src, dst, face_w * 0.05))
            items.append(("lips", "Balanced lips", "Lip liner and colour placement that balances upper and lower lip.", _warp(crop, src, dst, face_w * 0.05)))

    if not items:
        return None
    if len(items) > 1:
        combined = _clear_skin(crop, p, face_w, skin) if skin_flag else crop
        for src, dst, sigma in warps:
            combined = _warp(combined, src, dst, sigma)
        items.append(("all", "Your full plan", "All of the above together - an illustration of the direction, not a prediction of results.", combined))

    return {
        "before": _encode(crop),
        "items": [{"key": k, "title": t, "description": d, "image": _encode(img)} for k, t, d, img in items],
        # Accurate description of the method: classical image editing, NOT a generative/AI image model.
        "method": "classical_image_editing",
        "note": "Simulated preview made with image editing (smoothing, tone evening and small landmark-guided warps) - "
                "it is not an AI image model and not a guaranteed result. It shows the direction a routine or grooming "
                "could take your photo and is separate from your measurements. Skin colour is kept as it is.",
    }


# Recommendation types that image editing cannot show honestly (a wrong simulation would mislead more than no picture).
NOT_SIMULABLE = "Nose contouring, beard and moustache shaping, hairstyle changes, sleep and hydration cannot be shown honestly with image editing, so no picture is made for them."


def status(metrics: list[dict], skin: dict, glasses: bool, offered_keys: set[str], validation: dict | None = None) -> list[dict]:
    """For every kind of before/after preview: was it offered, and if not, WHY (so the report never silently omits it)."""
    by = {m["key"]: m for m in metrics}
    withheld_skin = [x for x in (validation or {}).get("suppressed", []) if str(x.get("item", "")).startswith("skin:")]

    def out_of_range(key, *dirs):
        m = by.get(key)
        return m is not None and m["status"] != "ideal" and m["direction"] in dirs

    def present(*keys):
        return any(k in by for k in keys)
    rows = []
    # skin
    if "skin" in offered_keys:
        rows.append({"preview": "skin", "offered": True, "reason": ""})
    elif withheld_skin and not any(c["score"] < 80 for c in skin.get("concerns", [])):
        why = "; ".join(sorted({x["reason"].rstrip(".") for x in withheld_skin})[:2])
        rows.append({"preview": "skin", "offered": False, "reason": f"Most skin readings were withheld, so a skin preview would be a guess ({why}). Retake the photo to get one."})
    elif not skin.get("available"):
        rows.append({"preview": "skin", "offered": False, "reason": "Skin could not be analysed from this photo."})
    else:
        rows.append({"preview": "skin", "offered": False, "reason": "Your skin readings are good, so there is nothing to simulate."})
    # brows / jaw / lips
    for key, label, metric_keys, dirs_fn in (
        ("brows", "brow lift", ("canthal_tilt", "nasofrontal"), lambda: out_of_range("canthal_tilt", "low") or out_of_range("nasofrontal", "high")),
        ("jaw", "jaw definition", ("jaw_zygo", "gonial_angle", "cervicomental"), lambda: out_of_range("jaw_zygo", "low") or out_of_range("gonial_angle", "high") or out_of_range("cervicomental", "high")),
        ("lips", "lip balance", ("lip_ratio",), lambda: out_of_range("lip_ratio", "low") or out_of_range("lip_ratio", "high")),
    ):
        if key in offered_keys:
            rows.append({"preview": key, "offered": True, "reason": ""})
        elif key == "brows" and glasses and dirs_fn():
            rows.append({"preview": key, "offered": False, "reason": "Glasses are in the photo; reshaping near the frames would distort them, so the brow preview is skipped."})
        elif not present(*metric_keys):
            rows.append({"preview": key, "offered": False, "reason": f"The measurements needed for the {label} preview were not available from this photo."})
        else:
            rows.append({"preview": key, "offered": False, "reason": f"Your {label} measurements are within the reference range, so there is nothing to simulate."})
    rows.append({"preview": "other", "offered": False, "reason": NOT_SIMULABLE})
    return rows
