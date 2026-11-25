"""Longitudinal comparison must REFUSE when conditions differ. Each refusal has a positive control (comparable inputs ARE compared) so the
tests also prove the check is not simply always refusing. Software behaviour on synthetic scenes; not accuracy evidence.
The pose / lighting limits below are PLACEHOLDERS (docs/HAIRLINE_THRESHOLD_REGISTER.md): these tests pin current behaviour, they do not validate it."""
import unittest

import hair_fixtures as F
from app import hairline


def build(**kw):
    return hairline.build(*F.scene(**kw))


class Refusals(unittest.TestCase):
    def refused(self, a, b, *words):
        r = hairline.compare(a, b)
        self.assertEqual(r["status"], "inconclusive", r)
        self.assertTrue(r.get("reasons"))
        text = " ".join(r["reasons"]).lower()
        for w in words:
            self.assertIn(w, text)
        self.assertNotIn("text", r, "no change statement may accompany a refusal")
        return r

    def test_positive_control_same_conditions_are_compared(self):
        self.assertEqual(hairline.compare(build(seed=1), build(seed=2))["status"], "stable")

    def test_head_pose_differs(self):
        self.refused(build(), build(nose_dx=60), "angle")

    def test_pose_limit_pin_small_turn_is_tolerated_larger_is_refused(self):
        self.assertEqual(hairline.compare(build(), build(nose_dx=10))["status"], "stable")
        self.refused(build(), build(nose_dx=15), "angle")

    def test_lighting_differs(self):
        self.refused(build(), build(light_gain=40), "lighting")          # brighter, photo otherwise fine: refused for lighting
        self.assertEqual(hairline.compare(build(), build(light_gain=0.55))["status"], "inconclusive")  # much darker: refused (quality)

    def test_hair_length_differs(self):
        self.refused(build(thickness=0.37), build(thickness=0.05), "length")

    def test_wetness_differs(self):
        self.refused(build(), build(wet=True), "wet")

    def test_hairline_visibility_differs(self):
        self.refused(build(), build(fringe=True), "hairline")

    def test_hairline_outside_frame_in_one_photo(self):
        self.refused(build(), build(crop_top=300), "hairline")

    def test_image_quality_differs(self):
        self.refused(build(), build(scale=0.3), "quality")

    def test_refusal_is_symmetric(self):
        a, b = build(), build(nose_dx=60)
        self.assertEqual(hairline.compare(a, b)["status"], hairline.compare(b, a)["status"])

    def test_missing_side_is_not_available_and_unusable_input_never_raises(self):
        self.assertEqual(hairline.compare(None, build())["status"], "not_available")
        self.assertEqual(hairline.compare(build(), None)["status"], "not_available")
        self.assertEqual(hairline.compare(build(), {"hairline": {"status": "not_detected"}, "image_quality": {"confidence": 0, "flags": []}})["status"], "inconclusive")

    def test_a_real_change_is_reported_only_when_conditions_match_and_is_hedged(self):
        r = hairline.compare(build(hairline=F.mature(0.0)), build(hairline=F.mature(0.12)))
        self.assertIn(r["status"], ("possible_change", "measurable_change"))
        self.assertIn("unvalidated", r["note"])
        for w in ("progressed", "worse", "worsen", "lost", "balding"):
            self.assertNotIn(w, r["text"].lower())


if __name__ == "__main__":
    unittest.main()
