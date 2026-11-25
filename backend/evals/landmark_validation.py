"""Landmark repeatability / robustness / mapping validation on a photograph you are authorised to use.

    python -m evals.landmark_validation --image <path> --label A [--out evals/results]

The photograph is read from the path you give and is NEVER copied into the repository; the JSON output holds only
numbers. All displacements are expressed in units of the subject's inter-pupil distance (IPD, measured on the
untouched photo), so they are comparable across photos and resolutions. These are measurements of how much the
landmarks move under a transformation - they are NOT accuracy against ground truth (no ground truth exists here).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

from app import landmark_map as LM
from app import landmarks, metrics

SUBSET = sorted({*LM.ALL_NAMED.values(), *LM.MIDLINE, *(i for p in LM.SYMMETRY_PAIRS for i in p)})


def ipd(points: np.ndarray) -> float:
    return float(np.linalg.norm(points[LM.R_IRIS, :2] - points[LM.L_IRIS, :2]))


def stats(a: np.ndarray, b: np.ndarray, scale: float) -> dict:
    """Per-landmark 2D displacement between two (478,3) sets, in IPD units (x100 = % of IPD)."""
    d = np.linalg.norm(a[:, :2] - b[:, :2], axis=1) / scale
    s = d[SUBSET]
    return {"all_mean_pct_ipd": round(float(d.mean() * 100), 3), "all_max_pct_ipd": round(float(d.max() * 100), 3),
            "metric_subset_mean_pct_ipd": round(float(s.mean() * 100), 3), "metric_subset_max_pct_ipd": round(float(s.max() * 100), 3)}


def detect(img):
    f = landmarks.detect(img)
    return None if f is None else f


def jpeg(img, q):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def rotate(img, deg):
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), m


def run(path: str) -> dict:
    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"cannot read {path}")
    base = detect(img)
    if base is None:
        raise SystemExit("no face detected in the reference photo")
    P0, S = base.points, ipd(base.points)
    out: dict = {"image_size": list(img.shape[:2]), "ipd_px": round(S, 1), "landmarks": int(len(P0)),
                 "pose_reported": {k: round(v, 2) for k, v in base.pose.items()}, "num_faces": base.num_faces,
                 "subset_size": len(SUBSET)}

    # 1. determinism: same image, repeated
    reps = [detect(img).points for _ in range(5)]
    out["repeat_same_image_x5_max_abs_diff_px"] = float(max(np.abs(r - P0).max() for r in reps))

    # 2. lossless copy
    ok, png = cv2.imencode(".png", img)
    out["lossless_png_copy"] = stats(P0, detect(cv2.imdecode(png, cv2.IMREAD_COLOR)).points, S)

    # 3. JPEG recompression
    out["jpeg"] = {}
    for q in (95, 85, 70, 50, 30):
        f = detect(jpeg(img, q))
        out["jpeg"][f"q{q}"] = stats(P0, f.points, S) if f else "no face"

    # 4. resolution (landmarks scaled back to the original frame)
    out["resize"] = {}
    for s in (0.25, 0.5, 0.75, 1.25):
        f = detect(cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC))
        if f is None:
            out["resize"][f"x{s}"] = "no face"
            continue
        p = f.points.copy(); p /= s
        out["resize"][f"x{s}"] = {**stats(P0, p, S), "face_ipd_px_in_resized": round(ipd(f.points), 1)}

    # 5. in-plane rotation (roll): detect on the rotated photo, rotate landmarks back
    out["roll"] = {}
    for deg in (5, 10, 20, 30):
        rot, m = rotate(img, deg)
        f = detect(rot)
        if f is None:
            out["roll"][f"{deg}deg"] = "no face"
            continue
        inv = cv2.invertAffineTransform(m)
        p = f.points.copy(); p[:, :2] = f.points[:, :2] @ inv[:, :2].T + inv[:, 2]
        out["roll"][f"{deg}deg"] = {**stats(P0, p, S), "roll_reported_deg": round(f.pose["roll"], 1)}

    # 6. photometric changes
    out["photometric"] = {}
    for name, variant in {"darker_x0.5": (img * 0.5).astype(np.uint8), "brighter_x1.5": np.clip(img * 1.5, 0, 255).astype(np.uint8),
                          "warm_cast": np.clip(img * np.array([0.8, 1.0, 1.25]), 0, 255).astype(np.uint8),
                          "blur_sigma2": cv2.GaussianBlur(img, (0, 0), 2), "blur_sigma5": cv2.GaussianBlur(img, (0, 0), 5)}.items():
        f = detect(variant)
        out["photometric"][name] = stats(P0, f.points, S) if f else "no face"

    # 7. occlusion: black box over a region; stats only on landmarks OUTSIDE the box
    out["occlusion"] = {}
    x0, y0, x1, y1 = P0[:, 0].min(), P0[:, 1].min(), P0[:, 0].max(), P0[:, 1].max()
    boxes = {"mouth_chin": (x0, P0[LM.UPPER_LIP_TOP, 1], x1, y1), "one_eye_region": (P0[LM.L_EYE_OUT, 0] - 0.0, P0[LM.L_BROW_TOP, 1] - 10, x1, P0[LM.L_EYE_LOW, 1] + 10),
             "forehead": (x0, y0 - 20, x1, P0[LM.R_BROW_TOP, 1] - 5)}
    for name, (bx0, by0, bx1, by1) in boxes.items():
        occ = img.copy(); cv2.rectangle(occ, (int(bx0), int(by0)), (int(bx1), int(by1)), (0, 0, 0), -1)
        f = detect(occ)
        if f is None:
            out["occlusion"][name] = "no face"
            continue
        outside = ~((P0[:, 0] >= bx0) & (P0[:, 0] <= bx1) & (P0[:, 1] >= by0) & (P0[:, 1] <= by1))
        d = np.linalg.norm(f.points[:, :2] - P0[:, :2], axis=1) / S
        out["occlusion"][name] = {"landmarks_outside_box": int(outside.sum()), "mean_pct_ipd_outside": round(float(d[outside].mean() * 100), 3),
                                  "max_pct_ipd_outside": round(float(d[outside].max() * 100), 3),
                                  "mean_pct_ipd_inside(hallucinated)": round(float(d[~outside].mean() * 100), 3) if (~outside).any() else None}

    # 8. mirror test: flip the photo; every R/L pair must swap and x must reflect. This checks the pair table
    #    against the REAL model; a wrong pair shows up as a large error.
    flipped = cv2.flip(img, 1)
    f = detect(flipped)
    W = img.shape[1]
    err = {}
    for r, l in LM.SYMMETRY_PAIRS:
        e1 = np.linalg.norm(np.array([W - f.points[l, 0], f.points[l, 1]]) - P0[r, :2]) / S
        e2 = np.linalg.norm(np.array([W - f.points[r, 0], f.points[r, 1]]) - P0[l, :2]) / S
        err[f"{r}-{l}"] = round(float(max(e1, e2) * 100), 2)
    wrong_if_swapped = {k: round(float(np.linalg.norm(np.array([W - f.points[int(k.split('-')[0]), 0], f.points[int(k.split('-')[0]), 1]]) - P0[int(k.split('-')[0]), :2]) / S * 100), 2) for k in err}
    out["mirror_pairs"] = {"max_pair_error_pct_ipd": max(err.values()), "mean_pair_error_pct_ipd": round(float(np.mean(list(err.values()))), 2),
                           "per_pair_pct_ipd": err, "same_side_error_pct_ipd_for_contrast": wrong_if_swapped}

    # 9. two faces in one frame: which face is analysed?
    h = img.shape[0]
    two = np.hstack([img, cv2.resize(img, (int(img.shape[1] * 0.5), int(h * 0.5)))[:h]]) if False else np.hstack([img, img])
    f2 = landmarks.detect(two)
    out["two_faces"] = {"detected": f2.num_faces if f2 else 0, "analysed_face_x_range_px": [round(float(f2.points[:, 0].min())), round(float(f2.points[:, 0].max()))] if f2 else None,
                        "frame_width_px": int(two.shape[1])}

    # 10. frontalize(): yaw pose-correction behaviour on this photo's 3D landmarks
    out["frontalize"] = frontalize_study(P0)
    return out


def frontalize_study(P0: np.ndarray) -> dict:
    """Rotate the REAL 3D landmarks by a known yaw, then ask frontalize() to recover it. This tests the algorithm on
    realistic geometry with a known answer (an approximation of a real head turn, not a substitute for captured poses)."""
    base_pts, base_yaw = metrics.frontalize(P0)
    res = {"estimated_yaw_of_untouched_photo_deg": round(base_yaw, 2), "known_yaw_recovery": {}}
    for deg in (-40, -35, -30, -25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30, 35, 40):
        turned = metrics._yaw_rotate(P0, deg)
        _, est = metrics.frontalize(turned)
        res["known_yaw_recovery"][str(deg)] = {"recovered_deg": round(est, 2), "total_estimate_vs_applied_deg": round(est - (-deg) - base_yaw * 0, 2)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--label", default="photo")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "results"))
    a = ap.parse_args()
    res = run(a.image)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    p = Path(a.out) / f"landmark_validation_{a.label}.json"
    p.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("mirror_pairs", "frontalize")}, indent=1)[:6000])
    print("mirror pairs:", {k: v for k, v in res["mirror_pairs"].items() if k != "per_pair_pct_ipd" and k != "same_side_error_pct_ipd_for_contrast"})
    print("frontalize:", res["frontalize"]["estimated_yaw_of_untouched_photo_deg"])
    print("wrote", p)


if __name__ == "__main__":
    main()
