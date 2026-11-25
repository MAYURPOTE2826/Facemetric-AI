"""Tests for the central report validator (rules A-I), the recommendation consistency engine and preview labels.

Run from backend/:  python -m unittest discover -s tests -v
Synthetic and anonymised data only.
"""
import copy
import json
import re
import unittest
from pathlib import Path

import numpy as np

from app import consistency, previews, recommendations, report_validator as rv, styling

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))


def analysis(**over):
    a = copy.deepcopy(BASE)
    a.setdefault("yaw_correction", 0.0)
    a.update(over)
    return a


def quality(*codes):
    return {"ok": True, "issues": [{"level": "warning", "code": c, "message": c} for c in codes]}


CAM_OK = {"mm_per_px": 0.2, "distance_mm": 400}
MM = 0.2


def skin_keys(a):
    return {c["key"] for c in a["skin"]["concerns"]}


class Validator(unittest.TestCase):
    def setUp(self):
        a = analysis()
        self.assertTrue(a["skin"].get("available"), "fixture must have skin analysis")
        self.base_skin_keys = skin_keys(a)

    # --- C / A / D: skin
    def test_colour_cast_drops_colour_based_skin_and_tone_group(self):
        a = analysis()
        a["skin"]["tone"] = {"group": "light", "advice": "x"}
        audit = rv.apply_quality_rules(a, quality("colour_cast"), MM, CAM_OK)
        self.assertFalse(skin_keys(a) & rv.COLOUR_SKIN)
        self.assertEqual(a["skin"]["tone"]["group"], "unknown")
        self.assertTrue(any(s["item"] == "skin:tone_group" for s in audit["suppressed"]))

    def test_overexposure_drops_brightness_dependent_skin(self):
        a = analysis()
        rv.apply_quality_rules(a, quality("too_bright"), MM, CAM_OK)
        self.assertFalse(skin_keys(a) & rv.BRIGHTNESS_SKIN)

    def test_beauty_filter_flags_texture_readings_but_keeps_them(self):
        a = analysis()
        keys_before = skin_keys(a)
        audit = rv.apply_quality_rules(a, quality("beauty_filter"), MM, CAM_OK)
        self.assertEqual(skin_keys(a), keys_before)
        self.assertTrue(audit["flagged"])
        self.assertTrue(set(a["skin"]["reliability"]) <= rv.TEXTURE_SKIN)

    def test_skin_score_is_recomputed_when_at_least_half_the_readings_survive(self):
        a = analysis()
        rv.apply_quality_rules(a, quality("glasses"), MM, CAM_OK)  # withholds only the under-eye reading
        rem = a["skin"]["concerns"]
        self.assertGreaterEqual(len(rem) * 2, len(BASE["skin"]["concerns"]))
        self.assertAlmostEqual(a["skin"]["score"], sum(c["score"] for c in rem) / len(rem), places=1)

    def test_skin_score_is_withheld_when_fewer_than_half_the_readings_survive(self):
        """Changed rule (found on a real report): after a colour cast only 3 of 10 readings survive, and their average
        was shown as 'Skin score 100'. An average of a few survivors must not pass for an overall score."""
        a = analysis()
        rv.apply_quality_rules(a, quality("colour_cast"), MM, CAM_OK)
        self.assertLess(len(a["skin"]["concerns"]) * 2, len(BASE["skin"]["concerns"]))
        self.assertIsNone(a["skin"]["score"])

    def test_clean_photo_suppresses_nothing(self):
        a = analysis()
        audit = rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        self.assertEqual(audit["suppressed"], [])
        self.assertEqual(a["validation"]["status"], "complete")
        self.assertEqual(skin_keys(a), self.base_skin_keys)

    def test_everything_withheld_marks_skin_unavailable_not_fabricated(self):
        a = analysis()
        a["skin"]["concerns"] = [c for c in a["skin"]["concerns"] if c["key"] in rv.COLOUR_SKIN]
        rv.apply_quality_rules(a, quality("colour_cast"), MM, CAM_OK)
        self.assertFalse(a["skin"]["available"])
        self.assertIsNone(a["skin"]["score"])
        self.assertEqual(a["validation"]["modules"]["skin"], "unavailable")

    # --- E: pose
    def test_saturated_yaw_correction_drops_symmetry_and_flags_width_ratios(self):
        a = analysis(yaw_correction=30.0)
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        keys = {m["key"] for m in a["metrics"]}
        self.assertNotIn("symmetry", keys)
        self.assertTrue(any("quality_note" in m for m in a["metrics"] if m["key"] in rv.POSE_SENSITIVE))

    def test_moderate_yaw_keeps_symmetry(self):
        a = analysis(yaw_correction=8.0)
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        self.assertIn("symmetry", {m["key"] for m in a["metrics"]})

    def test_smiling_flags_lip_metrics_without_removing_them(self):
        a = analysis()
        n = len(a["metrics"])
        rv.apply_quality_rules(a, quality("smiling"), MM, CAM_OK)
        self.assertEqual(len(a["metrics"]), n)
        flagged = [m["key"] for m in a["metrics"] if "quality_note" in m]
        self.assertTrue(set(flagged) <= rv.SMILE_SENSITIVE)

    # --- B: calibration
    def test_unusable_scale_withholds_mm_but_keeps_ratios(self):
        a = analysis()
        rv.apply_quality_rules(a, quality(), None, None)
        anth = {"rows": [{"key": "face_width", "value": 130}], "ratios": [{"key": "r", "value": 1.0}], "note": "n"}
        rv.apply_mm_rules(anth, None, None, a["validation"])
        self.assertEqual(anth["rows"], [])
        self.assertEqual(len(anth["ratios"]), 1)
        self.assertEqual(anth["calibration"]["status"], "unavailable")
        self.assertEqual(a["validation"]["status"], "partial")

    def test_estimated_scale_is_never_reported_as_validated(self):
        self.assertEqual(rv.calibration_status(MM, CAM_OK), "estimated")
        a = analysis()
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        self.assertFalse(a["validation"]["calibration"]["validated"])

    def test_upload_without_exif_still_has_an_iris_scale(self):
        """Regression: cam is None for uploads without EXIF focal length; the iris scale is still usable."""
        self.assertEqual(rv.calibration_status(MM, None), "estimated")
        a = analysis()
        rv.apply_quality_rules(a, quality(), MM, None)
        self.assertEqual(a["validation"]["calibration"], {"status": "estimated", "validated": False, "perspective_corrected": False})
        anth = {"rows": [{"key": "face_width", "value": 130}], "ratios": [], "note": "n"}
        rv.apply_mm_rules(anth, MM, None, a["validation"])
        self.assertEqual(len(anth["rows"]), 1)  # mm kept, labelled estimated

    def test_implausible_scale_or_camera_distance_is_unavailable(self):
        self.assertEqual(rv.calibration_status(MM, {"distance_mm": 50}), "unavailable")
        self.assertEqual(rv.calibration_status(MM, {"distance_mm": 9000}), "unavailable")
        self.assertEqual(rv.calibration_status(None, None), "unavailable")
        self.assertEqual(rv.calibration_status(float("nan"), None), "unavailable")
        self.assertEqual(rv.calibration_status(50.0, None), "unavailable")

    # --- F: hair
    def test_no_crown_photo_means_no_overall_hair_score(self):
        a = analysis()
        a["hair"] = {"available": True, "hairline": {"score": 95}, "crown": None, "score": 95}
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        rv.apply_hair_rules(a["hair"], a["validation"])
        self.assertIsNone(a["hair"]["score"])
        self.assertEqual(a["hair"]["hairline"]["score"], 95)  # the observed hairline reading itself is kept
        self.assertTrue(any(s["item"] == "hair:overall_score" for s in a["validation"]["suppressed"]))

    def test_crown_photo_allows_overall_hair_score(self):
        a = analysis()
        a["hair"] = {"available": True, "hairline": {"score": 90}, "crown": {"score": 80}, "score": 85}
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        rv.apply_hair_rules(a["hair"], a["validation"])
        self.assertEqual(a["hair"]["score"], 85)

    # --- G: landmarks
    def test_nan_landmarks_are_rejected(self):
        p = np.full((478, 3), 100.0)
        p[5, 0] = np.nan
        with self.assertRaises(rv.LandmarkError):
            rv.check_landmarks(p, (400, 400, 3))

    def test_too_few_landmarks_are_rejected(self):
        with self.assertRaises(rv.LandmarkError):
            rv.check_landmarks(np.zeros((100, 3)), (400, 400, 3))

    def test_face_partly_outside_the_frame_is_rejected(self):
        p = np.full((478, 3), 200.0)
        p[:40, 1] = 900.0  # 40 landmarks far below a 400px-tall image
        with self.assertRaises(rv.LandmarkError):
            rv.check_landmarks(p, (400, 400, 3))

    def test_valid_landmarks_pass(self):
        rv.check_landmarks(np.full((478, 3), 200.0), (400, 400, 3))

    # --- H: failed module
    def test_failed_hair_module_is_reported_unavailable_not_defaulted(self):
        a = analysis()
        rv.apply_quality_rules(a, quality(), MM, CAM_OK)
        rv.apply_hair_rules({"available": False, "hairline_note": "failed"}, a["validation"])
        self.assertEqual(a["validation"]["modules"]["hair"], "unavailable")

    # --- I: confidence
    def test_heuristic_confidence_is_not_published(self):
        out = rv.public_filter({"style": {"shape": "round", "confidence": 0.62}})
        self.assertNotIn("confidence", out["style"])

    def test_model_fingerprint_is_a_real_checksum_or_explicitly_missing(self):
        fp = rv.model_fingerprint("face_landmarker.task")
        self.assertIn(fp["status"], ("ok", "missing"))
        if fp["status"] == "ok":
            self.assertEqual(len(fp["sha256"]), 64)


def metric(key, score, direction, status="outside"):
    return {"key": key, "score": score, "direction": direction, "status": status, "label": key, "value": 0}


class Consistency(unittest.TestCase):
    def test_every_title_in_the_stance_table_still_exists_in_the_library(self):
        titles = {m[0] for v in recommendations.LIBRARY.values() for lst in v.values() for m in lst}
        self.assertFalse(set(consistency.CHIN_STANCE) - titles, "stance table references a recommendation that no longer exists")

    def test_long_lower_face_never_gets_grow_chin_advice(self):
        """The PDF case: long lower face (thirds high) + lower-third split 0.37 (low). Previously produced
        'keep chin short' AND 'chin-length beard styling adds height'."""
        ms = [metric("thirds_lower_mid", 20, "high"), metric("lower_third_split", 70, "low", "near")]
        cands = recommendations.candidates(ms, {"available": False}, {"sex": "male", "age": 28})
        titles = {c["title"] for c in cands}
        self.assertNotIn("Elongate the lower face", titles)
        for c in cands:
            if c["title"] == "Balance lip-to-chin height":
                self.assertNotIn("adds height below the mouth", c["detail"])
                self.assertIn("short", c["detail"].lower())

    def test_opposite_evidence_with_clear_winner_suppresses_the_loser(self):
        ms = [metric("thirds_lower_mid", 20, "low"), metric("lower_third_split", 70, "low", "near")]
        d = consistency.chin_decision(ms)
        self.assertEqual(d["stance"], "long")
        kept, supp = consistency.resolve([
            {"for": "thirds_lower_mid", "feature": "F", "title": "Elongate the lower face", "type": "grooming", "detail": "d", "cost": "$", "timeline": "t"},
            {"for": "lower_third_split", "feature": "G", "title": "Balance lip-to-chin height", "type": "grooming", "detail": "d", "cost": "$", "timeline": "t"},
        ], ms)
        self.assertEqual([k["title"] for k in kept], ["Elongate the lower face"])
        self.assertEqual([s["title"] for s in supp], ["Balance lip-to-chin height"])
        self.assertIn("conflicts", supp[0]["reason"])

    def test_close_call_suppresses_both_sides_and_says_why(self):
        ms = [metric("thirds_lower_mid", 40, "high"), metric("thirds_lower_mid", 45, "low")]
        d = consistency.chin_decision(ms)
        self.assertEqual(d["stance"], "unresolved")
        kept, supp = consistency.resolve([
            {"for": "a", "feature": "F", "title": "Elongate the lower face", "type": "grooming", "detail": "d", "cost": "$", "timeline": "t"},
            {"for": "b", "feature": "G", "title": "Soften lower-face length", "type": "grooming", "detail": "d", "cost": "$", "timeline": "t"},
        ], ms)
        self.assertEqual(kept, [])
        self.assertEqual(len(supp), 2)
        self.assertTrue(all("disagree" in s["reason"] for s in supp))

    def test_no_evidence_changes_nothing(self):
        d = consistency.chin_decision([metric("canthal_tilt", 90, "low", "ideal")])
        self.assertIsNone(d["stance"])

    def test_beard_styles_agree_with_a_long_lower_face(self):
        beard = ["Goatee or anchor beard to lengthen the face", "Boxed beard with short sides and a longer chin",
                 "Keep cheek lines sharp and high-angled"]
        out, _ = consistency.reconcile_beard_styles(beard, [metric("thirds_lower_mid", 20, "high")])
        self.assertFalse([b for b in out if consistency.LONG_RE.search(b)])
        self.assertTrue([b for b in out if "chin short" in b.lower()])
        self.assertIn("Keep cheek lines sharp and high-angled", out)

    def test_unresolved_chin_gives_no_chin_length_beard_advice(self):
        beard = ["Goatee or anchor beard to lengthen the face", "Keep the chin short", "Keep cheek lines sharp"]
        ms = [metric("thirds_lower_mid", 40, "high"), metric("thirds_lower_mid", 45, "low")]
        out, notes = consistency.reconcile_beard_styles(beard, ms)
        self.assertEqual(out, ["Keep cheek lines sharp"])
        self.assertTrue(notes)

    def test_styling_advice_for_the_pdf_case_has_no_contradiction(self):
        shape = {"shape": "round", "label": "Round", "secondary": None, "confidence": 0.6, "ratios": {}}
        adv = styling.advice(shape, {"sex": "male"}, [metric("thirds_lower_mid", 20, "high")], None)
        text = " | ".join(adv["beard"]).lower()
        self.assertIn("keep the chin short", text)
        self.assertNotIn("lengthen the face", text)
        self.assertNotIn("longer chin", text)

    def test_every_recommendation_is_traceable(self):
        ms = [metric("thirds_lower_mid", 20, "high")]
        for c in recommendations.candidates(ms, {"available": False}, {"sex": "male", "age": 28}):
            for k in ("id", "category", "supporting_metrics", "preconditions", "limitations", "priority"):
                self.assertIn(k, c)
            self.assertTrue(c["id"].startswith("rec_"))
            self.assertTrue(c["limitations"])
            if c["for"] != "baseline":
                self.assertEqual(c["supporting_metrics"], [c["for"]])

    def test_recommendation_ids_are_stable_and_unique(self):
        ms = [metric("thirds_lower_mid", 20, "high")]
        a = recommendations.candidates(ms, {"available": False}, {"sex": "male", "age": 28})
        b = recommendations.candidates(ms, {"available": False}, {"sex": "male", "age": 28})
        self.assertEqual([c["id"] for c in a], [c["id"] for c in b])
        self.assertEqual(len({c["id"] for c in a}), len(a))

    def test_no_recommendation_claims_to_change_bone_structure(self):
        for lst in (v for lib in recommendations.LIBRARY.values() for v in lib.values()):
            for m in lst:
                if m[1] in ("grooming", "makeup"):
                    text = m[2].lower()
                    # a disclaimer ("doesn't change bone structure") is fine; an affirmative claim is not
                    if re.search(r"change (your )?bone|reshape (the )?bone", text):
                        self.assertRegex(text, r"don't|doesn't|does not|do not|cannot|can't|not ")


class PreviewLabels(unittest.TestCase):
    def test_previews_are_described_as_image_editing_not_ai(self):
        src = Path(previews.__file__).read_text(encoding="utf-8")
        self.assertIn('"method": "classical_image_editing"', src)
        self.assertIn("not an AI image model", src)
        self.assertNotIn('"note": "AI simulation', src)

    def test_preview_module_uses_no_ml_model(self):
        src = Path(previews.__file__).read_text(encoding="utf-8")
        for forbidden in ("onnxruntime", "tflite", "torch", "diffusers", "openai", "anthropic", "httpx"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
