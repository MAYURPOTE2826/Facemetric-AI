"""Metric-specific skin gating, segmentation metric maths, and mask invariants.

Run from backend/:  python -m unittest discover -s tests -v
Real-photo mask tests run only with PFI_TEST_IMAGE=path[,path] (an authorised photograph; never stored in the repo).

IMPORTANT: nothing here measures segmentation ACCURACY. That needs labelled ground-truth masks, which do not exist in
this repository. These tests check (a) the gating table, (b) that the IoU/Dice/FPR/FNR arithmetic is right so it can be
used when labelled data arrives, and (c) structural invariants of the mask.
"""
import copy
import json
import os
import unittest
from pathlib import Path

import numpy as np

from app import report_validator as rv

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))
ALL = set(rv.SKIN_NEEDS)


def decided(*codes):
    return rv.skin_decisions(set(codes))


def withheld(*codes):
    return {k for k, (a, _) in decided(*codes).items() if a == "withhold"}


def flagged(*codes):
    return {k for k, (a, _) in decided(*codes).items() if a == "flag"}


class MetricSpecificGating(unittest.TestCase):
    def test_every_base_skin_concern_has_a_declared_requirement(self):
        keys = {c["key"] for c in BASE["skin"]["concerns"]}
        self.assertFalse(keys - ALL, f"skin concerns without a requirement entry: {keys - ALL}")

    def test_every_flag_effect_names_a_real_dependency_and_has_a_reason(self):
        deps = set().union(*rv.SKIN_NEEDS.values())
        for code, eff in rv.FLAG_EFFECTS.items():
            self.assertIn(code, rv.FLAG_REASON, code)
            self.assertTrue(set(eff) <= deps, f"{code} targets a dependency no metric declares: {set(eff) - deps}")
            self.assertTrue(set(eff.values()) <= {"withhold", "flag"})

    def test_colour_cast_withholds_colour_metrics_but_leaves_geometry_and_texture_alone(self):
        w = withheld("colour_cast")
        self.assertEqual(w, rv.COLOUR_SKIN)
        for safe in ("texture", "wrinkles", "shine"):
            self.assertNotIn(safe, w)
            self.assertNotIn(safe, flagged("colour_cast"))

    def test_beauty_filter_flags_detail_metrics_and_withholds_nothing(self):
        self.assertEqual(withheld("beauty_filter"), set())
        self.assertEqual(flagged("beauty_filter"), rv.TEXTURE_SKIN)
        self.assertNotIn("redness", flagged("beauty_filter"))

    def test_blur_withholds_detail_metrics_only(self):
        w = withheld("blurry")
        self.assertEqual(w, {k for k, n in rv.SKIN_NEEDS.items() if "detail" in n})
        for colour_only in ("redness", "dark_spots", "shine", "pigmentation"):
            self.assertNotIn(colour_only, w)

    def test_overexposure_withholds_lightness_metrics_not_texture(self):
        w = withheld("too_bright")
        self.assertEqual(w, {"uneven_tone", "pigmentation", "shine"})
        self.assertNotIn("texture", w)
        self.assertNotIn("redness", w)

    def test_glasses_withhold_under_eye_reading_and_only_flag_wrinkles(self):
        self.assertEqual(withheld("glasses"), {"dark_circles"})
        self.assertIn("wrinkles", flagged("glasses"))
        for unaffected in ("redness", "texture", "uneven_tone", "shine"):
            self.assertNotIn(unaffected, withheld("glasses") | flagged("glasses"))

    def test_beard_only_flags_lower_face_metrics(self):
        self.assertEqual(withheld("beard"), set())
        self.assertEqual(flagged("beard"), {k for k, n in rv.SKIN_NEEDS.items() if "lower_face" in n})
        self.assertNotIn("dark_circles", flagged("beard"))
        self.assertNotIn("shine", flagged("beard"))

    def test_uneven_light_flags_comparisons_between_regions(self):
        self.assertEqual(flagged("uneven_light"), {"uneven_tone", "pigmentation"})

    def test_withhold_beats_flag_when_both_apply(self):
        d = decided("beauty_filter", "blurry")  # texture is flagged by one and withheld by the other
        self.assertEqual(d["texture"][0], "withhold")
        d2 = decided("blurry", "beauty_filter")
        self.assertEqual(d2["texture"][0], "withhold")

    def test_unrelated_flags_change_nothing(self):
        for code in ("smiling", "slightly_turned", "tilted", "mouth_open", "multiple_faces"):
            self.assertEqual(decided(code), {}, code)

    def test_reasons_name_the_actual_cause(self):
        self.assertIn("colour cast", decided("colour_cast")["redness"][1].lower())
        self.assertIn("glasses", decided("glasses")["dark_circles"][1].lower())

    def run_rules(self, code):
        a = copy.deepcopy(BASE)
        a.setdefault("yaw_correction", 0.0)
        before = {c["key"] for c in a["skin"]["concerns"]}
        audit = rv.apply_quality_rules(a, {"issues": [{"level": "warning", "code": code, "message": code}]}, 0.2, None)
        return before, {c["key"] for c in a["skin"]["concerns"]}, a, audit

    def test_applying_glasses_through_the_validator_drops_exactly_the_under_eye_metric_and_flags_wrinkles(self):
        before, after, a, audit = self.run_rules("glasses")
        self.assertIn("dark_circles", before, "fixture must contain the metric this test is about")
        self.assertEqual(before - after, {"dark_circles"})
        self.assertEqual(after, before - {"dark_circles"})
        self.assertIn("wrinkles", before)
        self.assertIn("wrinkles", a["skin"]["reliability"])
        self.assertEqual({s["item"] for s in audit["suppressed"]}, {"skin:dark_circles"})

    def test_blur_through_the_validator_drops_exactly_the_detail_metrics(self):
        before, after, a, audit = self.run_rules("blurry")
        expected = {"texture", "wrinkles", "blemishes"}
        self.assertTrue(expected <= before, "fixture must contain the detail metrics")
        self.assertEqual(before - after, expected)
        self.assertTrue({"redness", "uneven_tone"} <= before and {"redness", "uneven_tone"} <= after)

    def test_skin_score_is_recomputed_from_the_remaining_metrics(self):
        _, after, a, _ = self.run_rules("blurry")
        rem = a["skin"]["concerns"]
        self.assertAlmostEqual(a["skin"]["score"], sum(c["score"] for c in rem) / len(rem), places=1)


class SegmentationMetricArithmetic(unittest.TestCase):
    """Hand-computed expectations for the evaluation harness (needed before any labelled data is used)."""

    def setUp(self):
        from evals.skin_segmentation_eval import confusion
        self.confusion = confusion

    def test_perfect_prediction(self):
        m = np.zeros((10, 10), bool)
        m[2:8, 2:8] = True
        c = self.confusion(m, m)
        self.assertEqual((c["iou"], c["dice"], c["false_positive_rate"], c["false_negative_rate"]), (1.0, 1.0, 0.0, 0.0))

    def test_known_overlap(self):
        truth = np.zeros((10, 10), bool); truth[0:5, :] = True          # 50 px
        pred = np.zeros((10, 10), bool); pred[3:8, :] = True            # 50 px, overlap rows 3-4 = 20 px
        c = self.confusion(pred, truth)
        self.assertEqual((c["tp"], c["fp"], c["fn"], c["tn"]), (20, 30, 30, 20))
        self.assertAlmostEqual(c["iou"], 20 / 80)
        self.assertAlmostEqual(c["dice"], 40 / 100)
        self.assertAlmostEqual(c["false_positive_rate"], 30 / 50)
        self.assertAlmostEqual(c["false_negative_rate"], 30 / 50)
        self.assertAlmostEqual(c["precision"], 20 / 50)
        self.assertAlmostEqual(c["recall"], 20 / 50)

    def test_disjoint_masks(self):
        a = np.zeros((6, 6), bool); a[:3] = True
        b = ~a
        c = self.confusion(a, b)
        self.assertEqual((c["iou"], c["dice"]), (0.0, 0.0))
        self.assertEqual((c["false_positive_rate"], c["false_negative_rate"]), (1.0, 1.0))

    def test_empty_truth_has_undefined_not_fabricated_rates(self):
        c = self.confusion(np.ones((4, 4), bool), np.zeros((4, 4), bool))
        self.assertIsNone(c["false_negative_rate"])
        self.assertIsNone(c["recall"])
        self.assertEqual(c["false_positive_rate"], 1.0)

    def test_both_empty_is_undefined(self):
        c = self.confusion(np.zeros((4, 4), bool), np.zeros((4, 4), bool))
        self.assertIsNone(c["iou"])
        self.assertIsNone(c["dice"])

    def test_dice_iou_relation_holds(self):
        rng = np.random.default_rng(3)
        for _ in range(20):
            a, b = rng.random((20, 20)) > 0.5, rng.random((20, 20)) > 0.4
            c = self.confusion(a, b)
            self.assertAlmostEqual(c["dice"], 2 * c["iou"] / (1 + c["iou"]), places=9)


IMAGES = [p for p in os.environ.get("PFI_TEST_IMAGE", "").split(",") if p.strip() and Path(p.strip()).exists()]


@unittest.skipUnless(IMAGES, "set PFI_TEST_IMAGE to an authorised photograph to run real-photo mask tests")
class RealPhotoMaskInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import cv2
        from app import hair, landmarks
        cls.cases = []
        for p in IMAGES:
            bgr = cv2.imread(p.strip())
            cls.cases.append((bgr, landmarks.detect(bgr), hair.segment(bgr)))

    def test_mask_never_contains_eye_brow_or_lip_polygons_nor_pixels_outside_the_face_oval(self):
        from evals.skin_segmentation_eval import contamination
        for bgr, _, _ in self.cases:
            c = contamination(bgr)
            self.assertEqual(c["pct_mask_inside_eye_brow_lip_polygons"], 0.0)
            self.assertEqual(c["pct_mask_outside_face_oval"], 0.0)

    def test_dark_facial_hair_rule_only_ever_removes_pixels(self):
        from app import skin
        from evals.skin_segmentation_eval import pipeline_mask
        for bgr, face, seg in self.cases:
            with_rule = pipeline_mask(bgr, face, seg)[0]
            old = skin.DARK_HAIR_REL
            skin.DARK_HAIR_REL = 0.0  # disables the rule (nothing is darker than 0)
            try:
                without_rule = pipeline_mask(bgr, face, seg)[0]
            finally:
                skin.DARK_HAIR_REL = old
            self.assertFalse((with_rule & ~without_rule).any(), "the rule added pixels to the mask")
            self.assertLessEqual(int(with_rule.sum()), int(without_rule.sum()))

    def test_mask_is_deterministic(self):
        from evals.skin_segmentation_eval import pipeline_mask
        for bgr, face, seg in self.cases:
            self.assertTrue(np.array_equal(pipeline_mask(bgr, face, seg)[0], pipeline_mask(bgr, face, seg)[0]))


if __name__ == "__main__":
    unittest.main()
