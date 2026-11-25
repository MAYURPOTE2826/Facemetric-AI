"""Report honesty fixes found by reading a real report PDF:
  * 'Skin score 100' was shown after 9 of 10 skin readings were withheld (the average of the single survivor);
  * goals said 'no measurement points to a specific change' when the readings had been WITHHELD, not clean;
  * the before/after section vanished with no explanation."""
import copy
import json
import unittest
from pathlib import Path

from app import personalization as P, previews, report_validator as rv

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))


def analysis(*codes):
    a = copy.deepcopy(BASE)
    a.setdefault("yaw_correction", 0.0)
    audit = rv.apply_quality_rules(a, {"issues": [{"level": "warning", "code": c, "message": c} for c in codes]}, 0.2, None)
    return a, audit


def metric(key, status="ideal", direction="low", category="eyes"):
    return {"key": key, "label": key, "status": status, "direction": direction, "category": category, "score": 90 if status == "ideal" else 30}


class SkinScore(unittest.TestCase):
    def test_the_pdf_case_colour_cast_plus_blur_withholds_the_overall_score(self):
        a, audit = analysis("colour_cast", "blurry")
        total = len(BASE["skin"]["concerns"])
        remaining = len(a["skin"]["concerns"])
        self.assertLess(remaining * 2, total, "fixture: this combination must leave fewer than half of the readings")
        self.assertIsNone(a["skin"]["score"])
        self.assertIn("not shown", a["skin"]["score_note"])
        self.assertIn(f"{remaining} of {total}", a["skin"]["score_note"])
        self.assertTrue(any(s["item"] == "skin:overall_score" for s in audit["suppressed"]))

    def test_a_score_is_still_shown_when_at_least_half_the_readings_survive(self):
        a, _ = analysis("beauty_filter")  # flags only, nothing withheld
        self.assertIsNotNone(a["skin"]["score"])
        self.assertNotIn("score_note", a["skin"])

    def test_the_surviving_metrics_are_still_listed(self):
        a, _ = analysis("colour_cast", "blurry")
        self.assertGreaterEqual(len(a["skin"]["concerns"]), 1)  # a few readings stay; only the misleading average is dropped


class RetakeTips(unittest.TestCase):
    def test_each_quality_flag_gives_a_specific_tip(self):
        a, _ = analysis("blurry", "colour_cast", "glasses", "smiling")
        tips = " ".join(a["validation"]["retake_tips"]).lower()
        for word in ("steady", "daylight", "glasses", "neutral"):
            self.assertIn(word, tips)

    def test_no_flags_no_tips(self):
        a, _ = analysis()
        self.assertEqual(a["validation"]["retake_tips"], [])


class PreviewStatus(unittest.TestCase):
    ms = [metric("canthal_tilt"), metric("jaw_zygo", category="jaw"), metric("lip_ratio", category="lips")]

    def by(self, rows):
        return {r["preview"]: r for r in rows}

    def test_every_kind_is_accounted_for_and_other_types_are_explained(self):
        rows = self.by(previews.status(self.ms, {"available": True, "concerns": [{"key": "redness", "score": 95}]}, False, set()))
        self.assertEqual(set(rows), {"skin", "brows", "jaw", "lips", "other"})
        self.assertFalse(any(r["offered"] for r in rows.values()))
        self.assertIn("Nose contouring", rows["other"]["reason"])
        self.assertIn("within the reference range", rows["jaw"]["reason"])
        self.assertIn("good", rows["skin"]["reason"])

    def test_withheld_skin_is_explained_as_withheld_not_as_good_skin(self):
        validation = {"suppressed": [{"item": "skin:redness", "reason": "A strong colour cast makes colour readings unreliable."},
                                     {"item": "skin:texture", "reason": "The photo is too blurry to resolve fine detail."}]}
        rows = self.by(previews.status(self.ms, {"available": True, "concerns": [{"key": "shine", "score": 100}]}, False, set(), validation))
        self.assertIn("withheld", rows["skin"]["reason"])
        self.assertIn("Retake", rows["skin"]["reason"])
        self.assertNotIn("good", rows["skin"]["reason"].lower().replace("good light", ""))

    def test_glasses_reason_for_the_brow_preview(self):
        ms = [metric("canthal_tilt", status="outside", direction="low")]
        rows = self.by(previews.status(ms, {"available": False}, True, set()))
        self.assertIn("Glasses", rows["brows"]["reason"])

    def test_offered_previews_have_no_reason_and_missing_metrics_are_reported(self):
        rows = self.by(previews.status([], {"available": False}, False, {"skin"}))
        self.assertTrue(rows["skin"]["offered"])
        self.assertEqual(rows["skin"]["reason"], "")
        self.assertIn("not available", rows["jaw"]["reason"])


class GoalWording(unittest.TestCase):
    def al(self, goals, ms, skin, cands, withheld):
        return {a["goal"]: a for a in P.alignment(goals, ms, skin, cands, {"suppressed": [{"item": w} for w in withheld]})}

    BASELINE = [{"for": "baseline", "feature": "General", "type": "skincare", "title": "Daily sunscreen"},
                {"for": "baseline", "feature": "General", "type": "lifestyle", "title": "Sleep 7-9 hours consistently"}]

    def test_withheld_skin_is_never_reported_as_nothing_to_change(self):
        skin = {"available": True, "concerns": [{"key": "shine", "score": 100}]}
        r = self.al(["Better skin"], [], skin, self.BASELINE, ["skin:redness", "skin:uneven_tone", "skin:texture"])
        self.assertEqual(r["Better skin"]["status"], "measurement_unavailable")
        self.assertIn("skin:redness", r["Better skin"]["supporting_metrics"])

    def test_look_less_tired_is_partly_unavailable_when_eye_metrics_are_fine_but_under_eyes_withheld(self):
        ms = [metric("canthal_tilt"), metric("eye_aspect")]
        skin = {"available": True, "concerns": [{"key": "shine", "score": 100}]}
        r = self.al(["Look less tired", "Eye area"], ms, skin, self.BASELINE, ["skin:dark_circles"])
        self.assertEqual(r["Look less tired"]["status"], "partly_unavailable")
        self.assertEqual(r["Eye area"]["status"], "partly_unavailable")

    def test_clean_skin_with_no_withheld_readings_still_says_in_range_or_general(self):
        skin = {"available": True, "concerns": [{"key": "texture", "score": 95}]}
        r = self.al(["Better skin"], [], skin, [], [])
        self.assertEqual(r["Better skin"]["status"], "measurements_in_range")

    def test_a_specific_recommendation_still_wins_over_the_withheld_note(self):
        cands = [{"for": "redness", "feature": "Skin", "type": "skincare", "title": "x"}]
        skin = {"available": True, "concerns": [{"key": "redness", "score": 40}]}
        r = self.al(["Better skin"], [], skin, cands, ["skin:dark_spots"])
        self.assertEqual(r["Better skin"]["status"], "recommendations_available")

    def test_tone_group_and_overall_score_withholding_do_not_count_as_a_related_skin_reading(self):
        skin = {"available": True, "concerns": [{"key": "texture", "score": 95}]}
        r = self.al(["Better skin"], [], skin, [], ["skin:tone_group", "skin:overall_score"])
        self.assertEqual(r["Better skin"]["status"], "measurements_in_range")


class FrontendWiring(unittest.TestCase):
    def test_the_report_page_renders_the_explanations_and_never_shows_a_missing_score_as_zero(self):
        src = (Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "app" / "report" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        for needle in ('data-testid="preview-status"', 'data-testid="retake-tips"', 'data-testid="skin-score-withheld"', "partly_unavailable"):
            self.assertIn(needle, src)
        self.assertNotIn("data.skin.score ?? 0", src)


if __name__ == "__main__":
    unittest.main()
