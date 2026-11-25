"""Create empty validation-dataset skeletons and count what really exists.

    python -m evals.dataset_status --init <root>     # create empty skeletons + protocol READMEs (never overwrites)
    python -m evals.dataset_status --status <root>   # count subjects / images / annotations / masks / measurements

Real-person data lives under <root>, which MUST be outside the repository. Nothing here creates data: an empty skeleton reports zero,
and the evaluators then report NOT MEASURED. Counts only include items whose files exist and pass each dataset's own validator.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REFERENCE_STANDARD = """# Landmark reference standard (annotate to THIS, do not improvise)

Coordinate system   pixel coordinates of the ORIGINAL, un-mirrored image; origin = top-left corner of the top-left pixel; x increases to the
                    right, y increases DOWNWARD. Normalised coordinates are not stored.
Left / right        R_ = the SUBJECT's right = the IMAGE's left; L_ = the subject's left. Same as backend/app/landmark_map.py. Do not mirror.
Indexing            MediaPipe Face Landmarker indices 0-477 exactly as in backend/app/landmark_map.py (468 mesh + 10 iris). Annotate only
                    the indices your protocol covers (a subset is allowed); never re-number.
Visibility          visible=true only if the landmark's true position can be located from the pixels. Occluded by hair, hand, mask, glasses
                    frame, or outside the frame -> visible=false (the evaluator then excludes it). Do not guess hidden points.
Precision           annotate to the nearest pixel at full resolution; two annotators on a subset to measure inter-annotator error.
Annotator           independent of the software under test: annotate WITHOUT showing the model's output. A model-assisted pre-fill makes the
                    labels a model's, and the evaluator then reports AGREEMENT, not accuracy.
Provenance          annotation_source = "human:<annotator id>", annotation_version = protocol version string.
Privacy             photographs stay outside the repository and are not uploaded to third parties; consent_ref identifies the consent record.
"""
SKIN_PROTOCOL = """# Skin-mask labelling protocol
One 8-bit greyscale PNG per image, same size, one class per pixel:
 0 background   1 skin (bare facial skin that SHOULD be analysed)   2 beard   3 moustache   4 glasses (lens + frame)   5 hair
 6 eyes/brows   7 lips/mouth interior   8 other occlusion        (stubble: label as 2 beard and add the tag "stubble" in conditions.tags)
Label by hand (or with a general-purpose annotation tool) WITHOUT using this project's skin-mask output. Tags to record per image:
lighting, beard condition (none|stubble|short|full), glasses (yes|no), colour cast (yes|no), pose group, device.
"""
MEASUREMENT_PROTOCOL = """# Physical-measurement protocol (see docs/MEASUREMENT_VALIDATION_PLAN.md)
reference.csv  : subject_id, measurement, operator, repetition, value_mm, instrument      (caliper readings, 2 repetitions + 2nd operator)
automated.csv  : subject_id, image_id, measurement, value_mm, device, conditions, measurement_version  (from the software's table)
Ground truth is the caliper reading, never a 'typical' value. Measure the SAME anatomical distance the software defines.
"""
POSE_PROTOCOL = """# Head-pose reference protocol
pose_reference.csv: image_id, subject_id, image_file, reference_yaw_deg, reference_pitch_deg, reference_roll_deg, method, uncertainty_deg
`method` = how the pose was MEASURED independently (calibrated turntable, motion capture, head-mounted IMU). Not eyeballed, not from the software.
Yaw sign convention = MediaPipe's (the tool warns when a flipped sign fits better).
"""
LAYOUT = {
    "landmarks": {"dirs": ["images", "annotations"], "manifest": {"dataset_version": "v0-empty", "annotation_protocol": "REFERENCE_STANDARD.md", "items": []}, "files": {"REFERENCE_STANDARD.md": REFERENCE_STANDARD}},
    "skin_masks": {"dirs": ["images", "labels"], "manifest": {"dataset_version": "v0-empty", "label_protocol": "PROTOCOL.md", "label_source": "human:UNSET", "items": []}, "files": {"PROTOCOL.md": SKIN_PROTOCOL}},
    "measurements": {"dirs": [], "csv": {"reference.csv": ["subject_id", "measurement", "operator", "repetition", "value_mm", "instrument"],
                                         "automated.csv": ["subject_id", "image_id", "measurement", "value_mm", "device", "conditions", "measurement_version"]}, "files": {"PROTOCOL.md": MEASUREMENT_PROTOCOL}},
    "pose": {"dirs": ["images"], "csv": {"pose_reference.csv": ["image_id", "subject_id", "image_file", "reference_yaw_deg", "reference_pitch_deg", "reference_roll_deg", "method", "uncertainty_deg"]}, "files": {"PROTOCOL.md": POSE_PROTOCOL}},
}


def init(root: Path) -> list[str]:
    created = []
    repo = Path(__file__).resolve().parents[2]
    if repo in root.resolve().parents or root.resolve() == repo:
        raise SystemExit("REFUSING: the dataset root must be OUTSIDE the repository (real-person data must not live in the project folder).")
    for name, spec in LAYOUT.items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        for sub in spec["dirs"]:
            (d / sub).mkdir(exist_ok=True)
        if "manifest" in spec and not (d / "manifest.json").exists():
            (d / "manifest.json").write_text(json.dumps(spec["manifest"], indent=2), encoding="utf-8")
            created.append(f"{name}/manifest.json")
        for fn, header in spec.get("csv", {}).items():
            if not (d / fn).exists():
                with open(d / fn, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(header)
                created.append(f"{name}/{fn}")
        for fn, text in spec["files"].items():
            if not (d / fn).exists():
                (d / fn).write_text(text, encoding="utf-8")
                created.append(f"{name}/{fn}")
    return created


def _csv_rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def status(root: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from evals import landmark_accuracy as la, skin_labelled_eval as sl
    out: dict = {}
    # landmarks
    d = root / "landmarks"
    try:
        s = la.validate(d)
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        n = sum(len(json.loads((d / "annotations" / f"{i['image_id']}.json").read_text(encoding="utf-8"))["landmarks"]) for i in m["items"])
        out["landmarks"] = {"valid": True, "subjects": s["subjects"], "images": s["items"], "landmark_annotations": n}
    except Exception as e:  # noqa: BLE001
        out["landmarks"] = {"valid": False, "problem": str(e)[:200], "subjects": 0, "images": 0, "landmark_annotations": 0}
    # skin masks
    d = root / "skin_masks"
    try:
        s = sl.validate(d)
        out["skin_masks"] = {"valid": True, "subjects": s["subjects"], "images": s["items"], "masks": s["items"]}
    except Exception as e:  # noqa: BLE001
        out["skin_masks"] = {"valid": False, "problem": str(e)[:200], "subjects": 0, "images": 0, "masks": 0}
    # measurements
    ref, auto = _csv_rows(root / "measurements" / "reference.csv"), _csv_rows(root / "measurements" / "automated.csv")
    out["measurements"] = {"reference_readings": len(ref), "automated_values": len(auto), "subjects": len({r["subject_id"] for r in ref} | {r["subject_id"] for r in auto}),
                           "paired_subject_measurements": len({(r["subject_id"], r["measurement"]) for r in ref} & {(r["subject_id"], r["measurement"]) for r in auto})}
    # pose
    pr = _csv_rows(root / "pose" / "pose_reference.csv")
    out["pose"] = {"images": len(pr), "subjects": len({r["subject_id"] for r in pr})}
    total = lambda k: out[k].get("images", 0)  # noqa: E731
    out["evidence_status"] = {
        "landmark_accuracy": "MEASURABLE" if out["landmarks"]["landmark_annotations"] else "NOT MEASURED - no labelled landmarks",
        "skin_segmentation_accuracy": "MEASURABLE" if out["skin_masks"]["masks"] else "NOT MEASURED - no labelled masks",
        "physical_measurement_accuracy": "MEASURABLE" if out["measurements"]["paired_subject_measurements"] else "NOT MEASURED - no paired caliper data",
        "head_pose_validation": "MEASURABLE" if out["pose"]["images"] else "NOT MEASURED - no reference head pose",
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init")
    ap.add_argument("--status")
    a = ap.parse_args()
    if a.init:
        print(json.dumps({"created": init(Path(a.init))}, indent=2))
    elif a.status:
        print(json.dumps(status(Path(a.status)), indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
