"""Zone-based skin analysis from the front photo.

Classical computer vision on a size-normalised face crop, using MediaPipe landmarks
to define skin zones and exclude eyes, brows, lips, nostrils and facial hair:

- wrinkles:      Hessian ridge (valley) detector on forehead, crow's feet, under-eye, smile lines
- blemishes:     small blobs redder than the surrounding skin (LAB a* residual)
- dark spots:    small blobs darker than the surrounding skin that aren't red
- dark circles:  under-eye brightness vs cheek brightness
- redness:       share of skin noticeably redder than the face's own baseline
- texture:       fine high-frequency energy on the cheeks (pores, roughness)
- shine:         specular highlights in the T-zone
- uneven tone:   colour (chromaticity) differences between forehead, nose, cheeks and chin -
                 tanning. Chromaticity ignores brightness, so shadows and overhead light
                 don't read as uneven tone.
- pigmentation:  larger darker patches (melasma-type) on cheeks, forehead, upper lip
- acne marks:    dark spots with a reddish-brown cast (post-inflammatory hyperpigmentation)

Thresholds scale with the person's own skin brightness so melanin-rich skin isn't
over-flagged. Skin tone (ITA° group) is reported only to make advice safer - e.g.
melanin-rich skin marks more easily, so harsh peels and scrubs are avoided. The
product never scores or recommends "fairness".

Thresholds are starting values; calibrate them on labelled photos, or swap any
detector for a trained model, without changing the output format.
"""
from __future__ import annotations

import base64

import math

import cv2
import numpy as np

from .landmarks import FaceDetection

FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
R_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
L_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
R_BROW = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
L_BROW = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185]
NOSTRILS = [64, 98, 97, 2, 326, 327, 294, 278, 48]

FACE_W = 400  # cheek-to-cheek width of the normalised crop, px
DARK_HAIR_REL = 0.62  # pixels darker than this x the median cheek lightness, in a big region below the nose = facial hair

CONCERNS = {
    "wrinkles": "Fine lines & wrinkles",
    "blemishes": "Blemishes & breakouts",
    "dark_spots": "Dark spots & pigmentation",
    "dark_circles": "Dark circles",
    "redness": "Redness",
    "texture": "Texture & pores",
    "shine": "Shine / oiliness",
    "uneven_tone": "Uneven tone & tan",
    "pigmentation": "Pigmentation patches",
    "acne_marks": "Acne marks",
}

# Chardon ITA° skin-tone groups (Del Bino et al.). Neutral labels, used only for safety advice.
TONE_GROUPS = [
    (55, "very light", "Burns easily - daily SPF is essential."),
    (41, "light", "Burns before tanning - daily SPF is essential."),
    (28, "intermediate", "Tans easily and can develop marks after breakouts - SPF and gentle actives work best."),
    (10, "tan", "Prone to dark marks after acne or irritation (PIH) - avoid harsh scrubs and strong peels without a dermatologist."),
    (-30, "brown", "Melanin-rich: prone to PIH and melasma - prioritise SPF, gentle actives, and avoid bleaching or steroid creams."),
    (-999, "deep", "Melanin-rich: prone to PIH - prioritise SPF, gentle actives, and avoid bleaching or steroid creams."),
]


def _ita(L: np.ndarray, B: np.ndarray, mask: np.ndarray) -> float | None:
    """Individual Typology Angle (degrees) from OpenCV LAB channels over a mask."""
    if mask.sum() < 30:
        return None
    l_star = float(np.median(L[mask])) * 100 / 255
    b_star = float(np.median(B[mask])) - 128
    return float(np.degrees(np.arctan2(l_star - 50, b_star)))


def _poly_mask(shape, pts, dilate=0):
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [cv2.convexHull(pts.astype(np.int32))], 255)
    if dilate:
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate, dilate)))
    return m


def _rect_mask(shape, x0, y0, x1, y1):
    m = np.zeros(shape, np.uint8)
    cv2.rectangle(m, (int(x0), int(y0)), (int(x1), int(y1)), 255, -1)
    return m


def _normalise(bgr: np.ndarray, pts: np.ndarray, seg: np.ndarray | None = None):
    """Crop around the face and scale so the face is FACE_W px wide. The optional
    segmentation mask gets the same crop/scale (nearest neighbour)."""
    s = FACE_W / max(1.0, float(np.linalg.norm(pts[454] - pts[234])))
    x0, y0 = pts.min(axis=0) - 0.08 * FACE_W / s
    x1, y1 = pts.max(axis=0) + 0.08 * FACE_W / s
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(bgr.shape[1], int(x1)), min(bgr.shape[0], int(y1))
    crop = cv2.resize(bgr[y0:y1, x0:x1], None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    seg_crop = None
    if seg is not None:
        seg_crop = cv2.resize(seg[y0:y1, x0:x1], (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST)
    return crop, (pts - [x0, y0]) * s, seg_crop


def sclera_bgr(img: np.ndarray, p: np.ndarray) -> np.ndarray | None:
    """Mean B, G, R of the whites of the eyes (iris and dark/shadowed pixels excluded), or
    None when too little clean sclera is visible."""
    shape = img.shape[:2]
    eyes = (_poly_mask(shape, p[R_EYE]) > 0) | (_poly_mask(shape, p[L_EYE]) > 0)
    for c, edge in ((468, 469), (473, 474)):
        r = float(np.linalg.norm(p[c] - p[edge])) * 1.15
        eyes[cv2.circle(np.zeros(shape, np.uint8), tuple(p[c].astype(int)), max(2, int(r)), 1, -1) > 0] = False
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Saturation limit is loose so a strongly tinted light (whose cast we want to measure)
    # doesn't hide the sclera; the brightest 40% then excludes eyelid skin and lashes.
    cand = eyes & (hsv[..., 1] < 110)
    if cand.sum() < 25:  # very strong tint: fall back to the brightest unclipped eye pixels
        cand = eyes & (hsv[..., 2] < 250)
    if cand.sum() < 25:
        return None
    v = hsv[..., 2][cand]
    sclera = cand & (hsv[..., 2] >= np.percentile(v, 60))
    means = img[sclera].reshape(-1, 3).astype(np.float32).mean(axis=0)
    return None if means.min() < 60 else means  # too dark or shadowed to trust


def _white_balance(img: np.ndarray, p: np.ndarray) -> tuple[np.ndarray, bool]:
    """Grey-world on the whites of the eyes (sclera), which are colour-neutral whatever the
    skin tone. Gains are clamped to +/-15%. Returns (image, whether it was applied)."""
    means = sclera_bgr(img, p)
    if means is None:
        return img, False
    gains = np.clip(means.mean() / means, 0.85, 1.15)
    return np.clip(img.astype(np.float32) * gains, 0, 255).astype(np.uint8), True


def _area_score(frac: float) -> int:
    """MASI area grade 0-6 from the share of a zone covered."""
    return 0 if frac <= 0.005 else 1 if frac < 0.1 else 2 if frac < 0.3 else 3 if frac < 0.5 else 4 if frac < 0.7 else 5 if frac < 0.9 else 6


HAYASHI = [(5, "Mild"), (20, "Moderate"), (50, "Severe"), (10 ** 9, "Very severe")]


def _blobs(mask: np.ndarray, min_area: int, max_area: int) -> list[tuple[int, int, int]]:
    """Compact, roundish spots only (lines and smears are rejected)."""
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    out = []
    for i in range(1, n):
        a = stats[i, cv2.CC_STAT_AREA]
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if min_area <= a <= max_area and max(w, h) <= 2 * max(1, min(w, h)) and a >= 0.5 * w * h:
            out.append((int(cents[i][0]), int(cents[i][1]), int(max(w, h) / 2 + 3)))
    return out


def _line_segments(hit: np.ndarray, min_len: float) -> np.ndarray:
    """Keep connected components that are long and thin (aspect >= 3)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hit.astype(np.uint8))
    keep = np.zeros(hit.shape, bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 6:
            continue
        ys, xs = np.nonzero(labels == i)
        (_, _), (rw, rh), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        length, width = max(rw, rh), max(1.0, min(rw, rh))
        if length >= min_len and length / width >= 3:
            keep |= labels == i
    return keep


def _ridges(L: np.ndarray) -> np.ndarray:
    """Valley strength (dark thin lines) from the Hessian's largest eigenvalue."""
    best = np.zeros_like(L)
    h, w = L.shape
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    for sigma in (1.5, 2.5):
        g = cv2.GaussianBlur(L, (0, 0), sigma)
        dxx = cv2.Sobel(g, cv2.CV_32F, 2, 0, ksize=3) * sigma ** 2
        dyy = cv2.Sobel(g, cv2.CV_32F, 0, 2, ksize=3) * sigma ** 2
        dxy = cv2.Sobel(g, cv2.CV_32F, 1, 1, ksize=3) * sigma ** 2
        lam = (dxx + dyy) / 2 + np.sqrt(((dxx - dyy) / 2) ** 2 + dxy ** 2)
        # Direction across the line (eigenvector of the largest eigenvalue).
        vx, vy = dxy, lam - dxx
        flat = np.hypot(vx, vy) < 1e-3
        vx, vy = np.where(flat, lam - dyy, vx), np.where(flat, dxy, vy)
        norm = np.hypot(vx, vy) + 1e-6
        vx, vy = vx / norm, vy / norm
        # A wrinkle is a valley: brighter on *both* sides. The dark side of a step edge
        # (hairline, jaw shadow) is only brighter on one side.
        off = 2.0 * sigma
        side1 = cv2.remap(g, grid_x + vx * off, grid_y + vy * off, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        side2 = cv2.remap(g, grid_x - vx * off, grid_y - vy * off, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        valley = (side1 - g > 1.5) & (side2 - g > 1.5)
        best = np.maximum(best, np.where(valley, lam, 0))
    return best


def _neck(bgr: np.ndarray, pts: np.ndarray, seg: np.ndarray | None) -> dict:
    """Neck vs cheek colour on the full photo.
    - Neck clearly darker (and more textured) than the face can be acanthosis nigricans - dark,
      velvety skin linked to insulin resistance, common in Indians with PCOS, diabetes or extra
      weight. A shadow under the chin also darkens the neck, so we sample the lower neck and only
      ever say "worth checking".
    - Face darker than the neck is sun tan (the face gets more sun)."""
    if seg is None:
        return {"available": False, "reason": "no segmentation"}
    face_h = float(pts[152, 1] - pts[10, 1])
    y0, y1 = int(pts[152, 1]), int(pts[152, 1] + 0.5 * face_h)
    xc, half = float(pts[152, 0]), 0.30 * float(pts[397, 0] - pts[172, 0])
    x0, x1 = int(xc - half), int(xc + half)
    h, w = bgr.shape[:2]
    if y0 >= h - 10 or x0 < 0 or x1 > w:
        return {"available": False, "reason": "Neck isn't in the photo."}
    neck = np.zeros((h, w), bool)
    neck[y0:min(y1, h), x0:x1] = True
    neck &= seg == BODY_SKIN
    rows = np.nonzero(neck.any(axis=1))[0]
    if len(rows) < 4:
        return {"available": False, "reason": "Neck is covered or not visible enough."}
    # Skip the upper 40% of the visible neck - that's where the chin casts its shadow - and stay
    # away from its edges (collar, hair, jaw outline).
    neck[:int(rows[0] + 0.4 * (rows[-1] - rows[0]))] = False
    k = max(3, int(0.03 * face_h))
    neck = cv2.erode(neck.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    if neck.sum() < max(150, 0.002 * face_h ** 2):
        return {"available": False, "reason": "Neck is covered or not visible enough."}
    bz = float(np.linalg.norm(pts[234, :2] - pts[454, :2]))
    cheek = np.zeros((h, w), np.uint8)
    for i in (50, 280):
        cv2.circle(cheek, (int(pts[i, 0]), int(pts[i, 1])), max(3, int(0.08 * bz)), 1, -1)
    cheek = (cheek > 0) & (seg == FACE_SKIN)
    if cheek.sum() < 100:
        return {"available": False, "reason": "Cheeks not clear enough to compare."}
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, B = lab[..., 0] * 100 / 255, lab[..., 2] - 128
    nL, cL = float(np.median(L[neck])), float(np.median(L[cheek]))
    ita = lambda m: float(np.degrees(np.arctan2(float(np.median(L[m])) - 50, float(np.median(B[m])))))  # noqa: E731
    d_ita = ita(cheek) - ita(neck)
    g = L.astype(np.float32)
    dog = np.abs(cv2.GaussianBlur(g, (0, 0), 1.0) - cv2.GaussianBlur(g, (0, 0), 3.0))
    texture = float(np.mean(dog[neck]) / max(np.mean(dog[cheek]), 1e-6))
    dL = cL - nL  # > 0: neck darker than cheeks
    if dL > 15:
        # A front photo can't tell chin shadow from real darkening, so this only prompts a question.
        finding, detail = "neck_darker", (
            f"In this photo your neck looks about {dL:.0f} units darker than your cheeks - usually that's just shadow "
            "from the chin. " + NECK_QUESTION)
    elif dL < -6:
        finding, detail = "face_tan", (
            f"Your face is about {-dL:.0f} units darker than your neck - that's sun tan on the face. Daily SPF and a "
            "gentle exfoliant help it fade over 6-12 weeks.")
    else:
        finding, detail = "even", "Your face and neck are a similar colour - no clear tan line or neck darkening."
    return {"available": True, "finding": finding, "delta_L": round(dL, 1), "delta_ita": round(d_ita, 1),
            "texture_ratio": round(texture, 2), "detail": detail}


BODY_SKIN, FACE_SKIN = 2, 3
NECK_QUESTION = ("Do you see dark, thick, velvety skin on the back or sides of your neck, or in your underarms? If so, "
                 "tell us in the questionnaire - it can be a sign of insulin resistance.")
NECK_REPORTED = ("You told us you have dark, velvety skin on your neck or underarms. This is called acanthosis "
                 "nigricans and is often an early sign of insulin resistance - very common in India, especially with "
                 "PCOS, extra weight around the waist or diabetes in the family. Please see a doctor and ask for a "
                 "fasting blood sugar and HbA1c test. Scrubbing, bleaching or 'whitening' creams won't fix it - "
                 "treating the cause (activity, diet, sometimes medicine) does, and the skin often lightens with it.")


def neck_with_answers(skin: dict, profile: dict) -> None:
    """Merge the self-reported sign (questionnaire) into the photo-based neck reading."""
    if "neck_dark" not in set(profile.get("skin_signs") or []):
        return
    neck = skin.setdefault("neck", {"available": False})
    neck.update(finding="reported", detail=NECK_REPORTED, see_doctor=True,
                tests=["Fasting blood sugar", "HbA1c", "Fasting insulin (if your doctor suggests)"])


def _severity(score: float) -> str:
    return "low" if score >= 75 else "moderate" if score >= 50 else "high"


def build_skin_mask(img: np.ndarray, p: np.ndarray, seg: np.ndarray | None, L: np.ndarray) -> dict | None:
    """The skin mask used by every skin measurement, built on the normalised crop (FACE_W px wide).
    Face oval minus eyes, brows, lips and nostrils, minus facial hair / dark textured regions (and the segmenter's hair
    and accessory classes). Returns None when too little reference cheek skin is visible.
    Returns {"skin_b", "skin", "ref", "cheek", "hair", "l_med"} (all boolean masks except l_med)."""
    shape = img.shape[:2]
    skin = _poly_mask(shape, p[FACE_OVAL])
    skin = cv2.erode(skin, np.ones((9, 9), np.uint8))
    for part, grow in ((R_EYE, 25), (L_EYE, 25), (R_BROW, 17), (L_BROW, 17), (LIPS, 13), (NOSTRILS, 9)):
        skin[_poly_mask(shape, p[part], grow) > 0] = 0
    cheek = cv2.bitwise_or(
        cv2.circle(np.zeros(shape, np.uint8), tuple(p[205].astype(int)), int(0.09 * FACE_W), 255, -1),
        cv2.circle(np.zeros(shape, np.uint8), tuple(p[425].astype(int)), int(0.09 * FACE_W), 255, -1),
    )
    ref = (cheek > 0) & (skin > 0)
    if ref.sum() < 200:
        return None
    l_med = float(np.median(L[ref]))
    # Facial hair: large dark textured regions (beard, moustache) - not thin dark wrinkles.
    hairy = ((L < l_med - 45) & (cv2.GaussianBlur(np.abs(L - cv2.GaussianBlur(L, (0, 0), 2)), (0, 0), 4) > 6)).astype(np.uint8)
    hairy = cv2.morphologyEx(hairy, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hairy)
    big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 0.012 * FACE_W ** 2]
    hair = np.isin(labels, big)
    if seg is not None:
        hair |= cv2.dilate(np.isin(seg, (1, 5)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    # Smooth, dark facial hair the texture test above misses (found on a smoothed beard photo, where the whole beard
    # stayed inside the mask): large dark regions below the base of the nose. Only ever REMOVES pixels from the mask.
    # UNVALIDATED threshold (checked visually on two photos; no labelled ground truth exists - see
    # docs/SKIN_SEGMENTATION_VALIDATION.md).
    lower = np.zeros(shape, bool)
    lower[int(p[2][1]):, :] = True
    dark_lower = cv2.morphologyEx(((L < DARK_HAIR_REL * l_med) & lower & (skin > 0)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(dark_lower)
    hair |= np.isin(lab2, [i for i in range(1, n2) if st2[i, cv2.CC_STAT_AREA] > 0.012 * FACE_W ** 2])
    skin[hair] = 0
    skin_b = skin > 0

    return {"skin_b": skin_b, "skin": skin, "ref": ref, "cheek": cheek, "hair": hair, "l_med": l_med}


def analyze(bgr: np.ndarray, face: FaceDetection, segmentation: np.ndarray | None = None) -> dict:
    """`segmentation`: optional MediaPipe multiclass category mask for the whole photo; its
    hair (incl. beard) and accessory (glasses) classes are removed from the skin mask."""
    img, p, seg = _normalise(bgr, face.points[:, :2], segmentation)
    img, balanced = _white_balance(img, p)
    shape = img.shape[:2]
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    eye_w = float(np.linalg.norm(p[33] - p[133]))

    sm = build_skin_mask(img, p, seg, L)
    if sm is None:
        return {"available": False}
    skin_b, skin, ref, cheek, hair, l_med = sm["skin_b"], sm["skin"], sm["ref"], sm["cheek"], sm["hair"], sm["l_med"]

    # Line-like structures (wrinkles, folds) - spots must not sit on these
    ridge = _ridges(L)
    on_line = cv2.dilate((ridge > 2.0).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0

    # Local residuals: pixel vs its immediate surroundings
    L_bg = cv2.GaussianBlur(L, (0, 0), 6)
    A_bg = cv2.GaussianBlur(A, (0, 0), 6)
    a_res, l_res = A - A_bg, L_bg - L  # redder than surroundings / darker than surroundings

    found: dict[str, list] = {"blemishes": [], "dark_spots": [], "acne_marks": [], "wrinkles": []}
    spot_area = skin_b & ~on_line
    # Thresholds relative to the person's own skin brightness (darker skin has less absolute contrast).
    dark_thr = max(9.0, 0.11 * l_med)
    # Blemishes (red spots)
    red = ((a_res > 7) & skin_b).astype(np.uint8) * 255
    found["blemishes"] = _blobs(cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), 12, 400)
    # Dark spots, split into acne marks (reddish-brown, PIH) and other dark spots
    dark = ((l_res > dark_thr) & (a_res < 7) & spot_area).astype(np.uint8) * 255
    for x, y, r in _blobs(cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), 15, 250):
        ring = cv2.circle(np.zeros(shape, np.uint8), (x, y), max(2, r - 2), 1, -1) > 0
        found["acne_marks" if float(np.mean(a_res[ring])) > 1.5 else "dark_spots"].append((x, y, r))

    # Pigmentation patches: broad areas darker than the wider surrounding skin
    patch_res = cv2.GaussianBlur(L, (0, 0), 25) - cv2.GaussianBlur(L, (0, 0), 4)
    patches = ((patch_res > 0.07 * l_med) & skin_b & ~on_line).astype(np.uint8)
    patches = cv2.morphologyEx(patches, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n_p, lab_p, st_p, _ = cv2.connectedComponentsWithStats(patches)
    patch_mask = np.isin(lab_p, [i for i in range(1, n_p) if st_p[i, cv2.CC_STAT_AREA] > 0.004 * FACE_W ** 2])
    patch_share = float(patch_mask.sum() / max(1, skin_b.sum()))

    # Wrinkle zones
    brow_top = min(p[105][1], p[334][1])
    zones = {
        "forehead": _rect_mask(shape, p[70][0], p[10][1] + 0.22 * (brow_top - p[10][1]), p[300][0], brow_top - 0.25 * eye_w),
        "crows_feet_r": _rect_mask(shape, p[33][0] - 0.75 * eye_w, p[33][1] - 0.45 * eye_w, p[33][0] - 0.12 * eye_w, p[33][1] + 0.55 * eye_w),
        "crows_feet_l": _rect_mask(shape, p[263][0] + 0.12 * eye_w, p[263][1] - 0.45 * eye_w, p[263][0] + 0.75 * eye_w, p[263][1] + 0.55 * eye_w),
        "under_eye_r": _rect_mask(shape, p[33][0], p[145][1] + 0.12 * eye_w, p[133][0], p[145][1] + 0.6 * eye_w),
        "under_eye_l": _rect_mask(shape, p[362][0], p[374][1] + 0.12 * eye_w, p[263][0], p[374][1] + 0.6 * eye_w),
        "smile_r": _poly_mask(shape, np.array([p[129], p[61], p[61] - [0.35 * eye_w, 0], p[129] - [0.5 * eye_w, 0]])),
        "smile_l": _poly_mask(shape, np.array([p[358], p[291], p[291] + [0.35 * eye_w, 0], p[358] + [0.5 * eye_w, 0]])),
    }
    line_px = (ridge > 3.0).astype(np.uint8) * 255
    line_px = cv2.morphologyEx(line_px, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    # Wrinkle zones hug the eyes, so only exclude the eyes themselves (not the wide skin-mask margin).
    oval = _poly_mask(shape, p[FACE_OVAL]) > 0
    eyes = (_poly_mask(shape, p[R_EYE], 7) > 0) | (_poly_mask(shape, p[L_EYE], 7) > 0)
    zone_density = {}
    wrinkle_vis = np.zeros(shape, np.uint8)
    for name, zm in zones.items():
        area = (zm > 0) & oval & ~eyes & ~hair
        if area.sum() < 50:
            continue
        keep = _line_segments((line_px > 0) & area, min_len=0.06 * FACE_W)
        zone_density[name] = float(keep.sum() / area.sum())
        wrinkle_vis[keep] = 255
    wrinkle_density = float(np.mean(list(zone_density.values()))) if zone_density else 0.0

    # Dark circles (relative to the person's own cheek brightness)
    ue = ((zones["under_eye_r"] > 0) | (zones["under_eye_l"] > 0)) & ~hair
    dc_delta = l_med - float(np.median(L[ue])) if ue.sum() > 50 else 0.0
    dc_rel = dc_delta / max(1.0, l_med)

    # Skin tone: overall ITA° group (colour photos only) + unevenness as the colour difference
    # between zones in brightness-free chromaticity. Both cheeks form one zone.
    tone_zones = {
        "forehead": (zones["forehead"] > 0) & skin_b,
        "nose": (_poly_mask(shape, p[[168, 6, 197, 195, 5]], 15) > 0) & skin_b,
        "cheeks": (cheek > 0) & skin_b,
        "chin": (cv2.circle(np.zeros(shape, np.uint8), tuple(p[199].astype(int)), int(0.06 * FACE_W), 255, -1) > 0) & skin_b,
    }
    rgb_sum = img.astype(np.float32).sum(axis=2) + 1e-6
    chrom_r, chrom_b = img[..., 2] / rgb_sum, img[..., 0] / rgb_sum  # brightness-free colour
    chrom = {k: (float(np.median(chrom_r[m])), float(np.median(chrom_b[m])))
             for k, m in tone_zones.items() if m.sum() >= 30}
    vals = list(chrom.values())
    tone_spread = max((np.hypot(a[0] - b[0], a[1] - b[1]) for a in vals for b in vals), default=0.0) * 100
    chroma = float(np.median(np.hypot(A[skin_b] - 128, B[skin_b] - 128)))
    ita_all = _ita(L, B, skin_b) if chroma > 4 else None  # grayscale / heavily filtered photo -> unknown
    # Melanin index is more stable across phones than ITA (Kang 2025); cheeks only.
    cheek_L = float(np.median(L[ref])) * 100 / 255
    melanin_index = 100 * math.log10(100 / max(cheek_L, 1.0))
    group = next((g for g in TONE_GROUPS if ita_all is not None and ita_all > g[0]),
                 (None, "unknown", "Colour couldn't be read from this photo - use natural daylight without filters."))

    # Redness: share of skin redder than the face's own baseline. Melanin masks redness (inflammation
    # looks brown/purple on deeper skin and a* contrast is smaller), so the threshold drops with
    # skin lightness: 6 a* units on light skin (L* ~65) down to 3.5 on deep skin.
    a_med = float(np.median(A[skin_b]))
    red_thr = float(np.clip(6.0 * cheek_L / 65.0, 3.5, 6.0))
    red_share = float(((A > a_med + red_thr) & skin_b).sum() / max(1, skin_b.sum()))

    # Texture on the cheeks
    dog = np.abs(cv2.GaussianBlur(L, (0, 0), 1.0) - cv2.GaussianBlur(L, (0, 0), 3.0))
    texture = float(np.mean(dog[ref]))

    # Shine in the T-zone
    tzone = (zones["forehead"] > 0) | (_poly_mask(shape, p[[168, 6, 197, 195, 5, 4, 1, 129, 358]], 9) > 0)
    tzone &= skin_b
    shine_share = float(((hsv[..., 2] > 235) & (hsv[..., 1] < 50) & tzone).sum() / max(1, tzone.sum()))

    # Acne grade (Hayashi): inflammatory lesions on the worse half of the face.
    mid_x = float(p[1][0])
    per_half = max(sum(1 for x, _, _ in found["blemishes"] if x < mid_x), sum(1 for x, _, _ in found["blemishes"] if x >= mid_x))
    acne_grade = "Clear" if per_half == 0 else next(label for top, label in HAYASHI if per_half <= top)

    # Pigmentation extent, modelled on mMASI (0-24): 0.3*A*D forehead + each malar side, 0.1*A*D chin.
    def masi_zone(zm: np.ndarray) -> float:
        area = zm & skin_b
        if area.sum() < 30:
            return 0.0
        a = _area_score(float((patch_mask & area).sum() / area.sum()))
        if a == 0:
            return 0.0
        delta = (float(np.median(L[area & ~patch_mask])) - float(np.median(L[patch_mask & area]))) / max(l_med, 1.0) \
            if (area & ~patch_mask).sum() > 10 else 0.08
        d = 1 if delta < 0.04 else 2 if delta < 0.08 else 3 if delta < 0.12 else 4
        return a * d
    malar_r = cv2.circle(np.zeros(shape, np.uint8), tuple(p[205].astype(int)), int(0.13 * FACE_W), 255, -1) > 0
    malar_l = cv2.circle(np.zeros(shape, np.uint8), tuple(p[425].astype(int)), int(0.13 * FACE_W), 255, -1) > 0
    mmasi = round(0.3 * masi_zone(zones["forehead"] > 0) + 0.3 * masi_zone(malar_r) + 0.3 * masi_zone(malar_l)
                  + 0.1 * masi_zone(tone_zones["chin"]), 1)
    dc_grade = 0 if dc_rel < 0.04 else 1 if dc_rel < 0.08 else 2 if dc_rel < 0.14 else 3

    clamp = lambda v: round(float(max(0.0, min(100.0, v))), 1)  # noqa: E731
    scores = {
        "wrinkles": clamp(100 - wrinkle_density / 0.20 * 100),
        "blemishes": clamp(100 - len(found["blemishes"]) * 6),
        "dark_spots": clamp(100 - len(found["dark_spots"]) * 4),
        "acne_marks": clamp(100 - len(found["acne_marks"]) * 5),
        "pigmentation": clamp(100 - patch_share * 400),
        "uneven_tone": clamp(100 - max(0.0, tone_spread - 0.8) * 30),
        "dark_circles": clamp(100 - max(0.0, dc_rel - 0.04) * 500),
        "redness": clamp(100 - red_share * 300),
        "texture": clamp(100 - max(0.0, texture - 1.6) * 30),
        "shine": clamp(100 - shine_share * 500),
    }
    details = {
        "wrinkles": f"Line density {wrinkle_density * 100:.1f}% across forehead, eye area and smile lines.",
        "blemishes": f"{len(found['blemishes'])} red spot(s) detected - acne grade: {acne_grade} "
                     f"(Hayashi scale, {per_half} on the more affected side).",
        "dark_spots": f"{len(found['dark_spots'])} dark spot(s) detected.",
        "dark_circles": f"Under-eyes are {max(0.0, dc_rel) * 100:.0f}% darker than your cheeks "
                        f"(grade {dc_grade} of 3).",
        "acne_marks": f"{len(found['acne_marks'])} mark(s) left by past breakouts.",
        "pigmentation": f"{patch_share * 100:.1f}% of visible skin has darker patches "
                        f"(extent score {mmasi:.1f} of 24, modelled on the mMASI melasma scale - not a diagnosis).",
        "uneven_tone": f"Skin colour differs by {tone_spread:.1f} units between forehead, nose, cheeks and chin - often from sun exposure (tanning).",
        "redness": f"{red_share * 100:.0f}% of skin is noticeably redder than your baseline."
                   + (" On deeper skin, redness can look brown or purple, so we use a more sensitive check - it can "
                      "still miss some." if cheek_L < 50 else ""),
        "texture": "Fine surface texture on the cheeks (pores, roughness).",
        "shine": f"{shine_share * 100:.1f}% of the T-zone shows shine.",
    }
    concerns = [
        {"key": k, "label": CONCERNS[k], "score": s, "severity": _severity(s), "detail": details[k]}
        for k, s in scores.items()
    ]
    concerns.sort(key=lambda c: c["score"])
    return {
        "available": True,
        "experimental": True,
        "score": round(sum(scores.values()) / len(scores), 1),
        "concerns": concerns,
        "zones": {k: round(v * 100, 2) for k, v in zone_density.items()},
        "tone": {
            "ita": round(ita_all, 1) if ita_all is not None else None,
            "group": group[1],
            "advice": group[2],
            "spread": round(float(tone_spread), 2),
            "melanin_index": round(melanin_index, 1),
            "white_balanced": balanced,
        },
        "grades": {"acne": acne_grade, "acne_lesions_worse_side": per_half, "pigmentation_mmasi": mmasi,
                   "dark_circles": dc_grade},
        "neck": _neck(bgr, face.points[:, :2], segmentation),
        "note": "Estimated from your photo. Lighting, camera and makeup affect results - use soft, even light and a bare face.",
        "image": _overlay(img, skin_b, wrinkle_vis, found, ue if dc_rel > 0.06 else None, patch_mask),
    }


def _overlay(img, skin_b, wrinkles, found, dark_circle_area, patches) -> str:
    vis = img.copy()
    dim = ~skin_b
    vis[dim] = (vis[dim] * 0.55).astype(np.uint8)
    if patches.any():
        contours, _ = cv2.findContours(patches.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, contours, -1, (200, 120, 60), 2, cv2.LINE_AA)
    if dark_circle_area is not None:
        tint = vis.copy()
        tint[dark_circle_area] = (150, 80, 160)
        vis = cv2.addWeighted(tint, 0.25, vis, 0.75, 0)
    vis[wrinkles > 0] = (60, 220, 255)
    for x, y, r in found["blemishes"]:
        cv2.circle(vis, (x, y), r, (70, 70, 235), 2, cv2.LINE_AA)
    for x, y, r in found["dark_spots"]:
        cv2.circle(vis, (x, y), r, (40, 110, 170), 2, cv2.LINE_AA)
    for x, y, r in found["acne_marks"]:
        cv2.circle(vis, (x, y), r, (60, 150, 240), 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""
