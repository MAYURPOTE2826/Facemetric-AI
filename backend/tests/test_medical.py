"""Always-visible medical/professional content: structure, consult statuses, health-history effects.
The red-flag TEXT is general information that has NOT been clinically reviewed; these tests check structure and behaviour, not medical correctness."""
import re
import unittest
from pathlib import Path

from app import medical, recommendations

ROOT = Path(__file__).resolve().parent.parent.parent
NO_SKIN = {"available": False}


def metric(key, status="ideal", direction="low", label=None):
    return {"key": key, "label": label or key, "status": status, "direction": direction, "category": "jaw", "score": 90 if status == "ideal" else 30, "value": 1, "unit": "", "ideal": 1}


class Structure(unittest.TestCase):
    def build(self, **kw):
        a = dict(metrics=[], skin=NO_SKIN, candidates=[], validation=None, profile={"age": 30, "sex": "male"})
        a.update(kw)
        return medical.build(a["metrics"], a["skin"], a["candidates"], a["validation"], a["profile"])

    def test_all_four_parts_and_the_review_status_are_always_present(self):
        m = self.build()
        self.assertEqual(set(m), {"content_status", "limits", "red_flags", "consults", "history", "history_note"})
        self.assertIn("NOT CLINICALLY REVIEWED", m["content_status"])
        self.assertGreaterEqual(len(m["limits"]), 5)
        self.assertEqual(set(m["red_flags"]), {"urgent", "soon", "dermatologist"})
        self.assertTrue(all(len(v["items"]) >= 3 for v in m["red_flags"].values()))

    def test_limits_state_the_important_boundaries(self):
        text = " ".join(medical.LIMITS).lower()
        for phrase in ("cannot diagnose", "moles", "placeholder", "see a doctor", "withheld"):
            self.assertIn(phrase, text)

    def test_urgent_flags_cover_allergy_and_infection(self):
        text = " ".join(medical.RED_FLAGS["urgent"]["items"]).lower()
        self.assertIn("breathing", text)
        self.assertIn("infection", text)

    def test_every_consult_title_exists_in_the_recommendation_library(self):
        titles = {m[0] for v in recommendations.LIBRARY.values() for lst in v.values() for m in lst}
        titles |= {m[0] for lst in recommendations.SKIN.values() for m in lst}
        self.assertFalse({c[0] for c in medical.CONSULTS} - titles, "a consult here no longer exists in the library")
        prof = {m[0] for v in recommendations.LIBRARY.values() for lst in v.values() for m in lst if m[1] == "professional"}
        prof |= {m[0] for lst in recommendations.SKIN.values() for m in lst if m[1] == "professional"}
        self.assertFalse(prof - {c[0] for c in medical.CONSULTS}, "a professional recommendation is missing from the overview")


class ConsultStatuses(unittest.TestCase):
    def status(self, title, **kw):
        m = medical.build(kw.get("metrics", []), kw.get("skin", NO_SKIN), kw.get("candidates", []), kw.get("validation"), kw.get("profile", {"age": 30}))
        return next(c for c in m["consults"] if c["title"] == title)

    def test_every_consult_always_appears_with_one_of_four_statuses(self):
        m = medical.build([], NO_SKIN, [], None, {"age": 30})
        self.assertEqual(len(m["consults"]), len(medical.CONSULTS))
        self.assertTrue({c["status"] for c in m["consults"]} <= {"indicated", "not_indicated", "could_not_assess", "not_offered_safety"})

    def test_indicated_only_when_the_measurement_is_out_of_range_and_the_consult_was_suggested(self):
        ms = [metric("nasofacial", status="outside", direction="high", label="Nasofacial angle")]
        c = self.status("Non-surgical rhinoplasty consult", metrics=ms, candidates=[{"title": "Non-surgical rhinoplasty consult"}])
        self.assertEqual(c["status"], "indicated")
        self.assertIn("not a recommendation to have a procedure", c["why"])

    def test_in_range_measurement_is_not_indicated(self):
        c = self.status("Jawline filler consult", metrics=[metric("jaw_zygo", "ideal")])
        self.assertEqual(c["status"], "not_indicated")

    def test_missing_or_withheld_measurement_is_could_not_assess_never_not_indicated(self):
        self.assertEqual(self.status("Jawline filler consult", metrics=[])["status"], "could_not_assess")

    def test_withheld_skin_reading_is_could_not_assess_and_still_says_to_see_a_dermatologist_if_concerned(self):
        skin = {"available": True, "concerns": [{"key": "shine", "score": 100}]}
        c = self.status("Dermatologist for persistent acne", skin=skin, validation={"suppressed": [{"item": "skin:blemishes"}]})
        self.assertEqual(c["status"], "could_not_assess")
        self.assertIn("see a dermatologist regardless", c["why"])

    def test_skin_concern_present_and_suggested_is_indicated(self):
        skin = {"available": True, "concerns": [{"key": "blemishes", "score": 40}]}
        c = self.status("Dermatologist for persistent acne", skin=skin, candidates=[{"title": "Dermatologist for persistent acne"}])
        self.assertEqual(c["status"], "indicated")
        self.assertIn("not a diagnosis", c["why"])

    def test_professional_consults_are_not_offered_to_minors_or_in_pregnancy(self):
        for prof in ({"age": 16}, {"age": 30, "safety": ["pregnant"]}, {"age": 30, "safety": ["breastfeeding"]}):
            self.assertEqual(self.status("Jawline filler consult", metrics=[metric("jaw_zygo", "outside")], profile=prof)["status"], "not_offered_safety", prof)


class HealthHistory(unittest.TestCase):
    def test_each_answer_given_is_listed_with_what_it_changed(self):
        m = medical.build([], NO_SKIN, [], None, {"age": 30, "safety": ["skin_condition", "isotretinoin", "not-a-real-flag"]})
        self.assertEqual({h["answer"] for h in m["history"]}, {"skin_condition", "isotretinoin"})
        self.assertTrue(all(h["effect"] for h in m["history"]))

    def test_no_answers_says_nothing_was_adjusted(self):
        self.assertIn("did not give any health answers", medical.build([], NO_SKIN, [], None, {"age": 30})["history_note"])

    def test_the_new_answers_really_remove_strong_actives(self):
        skin = {"available": True, "concerns": [{"key": "uneven_tone", "label": "Uneven tone", "score": 30, "severity": "high"},
                                                {"key": "pigmentation", "label": "Pigmentation", "score": 30, "severity": "high"}]}
        base = {c["title"] for c in recommendations.candidates([], skin, {"age": 30})}
        pat = re.compile(r"retinoid|retinol|peel|scrub|\bAHA\b|\bBHA\b|glycolic|salicylic|lactic|mandelic|exfoliat|laser|microneedl", re.I)
        strong = {t for t in base if pat.search(t) or any(pat.search(c["detail"]) for c in recommendations.candidates([], skin, {"age": 30}) if c["title"] == t)}
        self.assertTrue(strong, "fixture must include at least one strong active to remove")
        for flag in ("skin_condition", "prescribed_skin_treatment"):
            kept = recommendations.candidates([], skin, {"age": 30, "safety": [flag]})
            left = [c["title"] for c in kept if pat.search(c["title"] + " " + c["detail"]) and not re.search(r"\b(avoid|don'?t|never|not)\b", c["detail"], re.I)]
            self.assertEqual(left, [], flag)

    def test_nothing_is_asked_without_being_used(self):
        """Every health option on the analysis form must have a stated effect, and every stated effect must be on the form."""
        src = (ROOT / "frontend" / "src" / "app" / "analyze" / "page.tsx").read_text(encoding="utf-8")
        block = re.search(r"const SAFETY = \[(.*?)\] as const;", src, re.S).group(1)
        form_ids = set(re.findall(r'\["([a-z_]+)",', block))
        self.assertEqual(form_ids, set(medical.HISTORY_EFFECTS))
        from app import report
        # each answer must be enforced by a real rule: breastfeeding rides on the pregnancy rule, steroid history on ALWAYS_UNSAFE
        self.assertTrue({"pregnant", "isotretinoin", "skin_condition", "prescribed_skin_treatment"} <= set(report.UNSAFE))
        self.assertIn("clobetasol", report.ALWAYS_UNSAFE)


class FrontendWiring(unittest.TestCase):
    def test_the_medical_section_is_rendered_for_everyone_not_only_paid_reports(self):
        page = (ROOT / "frontend" / "src" / "app" / "report" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        self.assertGreater(page.index("<MedicalSection"), page.index("</>}"), "the section must sit after the paid-only block")
        comp = (ROOT / "frontend" / "src" / "components" / "MedicalSection.tsx").read_text(encoding="utf-8")
        for needle in ('data-testid="medical-section"', 'data-testid="medical-content-status"', 'data-testid="consult-table"', "Not offered for you (safety)", "Could not assess from this photo"):
            self.assertIn(needle, comp)

    def test_the_routine_preview_block_explains_itself_when_no_simulation_exists(self):
        page = (ROOT / "frontend" / "src" / "app" / "report" / "[id]" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn('data-testid="routine-preview"', page)
        self.assertIn("image editing cannot show what an individual product does", page)


if __name__ == "__main__":
    unittest.main()
