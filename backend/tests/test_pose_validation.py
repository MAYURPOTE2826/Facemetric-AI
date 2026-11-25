"""Pose-validation evaluator arithmetic on SYNTHETIC numbers with stub estimators. Says nothing about real pose accuracy."""
import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from evals import pose_validation as pv


def rows(refs):
    return [{"image_id": f"i{k}", "subject_id": f"s{k}", "image_file": f"i{k}.png", "reference_yaw_deg": str(v), "method": "turntable"} for k, v in enumerate(refs)]


def stub(mp_fn, fr_fn, status="ok"):
    state = {"i": 0}
    refs = state

    def est(img):
        v = img
        return mp_fn(v), fr_fn(v), status(v) if callable(status) else status
    return est


class Evaluate(unittest.TestCase):
    def run_eval(self, refs, mp_fn, fr_fn, status="ok"):
        rs = rows(refs)
        lookup = {r["image_file"]: float(r["reference_yaw_deg"]) for r in rs}
        return pv.evaluate(rs, lambda f: lookup[f], estimators=stub(mp_fn, fr_fn, status))

    def test_no_reference_data_is_not_measured(self):
        self.assertIn("NOT MEASURED", pv.evaluate([], lambda f: None)["status"])

    def test_known_bias_and_absolute_errors(self):
        r = self.run_eval([0, 10, 20, 30], lambda v: v + 2.0, lambda v: v - 5.0)
        mp, fr = r["mediapipe"]["overall"], r["frontalize"]["overall"]
        self.assertEqual((mp["bias_signed_mean"], mp["mean_abs"], mp["max_abs"]), (2.0, 2.0, 2.0))
        self.assertEqual((fr["bias_signed_mean"], fr["mean_abs"], fr["median_abs"], fr["max_abs"]), (-5.0, 5.0, 5.0, 5.0))
        self.assertEqual(r["reference_range_deg"], [0, 30])
        self.assertEqual(r["mediapipe_vs_frontalize_difference_deg"]["bias_signed_mean"], -7.0)

    def test_line_fit_recovers_slope_and_intercept(self):
        r = self.run_eval([-20, -10, 0, 10, 20], lambda v: 0.9 * v + 1.0, lambda v: v)
        fit = r["mediapipe"]["line_fit_estimate_vs_reference"]
        self.assertAlmostEqual(fit["slope"], 0.9, places=3)
        self.assertAlmostEqual(fit["intercept_deg"], 1.0, places=3)

    def test_errors_are_split_by_reference_yaw_band(self):
        r = self.run_eval([5, 15, 25, 40], lambda v: v + (1 if v < 20 else 4), lambda v: v)
        b = r["mediapipe"]["by_reference_yaw_band"]
        self.assertEqual((b["0-10"]["mean_abs"], b["10-20"]["mean_abs"], b["20-30"]["mean_abs"], b["30-360"]["mean_abs"]), (1.0, 1.0, 4.0, 4.0))

    def test_saturated_cases_are_listed_not_dropped(self):
        r = self.run_eval([10, 35], lambda v: v, lambda v: min(v, 30.5), status=lambda v: "saturated" if v > 30 else "ok")
        sat = r["frontalize"]["saturated_or_undetermined"]
        self.assertEqual(len(sat), 1)
        self.assertEqual((sat[0]["reference"], sat[0]["status"]), (35.0, "saturated"))
        self.assertEqual(r["frontalize"]["overall"]["n"], 2)  # still counted in the error statistics

    def test_detection_failures_are_counted(self):
        rs = rows([0, 10])
        r = pv.evaluate(rs, lambda f: f, estimators=lambda img: None if img == "i0.png" else (10.0, 10.0, "ok"))
        self.assertEqual(r["failures"], [{"image_id": "i0", "reason": "no face detected"}])
        self.assertEqual(r["images"], 1)

    def test_a_flipped_sign_convention_is_warned_about(self):
        r = self.run_eval([-20, -10, 10, 20], lambda v: -v, lambda v: v)
        self.assertIn("SIGN_WARNING", r["mediapipe"])
        self.assertNotIn("SIGN_WARNING", r["frontalize"])

    def test_no_thresholds_or_verdicts(self):
        r = self.run_eval([0, 10, 20], lambda v: v, lambda v: v)
        self.assertIn("NOT DEFINED", r["acceptance_criteria"])
        flat = " ".join(str(k).lower() for k in r)
        self.assertNotIn("verdict", flat)

    def test_small_n_flags_p95(self):
        self.assertIn("p95_note", self.run_eval([0, 10, 20], lambda v: v + 1, lambda v: v)["mediapipe"]["overall"])


class ReferenceFile(unittest.TestCase):
    def write(self, data):
        d = Path(tempfile.mkdtemp())
        p = d / "ref.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            w.writerows(data)
        return p

    def test_software_derived_references_are_rejected(self):
        for bad in ("mediapipe", "frontalize", "software", "estimated", "visual"):
            p = self.write([{"image_id": "a", "subject_id": "s", "image_file": "a.png", "reference_yaw_deg": "5", "method": bad}])
            with self.assertRaises(ValueError, msg=bad):
                pv.read_reference(p)

    def test_missing_columns_are_rejected(self):
        p = self.write([{"image_id": "a", "subject_id": "s", "image_file": "a.png", "reference_yaw_deg": "", "method": "turntable"}])
        with self.assertRaises(ValueError):
            pv.read_reference(p)

    def test_valid_file_loads(self):
        p = self.write([{"image_id": "a", "subject_id": "s", "image_file": "a.png", "reference_yaw_deg": "5", "method": "calibrated turntable"}])
        self.assertEqual(len(pv.read_reference(p)), 1)


if __name__ == "__main__":
    unittest.main()
