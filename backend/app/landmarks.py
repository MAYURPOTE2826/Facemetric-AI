"""Face detection + 478-point landmarking via MediaPipe Face Landmarker."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"

_landmarker: vision.FaceLandmarker | None = None


def _get_landmarker() -> vision.FaceLandmarker:
    global _landmarker
    if _landmarker is None:
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=2,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
        _landmarker = vision.FaceLandmarker.create_from_options(options)
    return _landmarker


@dataclass
class FaceDetection:
    points: np.ndarray  # (478, 3) pixel coords; z scaled by image width
    pose: dict[str, float]  # yaw / pitch / roll in degrees
    blendshapes: dict[str, float]
    num_faces: int
    second_face_ratio: float = 0.0  # width of the 2nd-largest face / width of the analysed face (0 if only one)


def detect(bgr: np.ndarray) -> FaceDetection | None:
    """Landmarks for the largest face. The face detector misses faces narrower than ~1/5 of
    the frame (e.g. arm's-length shots on landscape webcams), so if nothing is found we retry
    on centred crops and map the points back to the full image."""
    h, w = bgr.shape[:2]
    for frac in (1.0, 0.7, 0.5):
        cw, ch = int(w * frac), int(h * frac)
        x0, y0 = (w - cw) // 2, (h - ch) // 2
        found = _detect(bgr[y0:y0 + ch, x0:x0 + cw])
        if found is not None:
            if frac < 1.0:
                found.points[:, 0] += x0
                found.points[:, 1] += y0
            return found
    return None


def _detect(bgr: np.ndarray) -> FaceDetection | None:
    h, w = bgr.shape[:2]
    rgb = cv2.cvtColor(np.ascontiguousarray(bgr), cv2.COLOR_BGR2RGB)
    result = _get_landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not result.face_landmarks:
        return None

    # Use the largest face if more than one is present.
    def face_width(lms):
        xs = [p.x for p in lms]
        return max(xs) - min(xs)

    idx = max(range(len(result.face_landmarks)), key=lambda i: face_width(result.face_landmarks[i]))
    lms = result.face_landmarks[idx]
    points = np.array([[p.x * w, p.y * h, p.z * w] for p in lms], dtype=np.float64)

    pose = {"yaw": 0.0, "pitch": 0.0, "roll": 0.0}
    if result.facial_transformation_matrixes:
        rot = np.array(result.facial_transformation_matrixes[idx])[:3, :3]
        angles, *_ = cv2.RQDecomp3x3(rot)
        pose = {"pitch": float(angles[0]), "yaw": float(angles[1]), "roll": float(angles[2])}

    blend = {}
    if result.face_blendshapes:
        blend = {c.category_name: float(c.score) for c in result.face_blendshapes[idx]}

    widths = sorted((face_width(f) for f in result.face_landmarks), reverse=True)
    ratio = float(widths[1] / widths[0]) if len(widths) > 1 and widths[0] > 0 else 0.0
    return FaceDetection(points=points, pose=pose, blendshapes=blend, num_faces=len(result.face_landmarks), second_face_ratio=ratio)
