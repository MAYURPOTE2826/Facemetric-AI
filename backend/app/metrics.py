"""Aesthetic measurements computed from MediaPipe face-mesh landmarks (frontal photo).

Reference ranges below are starting values drawn from common facial-proportion
literature. They are placeholders to be calibrated per sex / ethnicity / age by
an expert before launch.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

# --- landmark indices now live in landmark_map.py (single documented source) ---
from .landmark_map import (  # noqa: F401
    FOREHEAD, GLABELLA, LOWER_LIP_BOTTOM, LOWER_LIP_IN, L_ALA, L_BROW_TOP, L_EYE_IN, L_EYE_LOW, L_EYE_OUT, L_EYE_UP, L_GONION, L_IRIS, L_MOUTH, L_ZYGO, MENTON, MIDLINE, MIDLINE_STABLE, NASION, NOSE_TIP, R_ALA, R_BROW_TOP, R_EYE_IN, R_EYE_LOW, R_EYE_OUT, R_EYE_UP, R_GONION, R_IRIS, R_MOUTH, R_ZYGO, SUBNASALE, SYMMETRY_PAIRS, UPPER_LIP_IN, UPPER_LIP_TOP,
)


@dataclass
class Metric:
    key: str
    label: str
    category: str
    value: float
    unit: str
    ideal: float
    tolerance: float
    score: float
    status: str  # "ideal" | "near" | "outside"
    direction: str  # "low" | "high" | "ok"
    description: str


def _ref(sex: str) -> dict[str, tuple[float, float]]:
    male = sex.lower().startswith("m")
    return {
        # SOURCE CLAIMS UNVERIFIED: the author's note says these follow the literature, re-centred on Indian anthropometric
        # data (Kerala/North-Indian studies; Farkas 2005). None of those sources was re-checked; see REFERENCE_STATUS.
        "canthal_tilt": (5.0, 4.0),
        "eye_aspect": (0.30, 0.06),
        "intercanthal_eye": (1.0, 0.12),
        "esr": (0.46, 0.025),
        "fwhr": (1.9, 0.15),  # sex difference is negligible after body size (meta-analysis d=0.11)
        "midface_ratio": (1.0, 0.08),
        "thirds_lower_mid": (1.0 if male else 0.95, 0.10),
        "lower_third_split": (0.50, 0.07),
        "nose_intercanthal": (1.15, 0.15),  # unverified: claimed Indian alar width ~1.2-1.3x intercanthal; canon 1.0
        "mouth_nose": (1.40, 0.15),  # unverified: claimed Kerala sample 1.32-1.35; canon 1.5-1.6
        "lip_ratio": (1.6, 0.35),
        "jaw_zygo": (0.86 if male else 0.80, 0.05),
    }


def _score(value: float, ideal: float, tol: float) -> tuple[float, str, str]:
    z = (value - ideal) / tol
    score = 100.0 * math.exp(-0.5 * (z / 1.5) ** 2)
    status = "ideal" if abs(z) <= 1 else "near" if abs(z) <= 2 else "outside"
    direction = "ok" if abs(z) <= 1 else ("low" if z < 0 else "high")
    return round(score, 1), status, direction


def _yaw_rotate(points: np.ndarray, deg: float) -> np.ndarray:
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    centre = points.mean(axis=0)
    q = points - centre
    x = q[:, 0] * c + q[:, 2] * s
    z = -q[:, 0] * s + q[:, 2] * c
    return np.stack([x, q[:, 1], z], axis=1) + centre


def _side_imbalance(points: np.ndarray) -> float:
    xs = points[:, 0]
    mid_x = np.median(xs[MIDLINE_STABLE])
    left = sum(abs(xs[l] - mid_x) for _, l in SYMMETRY_PAIRS)
    right = sum(abs(xs[r] - mid_x) for r, _ in SYMMETRY_PAIRS)
    return abs(left - right)


REFERENCE_STATUS = ("Ideal values and tolerances are literature-derived approximations; their source claims have NOT been verified and they are NOT "
                    "calibrated to any population - PLACEHOLDER - NOT PRODUCTION VALIDATED")
YAW_SEARCH_LIMIT = 30.0  # degrees; the search grid is [-30, +30]


def frontalize_with_status(points: np.ndarray) -> tuple[np.ndarray, float, str]:
    """Undo head yaw by rotating the 3D landmarks about the vertical axis until the two halves of the face are
    balanced. Returns (points, estimated_yaw_deg, status).

    status:
      "ok"           the best balance was found strictly inside the search range.
      "saturated"    the best balance is at the edge of the +/-30 deg search (the true turn is larger, or the
                     result wrapped to the wrong side): the correction is PARTIAL and must not be treated as a
                     normal frontalised face. Measured: a known extra turn beyond the range clamps at +/-30.5 deg and
                     can even flip sign.
      "undetermined" the balance measure does not change with rotation (no usable depth), so no yaw can be
                     estimated. No rotation is applied (previously the tie was broken toward -30 deg).
    Note: this also absorbs a small amount of genuine left/right width difference."""
    # Remove in-plane roll FIRST. The balance measure compares x-distances to the midline, so a rolled head leaks
    # into the yaw estimate (measured on a synthetic symmetric face whose true yaw is 0: 2 deg of roll gave -7.3 deg
    # of "yaw", and 10 deg of roll saturated the search). Levelled first, the yaw estimate is exact.
    points = _level3(points)
    grid = np.arange(-YAW_SEARCH_LIMIT, YAW_SEARCH_LIMIT + 0.5, 0.5)
    scores = np.array([_side_imbalance(_yaw_rotate(points, d)) for d in grid])
    scale = max(1.0, float(np.abs(points[:, 0]).max()))
    if float(scores.max() - scores.min()) < 1e-9 * scale:
        return points, 0.0, "undetermined"
    # among (numerically) equal minima prefer the smallest rotation, never the first one in the grid
    coarse = min(zip(np.round(scores, 9), np.abs(grid), grid))[2]
    fine_grid = np.arange(coarse - 0.5, coarse + 0.55, 0.05)
    fine = min((round(_side_imbalance(_yaw_rotate(points, d)), 9), abs(d), d) for d in fine_grid)
    yaw = float(fine[2])
    status = "saturated" if abs(yaw) >= YAW_SEARCH_LIMIT - 0.5 else "ok"
    return _yaw_rotate(points, yaw), yaw, status


def frontalize(points: np.ndarray) -> tuple[np.ndarray, float]:
    """Compatibility wrapper: (points, yaw). Use frontalize_with_status() where the reliability matters."""
    p, yaw, _ = frontalize_with_status(points)
    return p, yaw


def _level3(points: np.ndarray) -> np.ndarray:
    """Rotate x, y (in the image plane, about the pupil midpoint) so the inter-pupil line is horizontal; z is kept."""
    out = points.copy()
    out[:, :2] = _level(points)
    return out


def _level(points: np.ndarray) -> np.ndarray:
    """Rotate 2D points so the inter-pupil line is horizontal (removes head roll)."""
    p = points[:, :2].copy()
    r, l = p[R_IRIS], p[L_IRIS]
    angle = math.atan2(l[1] - r[1], l[0] - r[0])
    c, s = math.cos(-angle), math.sin(-angle)
    centre = (r + l) / 2
    rot = np.array([[c, -s], [s, c]])
    return (p - centre) @ rot.T + centre


def compute(points: np.ndarray, sex: str = "unspecified") -> dict:
    frontal, yaw_correction, yaw_status = frontalize_with_status(points)
    p = _level(frontal)
    d = lambda a, b: float(np.linalg.norm(p[a] - p[b]))  # noqa: E731
    dy = lambda a, b: float(abs(p[b][1] - p[a][1]))  # noqa: E731

    ref = _ref(sex)
    raw: dict[str, float] = {}

    # Eyes
    def tilt(inner, outer):
        dx = abs(p[outer][0] - p[inner][0])
        return math.degrees(math.atan2(p[inner][1] - p[outer][1], dx))

    raw["canthal_tilt"] = (tilt(R_EYE_IN, R_EYE_OUT) + tilt(L_EYE_IN, L_EYE_OUT)) / 2
    r_w, l_w = d(R_EYE_IN, R_EYE_OUT), d(L_EYE_IN, L_EYE_OUT)
    eye_w = (r_w + l_w) / 2
    raw["eye_aspect"] = (dy(R_EYE_UP, R_EYE_LOW) / r_w + dy(L_EYE_UP, L_EYE_LOW) / l_w) / 2
    intercanthal = d(R_EYE_IN, L_EYE_IN)
    raw["intercanthal_eye"] = intercanthal / eye_w

    # Overall proportions
    bizygo = d(R_ZYGO, L_ZYGO)
    ipd = d(R_IRIS, L_IRIS)
    raw["esr"] = ipd / bizygo
    brow_y = (p[R_BROW_TOP][1] + p[L_BROW_TOP][1]) / 2  # standard fWHR: brow to upper lip (not eyelid)
    raw["fwhr"] = bizygo / abs(p[UPPER_LIP_TOP][1] - brow_y)
    pupil_y = (p[R_IRIS][1] + p[L_IRIS][1]) / 2
    raw["midface_ratio"] = ipd / abs(p[UPPER_LIP_TOP][1] - pupil_y)
    raw["thirds_lower_mid"] = dy(SUBNASALE, MENTON) / dy(GLABELLA, SUBNASALE)
    stomion_y = (p[UPPER_LIP_IN][1] + p[LOWER_LIP_IN][1]) / 2
    raw["lower_third_split"] = abs(stomion_y - p[SUBNASALE][1]) / abs(p[MENTON][1] - stomion_y)

    # Nose & mouth
    nose_w = d(R_ALA, L_ALA)
    raw["nose_intercanthal"] = nose_w / intercanthal
    raw["mouth_nose"] = d(R_MOUTH, L_MOUTH) / nose_w
    upper_lip = dy(UPPER_LIP_TOP, UPPER_LIP_IN)
    raw["lip_ratio"] = dy(LOWER_LIP_IN, LOWER_LIP_BOTTOM) / max(upper_lip, 1e-6)

    # Jaw
    raw["jaw_zygo"] = d(R_GONION, L_GONION) / bizygo

    meta = {
        "canthal_tilt": ("Canthal tilt", "eyes", "°", "Angle of the line from inner to outer eye corner. Slight positive (upward) tilt is commonly considered attractive."),
        "eye_aspect": ("Eye openness", "eyes", "ratio", "Eye height divided by eye width."),
        "intercanthal_eye": ("Eye spacing (rule of fifths)", "eyes", "ratio", "Gap between the eyes divided by one eye's width. Classical ideal is 1.0."),
        "esr": ("Eye separation ratio", "proportions", "ratio", "Pupil distance divided by cheekbone width. ~0.46 is the value reported as most attractive in one perception study (Pallett et al. 2010; citation not re-verified here)."),
        "fwhr": ("Facial width-to-height ratio", "proportions", "ratio", "Cheekbone width divided by brow-to-upper-lip height."),
        "midface_ratio": ("Midface ratio", "proportions", "ratio", "Pupil distance divided by pupil-to-upper-lip height. ~1.0 reads as a compact, balanced midface."),
        "thirds_lower_mid": ("Facial thirds (lower : middle)", "proportions", "ratio", "Subnasale-to-chin height vs brow-to-subnasale height. Equal thirds is the classical ideal."),
        "lower_third_split": ("Lower-third split", "lips", "ratio", "Nose-to-mouth vs mouth-to-chin height. Ideal is about 1:2."),
        "nose_intercanthal": ("Nose width vs eye gap", "nose", "ratio", "Nose (alar) width divided by the gap between the eyes. The classical canon is 1.0; the reference used here (~1.15) is an unverified approximation for South Asian faces."),
        "mouth_nose": ("Mouth width vs nose width", "lips", "ratio", "Mouth width divided by nose width. The classical canon is 1.5-1.6; the reference used here (~1.35-1.4) is an unverified approximation for Indian faces."),
        "lip_ratio": ("Lip ratio (lower : upper)", "lips", "ratio", "Lower lip height vs upper lip height. Ideal ~1.6."),
        "jaw_zygo": ("Jaw-to-cheekbone width", "jaw", "ratio", "Jaw width divided by cheekbone width."),
    }

    metrics: list[Metric] = []
    for key, value in raw.items():
        ideal, tol = ref[key]
        score, status, direction = _score(value, ideal, tol)
        label, category, unit, desc = meta[key]
        metrics.append(Metric(key, label, category, round(value, 3), unit, ideal, tol, score, status, direction, desc))

    # Symmetry: compare each left/right pair's distance from a fitted midline.
    mid = p[MIDLINE_STABLE]
    a, b = np.polyfit(mid[:, 1], mid[:, 0], 1)  # x = a*y + b
    norm = math.sqrt(1 + a * a)
    devs = []
    for r, l in SYMMETRY_PAIRS:
        dr = abs(p[r][0] - (a * p[r][1] + b)) / norm
        dl = abs(p[l][0] - (a * p[l][1] + b)) / norm
        devs.append((abs(dr - dl) + abs(p[r][1] - p[l][1])) / bizygo)
    asym = float(np.mean(devs))
    sym_score = round(max(0.0, 100.0 - asym * 400.0), 1)
    metrics.append(Metric(
        "symmetry", "Facial symmetry", "symmetry", round(asym * 100, 2), "% deviation", 0.0, 1.5,
        sym_score, "ideal" if asym * 100 <= 1.5 else "near" if asym * 100 <= 3 else "outside",
        "ok" if asym * 100 <= 1.5 else "high",
        "Average left/right landmark mismatch as a percentage of face width. Everyone is a little asymmetric; under 2% is typical.",
    ))

    out = {"metrics": [asdict(m) for m in metrics], "yaw_correction": round(yaw_correction, 1), "yaw_correction_status": yaw_status}
    out.update(rescore(out["metrics"]))
    return out


def rescore(metrics: list[dict]) -> dict:
    """Category scores (mean per category) and the overall harmony score (mean of categories)."""
    categories: dict[str, list[float]] = {}
    for m in metrics:
        categories.setdefault(m["category"], []).append(m["score"])
    category_scores = {k: round(sum(v) / len(v), 1) for k, v in categories.items()}
    return {
        "category_scores": category_scores,
        "harmony_score": round(sum(category_scores.values()) / len(category_scores), 1),
    }
