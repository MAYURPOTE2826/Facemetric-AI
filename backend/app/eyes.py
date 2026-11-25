"""Eye and brow proportions from face-mesh landmarks, with plain-language findings and brow advice.

RECONSTRUCTED MODULE. Every threshold below (eye openness 0.24 / 0.36, eye spacing 0.9 / 1.15, brow height 18 / 28 mm, brow slope -8 / 22 deg)
is a PLACEHOLDER with no verified source - PLACEHOLDER - NOT PRODUCTION VALIDATED. See docs/RECONSTRUCTED_MODULES.md.
"""
from __future__ import annotations

import base64
import math

import cv2
import numpy as np

from . import align, geometry
from . import landmark_map as LM

R_EYE = dict(out=LM.R_EYE_OUT, inn=LM.R_EYE_IN, up=LM.R_EYE_UP, low=LM.R_EYE_LOW, brow=LM.R_BROW_TOP, brow_in=LM.R_BROW_IN, brow_out=LM.R_BROW_OUT)
L_EYE = dict(out=LM.L_EYE_OUT, inn=LM.L_EYE_IN, up=LM.L_EYE_UP, low=LM.L_EYE_LOW, brow=LM.L_BROW_TOP, brow_in=LM.L_BROW_IN, brow_out=LM.L_BROW_OUT)


def _b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 93])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def analyze(img: np.ndarray, shape_points: np.ndarray, raw_points: np.ndarray, blink: float = 0.0) -> dict:
    p = shape_points
    k = geometry.mm_per_px(raw_points)
    findings: list[str] = []
    advice: list[str] = []

    def side(e):
        w = float(np.linalg.norm(p[e["out"], :2] - p[e["inn"], :2]))
        h = float(abs(p[e["up"], 1] - p[e["low"], 1]))
        bh = float(abs(p[e["brow"], 1] - p[e["up"], 1]))
        return w, h, bh

    rw, rh, rb = side(R_EYE)
    lw, lh, lb = side(L_EYE)
    eye_h = (rh + lh) / 2 * k
    brow_h = (rb + lb) / 2 * k
    aspect = (rh + lh) / max(rw + lw, 1e-6)
    gap = float(abs(p[LM.R_EYE_IN, 0] - p[LM.L_EYE_IN, 0]))
    gap_ratio = gap / max((rw + lw) / 2, 1e-6)

    if blink > 0.5:
        findings.append("Your eyes were partly closed in this photo, so eye openness may read low.")
    if aspect < 0.24:
        findings.append("Eyes are on the narrower side (low height-to-width ratio).")
        advice.append("Light, matte shades on the lid and a lifted outer lash line make narrow eyes read more open.")
    elif aspect > 0.36:
        findings.append("Eyes are on the rounder, more open side.")
        advice.append("Extend liner or lash definition toward the outer third to elongate round eyes.")
    else:
        findings.append("Eye openness is in the typical range.")
    if gap_ratio < 0.9:
        findings.append("Eyes sit relatively close together.")
        advice.append("Keep brow heads slightly apart and brighten the inner corners to add visual space.")
    elif gap_ratio > 1.15:
        findings.append("Eyes sit relatively wide apart.")
        advice.append("Start brows a touch closer to the nose and deepen the inner corners to balance spacing.")
    else:
        findings.append("Eye spacing is close to the classical one-eye-width ideal.")

    if 5 <= brow_h < 18:
        findings.append(f"Brows sit low (about {brow_h:.0f} mm above the eye).")
        advice.append("Clean up beneath the arch only, never above, to open the eye without thinning the brow.")
    elif brow_h > 28:
        findings.append(f"Brows sit high (about {brow_h:.0f} mm above the eye).")
        advice.append("Fill the lower edge of the brow slightly to bring the frame closer to the eye.")
    else:
        findings.append(f"Brow height is balanced (about {brow_h:.0f} mm above the eye).")

    # Brow arch position: highest point of the brow should sit about two thirds from the inner end.
    for name, e in (("right", R_EYE), ("left", L_EYE)):
        tilt = math.degrees(math.atan2(p[e["brow_in"], 1] - p[e["brow_out"], 1],
                                       abs(p[e["brow_out"], 0] - p[e["brow_in"], 0]) or 1))
        if name == "right" and tilt < -8:
            findings.append("Brow tails slope downward, which can look tired.")
            advice.append("Lift the tail of the brow slightly (thread or pencil along the lower edge).")
        elif name == "right" and tilt > 22:
            findings.append("Brows have a steep upward slant.")
            advice.append("Soften the tail so the brow ends level with the brow head.")
    if not advice:
        advice.append("Your brow and eye proportions are balanced - keep the natural shape and just tidy stray hairs.")

    # Annotated crop: level the photo on the pupil line, enlarge, then draw crisp eye/brow lines.
    lv, q, _ = align.level(img, raw_points)
    xs = q[:, 0]
    pad = 0.12 * (xs.max() - xs.min())
    y0 = int(max(q[[LM.R_BROW_TOP, LM.L_BROW_TOP, LM.R_BROW_OUT, LM.L_BROW_OUT, LM.R_BROW_IN, LM.L_BROW_IN], 1].min() - pad, 0))
    y1 = int(min(q[[LM.R_EYE_LOW, LM.L_EYE_LOW], 1].max() + pad, lv.shape[0]))
    x0 = int(max(xs.min() - pad * 0.5, 0))
    x1 = int(min(xs.max() + pad * 0.5, lv.shape[1]))
    crop = lv[y0:y1, x0:x1] if y1 > y0 and x1 > x0 else lv
    crop, sc = align.upscale(crop, 1000)
    th = max(2, int(crop.shape[1] / 450))
    pt = lambda i: (int((q[i, 0] - x0) * sc), int((q[i, 1] - y0) * sc))  # noqa: E731
    for e in (R_EYE, L_EYE):
        for a, b, col in ((e["inn"], e["out"], (60, 180, 255)), (e["up"], e["low"], (230, 200, 60)),
                          (e["brow_in"], e["brow_out"], (180, 105, 255)), ):
            cv2.line(crop, pt(a), pt(b), col, th, cv2.LINE_AA)
            for i in (a, b):
                cv2.circle(crop, pt(i), th + 1, col, -1, cv2.LINE_AA)
    for e in (R_EYE, L_EYE):  # brow height is measured straight up from the upper lid
        top, lid = pt(e["brow"]), pt(e["up"])
        cv2.line(crop, (lid[0], top[1]), lid, (230, 200, 60), th, cv2.LINE_AA)
        cv2.circle(crop, (lid[0], top[1]), th + 1, (230, 200, 60), -1, cv2.LINE_AA)
    ann_crop = crop

    return {
        "findings": findings, "advice": advice, "thresholds_status": "PLACEHOLDER - NOT PRODUCTION VALIDATED",
        "note": "Brow guidance is a starting point for your threading or grooming appointment, not a prescription.",
        "image": _b64(ann_crop), "eye_height_mm": round(eye_h, 1), "brow_height_mm": round(brow_h, 1),
    }
