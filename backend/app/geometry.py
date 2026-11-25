"""Real-world scale, camera distance and selfie-perspective correction.

The human iris is ~11.7 mm wide (MediaPipe Iris, depth error <10%), which gives a mm scale
and, with the focal length, the camera-to-face distance. At arm's-length selfie distances
(~30 cm) the nose is ~1.3x closer than the cheekbones, so widths of central features are
inflated relative to the face (Ward et al., JAMA Facial Plast Surg 2018). `undistort`
rescales each landmark by its depth so ratios match a distant (near-orthographic) view.
"""
from __future__ import annotations

import io

import numpy as np

IRIS_MM = 11.7
DEFAULT_F35 = 26.0  # typical phone front camera, 35mm-equivalent focal length
R_IRIS_H, L_IRIS_H = (469, 471), (474, 476)  # horizontal iris edge points


def iris_px(points: np.ndarray) -> float:
    r = np.linalg.norm(points[R_IRIS_H[0], :2] - points[R_IRIS_H[1], :2])
    l_ = np.linalg.norm(points[L_IRIS_H[0], :2] - points[L_IRIS_H[1], :2])
    return float((r + l_) / 2)


def mm_per_px(points: np.ndarray) -> float:
    return IRIS_MM / max(iris_px(points), 1e-6)


def exif_f35(data: bytes) -> float | None:
    """35mm-equivalent focal length from EXIF, if the photo still has it."""
    try:
        from PIL import Image
        exif = Image.open(io.BytesIO(data)).getexif()
        f35 = exif.get_ifd(0x8769).get(41989) or exif.get(41989)
        return float(f35) if f35 and 10 <= float(f35) <= 200 else None
    except Exception:  # noqa: BLE001 - EXIF is optional
        return None


def camera(points: np.ndarray, shape, f35: float | None = None) -> dict:
    """Estimated camera distance (mm) and focal length (px) for this photo."""
    h, w = shape[:2]
    f_px = (f35 or DEFAULT_F35) / 36.0 * max(h, w)
    dist = f_px * IRIS_MM / max(iris_px(points), 1e-6)
    return {"distance_mm": round(float(dist)), "f_px": round(f_px, 1), "f35_from_exif": f35 is not None,
            "mm_per_px": round(mm_per_px(points), 4)}


def undistort(points: np.ndarray, shape, cam: dict) -> np.ndarray:
    """Rescale x,y of every landmark to the scale of the eye plane, removing perspective
    exaggeration. MediaPipe z is in the same pixel units as x (scaled by image width)."""
    d = cam["distance_mm"]
    if not 150 <= d <= 3000:
        return points
    h, w = shape[:2]
    c = np.array([w / 2, h / 2])
    k = cam["mm_per_px"]
    z_eye = (points[468, 2] + points[473, 2]) / 2
    depth = d + (points[:, 2] - z_eye) * k  # mm from camera for each point
    out = points.copy()
    out[:, :2] = c + (points[:, :2] - c) * (depth / d)[:, None]
    return out


def average_frames(points: np.ndarray, frames: list, shape) -> tuple[np.ndarray, int]:
    """Per-landmark median of the photo's landmarks and the live-camera frames captured just
    before it (normalised x, y, z). Each frame is similarity-aligned to the photo first; frames
    that don't fit (moved, different expression) are dropped. Random jitter falls ~sqrt(N)."""
    import cv2

    h, w = shape[:2]
    ref = points[:, :2].astype(np.float32)
    bz = float(np.linalg.norm(ref[234] - ref[454]))
    stack = [points]
    for f in frames[:30]:
        a = np.asarray(f, dtype=np.float64)
        if a.shape != (478, 3):
            continue
        q = np.stack([a[:, 0] * w, a[:, 1] * h, a[:, 2] * w], axis=1)
        m, _ = cv2.estimateAffinePartial2D(q[:, :2].astype(np.float32), ref)
        if m is None:
            continue
        xy = q[:, :2] @ m[:, :2].T + m[:, 2]
        if float(np.mean(np.linalg.norm(xy - ref, axis=1))) / bz > 0.02:
            continue
        scale = float(np.sqrt(abs(np.linalg.det(m[:, :2]))))
        stack.append(np.column_stack([xy, q[:, 2] * scale]))
    if len(stack) < 4:
        return points, 1
    return np.median(np.stack(stack), axis=0), len(stack)
