"""FALSE-REASSURANCE software-safety tests: when the evidence is insufficient the engine must not produce a clean-looking result.
These prove SOFTWARE behaviour on synthetic scenes. They are NOT accuracy validation and say nothing about real photographs."""
import base64
import json
import unittest

import cv2
import numpy as np
from types import SimpleNamespace

import hair_fixtures as F
from app import hair, hairline

REASSURING = ("no obvious recession", "no reduced visible density", "healthy", "no hair loss", "hair score", "within the reference range")


def strings(a):
    return json.dumps({k: v for k, v in a.items() if k not in ("image", "limitations")}).lower()


def assert_not_reassuring(tc, a):
    s = strings(a)
    for phrase in REASSURING:
        tc.assertNotIn(phrase, s, phrase)
    tc.assertEqual(a["status"], "inconclusive")
    tc.assertNotEqual(a["hairline"]["status"], "detected")
    for side in ("left", "right"):
        tc.assertEqual(a["temples"][side]["status"], "not_assessable")
    tc.assertEqual(a["frontal_density"]["status"], "not_assessable")
    tc.assertEqual(a["crown"]["status"], "not_assessable")
    tc.assertIn("confidence", a["hairline"])
    tc.assertLess(a["hairline"]["confidence"], 0.4)


class Cases(unittest.TestCase):
    def test_case1_hairline_hidden(self):
        # hair over the whole forehead (fringe)
        assert_not_reassuring(self, hairline.build(*F.scene(fringe=True)))

    def test_case2_hairline_outside_the_frame(self):
        a = hairline.build(*F.scene(crop_top=300))
        assert_not_reassuring(self, a)
        self.assertIn("hairline_outside_frame", a["image_quality"]["flags"])

    def test_case3_poor_contrast_lowers_confidence_and_flags_it(self):
        good = hairline.build(*F.scene())
        poor = hairline.build(*F.scene(hair=(128, 162, 206)))
        self.assertIn("hair_colour_close_to_skin", poor["image_quality"]["flags"])
        self.assertLess(poor["image_quality"]["confidence"], good["image_quality"]["confidence"])
        self.assertLess(poor["hairline"]["confidence"], good["hairline"]["confidence"])
        for side in ("left", "right"):  # no recession is invented from a low-contrast boundary
            self.assertNotIn("recession_pattern", poor["temples"][side]["status"])

    def test_case3b_near_zero_contrast_is_not_a_confident_detection(self):
        a = hairline.build(*F.scene(hair=(112, 150, 198)))  # hair ~ skin colour
        self.assertIn("hair_colour_close_to_skin", a["image_quality"]["flags"])
        self.assertLessEqual(a["hairline"]["confidence"], 0.6)

    def test_case4_fringe_covering_the_hairline(self):
        a = hairline.build(*F.scene(fringe=True))
        self.assertIn("fringe_or_hair_over_forehead", a["image_quality"]["flags"])
        self.assertFalse(a["image_quality"]["hairline_visible"])
        self.assertTrue(any("Retake" in g for g in a["guidance"]))

    def test_case5_front_image_without_top_image_never_infers_the_crown(self):
        for kw in ({}, {"hairline": F.mature(0.14)}, {"hair": F.LIGHT}, {"thickness": 0.05}, {"wet": True}):
            a = hairline.build(*F.scene(**kw))
            self.assertEqual(a["crown"]["status"], "not_assessable", kw)
            self.assertIsNone(a["crown"]["density"], kw)
            self.assertFalse(a["image_quality"]["crown_visible"], kw)
            self.assertNotEqual(a["status"], "complete", kw)

    def test_case5b_unusable_top_image_is_inconclusive_not_healthy(self):
        a = hairline.build(*F.scene(), None, "Couldn't find enough hair in the photo.")
        self.assertEqual(a["crown"]["status"], "inconclusive")
        self.assertIsNone(a["crown"]["density"])
        self.assertNotIn("no reduced visible density", json.dumps(a["crown"]).lower())

    def test_case6_engine_failure_fabricates_no_healthy_hair_result(self):
        img, cat, pts = F.scene()
        orig = hairline.build
        hairline.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            out = hair.analyze(img, SimpleNamespace(points=pts), {"sex": "male"}, None, cat)
        finally:
            hairline.build = orig
        a = out["analysis"]
        assert_not_reassuring(self, a)
        self.assertIn("error", a["reason"].lower())

    def test_case6b_no_face_and_garbage_input_fabricate_nothing(self):
        img, cat, _ = F.scene()
        assert_not_reassuring(self, hairline.build(img, cat, None))
        assert_not_reassuring(self, hairline.build(img[:0], cat[:0], F.landmarks()))

    def test_clean_input_is_NOT_blocked_so_the_gate_is_not_simply_refusing_everything(self):
        a = hairline.build(*F.scene())
        self.assertEqual(a["hairline"]["status"], "detected")
        self.assertEqual(a["temples"]["left"]["status"], "no_obvious_recession")


def green_pixels(a):
    img = cv2.imdecode(np.frombuffer(base64.b64decode(a["image"]), np.uint8), cv2.IMREAD_COLOR)
    g = np.array(hairline.GREEN, dtype=int)
    return int((np.abs(img.astype(int) - g).max(axis=2) < 45).sum())


class OverlayNeverMoreCertainThanTheVerdict(unittest.TestCase):
    """PDF QA found a green 'high-confidence' line drawn under a 'not reliably visible' verdict. The overlay must follow the gate."""

    def test_clean_hairline_draws_a_green_high_confidence_line(self):
        self.assertGreater(green_pixels(hairline.build(*F.scene())), 100)

    def test_hidden_hairline_draws_no_green_line(self):
        a = hairline.build(*F.scene(fringe=True))
        self.assertFalse(a["image_quality"]["hairline_visible"])
        self.assertLess(green_pixels(a), 20)

    def test_not_assessable_density_shows_no_analysis_region(self):
        clean = hairline.build(*F.scene())
        hidden = hairline.build(*F.scene(fringe=True))
        self.assertEqual(hidden["frontal_density"]["status"], "not_assessable")
        self.assertNotEqual(clean["image"], hidden["image"])


if __name__ == "__main__":
    unittest.main()
