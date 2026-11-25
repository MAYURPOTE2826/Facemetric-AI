"""Physical-measurement validation against caliper reference measurements (the study in docs/MEASUREMENT_VALIDATION_PLAN.md).

    python -m evals.measurement_validation --reference reference.csv --automated automated.csv [--out report.json]

STATUS: every millimetre value stays "ESTIMATED". This tool produces the evidence a future decision needs; it NEVER
declares a measurement validated and defines NO acceptance thresholds ("ACCEPTANCE CRITERIA NOT YET DEFINED"). No
caliper data exists in this repository and none is fabricated; real-person data belongs OUTSIDE the repository.

reference.csv   subject_id, measurement, operator, repetition, value_mm, instrument
automated.csv   subject_id, image_id, measurement, value_mm, device, conditions, measurement_version
   (`measurement` uses the software's keys, e.g. face_width, nose_width, intercanthal ... and must mean the same
    anatomical distance as the caliper measurement - see FACIAL_MEASUREMENT_METHODOLOGY.md)

Per measurement it reports (all in mm unless stated):
  agreement   n pairs, mean error (bias = automated - reference), SD of errors, 95% limits of agreement (bias +/- 1.96 SD),
              the standard error of those limits (about 1.71 * SD / sqrt(n)), proportional-bias slope
  error       absolute error: mean, median, P95, max; relative error: mean and median absolute % of the reference
  Bland-Altman  the (mean of the pair, difference) points for plotting
  reference repeatability   within-subject SD and repeatability coefficient (1.96 * sqrt(2) * Sw) across repetitions, and
              the mean difference between operators
  automated repeatability   within-subject SD across the subject's different photographs
A "pair" = one automated value (one photograph) against the subject's reference value (mean of all operators and
repetitions for that subject and measurement).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

PILOT_N = 30  # below this the limits of agreement are flagged as imprecise (the plan's pilot size); not an acceptance criterion


def read_csv(path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _f(x):
    return float(x)


def pstats(v: list[float]) -> dict:
    if not v:
        return {"n": 0}
    a = np.asarray(v, float)
    return {"n": int(a.size), "mean": round(float(a.mean()), 4), "median": round(float(np.median(a)), 4),
            "p95": round(float(np.percentile(a, 95)), 4), "max": round(float(a.max()), 4)}


def within_subject_sd(groups: list[list[float]]) -> dict:
    """Pooled within-subject SD from subjects with >= 2 values (sqrt of the mean within-subject variance)."""
    var = [np.var(g, ddof=1) for g in groups if len(g) >= 2]
    if not var:
        return {"subjects_with_repeats": 0}
    sw = float(np.sqrt(np.mean(var)))
    return {"subjects_with_repeats": len(var), "within_subject_sd": round(sw, 4), "repeatability_coefficient": round(1.96 * math.sqrt(2) * sw, 4)}


def agreement(errors: np.ndarray, means: np.ndarray) -> dict:
    n = int(errors.size)
    out = {"n_pairs": n, "bias": round(float(errors.mean()), 4)}
    if n < 2:
        out["note"] = "n < 2: SD and limits of agreement are undefined"
        return out
    sd = float(errors.std(ddof=1))
    out.update(sd_of_errors=round(sd, 4), loa_lower=round(float(errors.mean() - 1.96 * sd), 4), loa_upper=round(float(errors.mean() + 1.96 * sd), 4),
               se_of_each_limit=round(float(sd * math.sqrt(1 / n + 1.96 ** 2 / (2 * (n - 1)))), 4))
    if n < PILOT_N:
        out["precision_note"] = f"n < {PILOT_N}: the limits of agreement are imprecise (see se_of_each_limit)"
    if n >= 3 and float(means.std()) > 0:
        slope = float(np.polyfit(means, errors, 1)[0])
        out["proportional_bias_slope_mm_per_mm"] = round(slope, 5)  # error grows with size when != 0
    return out


def evaluate(reference: list[dict], automated: list[dict]) -> dict:
    ref = defaultdict(list)            # (subject, measurement) -> all reference values
    by_op = defaultdict(lambda: defaultdict(list))  # (subject, measurement) -> operator -> values
    for r in reference:
        k = (r["subject_id"], r["measurement"])
        ref[k].append(_f(r["value_mm"]))
        by_op[k][r["operator"]].append(_f(r["value_mm"]))
    auto = defaultdict(list)           # (subject, measurement) -> [(image_id, value, device, conditions)]
    for a in automated:
        auto[(a["subject_id"], a["measurement"])].append((a["image_id"], _f(a["value_mm"]), a.get("device", ""), a.get("conditions", "")))
    measurements = sorted({m for _, m in ref} | {m for _, m in auto})
    out, unmatched = {}, {"automated_without_reference": [], "reference_without_automated": []}
    for m in measurements:
        errs, means, rels, diffs_op = [], [], [], []
        ref_groups, auto_groups, pairs = [], [], []
        for (s, mm), rv in ref.items():
            if mm != m:
                continue
            ref_groups.append(rv)
            ops = by_op[(s, mm)]
            if len(ops) >= 2:
                om = [float(np.mean(v)) for v in ops.values()]
                diffs_op.append(max(om) - min(om))
            if (s, mm) not in auto:
                unmatched["reference_without_automated"].append(f"{s}/{m}")
                continue
            rmean = float(np.mean(rv))
            vals = [v for _, v, _, _ in auto[(s, mm)]]
            auto_groups.append(vals)
            for image_id, v, dev, cond in auto[(s, mm)]:
                e = v - rmean
                errs.append(e); means.append((v + rmean) / 2); rels.append(abs(e) / rmean * 100 if rmean else float("nan"))
                pairs.append({"subject_id": s, "image_id": image_id, "reference_mm": round(rmean, 3), "automated_mm": round(v, 3),
                              "mean_mm": round((v + rmean) / 2, 3), "difference_mm": round(e, 3), "device": dev, "conditions": cond})
        for (s, mm) in auto:
            if mm == m and (s, mm) not in ref:
                unmatched["automated_without_reference"].append(f"{s}/{m}")
        e, mn = np.asarray(errs, float), np.asarray(means, float)
        out[m] = {
            "status": "ESTIMATED - NOT VALIDATED",
            "agreement": agreement(e, mn) if errs else {"n_pairs": 0},
            "absolute_error_mm": pstats([abs(x) for x in errs]),
            "relative_absolute_error_pct": pstats([r for r in rels if not math.isnan(r)]),
            "reference_repeatability": {**within_subject_sd(ref_groups),
                                        "mean_difference_between_operators_mm": round(float(np.mean(diffs_op)), 4) if diffs_op else None},
            "automated_repeatability_across_photos": within_subject_sd(auto_groups),
            "bland_altman_points": pairs,
        }
    return {
        "measurements": out, "unmatched": unmatched,
        "acceptance_criteria": "ACCEPTANCE CRITERIA NOT YET DEFINED - nothing here is declared valid or invalid",
        "claim_policy": "Do not state a +/- mm figure or a precision claim unless it comes from a study that meets the plan, "
                        "applies to the same capture conditions, and has criteria agreed beforehand.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--automated", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = evaluate(read_csv(a.reference), read_csv(a.automated))
    txt = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
