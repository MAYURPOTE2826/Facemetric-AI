"""'What to remove from the routine' guidance: built only from steps really in the routine."""
import unittest
from app import products

SKIN = {"available": True, "concerns": [{"key": "wrinkles", "score": 40}, {"key": "blemishes", "score": 40}, {"key": "dark_circles", "score": 40}, {"key": "shine", "score": 50}]}


class Removals(unittest.TestCase):
    def test_present_and_labelled(self):
        r = products.build(SKIN, {"age": 30, "budget": "mid"})["removals"]
        self.assertIn("NOT CLINICALLY REVIEWED", r["status"])
        self.assertTrue(r["stop_now"])
        self.assertIn("Sunscreen", r["keep"])

    def test_step_down_only_for_steps_in_the_routine(self):
        r = products.build({"available": True, "concerns": [{"key": "shine", "score": 50}]}, {"age": 30})["removals"]
        self.assertFalse(any("Under-eye" in x["item"] for x in r["step_down"]))
        r2 = products.build(SKIN, {"age": 30})["removals"]
        self.assertTrue(any("Under-eye" in x["item"] for x in r2["step_down"]))

    def test_steroid_history_adds_stop_item_and_isotretinoin_adds_note(self):
        r = products.build(SKIN, {"age": 30, "safety": ["steroid_history", "isotretinoin"]})["removals"]
        self.assertTrue(any("Steroid" in x["item"] for x in r["stop_now"]))
        self.assertIsNotNone(r["note"])

    def test_no_skin_no_routine(self):
        self.assertIsNone(products.build({"available": False}, {}))


if __name__ == "__main__":
    unittest.main()
