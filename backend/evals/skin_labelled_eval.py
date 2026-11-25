"""Skin-mask evaluation against multi-class LABELLED masks (overall and per region).

    python -m evals.skin_labelled_eval --dataset <dir> [--out report.json]
    python -m evals.skin_labelled_eval --validate <dir>

STATUS WITHOUT LABELS: if the dataset has no items the result says "ACCURACY NOT MEASURED". No ground-truth masks exist
in this repository and none are fabricated; real-person data belongs OUTSIDE the repo.

LABEL MAP  (<dir>/labels/<image_id>.png, 8-bit greyscale, same size as the image, one class id per pixel)
   0 background   1 skin (bare facial skin that SHOULD be analysed)   2 beard   3 moustache   4 glasses (lens + frame)
   5 hair         6 eyes/brows   7 lips/mouth interior   8 other occlusion (hand, mask, scarf, makeup layer ...)
MANIFEST  <dir>/manifest.json
   {"dataset_version": str, "label_protocol": str, "label_source": "human:<id>" | "model:<name>", "items": [
      {"image_id": str, "subject_id": str, "image_file": "images/x.jpg", "labels_file": "labels/x.png",
       "conditions": {"lighting": "even|side|dim|bright|warm|cool|mixed", "tags": ["beard","glasses","colour_cast",...]},
       "consent_ref": str}]}

WHAT IS MEASURED. "Positive" = pixel is inside the predicted analysis mask.
  overall   skin-vs-everything-else: IoU, Dice, precision, recall, false-positive rate, false-negative rate.
  per region
     skin class       recall = share of true skin that the mask keeps (1 - false-negative rate)
     every other class  contamination = share of that region's pixels wrongly INSIDE the mask (a false-positive rate
                        restricted to the region): BEARD, MOUSTACHE, GLASSES, HAIR, EYES/BROWS, LIPS, OTHER, BACKGROUND.
  by condition  the same overall metrics per lighting value and per tag.
No acceptance thresholds are defined or applied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

CLASSES = {0: "background", 1: "skin", 2: "beard", 3: "moustache", 4: "glasses", 5: "hair", 6: "eyes_brows", 7: "lips_mouth", 8: "other_occlusion"}
SKIN = 1


class DatasetError(ValueError):
    pass


def metrics(pred: np.ndarray, skin_truth: np.ndarray) -> dict:
    """Binary agreement of the predicted mask with the true skin region. Undefined rates are None, never invented."""
    p, t = pred.astype(bool), skin_truth.astype(bool)
    tp, fp, fn, tn = int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum()), int((~p & ~t).sum())
    div = lambda a, b: None if b == 0 else round(a / b, 4)  # noqa: E731
    return {"pixels": int(p.size), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "iou": div(tp, tp + fp + fn), "dice": div(2 * tp, 2 * tp + fp + fn),
            "precision": div(tp, tp + fp), "recall": div(tp, tp + fn), "false_positive_rate": div(fp, fp + tn), "false_negative_rate": div(fn, fn + tp)}


def pool(items: list[dict]) -> dict:
    """Sum the confusion counts of several images (pixel-pooled, so large faces weigh more - stated, not hidden)."""
    s = {k: sum(i[k] for i in items) for k in ("pixels", "tp", "fp", "fn", "tn")}
    div = lambda a, b: None if b == 0 else round(a / b, 4)  # noqa: E731
    return {"images": len(items), **s, "iou": div(s["tp"], s["tp"] + s["fp"] + s["fn"]), "dice": div(2 * s["tp"], 2 * s["tp"] + s["fp"] + s["fn"]),
            "precision": div(s["tp"], s["tp"] + s["fp"]), "recall": div(s["tp"], s["tp"] + s["fn"]),
            "false_positive_rate": div(s["fp"], s["fp"] + s["tn"]), "false_negative_rate": div(s["fn"], s["fn"] + s["tp"])}


def region_stats(pred: np.ndarray, labels: np.ndarray) -> dict:
    out = {}
    for cid, name in CLASSES.items():
        region = labels == cid
        n = int(region.sum())
        if n == 0:
            continue
        inside = int((pred & region).sum())
        out[name] = {"pixels": n, "inside_mask": inside}
    return out


def validate(dataset: Path) -> dict:
    mf = dataset / "manifest.json"
    if not mf.exists():
        raise DatasetError("manifest.json missing")
    m = json.loads(mf.read_text(encoding="utf-8"))
    for k in ("dataset_version", "label_protocol", "label_source", "items"):
        if k not in m:
            raise DatasetError(f"manifest missing '{k}'")
    problems, seen = [], set()
    for it in m["items"]:
        iid = it.get("image_id")
        if not iid or iid in seen:
            problems.append(f"duplicate or missing image_id {iid}")
            continue
        seen.add(iid)
        for k in ("subject_id", "image_file", "labels_file", "conditions", "consent_ref"):
            if k not in it:
                problems.append(f"{iid}: missing '{k}'")
        for f in ("image_file", "labels_file"):
            if f in it and not (dataset / it[f]).exists():
                problems.append(f"{iid}: {f} not found")
    if problems:
        raise DatasetError("; ".join(problems[:25]))
    return {"items": len(m["items"]), "subjects": len({i["subject_id"] for i in m["items"]})}


def default_predict(bgr, labels):
    """Production mask on the normalised crop, with the labels resampled into the same crop. -> (pred, labels) or None."""
    from app import hair as hair_mod, landmarks
    from evals.skin_segmentation_eval import pipeline_mask
    face = landmarks.detect(bgr)
    if face is None:
        return None
    r = pipeline_mask(bgr, face, hair_mod.segment(bgr), labels, raw_truth=True)
    return None if r is None else (r[0], r[1])


def evaluate(dataset: Path, predict=default_predict, read_image=None, read_labels=None) -> dict:
    import cv2
    read_image = read_image or (lambda p: cv2.imread(str(p)))
    read_labels = read_labels or (lambda p: cv2.imread(str(p), cv2.IMREAD_GRAYSCALE))
    summary = validate(dataset)
    m = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if not m["items"]:
        return {"status": "ACCURACY NOT MEASURED - the dataset has no labelled images", "dataset": summary}
    per_img, failures, reg_acc = [], [], {}
    by_light: dict[str, list[dict]] = {}
    by_tag: dict[str, list[dict]] = {}
    for it in m["items"]:
        r = predict(read_image(dataset / it["image_file"]), read_labels(dataset / it["labels_file"]))
        if r is None:
            failures.append({"image_id": it["image_id"], "reason": "no face or mask unavailable"})  # counted, never dropped
            continue
        pred, labels = r
        c = metrics(pred, labels == SKIN)
        per_img.append({"image_id": it["image_id"], **c})
        for name, v in region_stats(pred, labels).items():
            a = reg_acc.setdefault(name, {"pixels": 0, "inside_mask": 0, "images": 0})
            a["pixels"] += v["pixels"]; a["inside_mask"] += v["inside_mask"]; a["images"] += 1
        by_light.setdefault(it["conditions"].get("lighting", "unspecified"), []).append(c)
        for tag in it["conditions"].get("tags", []):
            by_tag.setdefault(tag, []).append(c)
    regions = {}
    for name, a in reg_acc.items():
        share = round(a["inside_mask"] / a["pixels"], 4) if a["pixels"] else None
        regions[name] = {"images_containing_region": a["images"], "pixels": a["pixels"], "inside_mask": a["inside_mask"],
                         ("recall (share of true skin kept)" if name == "skin" else "contamination (share wrongly inside the mask)"): share}
    src = str(m["label_source"]).split(":")[0]
    return {
        "measurement": "ACCURACY against human-labelled masks" if src == "human" else "AGREEMENT (labels are model-generated; NOT accuracy)",
        "label_source": m["label_source"], "label_protocol": m["label_protocol"], "dataset": {**summary, "dataset_version": m["dataset_version"]},
        "images_evaluated": len(per_img), "failures": failures,
        "overall_pixel_pooled": pool(per_img) if per_img else {"images": 0},
        "per_region": regions,
        "by_lighting": {k: pool(v) for k, v in sorted(by_light.items())},
        "by_tag": {k: pool(v) for k, v in sorted(by_tag.items())},
        "per_image": per_img,
        "acceptance_criteria": "NOT DEFINED - no pass/fail is applied",
        "caveat": "Pixel-pooled: large faces weigh more. Read the image counts. Do not group by demographic labels inferred from photographs.",
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
