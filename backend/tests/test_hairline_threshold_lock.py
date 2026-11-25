"""BASELINE LOCK for the pre-validation hairline engine. If a pinned value changes this test fails on purpose: a threshold may only change
with a recorded reason in docs/HAIRLINE_THRESHOLD_REGISTER.md and an update of this baseline - never to improve a validation score."""
import unittest
from pathlib import Path

from app import hair, hairline
from evals import hairline_eval

ROOT = Path(__file__).resolve().parent.parent.parent
BASELINE = {
    "hairline.T_MILD": (hairline.T_MILD, 0.06), "hairline.T_POSSIBLE": (hairline.T_POSSIBLE, 0.11), "hairline.T_PRONOUNCED": (hairline.T_PRONOUNCED, 0.185),
    "hairline.MIN_CONTRAST_DE": (hairline.MIN_CONTRAST_DE, 18.0), "hairline.NOISE_FLOOR_V": (hairline.NOISE_FLOOR_V, 0.03),
    "hairline.CHANGE_V": (hairline.CHANGE_V, 0.06), "hairline.NOISE_FLOOR_DENSITY": (hairline.NOISE_FLOOR_DENSITY, 0.05),
    "hairline.COLUMNS.count": (len(hairline.COLUMNS), 25), "hairline.COLUMNS.first": (float(hairline.COLUMNS[0]), -0.5),
    "hairline.COLUMNS.last": (float(hairline.COLUMNS[-1]), 0.5),
    "hairline.ENGINE_VERSION": (hairline.ENGINE_VERSION, "hairline-engine-v1"),
    "hair.HEAD_BREADTH_MM": (hair.HEAD_BREADTH_MM, 145.0),
    "eval.MIN_N": (hairline_eval.MIN_N, 30), "eval.MIN_POS": (hairline_eval.MIN_POS, 8), "eval.REVIEW_TRIGGER_BZ": (hairline_eval.REVIEW_TRIGGER_BZ, 0.06),
}


class Lock(unittest.TestCase):
    def test_pinned_values_are_unchanged(self):
        changed = {k: (now, was) for k, (now, was) in BASELINE.items() if now != was}
        self.assertEqual(changed, {}, "A threshold changed. Record the reason in docs/HAIRLINE_THRESHOLD_REGISTER.md and update this baseline "
                                      "deliberately. Never tune a threshold to improve a validation score.")

    def test_register_lists_every_pinned_name_and_marks_everything_placeholder(self):
        doc = (ROOT / "docs" / "HAIRLINE_THRESHOLD_REGISTER.md").read_text(encoding="utf-8")
        for name in ("T_MILD", "T_POSSIBLE", "T_PRONOUNCED", "MIN_CONTRAST_DE", "NOISE_FLOOR_V", "CHANGE_V", "NOISE_FLOOR_DENSITY", "COLUMNS",
                     "HEAD_BREADTH_MM", "MIN_N / MIN_POS", "REVIEW_TRIGGER_BZ"):
            self.assertIn(name, doc, name)
        rows = [ln for ln in doc.splitlines() if ln.startswith("| `")]
        self.assertGreaterEqual(len(rows), 40)
        self.assertTrue(all("VALIDATION STATUS: PLACEHOLDER" in r for r in rows), "every registered threshold must say PLACEHOLDER")
        self.assertNotIn("VALIDATION STATUS: VALIDATED", doc)

    def test_the_registered_numbers_match_the_code_for_the_named_constants(self):
        doc = (ROOT / "docs" / "HAIRLINE_THRESHOLD_REGISTER.md").read_text(encoding="utf-8")
        for needle in ("| `T_MILD` | 0.06 ", "| `T_POSSIBLE` | 0.11 ", "| `T_PRONOUNCED` | 0.185 ", "| `NOISE_FLOOR_V` | 0.03 ", "| `CHANGE_V` | 0.06 "):
            self.assertIn(needle, doc, needle)


if __name__ == "__main__":
    unittest.main()
