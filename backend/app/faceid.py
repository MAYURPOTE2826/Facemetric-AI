"""Aligned-face models: image quality (eDifFIQA-tiny, CC-BY-4.0) and identity (SFace, Apache-2.0).

Both expect the ArcFace 112x112 alignment, built here from MediaPipe landmarks (pupils, nose
tip, mouth corners) instead of a separate face detector.
- quality(): eDifFIQA predicts how useful a face image is for recognition - it drops with
  blur, noise, bad exposure, occlusion and extreme pose (Babnik et al., IEEE TBIOM 2024).
- same_person(): SFace cosine similarity; OpenCV's threshold for "same person" is 0.363.
  Used to reject AI try-on images that changed who the person is.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODELS = Path(__file__).resolve().parent.parent / "models"
QUALITY_MODEL = MODELS / "ediffiqa_tiny_jun2024.onnx"
SFACE_MODEL = MODELS / "face_recognition_sface_2021dec.onnx"
SAME_PERSON = 0.363

# ArcFace reference points for a 112x112 crop: right eye, left eye, nose tip, mouth corners
# (image left/right, as seen in the photo).
ARCFACE = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                    [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)
FIVE = (468, 473, 1, 61, 291)

_quality = None
_sface = None


def align(bgr: np.ndarray, points: np.ndarray) -> np.ndarray:
    src = points[list(FIVE), :2].astype(np.float32)
    m, _ = cv2.estimateAffinePartial2D(src, ARCFACE, method=cv2.LMEDS)
    return cv2.warpAffine(bgr, m, (112, 112), borderValue=0)


def quality(bgr: np.ndarray, points: np.ndarray) -> float | None:
    """eDifFIQA score (higher = better; roughly 0.2 poor to 0.8 excellent). None if the model is missing."""
    global _quality
    if not QUALITY_MODEL.exists():
        return None
    if _quality is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _quality = ort.InferenceSession(str(QUALITY_MODEL), opts, providers=["CPUExecutionProvider"])
    face = cv2.cvtColor(align(bgr, points), cv2.COLOR_BGR2RGB).astype(np.float32)
    x = ((face / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    return float(_quality.run(None, {"input": x})[0].ravel()[0])


def embedding(bgr: np.ndarray, points: np.ndarray) -> np.ndarray | None:
    global _sface
    if not SFACE_MODEL.exists():
        return None
    if _sface is None:
        _sface = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")
    return _sface.feature(align(bgr, points))


def same_person(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two SFace embeddings (>= SAME_PERSON: same person)."""
    return float(_sface.match(a, b, cv2.FaceRecognizerSF_FR_COSINE))
