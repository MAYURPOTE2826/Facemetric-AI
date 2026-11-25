"""Skin-mask evaluation.

TWO different things, and only the first is accuracy:

1. ACCURACY against labelled ground truth (IoU, Dice, false-positive rate, false-negative rate):
       python -m evals.skin_segmentation_eval --labelled <dir>
   <dir> holds pairs  <name>.jpg|png  +  <name>_skinmask.png  (white = bare facial skin that SHOULD be analysed;
   black = everything else: eyes, brows, lips, nostrils, hair, beard, glasses, background, clothing). Only
   authorised photographs may be labelled. NO labelled set exists in this repository today, so NO accuracy has been
   measured; this harness is ready for one.

2. CONTAMINATION indicators that need no ground truth (a second opinion from another model + landmark geometry):
       python -m evals.skin_segmentation_eval --image <path>
   These are consistency checks, NOT accuracy: if the segmenter and the skin mask disagree it flags a problem, but
   agreement does not prove the mask is right.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from app import hair as hair_mod
from app import landmarks, skin

SEG_CLASSES = {0: "background", 1: "hair/beard", 2: "body_skin", 3: "face_skin", 4: "clothes", 5: "accessories/other"}


def confusion(pred: np.ndarray, truth: np.ndarray) -> dict:
    """Pixel-level agreement of two boolean masks. Rates are fractions in [0, 1]; undefined values are None."""
    p, t = pred.astype(bool), truth.astype(bool)
    tp, fp, fn = int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum())
    tn = int((~p & ~t).sum())
    div = lambda a, b: None if b == 0 else a / b  # noqa: E731
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "iou": div(tp, tp + fp + fn), "dice": div(2 * tp, 2 * tp + fp + fn),
            "false_positive_rate": div(fp, fp + tn), "false_negative_rate": div(fn, fn + tp),
            "precision": div(tp, tp + fp), "recall": div(tp, tp + fn)}


def pipeline_mask(bgr: np.ndarray, face, seg, truth: np.ndarray | None = None, raw_truth: bool = False):
    """Run the production mask builder on the normalised crop. If `truth` (a mask in original-photo coordinates)
    is given it is resampled into the same crop. Returns (pred_mask, truth_crop_or_None, crop_bgr, points) or None."""
    img, p, seg_c = skin._normalise(bgr, face.points[:, :2], seg)
    truth_c = None
    if truth is not None:
        _, _, truth_c = skin._normalise(bgr, face.points[:, :2], truth.astype(np.uint8))
    img, _ = skin._white_balance(img, p)
    L = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)[..., 0]
    sm = skin.build_skin_mask(img, p, seg_c, L)
    if sm is None:
        return None
    return sm["skin_b"], (None if truth_c is None else (truth_c if raw_truth else truth_c > 0)), img, p, seg_c, sm, L


def evaluate_dir(folder: str) -> dict:
    rows, agg = [], {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for img_path in sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png") and "_skinmask" not in p.stem):
        mp = img_path.with_name(img_path.stem + "_skinmask.png")
        if not mp.exists():
            continue
        bgr, truth = cv2.imread(str(img_path)), cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE) > 127
        face = landmarks.detect(bgr)
        if face is None:
            rows.append({"image": img_path.name, "status": "no face"})
            continue
        r = pipeline_mask(bgr, face, hair_mod.segment(bgr), truth)
        if r is None:
            rows.append({"image": img_path.name, "status": "mask unavailable"})
            continue
        c = confusion(r[0], r[1])
        rows.append({"image": img_path.name, **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items()}})
        for k in agg:
            agg[k] += c[k]
    pooled = confusion(np.array([True] * agg["tp"] + [True] * agg["fp"] + [False] * agg["fn"] + [False] * agg["tn"]) if False else np.zeros(1), np.zeros(1))
    tp, fp, fn, tn = agg["tp"], agg["fp"], agg["fn"], agg["tn"]
    pooled = {"iou": tp / max(1, tp + fp + fn), "dice": 2 * tp / max(1, 2 * tp + fp + fn), "false_positive_rate": fp / max(1, fp + tn),
              "false_negative_rate": fn / max(1, fn + tp), "images": len([r for r in rows if "iou" in r])}
    return {"per_image": rows, "pooled_pixels": pooled, "note": "pooled over pixels, not a per-subject average; report sample size with it"}


def contamination(bgr: np.ndarray) -> dict:
    face = landmarks.detect(bgr)
    if face is None:
        return {"status": "no face"}
    seg = hair_mod.segment(bgr)
    r = pipeline_mask(bgr, face, seg)
    if r is None:
        return {"status": "mask unavailable (too little reference cheek skin)"}
    mask, _, img, p, seg_c, sm, L = r
    shape = img.shape[:2]
    n = int(mask.sum())
    out = {"mask_pixels": n, "normalised_crop_px": list(shape[::-1])}
    # (a) construction check: mask must not contain eye / brow / lip polygons (landmark geometry)
    feat = np.zeros(shape, bool)
    for part in (skin.R_EYE, skin.L_EYE, skin.R_BROW, skin.L_BROW, skin.LIPS):
        feat |= skin._poly_mask(shape, p[part]) > 0
    out["pct_mask_inside_eye_brow_lip_polygons"] = round(float((mask & feat).sum() / max(1, n) * 100), 3)
    # (b) second opinion from the segmentation model
    if seg_c is not None:
        out["segmenter_labels_of_mask_pixels_pct"] = {SEG_CLASSES[k]: round(float((mask & (seg_c == k)).sum() / max(1, n) * 100), 2) for k in SEG_CLASSES}
        lower = np.zeros(shape, bool)
        lower[int(p[2, 1]):, :] = True  # below the base of the nose
        lh = lower & (seg_c == 1)
        out["lower_face_pct_labelled_hair_by_segmenter"] = round(float(lh.sum() / max(1, lower.sum()) * 100), 2)
        out["pct_of_segmenter_hair_pixels_inside_mask"] = round(float((mask & (seg_c == 1)).sum() / max(1, (seg_c == 1).sum()) * 100), 3)
    # (c) tone / exposure inside the mask
    out["pct_mask_darker_than_0.62x_median_cheek"] = round(float((mask & (L < 0.62 * sm["l_med"])).sum() / max(1, n) * 100), 2)
    out["pct_mask_clipped_highlights(L>=250)"] = round(float((mask & (L >= 250)).sum() / max(1, n) * 100), 2)
    # (d) shape of the mask
    cnt, _, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    areas = sorted((int(st[i, cv2.CC_STAT_AREA]) for i in range(1, cnt)), reverse=True)
    out["connected_components"] = len(areas)
    out["largest_component_share_pct"] = round(areas[0] / max(1, n) * 100, 1) if areas else None
    oval = skin._poly_mask(shape, p[skin.FACE_OVAL]) > 0
    out["pct_of_face_oval_covered_by_mask"] = round(float((mask & oval).sum() / max(1, oval.sum()) * 100), 1)
    out["pct_mask_outside_face_oval"] = round(float((mask & ~oval).sum() / max(1, n) * 100), 3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labelled", help="folder of image + *_skinmask.png pairs (accuracy)")
    ap.add_argument("--image", action="append", help="photo for contamination indicators (repeatable)")
    a = ap.parse_args()
    if a.labelled:
        print(json.dumps(evaluate_dir(a.labelled), indent=2))
    for path in a.image or []:
        print(f"--- {Path(path).name}: contamination indicators (NOT accuracy)")
        print(json.dumps(contamination(cv2.imread(path)), indent=2))
    if not a.labelled and not a.image:
        ap.print_help()


if __name__ == "__main__":
    main()
