"""Optional second landmark model (SPIGA) for a more accurate jaw corner (gonion).

MediaPipe's face mesh is weakest on the jaw outline; SPIGA (Prados-Torreblanca et al., BMVC 2022)
is a state-of-the-art 2D landmark model whose WFLW model traces the jaw with 33 points.
We use it only to re-place the two jaw-corner landmarks (MediaPipe 172 / 397) before the
jaw-width measurement; everything else stays MediaPipe.

LICENCE - CHECK BEFORE COMMERCIAL USE: the SPIGA code is BSD-3-Clause, but its pretrained weights
are trained on WFLW (from WIDER FACE), which is released for non-commercial research. So it is
off by default; set ENABLE_SPIGA=1 only after a legal review (or after retraining on licensed data).
Install: pip install spiga --extra-index-url https://download.pytorch.org/whl/cpu
(the weights, ~35 MB, download on first use).
"""
from __future__ import annotations

import logging
import os

import numpy as np

log = logging.getLogger(__name__)
R_GONION, L_GONION = 172, 397
_framework = None
_failed = False


def enabled() -> bool:
    return os.getenv("ENABLE_SPIGA", "") == "1" and not _failed


def _load():
    """SPIGA hard-codes CUDA; run it on CPU by skipping .cuda() while it loads and moving data to CPU."""
    global _framework
    if _framework is None:
        import torch
        from spiga.inference.config import ModelConfig
        from spiga.inference.framework import SPIGAFramework

        class CPUFramework(SPIGAFramework):
            def _data2device(self, data):
                if isinstance(data, dict):
                    return {k: self._data2device(v) for k, v in data.items()}
                if isinstance(data, list):
                    return [self._data2device(v) for v in data]
                return data.cpu() if hasattr(data, "cpu") else data

        cuda = torch.nn.Module.cuda
        torch.nn.Module.cuda = lambda self, *a, **k: self  # noqa: E731
        try:
            _framework = CPUFramework(ModelConfig("wflw"))
        finally:
            torch.nn.Module.cuda = cuda
    return _framework


# WFLW jaw-outline points at the jaw angles (0..32 runs image-left to image-right, 16 = chin).
GONION_IDX = {R_GONION: 8, L_GONION: 24}


def refine(bgr: np.ndarray, points: np.ndarray) -> tuple[np.ndarray, dict] | None:
    """Return (points with SPIGA jaw corners, info) or None if disabled / unavailable."""
    global _failed
    if not enabled():
        return None
    try:
        fw = _load()
        x0, y0 = points[:, :2].min(axis=0)
        x1, y1 = points[:, :2].max(axis=0)
        lms = np.asarray(fw.inference(bgr, [[float(x0), float(y0), float(x1 - x0), float(y1 - y0)]])["landmarks"][0])
    except Exception as e:  # noqa: BLE001 - optional model; fall back to MediaPipe
        log.warning("SPIGA unavailable, using MediaPipe jaw: %s", e)
        _failed = True
        return None
    contour = lms[:33]  # WFLW 0..32: jaw outline from image-left to image-right, 16 = chin
    out = points.copy()
    moved = []
    for idx, w in GONION_IDX.items():
        new = contour[w]
        moved.append(float(np.linalg.norm(new - points[idx, :2])))
        out[idx, :2] = new
    bz = float(np.linalg.norm(points[234, :2] - points[454, :2]))
    return out, {"model": "spiga-wflw", "gonion_shift_pct": round(100 * max(moved) / bz, 1)}
