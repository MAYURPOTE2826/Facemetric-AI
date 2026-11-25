"""Facial measurements in millimetres (frontal photo), compared with typical adult ranges.

RECONSTRUCTED MODULE (the original was lost). Scale comes from the iris (geometry.mm_per_px; an unvalidated constant).
The 'typical' mean +/- SD in _SPEC are APPROXIMATE VALUES WITH NO VERIFIED SOURCE: they were written from general knowledge, not taken
from a cited dataset, and are not calibrated to any population. They are labelled PLACEHOLDER - NOT PRODUCTION VALIDATED everywhere
they are shown, and must be replaced by values from a cited, appropriate reference (or calibrated on consented data) by an expert.
See docs/RECONSTRUCTED_MODULES.md.
"""
from __future__ import annotations

import numpy as np

from . import geometry
from .landmark_map import (LOWER_LIP_BOTTOM, L_ALA, L_EYE_IN, L_EYE_OUT, L_FOREHEAD_SIDE, L_GONION, L_MOUTH, L_ZYGO, MENTON, NASION, R_ALA, R_EYE_IN, R_EYE_OUT, R_FOREHEAD_SIDE, R_GONION, R_MOUTH, R_ZYGO, SUBNASALE, UPPER_LIP_IN)

# (key, label, group, landmark a, landmark b, axis, male (mean, sd), female (mean, sd), description)
# axis: "x" horizontal distance, "y" vertical distance, "d" straight-line distance
_SPEC = [
    ("face_width", "Face width (bizygomatic)", "Face", R_ZYGO, L_ZYGO, "x", (138, 6), (130, 6),
     "Distance between the outermost points of the cheekbones."),
    ("jaw_width", "Jaw width (bigonial)", "Face", R_GONION, L_GONION, "x", (106, 7), (98, 6),
     "Distance between the two jaw corners."),
    ("face_height", "Nasion-to-chin height", "Face", NASION, MENTON, "y", (118, 7), (111, 6),
     "Nasion (between the eyes) to the bottom of the chin."),
    ("forehead_width", "Forehead width", "Face", R_FOREHEAD_SIDE, L_FOREHEAD_SIDE, "x", (112, 7), (106, 6),
     "Width across the temples at the top of the forehead."),
    ("intercanthal", "Inner eye gap (intercanthal)", "Eyes", R_EYE_IN, L_EYE_IN, "x", (33, 3), (32, 3),
     "Distance between the inner corners of the eyes."),
    ("biocular", "Outer eye width (biocular)", "Eyes", R_EYE_OUT, L_EYE_OUT, "x", (92, 5), (88, 5),
     "Distance between the outer corners of the eyes."),
    ("eye_width_r", "Right eye width", "Eyes", R_EYE_OUT, R_EYE_IN, "d", (30, 2), (29, 2), "Width of the subject's right eye."),
    ("eye_width_l", "Left eye width", "Eyes", L_EYE_IN, L_EYE_OUT, "d", (30, 2), (29, 2), "Width of the subject's left eye."),
    ("nose_width", "Nose width (alar)", "Nose", R_ALA, L_ALA, "x", (38, 3), (34, 3), "Width across the nostril wings."),
    ("nose_length", "Nose length", "Nose", NASION, SUBNASALE, "y", (50, 4), (47, 4), "Nasion to the base of the nose."),
    ("mouth_width", "Mouth width", "Lips", R_MOUTH, L_MOUTH, "x", (50, 4), (47, 4), "Distance between the mouth corners."),
    ("upper_lip", "Upper lip height", "Lips", SUBNASALE, UPPER_LIP_IN, "y", (22, 3), (20, 3), "Base of the nose to the lip line."),
    ("lower_face", "Lower face height", "Face", SUBNASALE, MENTON, "y", (66, 5), (61, 5), "Base of the nose to the chin."),
    ("chin_height", "Chin height", "Face", LOWER_LIP_BOTTOM, MENTON, "y", (44, 4), (40, 4), "Lower lip to the bottom of the chin."),
]

RANGE_STATUS = "PLACEHOLDER - NOT PRODUCTION VALIDATED"

# Rows that need the jawline / chin, which a beard hides.
BEARD_HIDDEN = {"jaw_width", "face_height", "lower_face", "chin_height"}


def _dist(p: np.ndarray, a: int, b: int, axis: str) -> float:
    if axis == "x":
        return float(abs(p[a, 0] - p[b, 0]))
    if axis == "y":
        return float(abs(p[a, 1] - p[b, 1]))
    return float(np.linalg.norm(p[a, :2] - p[b, :2]))


def table(points: np.ndarray, sex: str = "unspecified") -> dict:
    k = geometry.mm_per_px(points)
    male = not str(sex).lower().startswith("f")
    rows = []
    for key, label, group, a, b, axis, m, f, desc in _SPEC:
        mean, sd = m if male else f
        value = round(_dist(points, a, b, axis) * k, 1)
        dev = (value - mean) / mean * 100
        status = "typical" if abs(value - mean) <= sd * 1.5 else ("above" if value > mean else "below")
        rows.append({
            "key": key, "label": label, "group": group, "value": value, "unit": "mm", "mean": mean,
            "range": [round(mean - 1.5 * sd, 1), round(mean + 1.5 * sd, 1)],
            "deviation_pct": round(dev, 1), "status": status, "description": desc,
        })
    v = {r["key"]: r["value"] for r in rows}
    ratios = []

    def ratio(key, label, num, den, note):
        if v.get(den):
            ratios.append({"key": key, "label": label, "value": round(v[num] / v[den], 2), "unit": "ratio", "note": note})

    ratio("face_wh", "Face width : height", "face_width", "face_height", "Width divided by nasion-to-chin height.")
    ratio("jaw_face", "Jaw : face width", "jaw_width", "face_width", "Lower the ratio, the more tapered the jaw.")
    ratio("nose_eye", "Nose width : eye gap", "nose_width", "intercanthal", "Classical canon is about 1.0.")
    ratio("mouth_nose", "Mouth : nose width", "mouth_width", "nose_width", "Classically about 1.5.")
    return {
        "rows": rows, "ratios": ratios, "range_status": RANGE_STATUS,
        # Honest capability statement: scale is estimated, NOT validated against ground-truth measurements.
        "calibration": {
            "method": "iris_constant", "reference_mm": geometry.IRIS_MM, "mm_per_px": round(k, 4), "validated": False,
        },
        "note": "Estimated sizes. Scale is inferred from your iris width, assuming the population-average iris "
                "diameter (11.7 mm). Individual iris size varies, which alone scales every size by the same unknown factor, "
                "before landmark error. This method has not been validated against physical measurements, so "
                "treat millimetre values as approximate; ratios do not depend on the scale estimate. Typical "
                "ranges are approximate adult norms, not a diagnosis.",
    }


def withhold(tbl: dict, keys: set[str]) -> list[str]:
    """Remove rows whose measurement a beard makes unreliable; return their labels."""
    gone = [r["label"] for r in tbl["rows"] if r["key"] in keys]
    tbl["rows"] = [r for r in tbl["rows"] if r["key"] not in keys]
    tbl["ratios"] = [r for r in tbl["ratios"] if r["key"] != "jaw_face"] if "jaw_width" in keys else tbl["ratios"]
    return gone
