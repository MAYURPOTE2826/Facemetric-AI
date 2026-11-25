"""Reproducible investigation of frontalize() vs MediaPipe's head-pose yaw.

    python -m evals.frontalize_investigation --image <path> [--image <path2>]

It does NOT decide which yaw is "right": there is no ground-truth head pose in this project. It establishes conventions,
isolates causes that can be shown with exact geometry, and measures what remains. Findings are in docs/FRONTALIZE_INVESTIGATION.md.

Conventions established
  frontalize_with_status() returns the rotation d (degrees) applied to the 3D landmarks about the vertical image axis
  (x' = x cos d + z sin d, z' = -x sin d + z cos d) that best balances the summed |x - midline| of the left and right
  members of the symmetry pairs. Adding a head turn of `a` changes the result by exactly -a (verified, slope 1).
  MediaPipe yaw is the Euler yaw (cv2.RQDecomp3x3) of the rotation block of facial_transformation_matrixes; that matrix
  is expressed with the x axis flipped relative to the image frame (found empirically: only the x-flipped convention
  makes the de-posed landmarks left/right balanced).
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np


def roll_points(P: np.ndarray, deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    Q = P.copy()
    ctr = Q[:, :2].mean(0)
    Q[:, :2] = (P[:, :2] - ctr) @ np.array([[c, -s], [s, c]]).T + ctr
    return Q


def synthetic_roll_leakage(face_points: np.ndarray) -> dict:
    """Exact geometry: a symmetric face with a KNOWN yaw plus in-plane roll. A correct estimator ignores the roll."""
    from app import metrics
    out = {}
    for true_yaw in (0, 10):
        base = metrics._yaw_rotate(face_points, true_yaw)
        out[f"true_yaw_{true_yaw}"] = {f"roll_{r}": round(metrics.frontalize_with_status(roll_points(base, r))[1], 2) for r in (0, 2, 5, 10, 20, 30)}
    return out


def pose_matrix_study(bgr) -> dict:
    """De-pose the landmarks with MediaPipe's own matrix under each axis-flip convention and see which one balances them."""
    import cv2
    import mediapipe as mp
    from app import landmarks, metrics
    h, w = bgr.shape[:2]
    res = landmarks._get_landmarker().detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    P = np.array([[p.x * w, p.y * h, p.z * w] for p in res.face_landmarks[0]])
    M = np.array(res.facial_transformation_matrixes[0])
    R = M[:3, :3] / np.cbrt(abs(np.linalg.det(M[:3, :3])))
    ang, *_ = cv2.RQDecomp3x3(R)
    c = P.mean(axis=0)
    rows = []
    for sx, sy, sz in itertools.product((1, -1), repeat=3):
        Pc = (R.T @ (np.diag([sx, sy, sz]) @ (P - c).T)).T
        rows.append({"flips": [sx, sy, sz], "imbalance": round(metrics._side_imbalance(Pc), 2), "frontalize_residual_yaw_deg": round(metrics.frontalize_with_status(Pc)[1], 2)})
    rows.sort(key=lambda r: r["imbalance"])
    return {"mediapipe_pose_deg": {"pitch": round(ang[0], 2), "yaw": round(ang[1], 2), "roll": round(ang[2], 2)},
            "imbalance_of_raw_landmarks": round(metrics._side_imbalance(P), 2), "best_convention": rows[0], "all_conventions": rows}


def real_photo_study(bgr) -> dict:
    import cv2
    from app import landmarks, metrics
    a = landmarks.detect(bgr)
    b = landmarks.detect(cv2.flip(bgr, 1))
    ya, st = metrics.frontalize_with_status(a.points)[1:]
    yb = metrics.frontalize_with_status(b.points)[1]
    return {"frontalize_yaw_deg": round(ya, 2), "status": st, "mediapipe_yaw_deg": round(a.pose["yaw"], 2), "difference_deg": round(ya - a.pose["yaw"], 2),
            "same_sign": bool(np.sign(ya) == np.sign(a.pose["yaw"])), "mirrored_frontalize_yaw_deg": round(yb, 2),
            "frontalize_mirror_asymmetry_deg": round(abs(ya + yb), 2), "mediapipe_mirror_asymmetry_deg": round(abs(a.pose["yaw"] + b.pose["yaw"]), 2),
            "pose_matrix": pose_matrix_study(bgr)}


def known_turn_recovery(P: np.ndarray) -> dict:
    from app import metrics
    base = metrics.frontalize_with_status(P)[1]
    return {"baseline_deg": round(base, 2), "applied_to_recovered": {str(t): [round(metrics.frontalize_with_status(metrics._yaw_rotate(P, t))[1], 2),
            metrics.frontalize_with_status(metrics._yaw_rotate(P, t))[2]] for t in (-40, -20, -10, 0, 10, 13, 15, 20, 35, 40)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", action="append", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))
    import cv2
    from test_measurements import face
    from app import landmarks
    res = {"synthetic_roll_leakage_true_yaw_known": synthetic_roll_leakage(face()), "photos": {}}
    for i, p in enumerate(a.image):
        bgr = cv2.imread(p)
        res["photos"][f"photo_{i + 1}"] = {**real_photo_study(bgr), "known_turn_recovery": known_turn_recovery(landmarks.detect(bgr).points)}
    txt = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
