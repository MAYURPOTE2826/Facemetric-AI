"""Three-quarter photo (head turned ~30-60°) → gonial (jaw) angle.

At this angle MediaPipe still tracks the face and the near-side jawline is on the
visible outline. We undo the yaw on the 3D landmarks, look at them from the side
(depth vs height) and measure the angle between the ramus (back edge of the jaw,
below the ear) and the mandibular body (lower jaw line).
"""
from __future__ import annotations

import base64
import math
from dataclasses import asdict

import cv2
import numpy as np

from . import landmarks
from .metrics import Metric, _score, frontalize

# Face-oval landmarks: below the ear (ramus) and along the lower jaw (body), per side.
# "R" = subject's right side (image left in a frontal photo).
RAMUS = {"R": [234, 93, 132], "L": [454, 323, 361]}
BODY = {"R": [136, 150, 149, 176], "L": [365, 379, 378, 400]}
JAW_OUTLINE = {"R": [234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152],
               "L": [454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152]}


class ThreeQuarterError(Exception):
    pass


def _direction(pts: np.ndarray) -> np.ndarray:
    _, _, vt = np.linalg.svd(pts - pts.mean(axis=0))
    return vt[0]


def _gonial_angle(points: np.ndarray, side: str) -> float:
    frontal, _ = frontalize(points)
    sagittal = frontal[:, [2, 1]]  # (depth, height) - the view from the side
    ramus = _direction(sagittal[RAMUS[side]])
    body = _direction(sagittal[BODY[side]])
    if ramus[1] > 0:  # point the ramus up
        ramus = -ramus
    if body[0] > 0:  # point the body forward (towards the camera / face front)
        body = -body
    inner = math.degrees(math.acos(float(np.clip(np.dot(ramus, body), -1, 1))))
    return 180.0 - inner if inner < 90 else inner


def analyze(bgr: np.ndarray, sex: str = "unspecified") -> dict:
    face = landmarks.detect(bgr)
    if face is None:
        raise ThreeQuarterError("Couldn't find your face. Turn about 45° (both eyes still visible) in good light.")
    yaw = face.pose["yaw"]
    if abs(yaw) < 20:
        raise ThreeQuarterError("You're facing the camera too directly. Turn your head about 45° to one side.")
    if abs(yaw) > 65:
        raise ThreeQuarterError("You've turned too far. Turn back a little so both eyes are visible (about 45°).")

    near = "R" if yaw > 0 else "L"  # the side of the jaw facing the camera
    angle = _gonial_angle(face.points, near)
    if not 100 <= angle <= 155:
        raise ThreeQuarterError("Couldn't trace your jawline clearly. Keep hair off the jaw and neck visible.")

    male = sex.lower().startswith("m")
    ideal, tol = (121.0 if male else 125.0), 6.0
    score, status, direction = _score(angle, ideal, tol)
    metric = Metric(
        "gonial_angle", "Jaw angle (gonial)", "jaw", round(angle, 1), "°", ideal, tol, score, status, direction,
        "Angle at the corner of the jaw, estimated from a three-quarter photo. Around 115-125° (men) and "
        "120-130° (women) reads as a defined jawline; higher is a steeper, softer jaw.",
    )
    return {
        "metrics": [asdict(metric)],
        "near_side": near,
        "yaw": round(yaw, 1),
        "annotated_image": _annotate(bgr, face.points, near, angle),
    }


def _annotate(bgr: np.ndarray, points: np.ndarray, side: str, angle: float) -> str:
    img = bgr.copy()
    p = points[:, :2]
    t = max(2, int(img.shape[1] / 450))
    gold, cyan, pink = (80, 190, 255), (230, 200, 60), (180, 105, 255)
    outline = p[JAW_OUTLINE[side]].astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(img, [outline], False, (240, 240, 240), t, cv2.LINE_AA)

    def extend(ids, length):
        pts = p[ids]
        c, d = pts.mean(axis=0), _direction(pts)
        return tuple((c - d * length).astype(int)), tuple((c + d * length).astype(int))

    jaw_len = float(np.linalg.norm(p[JAW_OUTLINE[side][0]] - p[152]))
    for ids, colour in ((RAMUS[side], cyan), (BODY[side], gold)):
        a, b = extend(ids, jaw_len * 0.45)
        cv2.line(img, a, b, colour, t, cv2.LINE_AA)
    corner = p[[58, 172] if side == "R" else [288, 397]].mean(axis=0).astype(int)
    cv2.circle(img, tuple(corner), t * 3, pink, -1, cv2.LINE_AA)
    label = f"{angle:.0f} deg"
    fs = img.shape[1] / 900
    cv2.putText(img, label, (int(corner[0] + 12 * fs), int(corner[1] + 40 * fs)), cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), t + 3, cv2.LINE_AA)
    cv2.putText(img, label, (int(corner[0] + 12 * fs), int(corner[1] + 40 * fs)), cv2.FONT_HERSHEY_SIMPLEX, fs, pink, t, cv2.LINE_AA)

    x0, y0 = p.min(axis=0)
    x1, y1 = p.max(axis=0)
    h = y1 - y0
    x0, x1 = int(max(0, x0 - 0.3 * h)), int(min(img.shape[1], x1 + 0.3 * h))
    y0, y1 = int(max(0, y0 - 0.3 * h)), int(min(img.shape[0], y1 + 0.35 * h))
    crop = img[y0:y1, x0:x1]
    scale = 1000 / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""
