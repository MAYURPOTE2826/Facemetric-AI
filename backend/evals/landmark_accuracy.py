"""Landmark ACCURACY evaluation against labelled reference landmarks.

    python -m evals.landmark_accuracy --dataset <dir> [--out report.json]
    python -m evals.landmark_accuracy --validate <dir>        # check the dataset only, run no model

Three different things are kept apart and labelled in every output:
  ACCURACY    error of the model against an independent HUMAN reference annotation (this tool).
  ROBUSTNESS  the same accuracy broken down by condition (pose, lighting, occlusion, quality) - reported per group.
  STABILITY   how much landmarks move when the INPUT is perturbed, with no reference needed -> evals/landmark_validation.py.
If the reference annotations were produced by a model (annotation_source starting with "model") the result is
labelled AGREEMENT, not accuracy: a model compared with another model proves nothing about truth.

NO acceptance thresholds are defined here and none are applied: results are reported as measurements. See
docs/LANDMARK_ACCURACY_DATASET.md for the dataset contract. Real-person data belongs OUTSIDE the repository.

DATASET LAYOUT
  <dir>/manifest.json
  <dir>/images/<image_file>
  <dir>/annotations/<image_id>.json
manifest.json
  {"dataset_version": str, "annotation_protocol": str, "items": [
     {"image_id": str, "subject_id": str, "image_file": "images/x.jpg",
      "capture": {"device": str, "format": "jpg|png|...", "width_px": int, "height_px": int},
      "conditions": {"pose": {"yaw_deg": float, "pitch_deg": float, "roll_deg": float, "source": str},
                     "pose_group": "frontal|yaw_15_30|yaw_over_30|pitch|roll|other",
                     "lighting": "even|side|dim|bright|warm|cool|mixed",
                     "occlusion": [ "glasses" | "beard" | "hand" | "mask" | "hair" | "none" ... ],
                     "expression": "neutral|smile|other", "quality_group": "good|blurred|low_res|compressed|filtered"},
      "consent_ref": str}]}
annotations/<image_id>.json
  {"image_id": str, "annotation_source": "human:<annotator id>" | "model:<name>", "annotation_version": str,
   "landmarks": {"<index 0-477>": {"xy": [x_px, y_px], "visible": bool}}}     (a subset of indices is allowed)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REGIONS = {
    "eyes": [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246,
             362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398],
    "iris": list(range(468, 478)),
    "brows": [70, 63, 105, 66, 107, 55, 65, 52, 53, 46, 300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
    "nose": [168, 6, 197, 195, 5, 4, 1, 19, 94, 2, 98, 327, 129, 358, 48, 278],
    "mouth": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185,
              78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191],
    "face_contour": [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
                     148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109],
}
POSE_GROUPS = {"frontal", "yaw_15_30", "yaw_over_30", "pitch", "roll", "other"}
MIN_FOR_P95 = 20  # below this many landmark errors a P95 is not meaningful and is flagged


class DatasetError(ValueError):
    pass


# --------------------------------------------------------------------------- dataset validation
def validate(dataset: Path) -> dict:
    """Structural validation. Raises DatasetError on problems; returns summary counts."""
    mf = dataset / "manifest.json"
    if not mf.exists():
        raise DatasetError("manifest.json missing")
    m = json.loads(mf.read_text(encoding="utf-8"))
    for k in ("dataset_version", "annotation_protocol", "items"):
        if k not in m:
            raise DatasetError(f"manifest missing '{k}'")
    seen, problems = set(), []
    for it in m["items"]:
        iid = it.get("image_id")
        if not iid or iid in seen:
            problems.append(f"duplicate or missing image_id: {iid}")
            continue
        seen.add(iid)
        for k in ("subject_id", "image_file", "capture", "conditions", "consent_ref"):
            if k not in it:
                problems.append(f"{iid}: missing '{k}'")
        if not (dataset / it.get("image_file", "")).exists():
            problems.append(f"{iid}: image file not found")
        cond = it.get("conditions", {})
        if cond.get("pose_group") not in POSE_GROUPS:
            problems.append(f"{iid}: pose_group must be one of {sorted(POSE_GROUPS)}")
        ap = dataset / "annotations" / f"{iid}.json"
        if not ap.exists():
            problems.append(f"{iid}: annotation file missing")
            continue
        a = json.loads(ap.read_text(encoding="utf-8"))
        if a.get("image_id") != iid:
            problems.append(f"{iid}: annotation image_id mismatch")
        for k in ("annotation_source", "annotation_version", "landmarks"):
            if k not in a:
                problems.append(f"{iid}: annotation missing '{k}'")
        for idx, lm in a.get("landmarks", {}).items():
            if not (idx.isdigit() and 0 <= int(idx) < 478):
                problems.append(f"{iid}: landmark index {idx} out of range 0-477")
            elif not (isinstance(lm.get("xy"), list) and len(lm["xy"]) == 2 and isinstance(lm.get("visible"), bool)):
                problems.append(f"{iid}: landmark {idx} needs xy:[x,y] and visible:bool")
    if problems:
        raise DatasetError("; ".join(problems[:25]) + (f" (+{len(problems) - 25} more)" if len(problems) > 25 else ""))
    return {"items": len(m["items"]), "subjects": len({i["subject_id"] for i in m["items"]})}


# --------------------------------------------------------------------------- statistics
def describe(errors: list[float]) -> dict:
    """Error statistics in % of the normaliser. Empty -> n=0 and no invented numbers."""
    if not errors:
        return {"n": 0}
    a = np.asarray(errors, float)
    out = {"n": int(a.size), "mean": round(float(a.mean()), 4), "median": round(float(np.median(a)), 4),
           "p95": round(float(np.percentile(a, 95)), 4), "max": round(float(a.max()), 4)}
    if a.size < MIN_FOR_P95:
        out["p95_note"] = f"n < {MIN_FOR_P95}: P95 not meaningful"
    return out


def normaliser(ref: dict[int, tuple[float, float]]) -> tuple[float, str] | None:
    """Inter-pupil distance (iris centres 468/473) if both are annotated; else outer-eye-corner distance (33/263)."""
    for (a, b), name in (((468, 473), "inter_pupil_distance"), ((33, 263), "outer_eye_corner_distance")):
        if a in ref and b in ref:
            d = float(np.hypot(ref[a][0] - ref[b][0], ref[a][1] - ref[b][1]))
            if d > 0:
                return d, name
    return None


# --------------------------------------------------------------------------- evaluation
def default_detector(bgr):
    from app import landmarks
    f = landmarks.detect(bgr)
    return None if f is None else f.points


def evaluate(dataset: Path, detector=default_detector, read_image=None) -> dict:
    import cv2
    read_image = read_image or (lambda p: cv2.imread(str(p)))
    summary = validate(dataset)
    m = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    pooled: list[float] = []
    per_landmark: dict[int, list[float]] = {}
    per_image_nme: list[float] = []
    groups: dict[str, dict[str, list[float]]] = {"pose_group": {}, "lighting": {}, "occlusion": {}, "quality_group": {}}
    failures, skipped, sources, norms = [], [], set(), set()
    for it in m["items"]:
        iid = it["image_id"]
        ann = json.loads((dataset / "annotations" / f"{iid}.json").read_text(encoding="utf-8"))
        sources.add(str(ann["annotation_source"]).split(":")[0])
        ref = {int(k): tuple(v["xy"]) for k, v in ann["landmarks"].items() if v["visible"]}
        norm = normaliser(ref)
        if norm is None:
            skipped.append({"image_id": iid, "reason": "no iris or outer-eye-corner reference to normalise by"})
            continue
        pred = detector(read_image(dataset / it["image_file"]))
        if pred is None:
            failures.append({"image_id": iid, "reason": "no face detected"})  # counted, never silently dropped
            continue
        d, norm_name = norm
        norms.add(norm_name)
        errs = {i: float(np.hypot(pred[i][0] - xy[0], pred[i][1] - xy[1]) / d * 100) for i, xy in ref.items()}
        pooled += errs.values()
        per_image_nme.append(float(np.mean(list(errs.values()))))
        for i, e in errs.items():
            per_landmark.setdefault(i, []).append(e)
        c = it["conditions"]
        keys = {"pose_group": [c["pose_group"]], "lighting": [c.get("lighting", "unspecified")],
                "quality_group": [c.get("quality_group", "unspecified")], "occlusion": c.get("occlusion") or ["none"]}
        for gname, labels in keys.items():
            for lab in labels:
                groups[gname].setdefault(lab, []).extend(errs.values())
    model_ref = "model" in sources
    return {
        "measurement": "AGREEMENT (reference annotations are model-generated; this is NOT accuracy)" if model_ref
        else "ACCURACY against reference annotations",
        "reference_sources": sorted(sources), "normaliser": sorted(norms), "unit": "% of the normaliser distance",
        "dataset": {**summary, "dataset_version": m["dataset_version"], "annotation_protocol": m["annotation_protocol"]},
        "images_evaluated": len(per_image_nme), "detection_failures": failures, "skipped": skipped,
        "overall": describe(pooled),
        "per_image_mean_error": describe(per_image_nme),
        "per_region": {r: describe([e for i in idx for e in per_landmark.get(i, [])]) for r, idx in REGIONS.items()},
        "per_landmark": {str(i): {"n": len(v), "mean": round(float(np.mean(v)), 4)} for i, v in sorted(per_landmark.items())},
        "ROBUSTNESS_by_condition": {g: {lab: describe(v) for lab, v in sorted(d.items())} for g, d in groups.items()},
        "STABILITY": "not measured by this tool - see evals/landmark_validation.py",
        "acceptance_criteria": "NOT DEFINED - no pass/fail is applied; thresholds must come from an expert/product decision",
        "caveat": "Small groups give unreliable statistics; always read n. Do not group images by demographic labels inferred from photographs.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset")
    ap.add_argument("--validate")
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    if a.validate:
        print(json.dumps(validate(Path(a.validate)), indent=2))
    elif a.dataset:
        res = evaluate(Path(a.dataset))
        txt = json.dumps(res, indent=2)
        if a.out:
            Path(a.out).write_text(txt, encoding="utf-8")
        print(txt)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
