"""Structural tests of the central landmark map. No images needed. Run from backend/: python -m unittest discover -s tests"""
import re
import unittest
from pathlib import Path

from app import landmark_map as LM

APP = Path(__file__).resolve().parent.parent / "app"


class MapStructure(unittest.TestCase):
    def test_every_index_is_inside_the_478_landmark_range(self):
        for name, i in LM.ALL_NAMED.items():
            self.assertTrue(0 <= i < LM.LANDMARK_COUNT, f"{name}={i}")
        for group in (LM.MIDLINE, LM.MIDLINE_STABLE):
            self.assertTrue(all(0 <= i < LM.LANDMARK_COUNT for i in group))
        for r, l in LM.SYMMETRY_PAIRS:
            self.assertTrue(0 <= r < LM.LANDMARK_COUNT and 0 <= l < LM.LANDMARK_COUNT)

    def test_left_and_right_names_never_share_an_index(self):
        right = {v for k, v in LM.ALL_NAMED.items() if k.startswith("R_")}
        left = {v for k, v in LM.ALL_NAMED.items() if k.startswith("L_")}
        self.assertFalse(right & left)

    def test_every_R_name_has_an_L_twin_and_they_are_a_symmetry_pair_where_declared(self):
        names = LM.ALL_NAMED
        for k in names:
            if k.startswith("R_") and k != "R_IRIS_H":
                twin = "L_" + k[2:]
                self.assertIn(twin, names, f"{k} has no left twin")
        pairs = {tuple(p) for p in LM.SYMMETRY_PAIRS}
        for r, l in (("R_EYE_OUT", "L_EYE_OUT"), ("R_EYE_IN", "L_EYE_IN"), ("R_ZYGO", "L_ZYGO"), ("R_GONION", "L_GONION"),
                     ("R_ALA", "L_ALA"), ("R_MOUTH", "L_MOUTH"), ("R_BROW_TOP", "L_BROW_TOP")):
            self.assertIn((LM.ALL_NAMED[r], LM.ALL_NAMED[l]), pairs, f"{r}/{l} missing from SYMMETRY_PAIRS")

    def test_symmetry_pairs_are_well_formed(self):
        flat = [i for p in LM.SYMMETRY_PAIRS for i in p]
        self.assertEqual(len(flat), len(set(flat)), "an index appears in more than one symmetry pair")
        self.assertTrue(all(r != l for r, l in LM.SYMMETRY_PAIRS))

    def test_midline_points_are_not_part_of_any_symmetry_pair(self):
        flat = {i for p in LM.SYMMETRY_PAIRS for i in p}
        self.assertFalse(set(LM.MIDLINE) & flat)

    def test_midline_stable_is_a_subset_of_midline(self):
        self.assertTrue(set(LM.MIDLINE_STABLE) <= set(LM.MIDLINE))

    def test_iris_indices(self):
        self.assertEqual((LM.R_IRIS, LM.L_IRIS), (468, 473))
        self.assertTrue(set(LM.R_IRIS_H) <= set(range(468, 473)) and set(LM.L_IRIS_H) <= set(range(473, 478)))

    def test_known_anatomical_landmarks_have_expected_indices(self):
        """Indices from MediaPipe's canonical face mesh; a typo here would silently corrupt every measurement."""
        expected = {"FOREHEAD": 10, "GLABELLA": 9, "NASION": 168, "NOSE_TIP": 1, "SUBNASALE": 2, "MENTON": 152,
                    "R_EYE_OUT": 33, "R_EYE_IN": 133, "L_EYE_IN": 362, "L_EYE_OUT": 263}
        for k, v in expected.items():
            self.assertEqual(LM.ALL_NAMED[k], v, k)

    def test_measurement_modules_use_the_map_not_private_copies(self):
        """metrics.py must not redefine indices (it imports them), and the rebuilt modules must reference names."""
        txt = (APP / "metrics.py").read_text(encoding="utf-8")
        self.assertIn("from .landmark_map import", txt)
        self.assertIsNone(re.search(r"^R_EYE_OUT, R_EYE_IN", txt, re.M))
        for mod in ("anthropometry.py", "eyes.py", "diagrams.py"):
            body = (APP / mod).read_text(encoding="utf-8")
            self.assertIn("landmark_map", body, mod)
            literals = re.findall(r"(?<![\w.])P\(\d{1,3}\)|(?<![\w.])(?:pts|p|q)\[\d{1,3},", body)
            self.assertEqual(literals, [], f"{mod} still has numeric landmark literals")


if __name__ == "__main__":
    unittest.main()
