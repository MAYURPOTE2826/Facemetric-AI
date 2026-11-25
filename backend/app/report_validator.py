"""Central report validator: decides which analysis results may be shown, BEFORE recommendations and the report are
built from them. Modules produce raw results; this layer withholds or flags the ones the photo cannot support and
records every decision in `analysis["validation"]` so the report is auditable.

Rules (the letters match docs/REPORT_VALIDATION.md):
  A poor light/exposure  -> drop the skin concerns that depend on brightness
  B physical calibration -> mm are only ever "estimated" (never validated); unusable scale -> mm withheld, ratios kept
  C colour cast          -> drop colour-derived skin concerns and the skin-tone group
  D beauty filter        -> flag texture / line / blemish readings as likely understated
  E extreme head pose    -> drop symmetry when frontalisation saturated; flag width ratios
  F missing crown photo  -> no overall hair score
  G invalid landmarks    -> reject the photo; never substitute defaults
  H failed module        -> explicit "unavailable" status
  I unsupported confidence-> heuristic "confidence" numbers are not published

Nothing here invents a value: every rule only removes, flags or relabels what a module already produced.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

MEASUREMENT_VERSION = "measurements-v2"
VALIDATOR_VERSION = "validator-v1"

# --- per-metric skin requirements -------------------------------------------------------------------------------
# Each skin metric declares what it DEPENDS on. A quality flag affects only the dependencies it actually damages, so a
# colour cast withholds colour-based metrics but leaves a texture metric alone (and vice versa).
#   colour      chroma / hue (a*, b*): redness, tone, pigmentation, under-eye colour
#   exposure    absolute lightness: tone, patches, shine
#   detail      fine spatial detail: texture, lines, small blemishes
#   eye_region  needs a clean, unobstructed eye area (under-eye colour)
#   eye_region_partial  uses the eye area among other zones (wrinkles also use forehead and smile lines)
#   lower_face  measured over the cheeks/chin, which facial hair or a beard-excluding mask makes unreliable
#   even_light  compares regions of the face with each other
SKIN_NEEDS = {
    "uneven_tone":  {"colour", "exposure", "even_light", "lower_face"},
    "pigmentation": {"colour", "exposure", "even_light"},
    "redness":      {"colour"},
    "dark_circles": {"colour", "eye_region"},
    "acne_marks":   {"colour", "lower_face"},
    "blemishes":    {"colour", "detail", "lower_face"},
    "dark_spots":   {"colour"},
    "shine":        {"exposure"},
    "texture":      {"detail", "lower_face"},
    "wrinkles":     {"detail", "eye_region_partial"},
}
# quality flag -> {dependency: "withhold" | "flag"}
FLAG_EFFECTS = {
    "colour_cast":    {"colour": "withhold"},
    "too_bright":     {"exposure": "withhold"},
    "too_dark":       {"exposure": "withhold", "colour": "flag"},
    "beauty_filter":  {"detail": "flag"},
    "blurry":         {"detail": "withhold"},
    "low_resolution": {"detail": "flag"},
    "glasses":        {"eye_region": "withhold", "eye_region_partial": "flag"},
    "uneven_light":   {"even_light": "flag"},
    "beard":          {"lower_face": "flag"},
}
FLAG_REASON = {
    "colour_cast": "a strong colour cast in the photo makes colour readings unreliable",
    "too_bright": "the photo is over-exposed, which distorts lightness and shine readings",
    "too_dark": "the photo is too dark for reliable lightness and colour readings",
    "beauty_filter": "smoothing or a filter was detected, so fine detail is likely understated",
    "blurry": "the photo is too blurry to resolve fine detail",
    "low_resolution": "the photo resolution is low for fine detail",
    "glasses": "glasses frames overlap the eye area",
    "uneven_light": "the face is unevenly lit, which skews comparisons between regions",
    "beard": "a beard covers part of the lower face, so the skin mask there is unreliable",
}
# Derived views (kept for tests and docs)
COLOUR_SKIN = {k for k, n in SKIN_NEEDS.items() if "colour" in n}
BRIGHTNESS_SKIN = {k for k, n in SKIN_NEEDS.items() if "exposure" in n}
DARK_SKIN = BRIGHTNESS_SKIN
TEXTURE_SKIN = {k for k, n in SKIN_NEEDS.items() if "detail" in n}


def skin_decisions(codes: set[str]) -> dict[str, tuple[str, str]]:
    """{metric: ("withhold"|"flag", reason)} for the active quality flags. "withhold" wins over "flag"."""
    out: dict[str, tuple[str, str]] = {}
    for key, needs in SKIN_NEEDS.items():
        for code in sorted(codes):
            for dep, action in FLAG_EFFECTS.get(code, {}).items():
                if dep in needs:
                    reason = f"{FLAG_REASON[code][0].upper()}{FLAG_REASON[code][1:]}."
                    if action == "withhold" or key not in out:
                        if out.get(key, ("", ""))[0] != "withhold":
                            out[key] = (action, reason)
    return out


SMILE_SENSITIVE = {"lower_third_split", "lip_ratio", "mouth_nose", "thirds_lower_mid"}
POSE_SENSITIVE = {"fwhr", "esr", "midface_ratio", "jaw_zygo"}
YAW_SATURATED = 29.5  # frontalize() searches +/-30 deg; at the bound the correction is not trustworthy
CAMERA_RANGE_MM = (150, 3000)  # same plausibility range geometry.undistort uses

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


RETAKE_TIPS = {
    "blurry": "Hold the phone steady and tap to focus; use the rear camera in good light.",
    "low_resolution": "Use a higher-resolution photo with your face filling more of the frame.",
    "colour_cast": "Take it in daylight by a window - not under a yellow bulb or tube light - and turn filters off.",
    "too_bright": "Avoid direct harsh light or flash; soft daylight is best.",
    "too_dark": "Face a window or a lamp so your face is evenly lit.",
    "uneven_light": "Face the light source so both sides of your face are lit equally.",
    "beauty_filter": "Turn off beauty/AI filters: they smooth the skin we need to read.",
    "glasses": "Take glasses off for the eye-area and under-eye readings.",
    "beard": "A clean-shaven photo lets us measure the jaw and chin and read lower-face skin.",
    "smiling": "Keep a relaxed, neutral expression for accurate lip and lower-face measurements.",
    "slightly_turned": "Look straight at the camera with your head level.",
}


class LandmarkError(ValueError):
    """The landmark set cannot be used (rule G)."""


@lru_cache(maxsize=4)
def model_fingerprint(name: str = "face_landmarker.task") -> dict:
    """Name + SHA-256 of a model asset, so each report records exactly which model produced it."""
    p = MODEL_DIR / name
    if not p.exists():
        return {"file": name, "sha256": None, "status": "missing"}
    return {"file": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "status": "ok"}


def check_landmarks(points: np.ndarray, shape: tuple) -> None:
    """Rule G. Raise LandmarkError for a landmark set that cannot be trusted."""
    if points is None or len(points) < 468:
        raise LandmarkError("Not enough facial landmarks were found. Take a clear, fully visible front photo.")
    if not np.isfinite(points).all():
        raise LandmarkError("The face detector returned invalid coordinates. Please retake the photo.")
    h, w = shape[:2]
    margin_x, margin_y = 0.02 * w, 0.02 * h
    outside = ((points[:468, 0] < -margin_x) | (points[:468, 0] > w + margin_x) |
               (points[:468, 1] < -margin_y) | (points[:468, 1] > h + margin_y)).sum()
    if outside > 10:
        raise LandmarkError("Part of your face is outside the photo. Keep your whole face, including the chin and "
                            "forehead, inside the frame.")


MIN_MM_PER_PX, MAX_MM_PER_PX = 0.005, 2.0  # plausible range for a face photo (iris 11.7 mm = ~6 px .. ~2300 px)


def calibration_status(mm_per_px: float | None, cam: dict | None = None) -> str:
    """Rule B. Scale comes from the iris (geometry.mm_per_px), so it exists whenever the iris was measured.
    'estimated' = iris constant, NOT validated. 'unavailable' = no usable scale, or a camera-distance estimate
    that is physically implausible. `cam` is None for uploads without EXIF focal length: perspective correction is
    then skipped but the iris scale is still valid."""
    if not mm_per_px or not np.isfinite(mm_per_px) or not MIN_MM_PER_PX <= mm_per_px <= MAX_MM_PER_PX:
        return "unavailable"
    if cam and not CAMERA_RANGE_MM[0] <= cam.get("distance_mm", 0) <= CAMERA_RANGE_MM[1]:
        return "unavailable"
    return "estimated"


def _drop_skin(skin: dict, keys: set[str], reason: str, audit: dict) -> None:
    kept = []
    for c in skin.get("concerns", []):
        if c["key"] in keys:
            audit["suppressed"].append({"item": f"skin:{c['key']}", "label": c.get("label", c["key"]), "reason": reason})
        else:
            kept.append(c)
    skin["concerns"] = kept


def apply_quality_rules(analysis: dict, quality: dict, mm_per_px: float | None = None, cam: dict | None = None) -> dict:
    """Mutate `analysis` in place (rules A-E, H) and return the audit trail."""
    codes = {i["code"] for i in (quality or {}).get("issues", [])}
    audit: dict = {"suppressed": [], "flagged": []}
    skin = analysis.get("skin") or {}

    if skin.get("available"):
        decisions = skin_decisions(codes)
        total_skin = len(skin.get("concerns", []))
        kept = []
        for c in skin.get("concerns", []):
            action, reason = decisions.get(c["key"], (None, None))
            if action == "withhold":
                audit["suppressed"].append({"item": f"skin:{c['key']}", "label": c.get("label", c["key"]), "reason": reason})
            else:
                kept.append(c)
                if action == "flag":
                    skin.setdefault("reliability", {})[c["key"]] = reason
                    audit["flagged"].append({"item": f"skin:{c['key']}", "reason": reason})
        skin["concerns"] = kept
        if codes & {"colour_cast", "too_bright", "too_dark", "beauty_filter"} and skin.get("tone"):
            skin["tone"].update(group="unknown", advice="Colour couldn't be read reliably from this photo - retake in "
                                "natural daylight without a filter to get your skin-tone group.")
            audit["suppressed"].append({"item": "skin:tone_group", "label": "Skin tone group",
                                        "reason": "Light colour, exposure or filtering makes the tone group unreliable."})
        concerns = skin.get("concerns", [])
        if concerns and len(concerns) * 2 < total_skin:  # fewer than half survive: an average of the rest would mislead
            skin["score"] = None
            skin["score_note"] = f"Skin score not shown: only {len(concerns)} of {total_skin} skin readings were reliable on this photo."
            audit["suppressed"].append({"item": "skin:overall_score", "label": "Overall skin score", "reason": skin["score_note"]})
        elif concerns:
            skin["score"] = round(sum(c["score"] for c in concerns) / len(concerns), 1)
        else:
            skin.update(available=False, score=None, withheld_reason="Photo conditions do not support skin readings.")
            audit["suppressed"].append({"item": "skin", "label": "Skin analysis", "reason": skin["withheld_reason"]})

    yaw = abs(analysis.get("yaw_correction") or 0)
    ystatus = analysis.get("yaw_correction_status")
    drop_keys: set[str] = set()
    if ystatus == "undetermined":
        audit["flagged"].append({"item": "pose", "reason": "Head turn could not be estimated; symmetry is uncorrected."})
    if yaw >= YAW_SATURATED or ystatus == "saturated":
        drop_keys.add("symmetry")
        audit["suppressed"].append({"item": "metric:symmetry", "label": "Facial symmetry",
                                    "reason": "Head turn is too large to correct, so left/right comparison is unreliable."})
        for m in analysis.get("metrics", []):
            if m["key"] in POSE_SENSITIVE:
                m["quality_note"] = "Head turn limits the accuracy of this width-based measurement."
                audit["flagged"].append({"item": f"metric:{m['key']}", "reason": m["quality_note"]})
    if "smiling" in codes:
        for m in analysis.get("metrics", []):
            if m["key"] in SMILE_SENSITIVE:
                m["quality_note"] = "Smiling changes lip and lower-face measurements."
                audit["flagged"].append({"item": f"metric:{m['key']}", "reason": m["quality_note"]})
    if drop_keys:
        analysis["metrics"] = [m for m in analysis["metrics"] if m["key"] not in drop_keys]

    cal = calibration_status(mm_per_px, cam)
    modules = {
        "skin": "ok" if skin.get("available") else "unavailable",
        "measurements_mm": cal,
    }
    tips = [RETAKE_TIPS[c] for c in ("blurry", "low_resolution", "colour_cast", "too_bright", "too_dark", "uneven_light", "beauty_filter", "glasses", "beard", "smiling", "slightly_turned") if c in codes]
    analysis["validation"] = {
        "retake_tips": tips,
        "validator": VALIDATOR_VERSION, "measurement_version": MEASUREMENT_VERSION,
        "status": "partial" if audit["suppressed"] else "complete",
        "suppressed": audit["suppressed"], "flagged": audit["flagged"], "modules": modules,
        "calibration": {"status": cal, "validated": False, "perspective_corrected": bool(cam)},
        "models": {"landmarker": model_fingerprint()},
        "reference_ranges": {"measurement_table_ranges": "PLACEHOLDER - NOT PRODUCTION VALIDATED",
                             "harmony_metric_references": "PLACEHOLDER - NOT PRODUCTION VALIDATED",
                             "eye_and_brow_thresholds": "PLACEHOLDER - NOT PRODUCTION VALIDATED"},
    }
    return audit


def apply_mm_rules(anthropometry: dict, mm_per_px: float | None, cam: dict | None, validation: dict) -> dict:
    """Rule B: with no usable scale keep the dimensionless ratios and withhold every millimetre value."""
    status = calibration_status(mm_per_px, cam)
    anthropometry.setdefault("calibration", {})["status"] = status
    if status == "unavailable":
        anthropometry["rows"] = []
        anthropometry["note"] = ("Physical sizes are unavailable for this photo (the scale could not be established). "
                                 "Dimensionless ratios are still shown.")
        validation["suppressed"].append({"item": "measurements_mm", "label": "Measurements in millimetres",
                                         "reason": "Scale could not be established from this photo."})
        validation["status"] = "partial"
    return anthropometry


def apply_hair_rules(hair: dict | None, validation: dict) -> None:
    """Rule F: a front photo cannot show crown thinning, so there is no 'overall' hair score without a top photo."""
    if hair and hair.get("available") and not hair.get("crown") and hair.get("score") is not None:
        hair["score"] = None
        hair["score_note"] = "Overall hair score withheld: it needs a top-of-head photo to assess the crown and parting."
        validation["suppressed"].append({"item": "hair:overall_score", "label": "Overall hair score",
                                         "reason": "No top-of-head photo, so crown health cannot be assessed."})
        validation["status"] = "partial"
    validation["modules"]["hair"] = "ok" if (hair or {}).get("available") else "unavailable"


def public_filter(data: dict) -> dict:
    """Rule I: heuristic numbers that are not calibrated probabilities are not published as 'confidence'."""
    if isinstance(data.get("style"), dict):
        data["style"].pop("confidence", None)
    return data
