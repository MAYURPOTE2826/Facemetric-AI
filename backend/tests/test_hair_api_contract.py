"""API contract for `hair.analysis`: additive, always well-formed, never breaks a consumer that does not know about it.
SOFTWARE contract tests on synthetic scenes - not accuracy evidence."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2

import hair_fixtures as F
from app import hair, hairline, main, recommendations, report

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))
TOP = {"scalp_pct": 6.0, "label": "Dense", "score": 92, "parting": None,
       "regional": {"central_scalp_pct": 5.0, "outer_scalp_pct": 4.0, "hair_area_fraction": 0.5}}

REQUIRED = {"engine", "status", "validation_status", "hairline", "temples", "frontal_density", "crown", "image_quality", "longitudinal",
            "capture", "limitations", "guidance"}
NESTED = {
    "hairline": {"status", "confidence", "points", "shape", "symmetry"},
    "frontal_density": {"status", "confidence"},
    "crown": {"status", "confidence"},
    "image_quality": {"confidence", "hairline_visible", "temples_visible", "flags", "crown_visible"},
}


def cases():
    out = {}
    img, cat, pts = F.scene(hairline=F.mature(0.14))
    out["front_only"] = hairline.build(img, cat, pts)
    out["front_plus_top"] = hairline.build(img, cat, pts, TOP, None)
    out["top_unusable"] = hairline.build(img, cat, pts, None, "Couldn't find enough hair in the photo.")
    out["low_quality"] = hairline.build(*F.scene(scale=0.3))
    out["hidden_hairline"] = hairline.build(*F.scene(fringe=True))
    out["off_frame"] = hairline.build(*F.scene(crop_top=300))
    out["no_face"] = hairline.build(img, cat, None)
    return out


def result_with(hair_block):
    a = copy.deepcopy(BASE)
    cands = recommendations.candidates(a["metrics"], a["skin"], a.get("profile"))
    a.update({"id": "a" * 32, "created_at": 1_700_000_000, "paid": False, "report": report.rule_report(a, cands), "report_source": "rules",
              "_candidates": cands, "hair": hair_block})
    return a


class Shape(unittest.TestCase):
    def test_every_outcome_has_the_same_required_structure_and_is_json_serialisable(self):
        for name, a in cases().items():
            self.assertTrue(REQUIRED <= set(a), f"{name}: missing {REQUIRED - set(a)}")
            for k, req in NESTED.items():
                self.assertTrue(req <= set(a[k]), f"{name}.{k}: missing {req - set(a[k])}")
            for side in ("left", "right"):
                self.assertTrue({"status", "text", "confidence"} <= set(a["temples"][side]), name)
            json.dumps({k: v for k, v in a.items() if k != "image"})

    def test_status_vocabularies_are_closed(self):
        for name, a in cases().items():
            self.assertIn(a["status"], {"complete", "partial", "inconclusive"}, name)
            self.assertIn(a["crown"]["status"], {"assessed", "not_assessable", "inconclusive"}, name)
            self.assertIn(a["longitudinal"]["status"], {"not_available"}, name)

    def test_front_only_front_plus_top_low_quality_and_hidden_outcomes(self):
        c = cases()
        self.assertEqual(c["front_only"]["crown"]["status"], "not_assessable")
        self.assertEqual(c["front_only"]["status"], "partial")
        self.assertEqual(c["front_plus_top"]["crown"]["status"], "assessed")
        self.assertEqual(c["front_plus_top"]["status"], "complete")
        self.assertEqual(c["top_unusable"]["crown"]["status"], "inconclusive")
        self.assertIn("low_resolution", c["low_quality"]["image_quality"]["flags"])
        self.assertLess(c["low_quality"]["image_quality"]["confidence"], 0.5)
        for k in ("hidden_hairline", "off_frame", "no_face"):
            self.assertEqual(c[k]["status"], "inconclusive", k)
            self.assertNotEqual(c[k]["hairline"]["status"], "detected", k)


class Consumers(unittest.TestCase):
    """The public (browser-facing) payload for old and new reports, free and paid."""

    def public(self, hair_block):
        return main._public(result_with(hair_block))

    def test_legacy_report_without_analysis_passes_through_untouched(self):
        legacy = {"available": True, "questionnaire": False, "hairline": None, "crown": None, "score": None, "plan": ["x"], "causes": [], "tests": [], "myths": []}
        d = self.public(legacy)
        self.assertTrue(d["hair"]["available"])
        self.assertIsNone(d["hair"].get("analysis"))

    def test_new_analysis_is_exposed_to_free_reports_and_legacy_keys_still_present(self):
        img, cat, pts = F.scene()
        block = hair.analyze(img, SimpleNamespace(points=pts), {"sex": "male"}, None, cat)
        d = self.public(block)
        self.assertEqual(d["hair"]["analysis"]["engine"], hairline.ENGINE_VERSION)
        for k in ("available", "hairline", "crown", "score", "image", "see_doctor"):
            self.assertIn(k, d["hair"])

    def test_missing_hair_block_or_unavailable_hair_does_not_break_the_report(self):
        for block in (None, {"available": False, "hairline_note": "Hair analysis failed: boom"}):
            d = self.public(block)
            self.assertFalse((d.get("hair") or {}).get("available", False))

    def test_engine_failure_keeps_the_legacy_result_and_returns_inconclusive(self):
        img, cat, pts = F.scene()
        orig = hairline.build
        hairline.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            block = hair.analyze(img, SimpleNamespace(points=pts), {}, None, cat)
        finally:
            hairline.build = orig
        self.assertTrue(block["available"])
        self.assertEqual(block["analysis"]["status"], "inconclusive")
        self.assertEqual(block["analysis"]["hairline"]["status"], "not_detected")
        self.assertEqual(block["analysis"]["crown"]["status"], "not_assessable")
        d = self.public(block)
        self.assertEqual(d["hair"]["analysis"]["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
