"""User-goal personalization: goals reorder evidence-backed recommendations and never create, resurrect or override anything."""
import copy
import json
import unittest
from pathlib import Path

from app import consistency, personalization as P, recommendations, report

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))
NO_SKIN = {"available": False}
PROFILE = {"sex": "male", "age": 28}


def metric(key, category, score, status, direction="low", label=None):
    return {"key": key, "label": label or key, "category": category, "value": 1.0, "unit": "", "ideal": 1.2, "tolerance": 0.1,
            "score": score, "status": status, "direction": direction, "description": f"{key} description"}


def cands(metrics, goals=None, skin=NO_SKIN):
    prof = {**PROFILE, **({"goals": goals} if goals is not None else {})}
    return recommendations.candidates_audited(metrics, skin, prof)


def titles(c):
    return [x["title"] for x in c]


class Ordering(unittest.TestCase):
    def setUp(self):
        self.ms = [metric("lip_ratio", "lips", 10, "outside"), metric("jaw_zygo", "jaw", 30, "outside"), metric("canthal_tilt", "eyes", 50, "near")]

    def test_every_metric_has_library_recommendations(self):
        base, _ = cands(self.ms)
        self.assertTrue({"lip_ratio", "jaw_zygo", "canthal_tilt"} <= {c["for"] for c in base}, "fixture metrics must produce recommendations")

    def test_no_goals_unknown_goals_or_glow_up_leave_the_order_untouched(self):
        base = titles(cands(self.ms)[0])
        for goals in ([], None, ["Not a real goal"], ["Overall glow-up"], ["Overall glow-up", "???"]):
            self.assertEqual(titles(cands(self.ms, goals)[0]), base, goals)

    def test_goal_moves_related_recommendations_first_within_the_same_tier(self):
        base = cands(self.ms)[0]
        first_default = next(c for c in base if c["for"] in ("lip_ratio", "jaw_zygo"))
        self.assertEqual(first_default["for"], "lip_ratio")  # worst measurement first by default
        goal = cands(self.ms, ["Sharper jawline"])[0]
        first_goal = next(c for c in goal if c["for"] in ("lip_ratio", "jaw_zygo"))
        self.assertEqual(first_goal["for"], "jaw_zygo")
        self.assertEqual(first_goal["goal_match"], ["Sharper jawline"])
        self.assertIn("Sharper jawline", first_goal["ranking_reason"])

    def test_a_goal_never_promotes_a_recommendation_above_a_worse_evidence_tier(self):
        ms = [metric("lip_ratio", "lips", 10, "outside"), metric("canthal_tilt", "eyes", 60, "near")]
        out = cands(ms, ["Eye area"])[0]  # the goal is about eyes, but the lip measurement is outside its range
        order = [c["for"] for c in out if c["for"] in ("lip_ratio", "canthal_tilt")]
        self.assertEqual(order[0], "lip_ratio")
        tiers = [P.tier(c, {m["key"]: m for m in ms}) for c in out]
        self.assertEqual(tiers, sorted(tiers))  # tiers never interleave

    def test_goals_never_create_or_drop_recommendations(self):
        base, goal = cands(self.ms)[0], cands(self.ms, ["Sharper jawline", "Lips", "Hair & grooming"])[0]
        self.assertEqual({c["id"] for c in base}, {c["id"] for c in goal})
        self.assertEqual(len(base), len(goal))

    def test_a_goal_about_an_in_range_measurement_creates_nothing_and_says_so(self):
        ms = [metric("jaw_zygo", "jaw", 95, "ideal"), metric("lip_ratio", "lips", 10, "outside")]
        c, _ = cands(ms, ["Sharper jawline"])
        self.assertFalse([x for x in c if x["for"] == "jaw_zygo"])
        al = P.alignment(["Sharper jawline"], ms, NO_SKIN, c)
        self.assertEqual(al[0]["status"], "measurements_in_range")
        self.assertEqual(al[0]["supporting_metrics"], ["jaw_zygo"])

    def test_a_goal_whose_measurement_was_withheld_is_reported_unavailable_not_answered(self):
        ms = [metric("lip_ratio", "lips", 10, "outside")]  # no jaw metric at all (e.g. a beard hid it)
        validation = {"suppressed": [{"item": "metric:jaw_zygo", "label": "Jaw", "reason": "beard"}]}
        c, _ = cands(ms, ["Sharper jawline"])
        al = P.alignment(["Sharper jawline"], ms, NO_SKIN, c, validation)
        self.assertEqual(al[0]["status"], "measurement_unavailable")
        self.assertEqual(al[0]["supporting_metrics"], ["metric:jaw_zygo"])
        self.assertFalse([x for x in c if "jaw" in x["for"]])

    def test_alignment_statuses_for_the_remaining_cases(self):
        ms = [metric("jaw_zygo", "jaw", 20, "outside")]
        c, _ = cands(ms, ["Sharper jawline", "Overall glow-up", "Hair & grooming", "Look less tired"])
        al = {a["goal"]: a for a in P.alignment(["Sharper jawline", "Overall glow-up", "Hair & grooming", "Look less tired", "bogus"], ms, NO_SKIN, c)}
        self.assertEqual(al["Sharper jawline"]["status"], "recommendations_available")
        self.assertEqual(al["Overall glow-up"]["status"], "no_specific_target")
        self.assertIn(al["Look less tired"]["status"], ("general_recommendations_only", "measurement_unavailable"))
        self.assertNotIn("bogus", al)

    def test_skin_goal_matches_skin_recommendations(self):
        skin = {"available": True, "concerns": [{"key": "uneven_tone", "label": "Uneven tone", "score": 30, "severity": "high"}]}
        base, goal = cands([], None, skin)[0], cands([], ["Better skin"], skin)[0]
        sk = [c for c in goal if c["feature"] == "Skin"]
        self.assertTrue(sk)
        self.assertTrue(all(c["goal_match"] == ["Better skin"] for c in sk))
        self.assertEqual({c["id"] for c in base}, {c["id"] for c in goal})


class TraceabilityAndSafety(unittest.TestCase):
    def test_every_recommendation_keeps_id_metric_direction_rationale_limitations_priority_and_no_confidence(self):
        ms = [metric("jaw_zygo", "jaw", 20, "outside")]
        c, _ = cands(ms, ["Sharper jawline"])
        for i, x in enumerate(c, 1):
            for k in ("id", "supporting_metrics", "direction", "rationale", "limitations", "priority", "goal_match"):
                self.assertIn(k, x, f"{x['title']} lacks {k}")
            self.assertEqual(x["priority"], i)
            self.assertNotIn("confidence", x)
            self.assertTrue(x["rationale"])
        metric_recs = [x for x in c if x["for"] == "jaw_zygo"]
        self.assertTrue(metric_recs)
        self.assertEqual(metric_recs[0]["direction"], "low")
        self.assertEqual(metric_recs[0]["supporting_metrics"], ["jaw_zygo"])
        self.assertIn("jaw_zygo", metric_recs[0]["rationale"])

    def test_conflict_suppression_cannot_be_overridden_by_a_goal(self):
        ms = [metric("thirds_lower_mid", "proportions", 20, "outside", "high"), metric("lower_third_split", "lips", 70, "near", "low")]
        base_kept, base_supp = cands(ms)
        goal_kept, goal_supp = cands(ms, ["Hair & grooming", "Facial balance", "Lips"])
        self.assertEqual({s["id"] for s in base_supp}, {s["id"] for s in goal_supp})
        suppressed_titles = {s["title"] for s in goal_supp}
        self.assertFalse(suppressed_titles & set(titles(goal_kept)))
        self.assertEqual(consistency.chin_decision(ms)["stance"], "short")

    def test_goals_do_not_change_which_recommendations_are_safe_for_the_user(self):
        young = {"sex": "male", "age": 16, "goals": ["Sharper jawline", "Hair & grooming"]}
        ms = [metric("jaw_zygo", "jaw", 20, "outside")]
        with_goals, _ = recommendations.candidates_audited(ms, NO_SKIN, young)
        without, _ = recommendations.candidates_audited(ms, NO_SKIN, {**young, "goals": []})
        self.assertEqual({c["id"] for c in with_goals}, {c["id"] for c in without})
        self.assertFalse([c for c in with_goals if c["type"] == "professional"])  # still withheld for a minor


class ReportSections(unittest.TestCase):
    def test_section_order_and_plan_follow_the_goal_within_a_status_tier(self):
        a = copy.deepcopy(BASE)
        ms = [metric("lip_ratio", "lips", 10, "outside", label="Lip ratio"), metric("jaw_zygo", "jaw", 30, "outside", label="Jaw ratio")]
        a["metrics"] = ms
        c, _ = recommendations.candidates_audited(ms, NO_SKIN, {**PROFILE, "goals": ["Sharper jawline"]})
        default = report.rule_report(a, recommendations.candidates(ms, NO_SKIN, PROFILE))
        goal = report.rule_report(a, c, goals=["Sharper jawline"])
        self.assertEqual(default["sections"][0]["feature"], "Lip ratio")
        self.assertEqual(goal["sections"][0]["feature"], "Jaw ratio")
        self.assertEqual({s["feature"] for s in goal["sections"]}, {s["feature"] for s in default["sections"]})

    def test_report_without_goals_is_unchanged(self):
        a = copy.deepcopy(BASE)
        base = report.rule_report(a, recommendations.candidates(a["metrics"], a["skin"], a.get("profile")))
        again = report.rule_report(a, recommendations.candidates(a["metrics"], a["skin"], a.get("profile")), goals=[])
        self.assertEqual(json.dumps(base, sort_keys=True), json.dumps(again, sort_keys=True))


class Vocabulary(unittest.TestCase):
    def test_goal_vocabulary_matches_the_frontend_chips(self):
        src = (Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "app" / "analyze" / "page.tsx").read_text(encoding="utf-8")
        import re
        chips = re.search(r"const GOALS = \[(.*?)\];", src, re.S).group(1)
        front = set(re.findall(r'"([^"]+)"', chips))
        self.assertEqual(front, set(P.GOALS), "backend goal map and frontend chips must list the same goals")


if __name__ == "__main__":
    unittest.main()
