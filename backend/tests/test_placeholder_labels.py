"""Reference values that have no verified source must be labelled as placeholders everywhere they are produced or shown."""
import copy
import json
import re
import unittest
from pathlib import Path

import numpy as np

from app import anthropometry, eyes, metrics, report_validator as rv
from test_measurements import face

LABEL = "PLACEHOLDER - NOT PRODUCTION VALIDATED"
ROOT = Path(__file__).resolve().parent.parent.parent
BASE = json.loads((ROOT / "backend" / "evals" / "base_analysis.json").read_text(encoding="utf-8"))


class Labels(unittest.TestCase):
    def test_measurement_table_carries_the_label(self):
        self.assertEqual(anthropometry.table(face(), "male")["range_status"], LABEL)

    def test_eye_and_brow_result_carries_the_label(self):
        img = np.full((700, 700, 3), 128, np.uint8)
        p = face()
        self.assertEqual(eyes.analyze(img, p, p, 0.0)["thresholds_status"], LABEL)

    def test_every_report_validation_block_lists_all_three_reference_sets_as_placeholders(self):
        a = copy.deepcopy(BASE)
        a.setdefault("yaw_correction", 0.0)
        rv.apply_quality_rules(a, {"issues": []}, 0.2, None)
        rr = a["validation"]["reference_ranges"]
        self.assertEqual(set(rr), {"measurement_table_ranges", "harmony_metric_references", "eye_and_brow_thresholds"})
        self.assertTrue(all(v == LABEL for v in rr.values()))

    def test_metrics_module_states_its_reference_status(self):
        self.assertIn("NOT PRODUCTION VALIDATED", metrics.REFERENCE_STATUS)
        self.assertIn("NOT", metrics.REFERENCE_STATUS)


class NoUnverifiedAuthority(unittest.TestCase):
    def test_modules_do_not_assert_an_unverified_source(self):
        a = (ROOT / "backend" / "app" / "anthropometry.py").read_text(encoding="utf-8")
        self.assertNotIn("Farkas-style", a)
        self.assertIn("NO VERIFIED SOURCE", a)
        self.assertIn("PLACEHOLDER", (ROOT / "backend" / "app" / "eyes.py").read_text(encoding="utf-8"))

    def test_user_visible_metric_text_does_not_claim_population_typicality_as_fact(self):
        src = (ROOT / "backend" / "app" / "metrics.py").read_text(encoding="utf-8")
        self.assertNotIn("is typical for South Asian faces", src)
        self.assertNotIn("is typical for Indian faces", src)
        self.assertIn("unverified approximation", src)

    def test_the_frontend_shows_the_labels(self):
        fig = (ROOT / "frontend" / "src" / "components" / "ReportFigures.tsx").read_text(encoding="utf-8")
        self.assertIn("placeholder - not validated", fig)
        self.assertIn('data-testid="range-status"', fig)
        self.assertIn('data-testid="eye-thresholds-status"', fig)
        page = (ROOT / "frontend" / "src" / "app" / "report" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn('data-testid="harmony-reference-status"', page)

    def test_the_audit_document_covers_all_four_modules_and_the_label(self):
        d = (ROOT / "docs" / "RECONSTRUCTED_MODULES.md").read_text(encoding="utf-8")
        for name in ("anthropometry.py", "eyes.py", "diagrams.py", "ReportFigures.tsx"):
            self.assertIn(name, d)
        for aspect in ("Source / specification", "Formula", "Independently validated", "Dependent outputs"):
            self.assertGreaterEqual(len(re.findall(aspect, d)), 3)
        self.assertIn(LABEL, d)


if __name__ == "__main__":
    unittest.main()
