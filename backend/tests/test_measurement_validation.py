"""Measurement-validation framework: arithmetic verified against hand calculations on SYNTHETIC numbers.
No caliper data exists; nothing here says anything about the software's real accuracy."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from evals import measurement_validation as mv


def ref(subject, m, op, rep, v):
    return {"subject_id": subject, "measurement": m, "operator": op, "repetition": str(rep), "value_mm": str(v), "instrument": "caliper"}


def auto(subject, m, img, v, dev="phoneA"):
    return {"subject_id": subject, "image_id": img, "measurement": m, "value_mm": str(v), "device": dev, "conditions": "daylight", "measurement_version": "t"}


class Agreement(unittest.TestCase):
    def test_hand_computed_errors(self):
        reference = [ref("s1", "face_width", "o1", 1, 100), ref("s2", "face_width", "o1", 1, 110), ref("s3", "face_width", "o1", 1, 120), ref("s4", "face_width", "o1", 1, 130)]
        automated = [auto("s1", "face_width", "i1", 102), auto("s2", "face_width", "i2", 107), auto("s3", "face_width", "i3", 125), auto("s4", "face_width", "i4", 128)]
        r = mv.evaluate(reference, automated)["measurements"]["face_width"]
        errs = np.array([2, -3, 5, -2.0])
        a = r["agreement"]
        self.assertEqual(a["n_pairs"], 4)
        self.assertAlmostEqual(a["bias"], 0.5, places=4)
        sd = float(errs.std(ddof=1))
        self.assertAlmostEqual(a["sd_of_errors"], round(sd, 4), places=4)
        self.assertAlmostEqual(a["loa_lower"], round(0.5 - 1.96 * sd, 4), places=3)
        self.assertAlmostEqual(a["loa_upper"], round(0.5 + 1.96 * sd, 4), places=3)
        self.assertAlmostEqual(r["absolute_error_mm"]["mean"], 3.0, places=4)
        self.assertAlmostEqual(r["absolute_error_mm"]["median"], 2.5, places=4)
        self.assertAlmostEqual(r["absolute_error_mm"]["max"], 5.0, places=4)
        self.assertAlmostEqual(r["absolute_error_mm"]["p95"], float(np.percentile([2, 3, 5, 2], 95)), places=3)
        self.assertAlmostEqual(r["relative_absolute_error_pct"]["mean"], round(np.mean([2 / 100, 3 / 110, 5 / 120, 2 / 130]) * 100, 4), places=3)
        self.assertIn("precision_note", a)  # n < 30

    def test_bland_altman_points_are_mean_and_difference(self):
        r = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "i1", 104)])["measurements"]["m"]
        pt = r["bland_altman_points"][0]
        self.assertEqual((pt["mean_mm"], pt["difference_mm"], pt["reference_mm"], pt["automated_mm"]), (102.0, 4.0, 100.0, 104.0))

    def test_reference_is_the_mean_over_operators_and_repetitions(self):
        reference = [ref("s1", "m", "o1", 1, 100), ref("s1", "m", "o1", 2, 102), ref("s1", "m", "o2", 1, 104), ref("s1", "m", "o2", 2, 106)]
        r = mv.evaluate(reference, [auto("s1", "m", "i1", 105)])["measurements"]["m"]
        self.assertEqual(r["bland_altman_points"][0]["reference_mm"], 103.0)
        self.assertAlmostEqual(r["agreement"]["bias"], 2.0, places=4)

    def test_multiple_photos_per_subject_each_form_a_pair(self):
        r = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "i1", 98), auto("s1", "m", "i2", 104)])["measurements"]["m"]
        self.assertEqual(r["agreement"]["n_pairs"], 2)
        self.assertAlmostEqual(r["agreement"]["bias"], 1.0, places=4)

    def test_perfect_agreement(self):
        reference = [ref(f"s{i}", "m", "o1", 1, 100 + i) for i in range(5)]
        automated = [auto(f"s{i}", "m", f"i{i}", 100 + i) for i in range(5)]
        r = mv.evaluate(reference, automated)["measurements"]["m"]
        self.assertEqual((r["agreement"]["bias"], r["agreement"]["sd_of_errors"]), (0.0, 0.0))
        self.assertEqual(r["absolute_error_mm"]["max"], 0.0)

    def test_proportional_bias_slope_detected(self):
        reference = [ref(f"s{i}", "m", "o1", 1, 100 + 10 * i) for i in range(6)]
        automated = [auto(f"s{i}", "m", f"i{i}", (100 + 10 * i) * 1.05) for i in range(6)]  # always 5% too large
        slope = mv.evaluate(reference, automated)["measurements"]["m"]["agreement"]["proportional_bias_slope_mm_per_mm"]
        self.assertGreater(slope, 0.04)

    def test_se_of_limits_matches_the_published_formula_and_shrinks_with_n(self):
        import math
        rng = np.random.default_rng(1)
        e = rng.normal(0, 2, 100)
        a = mv.agreement(e, np.full(100, 100.0))
        self.assertAlmostEqual(a["se_of_each_limit"], round(float(e.std(ddof=1)) * math.sqrt(1 / 100 + 1.96 ** 2 / (2 * 99)), 4), places=4)
        self.assertLess(a["se_of_each_limit"], mv.agreement(e[:30], np.full(30, 100.0))["se_of_each_limit"])
        self.assertNotIn("precision_note", a)  # n >= 30


class Repeatability(unittest.TestCase):
    def test_reference_repeatability_and_operator_difference(self):
        reference = [ref("s1", "m", "o1", 1, 100), ref("s1", "m", "o1", 2, 102), ref("s2", "m", "o1", 1, 110), ref("s2", "m", "o1", 2, 114)]
        rr = mv.evaluate(reference, [auto("s1", "m", "i", 101)])["measurements"]["m"]["reference_repeatability"]
        sw = float(np.sqrt(np.mean([np.var([100, 102], ddof=1), np.var([110, 114], ddof=1)])))
        self.assertAlmostEqual(rr["within_subject_sd"], round(sw, 4), places=4)
        self.assertAlmostEqual(rr["repeatability_coefficient"], round(1.96 * np.sqrt(2) * sw, 4), places=3)
        self.assertEqual(rr["subjects_with_repeats"], 2)

    def test_operator_difference(self):
        reference = [ref("s1", "m", "o1", 1, 100), ref("s1", "m", "o2", 1, 103)]
        rr = mv.evaluate(reference, [auto("s1", "m", "i", 101)])["measurements"]["m"]["reference_repeatability"]
        self.assertEqual(rr["mean_difference_between_operators_mm"], 3.0)

    def test_automated_repeatability_across_photos(self):
        r = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "a", 99), auto("s1", "m", "b", 101)])["measurements"]["m"]
        self.assertAlmostEqual(r["automated_repeatability_across_photos"]["within_subject_sd"], round(float(np.std([99, 101], ddof=1)), 4), places=4)

    def test_no_repeats_means_no_invented_repeatability(self):
        r = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "a", 99)])["measurements"]["m"]
        self.assertEqual(r["reference_repeatability"]["subjects_with_repeats"], 0)
        self.assertNotIn("within_subject_sd", r["reference_repeatability"])


class HonestyAndEdgeCases(unittest.TestCase):
    def test_never_declares_validity_and_defines_no_threshold(self):
        res = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "a", 100)])
        self.assertIn("NOT YET DEFINED", res["acceptance_criteria"])
        self.assertEqual(res["measurements"]["m"]["status"], "ESTIMATED - NOT VALIDATED")
        words = set(json.dumps({k: v for k, v in res.items() if k != "measurements"}).lower().replace('"', " ").split())
        self.assertFalse({"validated", "pass", "passed", "fail"} & words - {"validated"} or False)
        flat = json.dumps(res).lower()
        for banned in ("clinically accurate", "high precision", "+/- 3 mm", "±3 mm"):
            self.assertNotIn(banned, flat)

    def test_unmatched_records_are_reported_not_dropped(self):
        res = mv.evaluate([ref("s1", "m", "o1", 1, 100), ref("s2", "m", "o1", 1, 101)], [auto("s1", "m", "a", 100), auto("s9", "m", "z", 105)])
        self.assertEqual(res["unmatched"]["reference_without_automated"], ["s2/m"])
        self.assertEqual(res["unmatched"]["automated_without_reference"], ["s9/m"])
        self.assertEqual(res["measurements"]["m"]["agreement"]["n_pairs"], 1)

    def test_single_pair_has_no_invented_limits(self):
        a = mv.evaluate([ref("s1", "m", "o1", 1, 100)], [auto("s1", "m", "a", 103)])["measurements"]["m"]["agreement"]
        self.assertEqual(a["bias"], 3.0)
        self.assertNotIn("loa_lower", a)
        self.assertIn("note", a)

    def test_csv_round_trip(self):
        d = Path(tempfile.mkdtemp())
        rp, ap = d / "r.csv", d / "a.csv"
        with open(rp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(ref("s", "m", "o", 1, 1).keys())); w.writeheader(); w.writerow(ref("s1", "m", "o1", 1, 100))
        with open(ap, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(auto("s", "m", "i", 1).keys())); w.writeheader(); w.writerow(auto("s1", "m", "a", 101))
        r = mv.evaluate(mv.read_csv(rp), mv.read_csv(ap))
        self.assertEqual(r["measurements"]["m"]["agreement"]["bias"], 1.0)

    def test_the_software_never_attaches_a_pm_figure_to_a_millimetre_value(self):
        """Source scan: no unsupported precision claim anywhere in the application or the frontend source."""
        import re
        root = Path(__file__).resolve().parent.parent
        files = list((root / "app").glob("*.py")) + list((root.parent / "frontend" / "src").rglob("*.ts*"))
        pat = re.compile(r"(±|\+/-)\s*\d+(\.\d+)?\s*(mm|%)|clinically accurate|high precision", re.I)
        offenders = []
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if pat.search(line) and "clamp" not in line.lower():  # a parameter clamp is not an accuracy claim
                    offenders.append(f"{f.name}:{n}: {line.strip()[:90]}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
