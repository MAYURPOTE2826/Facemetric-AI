"""Hairline engine: SOFTWARE behaviour on synthetic scenes. These tests prove the logic (no hallucinated hairline, no crown from a
front photo, styling lowers confidence, no diagnosis wording...). They are NOT evidence of accuracy on real photographs:
'Hairline detection accuracy: NOT MEASURED' (docs/HAIRLINE_VALIDATION.md)."""
import json
import unittest
from types import SimpleNamespace

import numpy as np

import hair_fixtures as F
from app import hair, hairline


def run(top=None, top_error=None, **kw):
    img, cat, pts = F.scene(**kw)
    return hairline.build(img, cat, pts, top, top_error)


def assert_no_diagnosis(tc, result):
    text = json.dumps({k: v for k, v in result.items() if k != "image"}).lower()
    findings = json.dumps({k: v for k, v in result.items() if k not in ("image", "limitations")}).lower()
    for w in hairline.FORBIDDEN_WORDS:
        # the fixed disclaimer may say "does not diagnose"; no FINDING, guidance or label may use the word
        tc.assertNotIn(w, findings if w == "diagnos" else text, w)


class Shapes(unittest.TestCase):
    def test_01_clear_straight_hairline(self):
        r = run()
        self.assertEqual(r["hairline"]["status"], "detected")
        self.assertEqual(r["hairline"]["shape"]["label"], "relatively_straight")
        for s in ("left", "right"):
            self.assertEqual(r["temples"][s]["status"], "no_obvious_recession")
        self.assertGreaterEqual(r["hairline"]["confidence"], 0.6)
        self.assertGreater(len(r["hairline"]["points"]), 15)

    def test_02_naturally_rounded_hairline_is_not_recession(self):
        r = run(hairline=F.rounded)
        self.assertEqual(r["hairline"]["shape"]["label"], "rounded")
        self.assertEqual(r["temples"]["left"]["status"], "no_obvious_recession")

    def test_03_mild_temple_height_is_described_not_called_loss(self):
        r = run(hairline=F.mature(0.08))
        self.assertEqual(r["temples"]["left"]["status"], "mildly_mature_temple_shape")
        self.assertIn("not by itself hair loss", r["hairline"]["shape"]["text"])

    def test_03b_larger_temple_depth_is_a_possible_pattern_with_cautious_wording(self):
        r = run(hairline=F.mature(0.14))
        for s in ("left", "right"):
            self.assertEqual(r["temples"][s]["status"], "possible_recession_pattern")
            self.assertTrue(r["temples"][s]["text"].startswith("Possible"))
        self.assertEqual(r["hairline"]["shape"]["label"], "m_shaped")

    def test_04_asymmetric_temples_are_assessed_independently(self):
        r = run(hairline=F.asym(0.15, 0.0))
        self.assertEqual(r["temples"]["left"]["status"], "possible_recession_pattern")
        self.assertEqual(r["temples"]["right"]["status"], "no_obvious_recession")
        self.assertEqual(r["hairline"]["shape"]["label"], "asymmetric")
        self.assertLess(r["hairline"]["symmetry"]["score"], 75)
        self.assertIn("normal", r["hairline"]["symmetry"]["note"])

    def test_17_side_part_style_asymmetry_is_not_hidden_or_called_a_diagnosis(self):
        r = run(hairline=F.asym(0.10, 0.02))
        assert_no_diagnosis(self, r)
        self.assertIn(r["temples"]["left"]["status"], ("mildly_mature_temple_shape", "possible_recession_pattern"))


class Styling(unittest.TestCase):
    def test_05_fringe_hiding_the_hairline_is_inconclusive_not_a_finding(self):
        r = run(fringe=True)
        self.assertEqual(r["status"], "inconclusive")
        self.assertFalse(r["image_quality"]["hairline_visible"])
        self.assertIn("fringe_or_hair_over_forehead", r["image_quality"]["flags"])
        for s in ("left", "right"):
            self.assertEqual(r["temples"][s]["status"], "not_assessable")
        self.assertEqual(r["frontal_density"]["status"], "not_assessable")
        self.assertTrue(any("Retake" in g for g in r["guidance"]))
        self.assertLess(r["hairline"]["confidence"], 0.4)

    def test_06_hair_pulled_back_gives_a_clean_detection(self):
        self.assertEqual(run(thickness=0.3)["hairline"]["status"], "detected")

    def test_07_wet_or_glossy_hair_lowers_density_confidence(self):
        dry, wet = run(), run(wet=True)
        self.assertIn("glossy_or_wet_hair_or_strong_overhead_light", wet["image_quality"]["flags"])
        self.assertLess(wet["frontal_density"]["confidence"], dry["frontal_density"]["confidence"])

    def test_11_curly_or_textured_hair_flags_the_irregular_boundary_and_lowers_confidence(self):
        r = run(jagged=0.05)
        self.assertIn("irregular_boundary_textured_or_styled_hair", r["image_quality"]["flags"])
        self.assertLess(r["image_quality"]["confidence"], run()["image_quality"]["confidence"])

    def test_18_very_short_haircut_does_not_read_scalp_as_density_loss(self):
        r = run(thickness=0.05)
        self.assertIn("very_short_hair", r["image_quality"]["flags"])
        self.assertLessEqual(r["frontal_density"]["confidence"], 0.45)
        self.assertNotEqual(r["frontal_density"]["status"], "reduced_visible_density_detected")


class Lighting(unittest.TestCase):
    def test_08_strong_light_lowers_confidence(self):
        r = run(light_gain=90)
        self.assertLess(r["image_quality"]["confidence"], run()["image_quality"]["confidence"])
        self.assertIn("overexposed", r["image_quality"]["flags"])

    def test_09_low_light_lowers_confidence(self):
        r = run(light_gain=0.25)
        self.assertIn("too_dark", r["image_quality"]["flags"])
        self.assertLess(r["image_quality"]["confidence"], run()["image_quality"]["confidence"])

    def test_10_low_resolution_is_flagged_and_lowers_confidence(self):
        r = run(scale=0.3)
        self.assertIn("low_resolution", r["image_quality"]["flags"])
        self.assertLess(r["image_quality"]["confidence"], 0.5)

    def test_12_dark_hair_detected(self):
        self.assertEqual(run(hair=F.DARK)["hairline"]["status"], "detected")

    def test_13_light_hair_low_contrast_is_less_confident_than_dark_and_never_invents_recession(self):
        light = run(hair=(128, 162, 206))
        self.assertIn("hair_colour_close_to_skin", light["image_quality"]["flags"])
        self.assertLessEqual(light["hairline"]["confidence"], run()["hairline"]["confidence"])
        for s in ("left", "right"):
            self.assertNotIn("recession_pattern", light["temples"][s]["status"])


class Framing(unittest.TestCase):
    def test_19_hairline_outside_the_frame_is_inconclusive(self):
        r = run(crop_top=300)
        self.assertEqual(r["status"], "inconclusive")
        self.assertNotEqual(r["hairline"]["status"], "detected")

    def test_20_no_face_or_tiny_face_never_crashes_and_never_hallucinates(self):
        img, cat, _ = F.scene()
        for pts in (None, np.zeros((10, 3))):
            r = hairline.build(img, cat, pts)
            self.assertEqual(r["status"], "inconclusive")
            self.assertEqual(r["hairline"]["points"], [])
            self.assertEqual(r["crown"]["status"], "not_assessable")
        tiny = F.landmarks()
        tiny[:, :2] = (tiny[:, :2] - [F.CX, 400]) * 0.05 + [F.CX, 400]
        self.assertEqual(hairline.build(img, cat, tiny)["status"], "inconclusive")

    def test_head_roll_is_removed_by_the_face_frame(self):
        import cv2
        img, cat, pts = F.scene(hairline=F.mature(0.14))
        M = cv2.getRotationMatrix2D((F.CX, 400), 8, 1.0)
        img2 = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), borderValue=(200, 195, 190))
        cat2 = cv2.warpAffine(cat, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_NEAREST)
        p2 = pts.copy()
        p2[:, :2] = pts[:, :2] @ M[:, :2].T + M[:, 2]
        r = hairline.build(img2, cat2, p2)
        self.assertEqual(r["temples"]["left"]["status"], "possible_recession_pattern")


class Crown(unittest.TestCase):
    TOP = {"scalp_pct": 6.0, "label": "Dense", "score": 92, "parting": None, "regional": {"central_scalp_pct": 5, "outer_scalp_pct": 4, "hair_area_fraction": 0.5}}

    def test_15_front_only_never_infers_the_crown(self):
        r = run()
        self.assertEqual(r["crown"]["status"], "not_assessable")
        self.assertIsNone(r["crown"]["density"])
        self.assertEqual(r["status"], "partial")
        self.assertTrue(any("top-of-head" in g for g in r["guidance"]))

    def test_14_top_photo_is_assessed_and_makes_the_report_complete(self):
        r = run(top=self.TOP)
        self.assertEqual(r["crown"]["status"], "assessed")
        self.assertIn("density", r["crown"])
        self.assertEqual(r["status"], "complete")
        self.assertTrue(r["image_quality"]["crown_visible"])

    def test_16_obscured_or_unusable_top_photo_is_inconclusive(self):
        r = run(top=None, top_error="Couldn't find enough hair in the photo.")
        self.assertEqual(r["crown"]["status"], "inconclusive")
        self.assertEqual(r["crown"]["confidence"], 0.0)

    def test_parting_is_relative_not_millimetres(self):
        top = dict(self.TOP, parting={"width_mm": 4.4, "christmas_tree": False})
        p = run(top=top)["crown"]["parting"]
        self.assertIn("relative_width_of_head", p)
        self.assertNotIn("width_mm", p)


class Safety(unittest.TestCase):
    CASES = [{}, dict(hairline=F.mature(0.14)), dict(hairline=F.asym(0.15, 0)), dict(fringe=True), dict(thickness=0.05), dict(wet=True)]

    def test_no_diagnosis_cure_or_reassurance_wording_in_any_output(self):
        for kw in self.CASES:
            assert_no_diagnosis(self, run(**kw))
        assert_no_diagnosis(self, run(top=Crown.TOP))

    def test_every_result_has_confidence_and_the_not_measured_statement(self):
        for kw in self.CASES:
            r = run(**kw)
            self.assertIn("confidence", r["hairline"])
            self.assertIn("confidence", r["frontal_density"])
            self.assertIn("NOT MEASURED", r["validation_status"])
            self.assertTrue(r["limitations"])

    def test_no_physical_units_are_reported(self):
        text = json.dumps({k: v for k, v in run().items() if k not in ("image",)}).lower()
        for w in (" cm", " mm", "centimet", "millimet"):
            self.assertNotIn(w, text.replace("not physically calibrated", ""), w)
        self.assertIn("not physically calibrated", json.dumps(run()["hairline"]["ratios"]))

    def test_guidance_never_prescribes_a_medicine(self):
        for kw in self.CASES:
            g = " ".join(run(**kw)["guidance"]).lower()
            for w in ("minoxidil", "finasteride", "prescri", "supplement", "biotin"):
                self.assertNotIn(w, g)


class Longitudinal(unittest.TestCase):
    def test_same_conditions_same_hairline_is_stable(self):
        a, b = run(seed=1), run(seed=2)
        self.assertEqual(hairline.compare(a, b)["status"], "stable")

    def test_translated_copy_is_stable(self):
        a = run(hairline=F.mature(0.1))
        b = hairline.build(*F.scene(hairline=F.mature(0.1), dx=40, dy=25, seed=5))
        self.assertEqual(hairline.compare(a, b)["status"], "stable")

    def test_rescaling_does_not_change_the_normalised_curve(self):
        a = run(hairline=F.mature(0.1))
        b = hairline.build(*F.scene(hairline=F.mature(0.1), scale=0.8, dx=40, dy=25, seed=5))
        va = {p["u"]: p["v"] for p in a["hairline"]["points"]}
        vb = {p["u"]: p["v"] for p in b["hairline"]["points"]}
        common = set(va) & set(vb)
        self.assertGreater(len(common), 15)
        self.assertLess(max(abs(va[u] - vb[u]) for u in common), 0.03)

    def test_a_clear_hairline_shift_is_reported_as_change(self):
        a, b = run(hairline=F.mature(0.0)), run(hairline=F.mature(0.12))
        r = hairline.compare(a, b)
        self.assertIn(r["status"], ("possible_change", "measurable_change"))
        self.assertGreater(r["temple_depth_change"]["left"], 0.05)
        self.assertIn("unvalidated", r["note"])

    def test_different_lighting_refuses_to_compare(self):
        r = hairline.compare(run(), run(light_gain=0.55))
        self.assertEqual(r["status"], "inconclusive")
        self.assertTrue(r["reasons"])

    def test_fringe_in_one_photo_refuses_to_compare(self):
        self.assertEqual(hairline.compare(run(), run(fringe=True))["status"], "inconclusive")

    def test_missing_baseline_is_not_available(self):
        self.assertEqual(hairline.compare(None, run())["status"], "not_available")


class Compatibility(unittest.TestCase):
    def test_legacy_hair_result_keeps_every_old_key_and_adds_analysis(self):
        img, cat, pts = F.scene(hairline=F.mature(0.14))
        face = SimpleNamespace(points=pts)
        out = hair.analyze(img, face, {"sex": "male"}, None, cat)
        for k in ("available", "hairline", "crown", "score", "image", "causes", "tests", "plan", "myths", "questionnaire", "shedding_note"):
            self.assertIn(k, out)
        self.assertIn("analysis", out)
        self.assertEqual(out["analysis"]["engine"], hairline.ENGINE_VERSION)
        self.assertNotIn(" cm", out["hairline"]["detail"])

    def test_engine_failure_never_breaks_the_legacy_result(self):
        img, cat, pts = F.scene()
        orig = hairline.build
        hairline.build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            out = hair.analyze(img, SimpleNamespace(points=pts), {}, None, cat)
        finally:
            hairline.build = orig
        self.assertTrue(out["available"])
        self.assertEqual(out["analysis"]["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()


class EvaluatorHonesty(unittest.TestCase):
    def test_empty_dataset_is_not_measured_and_invents_nothing(self):
        import tempfile
        from pathlib import Path
        from evals import hairline_eval
        with tempfile.TemporaryDirectory() as d:
            r = hairline_eval.evaluate(Path(d))
        self.assertEqual(r["status"], "NOT MEASURED")
        self.assertEqual(r["annotations"], 0)
        for k in ("precision", "recall", "f1", "accuracy", "mean_boundary_error_bz"):
            self.assertNotIn(k, r)

    def test_model_assisted_annotations_are_rejected(self):
        import json as _json
        import tempfile
        from pathlib import Path
        from evals import hairline_eval
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "annotations").mkdir()
            (root / "images").mkdir()
            (root / "images" / "a.jpg").write_bytes(b"x")
            (root / "annotations" / "a.json").write_text(_json.dumps({
                "image": "images/a.jpg", "annotation_source": "model:prefill", "hairline_visible": True,
                "hairline_polyline_px": [[0, 0]] * 6}), encoding="utf-8")
            good, rejected = hairline_eval.load_annotations(root)
        self.assertEqual(good, [])
        self.assertIn("human:", rejected[0])

    def test_boundary_error_is_zero_on_the_same_line_and_scales_with_distance(self):
        from evals import hairline_eval
        truth = np.array([[0.0, 100.0], [300.0, 100.0]])
        on = np.array([[50.0, 100.0], [150.0, 100.0]])
        off = np.array([[50.0, 130.0], [150.0, 130.0]])
        self.assertAlmostEqual(hairline_eval.boundary_error(on, truth, 300.0), 0.0, delta=0.005)
        self.assertAlmostEqual(hairline_eval.boundary_error(off, truth, 300.0), 0.1, delta=0.005)


class FrontendWiring(unittest.TestCase):
    ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent.parent

    def test_report_renders_the_new_section_and_the_capture_flow_explains_both_photos(self):
        sec = (self.ROOT / "frontend/src/components/HairAnalysisSection.tsx").read_text(encoding="utf-8")
        for needle in ('data-testid="hair-analysis"', 'testid="hair-crown"', "NOT ASSESSABLE", 'data-testid="hair-legend"', "Limitations", "Hair-care guidance"):
            self.assertIn(needle, sec)
        life = (self.ROOT / "frontend/src/components/LifestyleSections.tsx").read_text(encoding="utf-8")
        self.assertIn("<HairAnalysisSection", life)
        page = (self.ROOT / "frontend/src/app/analyze/page.tsx").read_text(encoding="utf-8")
        self.assertIn('data-testid="hair-capture-explainer"', page)
        self.assertIn("Top-of-head photo → crown and parting", page)
        self.assertNotIn("profile.hair && top.file", page, "the top photo must not depend on the questionnaire")
