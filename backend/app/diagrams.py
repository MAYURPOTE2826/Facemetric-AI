"""Report figures drawn on the original photo: mm overlay, rule of fifths, thirds, mirror faces.

The photo is first levelled on the pupil line and cropped, upscaled, then every overlay is drawn at
the final resolution so lines are crisp and square to the face.
"""
from __future__ import annotations

import base64

import cv2
import numpy as np

from . import align
from . import landmark_map as LM
from .landmark_map import MIDLINE_STABLE

GOLD = (80, 200, 255)
CYAN = (230, 200, 60)
WHITE = (255, 255, 255)


def _b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 93])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def _text(img, s, org, scale, th=1):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (20, 20, 20), th + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, WHITE, th, cv2.LINE_AA)


def build(img: np.ndarray, pts: np.ndarray, mm: dict, k_raw: float, hairline_y: float | None = None) -> dict:
    out: dict[str, str] = {}
    lv, p, m = align.level(img, pts)
    top_y = align.transform_y(m, pts[LM.FOREHEAD, 0], hairline_y) if hairline_y is not None else p[LM.FOREHEAD, 1]

    h, w = lv.shape[:2]
    x0, x1 = p[:, 0].min(), p[:, 0].max()
    y0, y1 = min(p[:, 1].min(), top_y), p[:, 1].max()
    padx, pady = (x1 - x0) * 0.25, (y1 - y0) * 0.12
    cx0, cy0 = int(max(x0 - padx, 0)), int(max(y0 - pady, 0))
    cx1, cy1 = int(min(x1 + padx, w)), int(min(y1 + pady, h))
    base = lv[cy0:cy1, cx0:cx1]
    if base.size == 0:
        return out
    base, s = align.upscale(base)
    th = max(2, int(base.shape[1] / 450))
    fs = max(0.8, base.shape[1] / 700)

    def P(i):  # landmark -> crop pixel (levelled, upscaled)
        return ((p[i, 0] - cx0) * s, (p[i, 1] - cy0) * s)

    top = (top_y - cy0) * s
    bottom = P(LM.MENTON)[1]
    # True facial midline from stable landmarks (levelled, so it is vertical).
    mid_x = float(np.mean([P(i)[0] for i in MIDLINE_STABLE]))

    def vline(im, x, ya, yb, col=GOLD):
        cv2.line(im, (int(x), int(ya)), (int(x), int(yb)), col, th, cv2.LINE_AA)

    def hline(im, y, xa=0, xb=None, col=GOLD):
        cv2.line(im, (int(xa), int(y)), (int(xb if xb is not None else im.shape[1]), int(y)), col, th, cv2.LINE_AA)

    # Measurements overlay (true distances, on the levelled photo)
    f = base.copy()
    for key, a, b in (("face_width", LM.R_ZYGO, LM.L_ZYGO), ("biocular", LM.R_EYE_OUT, LM.L_EYE_OUT), ("nose_width", LM.R_ALA, LM.L_ALA), ("mouth_width", LM.R_MOUTH, LM.L_MOUTH)):
        if key in mm:
            (ax, ay), (bx, by) = P(a), P(b)
            cv2.line(f, (int(ax), int(ay)), (int(bx), int(by)), GOLD, th, cv2.LINE_AA)
            for q in ((ax, ay), (bx, by)):
                cv2.circle(f, (int(q[0]), int(q[1])), th + 1, GOLD, -1, cv2.LINE_AA)
            label = f"{mm[key]:.0f} mm"
            (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)
            # stagger labels so the eye / nose / mouth readings never overlap each other
            dy = {"face_width": -14, "biocular": -14, "nose_width": 26, "mouth_width": 30}[key] * fs
            _text(f, label, (int((ax + bx) / 2 - tw / 2), int((ay + by) / 2 + dy)), fs * 1.1)
    out["measurements"] = _b64(f)

    # Rule of fifths: verticals at the face edges and the four eye corners
    fi = base.copy()
    for i in (LM.R_ZYGO, LM.R_EYE_OUT, LM.R_EYE_IN, LM.L_EYE_IN, LM.L_EYE_OUT, LM.L_ZYGO):
        vline(fi, P(i)[0], top, bottom)
    xs = sorted(P(i)[0] for i in (LM.R_ZYGO, LM.R_EYE_OUT, LM.R_EYE_IN, LM.L_EYE_IN, LM.L_EYE_OUT, LM.L_ZYGO))
    for a, b, name in zip(xs[::1], xs[1:], ("1", "2", "3", "4", "5")):
        if name in ("1", "3", "5"):
            width_mm = (b - a) / s * k_raw
            _text(fi, f"{width_mm:.0f} mm", (int((a + b) / 2 - 22 * fs), int(top - 8 * fs)), fs * 0.8)
    out["fifths"] = _b64(fi)

    # Thirds: hairline, brow line (glabella), base of nose, chin - with real heights
    t = base.copy()
    ys = [top, P(LM.GLABELLA)[1], P(LM.SUBNASALE)[1], bottom]
    for y in ys:
        hline(t, y)
    for (ya, yb), name in zip(zip(ys, ys[1:]), ("Upper", "Middle", "Lower")):
        mm_h = (yb - ya) / s * k_raw
        _text(t, f"{name} {mm_h:.0f} mm", (10, int((ya + yb) / 2)), fs * 0.8)
    out["thirds"] = _b64(t)

    # Mirror faces around the true midline (levelled, so left/right halves line up)
    mx = int(min(max(mid_x, 2), base.shape[1] - 2))
    left, right = base[:, :mx], base[:, mx:]
    n = min(left.shape[1], right.shape[1])
    if n > 0:
        lh, rh = left[:, -n:], right[:, :n]
        out["symmetry_right"] = _b64(np.hstack([lh, cv2.flip(lh, 1)]))
        out["symmetry_left"] = _b64(np.hstack([cv2.flip(rh, 1), rh]))
    return out
