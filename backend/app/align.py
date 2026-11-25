"""Level a photo so the pupil line is horizontal, so every overlay (thirds, fifths, mirror faces,
eye lines) is drawn square to the face instead of square to a tilted phone."""
from __future__ import annotations

import math

import cv2
import numpy as np

R_IRIS, L_IRIS = 468, 473


def roll_degrees(points: np.ndarray) -> float:
    d = points[L_IRIS, :2] - points[R_IRIS, :2]
    return math.degrees(math.atan2(d[1], d[0]))


def level(img: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rotate the image about the pupil midpoint. Returns (image, points, 2x3 matrix)."""
    angle = roll_degrees(points)
    centre = tuple(float(v) for v in points[[R_IRIS, L_IRIS], :2].mean(axis=0))
    m = cv2.getRotationMatrix2D(centre, angle, 1.0)  # positive angle = counter-clockwise, undoes a clockwise tilt
    h, w = img.shape[:2]
    out = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    pts = points.copy()
    xy = points[:, :2]
    pts[:, :2] = xy @ m[:, :2].T + m[:, 2]
    return out, pts, m


def transform_y(m: np.ndarray, x: float, y: float) -> float:
    return float(m[1, 0] * x + m[1, 1] * y + m[1, 2])


def upscale(img: np.ndarray, min_width: int = 900) -> tuple[np.ndarray, float]:
    """Enlarge small crops with cubic interpolation so overlays are drawn crisp; returns (image, scale)."""
    s = max(1.0, min_width / max(img.shape[1], 1))
    s = min(s, 3.0)
    if s > 1.01:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return img, s
