"""Head-pose validation: reference yaw vs MediaPipe yaw vs frontalize() yaw.

    python -m evals.pose_validation --reference pose_reference.csv --images <dir> [--out report.json]

STATUS WITHOUT A REFERENCE: no ground-truth head pose exists in this project, so the result is "NOT MEASURED". Nothing is assumed
about which estimator is right.

REFERENCE FILE  pose_reference.csv  (one row per photograph)
  image_id, subject_id, image_file, reference_yaw_deg, reference_pitch_deg, reference_roll_deg, method, uncertainty_deg
  `method` says how the pose was MEASURED, independently of the software under test (calibrated turntable, motion capture, IMU on
  the head, laser-marked rig ...). A pose read off the image by eye, or taken from MediaPipe/frontalize, is NOT a reference.
  SIGN CONVENTION: reference yaw must use MediaPipe's sign (positive yaw has the same sign as MediaPipe's reported yaw, which is the
  Euler yaw of the rotation block of facial_transformation_matrixes). The tool also reports the error under the flipped sign, and
  warns if the flipped sign fits clearly better, so a convention mismatch is caught instead of silently producing bad numbers.
  frontalize_with_status() returns the rotation applied to frontalise the face; its sign relation to MediaPipe's yaw was found to
  be the same on the photographs available (see docs/FRONTALIZE_INVESTIGATION.md) and is stated per run, not assumed.

REPORTED per estimator (MediaPipe, frontalize): n, signed error (bias = mean of estimate - reference), mean / median / P95 / max absolute
error, the reference range covered, a straight-line fit of estimate vs reference (slope and intercept), saturated or failed cases
(listed, never dropped), and the same statistics by reference-yaw band (0-10, 10-20, 20-30, over 30 degrees). No threshold, no pass/fail.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

BANDS = [(0, 10), (10, 20), (20, 30), (30, 360)]


def stats(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    e = np.asarray(errors, float)
    a = np.abs(e)
    out = {"n": int(e.size), "bias_signed_mean": round(float(e.mean()), 3), "mean_abs": round(float(a.mean()), 3),
           "median_abs": round(float(np.median(a)), 3), "p95_abs": round(float(np.percentile(a, 95)), 3), "max_abs": round(float(a.max()), 3)}
    if e.size < 20:
        out["p95_note"] = "n < 20: P95 not meaningful"
    return out


def line_fit(ref: list[float], est: list[float]) -> dict:
    if len(ref) < 3 or float(np.std(ref)) == 0:
        return {"note": "needs >= 3 images with different reference yaw"}
    slope, icpt = np.polyfit(ref, est, 1)
    return {"slope": round(float(slope), 4), "intercept_deg": round(float(icpt), 3)}


def default_estimators(bgr):
    """-> (mediapipe_yaw, frontalize_yaw, frontalize_status) or None when no face is found."""
    from app import landmarks, metrics
    f = landmarks.detect(bgr)
    if f is None:
        return None
    _, yaw_f, status = metrics.frontalize_with_status(f.points)
    return float(f.pose["yaw"]), float(yaw_f), status


def evaluate(rows: list[dict], read_image, estimators=default_estimators) -> dict:
    if not rows:
        return {"status": "NOT MEASURED - no reference head-pose data was provided"}
    items, failures = [], []
    for r in rows:
        est = estimators(read_image(r["image_file"]))
        if est is None:
            failures.append({"image_id": r["image_id"], "reason": "no face detected"})
            continue
        mp_yaw, fr_yaw, status = est
        items.append({"image_id": r["image_id"], "subject_id": r["subject_id"], "reference": float(r["reference_yaw_deg"]), "mediapipe": mp_yaw,
                      "frontalize": fr_yaw, "frontalize_status": status, "method": r.get("method", ""), "uncertainty": r.get("uncertainty_deg", "")})
    out = {"status": "MEASURED against the supplied reference", "images": len(items), "failures": failures,
           "reference_methods": sorted({i["method"] for i in items}), "acceptance_criteria": "NOT DEFINED - no pass/fail is applied"}
    if not items:
        return {**out, "status": "NOT MEASURED - no usable images"}
    ref = [i["reference"] for i in items]
    out["reference_range_deg"] = [round(min(ref), 2), round(max(ref), 2)]
    for name in ("mediapipe", "frontalize"):
        err = [i[name] - i["reference"] for i in items]
        flipped = [-i[name] - i["reference"] for i in items]
        res = {"overall": stats(err), "line_fit_estimate_vs_reference": line_fit(ref, [i[name] for i in items]),
               "by_reference_yaw_band": {f"{lo}-{hi}": stats([i[name] - i["reference"] for i in items if lo <= abs(i["reference"]) < hi]) for lo, hi in BANDS}}
        if np.mean(np.abs(flipped)) < 0.5 * np.mean(np.abs(err)) and len(err) >= 3:
            res["SIGN_WARNING"] = "the error is much smaller with the sign flipped: the reference may use the opposite yaw convention"
        out[name] = res
    out["frontalize"]["saturated_or_undetermined"] = [{"image_id": i["image_id"], "status": i["frontalize_status"], "reference": i["reference"], "estimate": round(i["frontalize"], 2)}
                                                      for i in items if i["frontalize_status"] != "ok"]
    out["mediapipe_vs_frontalize_difference_deg"] = stats([i["frontalize"] - i["mediapipe"] for i in items])
    out["conservative_rule"] = "Until these numbers support a change, symmetry stays suppressed when frontalize reports saturated; nothing here widens its range."
    return out


def read_reference(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    need = {"image_id", "subject_id", "image_file", "reference_yaw_deg", "method"}
    for i, r in enumerate(rows, 2):
        miss = need - {k for k, v in r.items() if v not in (None, "")}
        if miss:
            raise ValueError(f"row {i}: missing {sorted(miss)}")
        if str(r["method"]).strip().lower() in ("mediapipe", "frontalize", "software", "estimated", "visual"):
            raise ValueError(f"row {i}: '{r['method']}' is not an independent reference method")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import cv2
    rows = read_reference(Path(a.reference))
    res = evaluate(rows, lambda f: cv2.imread(str(Path(a.images) / f)))
    txt = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
