"""Photo quality gate and annotated overlay image."""
from __future__ import annotations

import base64
import math

import cv2
import numpy as np

from . import align, faceid, skin
from . import metrics as M
from .landmarks import FaceDetection


SHARPNESS_MIN = 25.0  # Laplacian variance at 128 px interpupillary distance
TEXTURE_MIN = 0.10  # cheek/eye band-pass ratio: unfiltered photos ~0.15-0.20, bilateral "beauty" ~0.09 (calibrate on real selfies)
FIQA_MIN = 0.55  # eDifFIQA: good frontal photos ~0.75-0.82, three-quarter ~0.6, very dark/blurred <0.5
MULTI_FACE_AMBIGUOUS = 0.6  # 2nd face >= 60% as wide as the 1st = ambiguous subject (engineering choice, unvalidated)
CAST_MAX = 0.12  # sclera channel deviation from grey; skin analysis can only correct up to 15%


def colour_cast(bgr: np.ndarray, pts: np.ndarray) -> dict | None:
    """Colour of the light from the whites of the eyes: {'b','g','r'} as fractions above/below grey."""
    means = skin.sclera_bgr(bgr, pts[:, :2])
    if means is None:
        return None
    dev = means / means.mean() - 1
    return {"b": float(dev[0]), "g": float(dev[1]), "r": float(dev[2])}


def _face_box(points: np.ndarray, shape, margin: float = 0.0) -> tuple[int, int, int, int]:
    h, w = shape[:2]
    x0, y0 = points[:, 0].min(), points[:, 1].min()
    x1, y1 = points[:, 0].max(), points[:, 1].max()
    mx, my = (x1 - x0) * margin, (y1 - y0) * margin
    return (max(0, int(x0 - mx)), max(0, int(y0 - my)), min(w, int(x1 + mx)), min(h, int(y1 + my)))


def _disc(shape, centre, r) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    cv2.circle(m, (int(centre[0]), int(centre[1])), max(2, int(r)), 1, -1)
    return m.astype(bool)


def _iod_normalised(bgr: np.ndarray, pts: np.ndarray, iod_px: float = 128.0) -> tuple[np.ndarray, np.ndarray]:
    """Grey face crop resized so the pupils are `iod_px` apart (resolution-independent
    sharpness/texture), plus the landmarks in that crop."""
    iod = float(np.linalg.norm(pts[468, :2] - pts[473, :2]))
    k = iod_px / max(iod, 1e-6)
    x0, y0, x1, y1 = _face_box(pts, bgr.shape)
    crop = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    return crop, (pts[:, :2] - [x0, y0]) * k


def texture_ratio(bgr: np.ndarray, pts: np.ndarray) -> float:
    """Band-pass (DoG) energy on cheek skin divided by the same around the eyes. Beauty
    filters smooth skin but keep eyes sharp, so a low ratio suggests a filter."""
    g, p = _iod_normalised(bgr, pts)
    g = g.astype(np.float32)
    dog = cv2.GaussianBlur(g, (0, 0), 1.0) - cv2.GaussianBlur(g, (0, 0), 3.0)
    e = dog * dog
    r = 0.18 * 128
    cheeks = _disc(g.shape, p[50], r) | _disc(g.shape, p[280], r)
    eyes = _disc(g.shape, p[468], 0.35 * 128) | _disc(g.shape, p[473], 0.35 * 128)
    return float(e[cheeks].mean() / max(e[eyes].mean(), 1e-6))


def lighting(bgr: np.ndarray, pts: np.ndarray) -> dict:
    L = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)
    bz = float(np.linalg.norm(pts[234, :2] - pts[454, :2]))
    r = 0.08 * bz
    right, left = _disc(bgr.shape, pts[50], r), _disc(bgr.shape, pts[280], r)
    skin = right | left | _disc(bgr.shape, pts[151], r) | _disc(bgr.shape, pts[199], 0.6 * r)
    lr, ll = float(L[right].mean()), float(L[left].mean())
    vals = L[skin]
    med = float(np.median(vals))
    return {
        "side_diff": abs(lr - ll) / max((lr + ll) / 2, 1e-6),
        "shadow_frac": float((vals < 0.55 * med).mean()),
        "clipped_frac": float((bgr[skin].max(axis=1) >= 250).mean()),
        "skin_L": med * 100 / 255,
    }


def check_quality(bgr: np.ndarray, face: FaceDetection, cam: dict | None = None, segmentation=None) -> dict:
    """`cam` from geometry.camera (pass it only when the focal length is known);
    `segmentation` an optional multiclass category mask (hair=1, accessories=5)."""
    issues: list[dict] = []

    def add(level, code, message):
        issues.append({"level": level, "code": code, "message": message})

    if face.num_faces > 1:
        if face.second_face_ratio >= MULTI_FACE_AMBIGUOUS:  # engineering threshold, not validated on data
            add("error", "multiple_faces", "Two people of similar size are in the photo, so we can't tell whose face to "
                "analyse. Retake the photo with only you in the frame.")
        else:
            add("warning", "multiple_faces", "More than one face detected - the largest one was analysed.")

    x0, y0, x1, y1 = _face_box(face.points, bgr.shape)
    crop = cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    face_frac = (x1 - x0) / bgr.shape[1]
    brightness = float(crop.mean())
    # Sharpness at a fixed face scale (pupils 128 px apart), so it doesn't depend on resolution.
    norm, _ = _iod_normalised(bgr, face.points)
    sharpness = float(cv2.Laplacian(norm, cv2.CV_64F).var())
    light = lighting(bgr, face.points)
    texture = texture_ratio(bgr, face.points)
    cast = colour_cast(bgr, face.points)
    fiqa = faceid.quality(bgr, face.points)

    if face_frac < 0.15:
        add("warning", "too_far", "Face is small in the frame. Move a little closer or crop the photo around your face.")
    if (x1 - x0) < 200:
        add("warning", "low_resolution", "Face resolution is low - use a higher-quality photo for accurate results.")
    if cam and cam["distance_mm"] < 350:
        add("warning", "too_close", f"The camera was about {cam['distance_mm'] / 10:.0f} cm from your face. Close-up selfies "
            "make the nose look wider - hold the phone at full arm's length (45 cm or more) or use the back camera with a timer.")
    if sharpness < SHARPNESS_MIN:
        add("warning", "blurry", "Photo looks blurry. Hold the camera steady and use good focus.")
    if brightness < 70 or light["skin_L"] < 35:
        add("warning", "too_dark", "Photo is too dark. Face a window or soft light source.")
    elif brightness > 210 or light["clipped_frac"] > 0.03:
        add("warning", "too_bright", "Parts of your face are overexposed. Avoid direct harsh light or flash.")
    if light["side_diff"] > 0.20 or light["shadow_frac"] > 0.15:
        add("warning", "uneven_light", "One side of your face is in shadow. Face the light source straight on - "
            "uneven light affects skin and symmetry readings.")
    if texture < TEXTURE_MIN and sharpness >= SHARPNESS_MIN:
        add("warning", "beauty_filter", "Your skin looks smoothed, as if a beauty or AI filter is on. Turn off beauty mode "
            "for accurate skin results.")
    if cast and max(abs(v) for v in cast.values()) > CAST_MAX:
        tint = ("yellow/orange" if cast["r"] > 0 and cast["b"] < 0 else "blue" if cast["b"] > 0 and cast["r"] < 0
                else "green" if cast["g"] > 0 else "pink/purple")
        add("warning", "colour_cast", f"The light has a strong {tint} tint (e.g. a tube light, warm bulb or filter), so skin "
            "colour, tan and redness readings are less reliable. Daylight from a window works best.")
    if fiqa is not None and fiqa < FIQA_MIN and not any(i["code"] in ("blurry", "too_dark", "not_frontal") for i in issues):
        add("warning", "low_quality", "Our image-quality model rates this photo low (blur, noise, exposure or something "
            "covering the face). A clearer photo gives more accurate results.")
    if segmentation is not None:
        pts = face.points
        x_l, x_r = int(pts[234, 0]), int(pts[454, 0])
        eye_band = segmentation[int(min(pts[70, 1], pts[300, 1])):int(pts[4, 1]), x_l:x_r]
        if eye_band.size and (eye_band == 5).mean() > 0.05:
            add("warning", "glasses", "Glasses detected - take them off for accurate eye and skin measurements.")
        jaw = segmentation[int(pts[17, 1]):int(pts[152, 1]), int(pts[172, 0]):int(pts[397, 0])]
        if jaw.size and (jaw == 1).mean() > 0.18:
            add("warning", "beard", "A beard covers your jaw and chin, so we left out the jaw and chin measurements - "
                "the jawline under a beard can't be seen. Take a clean-shaven photo to get them.")

    yaw, pitch, roll = face.pose["yaw"], face.pose["pitch"], face.pose["roll"]
    if abs(yaw) > 15 or abs(pitch) > 18:
        add("error", "not_frontal", "Head is turned too far. Look straight at the camera for the front photo.")
    elif abs(yaw) > 7 or abs(pitch) > 10:
        add("warning", "slightly_turned", "Head is slightly turned - symmetry and width measurements may be less accurate.")
    if abs(roll) > 10:
        add("warning", "tilted", "Head is tilted sideways (we correct for this, but a level head is better).")

    b = face.blendshapes
    if b.get("jawOpen", 0) > 0.25:
        add("warning", "mouth_open", "Mouth is open - keep a relaxed, closed mouth.")
    if max(b.get("mouthSmileLeft", 0), b.get("mouthSmileRight", 0)) > 0.45:
        add("warning", "smiling", "Use a neutral expression - smiling changes lip and cheek measurements.")
    if max(b.get("eyeBlinkLeft", 0), b.get("eyeBlinkRight", 0)) > 0.5:
        add("warning", "eyes_closed", "Eyes appear partly closed - keep eyes open naturally.")

    return {
        "ok": not any(i["level"] == "error" for i in issues),
        "issues": issues,
        "pose": {k: round(v, 1) for k, v in face.pose.items()},
        "sharpness": round(sharpness, 1),
        "brightness": round(brightness, 1),
        "lighting": {k: round(v, 3) for k, v in light.items()},
        "texture_ratio": round(texture, 3),
        "colour_cast": {k: round(v, 3) for k, v in cast.items()} if cast else None,
        "fiqa": round(fiqa, 3) if fiqa is not None else None,
        "camera": cam,
    }


def _encode(img: np.ndarray, quality: int = 88) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def face_crop_b64(bgr: np.ndarray, face: FaceDetection, max_side: int = 768) -> str:
    x0, y0, x1, y1 = _face_box(face.points, bgr.shape, margin=0.35)
    crop = bgr[y0:y1, x0:x1]
    scale = max_side / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return _encode(crop)


def aligned_b64(bgr: np.ndarray, points: np.ndarray) -> str:
    """Face warped so the pupils always land on the same pixels (320x420, pupils 90 px apart),
    with room above for the hairline - repeat check-ins can then be overlaid exactly."""
    src = points[[468, 473], :2].astype(np.float32)
    dst = np.float32([[115, 190], [205, 190]])
    d_src, d_dst = src[1] - src[0], dst[1] - dst[0]
    k = float(np.linalg.norm(d_dst) / max(np.linalg.norm(d_src), 1e-6))
    a = math.atan2(d_dst[1], d_dst[0]) - math.atan2(d_src[1], d_src[0])
    c, s = k * math.cos(a), k * math.sin(a)
    m = np.float32([[c, -s, 0], [s, c, 0]])
    m[:, 2] = dst[0] - m[:, :2] @ src[0]
    out = cv2.warpAffine(bgr, m, (320, 420), flags=cv2.INTER_AREA, borderValue=(240, 240, 240))
    return _encode(out, 85)


def annotate(bgr: np.ndarray, face: FaceDetection) -> str:
    """Overlay on the front photo. The photo is levelled on the pupil line first so the thirds and
    width lines are square to the face, then crop, enlarge and draw at final resolution."""
    lv, pts3, _ = align.level(bgr, face.points)
    p = pts3[:, :2]
    x0, y0, x1, y1 = _face_box(pts3, lv.shape, margin=0.3)
    img = lv[y0:y1, x0:x1].copy()
    s = min(max(1000 / max(img.shape[:2]), 1.0), 3.0)
    if s > 1.01:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    elif max(img.shape[:2]) > 1000:
        s = 1000 / max(img.shape[:2])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    t = max(2, int(img.shape[1] / 450))
    pt = lambda i: (int((p[i][0] - x0) * s), int((p[i][1] - y0) * s))  # noqa: E731

    gold, cyan, pink = (80, 190, 255), (230, 200, 60), (180, 105, 255)
    # Midline from stable (non-protruding) landmarks, vertical because the photo is levelled
    # (least-squares fit, so a turned head still gets the line that follows the face, not the frame)
    mid = np.array([pt(i) for i in M.MIDLINE_STABLE], float)
    slope, icpt = np.polyfit(mid[:, 1], mid[:, 0], 1)
    ya, yb = pt(M.FOREHEAD)[1], pt(M.MENTON)[1]
    cv2.line(img, (int(slope * ya + icpt), ya), (int(slope * yb + icpt), yb), cyan, t, cv2.LINE_AA)
    # Thirds (horizontal guides)
    xa, xb = pt(M.R_ZYGO)[0], pt(M.L_ZYGO)[0]
    for idx in (M.GLABELLA, M.SUBNASALE, M.MENTON):
        y = pt(idx)[1]
        cv2.line(img, (xa, y), (xb, y), gold, t, cv2.LINE_AA)
    # Eye lines / canthal tilt
    cv2.line(img, pt(M.R_EYE_IN), pt(M.R_EYE_OUT), pink, t + 1, cv2.LINE_AA)
    cv2.line(img, pt(M.L_EYE_IN), pt(M.L_EYE_OUT), pink, t + 1, cv2.LINE_AA)
    # Widths
    cv2.line(img, pt(M.R_ZYGO), pt(M.L_ZYGO), gold, t, cv2.LINE_AA)
    cv2.line(img, pt(M.R_GONION), pt(M.L_GONION), gold, t, cv2.LINE_AA)
    cv2.line(img, pt(M.R_ALA), pt(M.L_ALA), cyan, t, cv2.LINE_AA)
    cv2.line(img, pt(M.R_MOUTH), pt(M.L_MOUTH), cyan, t, cv2.LINE_AA)
    for i in (M.R_IRIS, M.L_IRIS, M.R_ZYGO, M.L_ZYGO, M.R_GONION, M.L_GONION, M.R_ALA, M.L_ALA, M.R_MOUTH, M.L_MOUTH):
        cv2.circle(img, pt(i), t + 1, pink if i in (M.R_IRIS, M.L_IRIS) else (255, 255, 255), -1, cv2.LINE_AA)
    return _encode(img, 93)
