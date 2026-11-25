"""Deterministic tests for measurement formulas. Run from backend/:  python -m unittest discover -s tests -v

Uses synthetic landmark sets with known geometry, so expected values are computed by hand, not copied
from program output. No real-person photographs are used.
"""
import unittest

import numpy as np

from app import align, anthropometry, diagrams, geometry, metrics


def face(scale: float = 1.0, roll_deg: float = 0.0) -> np.ndarray:
    """Symmetric synthetic 478x3 face, centred at x=300. Distances (before `scale`):
    bizygomatic 200, brow y=100, upper-lip-top y=200, iris diameter 20 px (469-471 and 474-476)."""
    rng = np.random.default_rng(0)
    p = np.zeros((478, 3))
    p[:, 0] = 300 + rng.normal(0, 1, 478)
    p[:, 1] = 300 + rng.normal(0, 1, 478)
    cx = 300

    def setp(i, x, y):
        p[i, 0], p[i, 1] = x, y
    setp(234, cx - 100, 250); setp(454, cx + 100, 250)          # cheekbones: width 200
    setp(105, cx - 40, 100); setp(334, cx + 40, 100)            # brow tops
    setp(0, cx, 200)                                              # upper lip top
    setp(468, cx - 40, 150); setp(473, cx + 40, 150)            # irises
    setp(469, cx - 50, 150); setp(471, cx - 30, 150)            # iris edges: 20 px
    setp(474, cx + 30, 150); setp(476, cx + 50, 150)
    setp(168, cx, 130); setp(152, cx, 330); setp(2, cx, 215)    # nasion, menton, subnasale
    setp(133, cx - 15, 150); setp(362, cx + 15, 150)            # inner eye corners
    setp(33, cx - 60, 150); setp(263, cx + 60, 150)             # outer eye corners
    setp(129, cx - 20, 215); setp(358, cx + 20, 215)            # alar
    setp(61, cx - 30, 260); setp(291, cx + 30, 260)             # mouth corners
    placed = {234, 454, 105, 334, 468, 473, 133, 362, 33, 263, 129, 358, 61, 291}
    for r, l in metrics.SYMMETRY_PAIRS:  # every left/right pair mirrored about the midline
        if r not in placed and l not in placed:
            setp(r, cx - 55, 240); setp(l, cx + 55, 240)
    for i in metrics.MIDLINE_STABLE:
        if i not in (152, 0):
            p[i, 0] = cx
    p[:, 2] = 0.4 * np.abs(p[:, 0] - cx)  # symmetric depth: the sides sit further back than the midline
    p[:, :2] *= scale
    p[:, 2] *= scale
    if roll_deg:
        a = np.radians(roll_deg)
        r = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        p[:, :2] = (p[:, :2] - 300 * scale) @ r.T + 300 * scale
    return p


class Metrics(unittest.TestCase):
    def test_symmetric_frontal_face_needs_no_yaw_correction(self):
        self.assertAlmostEqual(metrics.compute(face(), "male")["yaw_correction"], 0.0, delta=1.0)

    def test_fwhr_is_width_over_brow_to_upper_lip(self):
        m = {x["key"]: x["value"] for x in metrics.compute(face(), "male")["metrics"]}
        self.assertAlmostEqual(m["fwhr"], 200 / (200 - 100), delta=0.1)  # 2.0: brow y=100, lip y=200

    def test_ratios_are_scale_invariant(self):
        a = {x["key"]: x["value"] for x in metrics.compute(face(1.0), "male")["metrics"]}
        b = {x["key"]: x["value"] for x in metrics.compute(face(2.5), "male")["metrics"]}
        for k in ("fwhr", "esr", "intercanthal_eye"):
            self.assertAlmostEqual(a[k], b[k], delta=0.05, msg=k)


class Anthropometry(unittest.TestCase):
    def test_millimetres_do_not_depend_on_photo_resolution(self):
        """Same face at 1x and 3x pixels must give the same mm (iris calibration cancels the scale)."""
        a = {r["key"]: r["value"] for r in anthropometry.table(face(1.0), "male")["rows"]}
        b = {r["key"]: r["value"] for r in anthropometry.table(face(3.0), "male")["rows"]}
        for k in ("face_width", "nose_width", "mouth_width"):
            self.assertAlmostEqual(a[k], b[k], delta=0.2, msg=k)

    def test_known_width(self):
        """Bizygomatic 200 px, iris 20 px = 11.7 mm -> 0.585 mm/px -> 117 mm."""
        r = {r["key"]: r["value"] for r in anthropometry.table(face(), "male")["rows"]}
        self.assertAlmostEqual(r["face_width"], 200 * geometry.IRIS_MM / 20, delta=1.5)

    def test_calibration_is_declared_unvalidated(self):
        c = anthropometry.table(face(), "male")["calibration"]
        self.assertFalse(c["validated"])
        self.assertNotIn("min_relative_uncertainty", c)  # no unmeasured uncertainty figure is published

    def test_beard_withholding_removes_jaw_and_chin_rows(self):
        t = anthropometry.table(face(), "male")
        gone = anthropometry.withhold(t, anthropometry.BEARD_HIDDEN)
        keys = {r["key"] for r in t["rows"]}
        self.assertTrue(gone)
        self.assertFalse(keys & anthropometry.BEARD_HIDDEN)
        self.assertIn("face_width", keys)  # unaffected measurements stay


class Alignment(unittest.TestCase):
    def test_level_makes_pupil_line_horizontal(self):
        p = face(roll_deg=12.0)
        img = np.zeros((700, 700, 3), np.uint8)
        _, q, _ = align.level(img, p)
        self.assertAlmostEqual(align.roll_degrees(q), 0.0, delta=0.05)


class Figures(unittest.TestCase):
    def test_diagrams_produce_all_figures(self):
        img = np.full((700, 700, 3), 128, np.uint8)
        mm = {"face_width": 117, "biocular": 70, "nose_width": 23, "mouth_width": 35}
        d = diagrams.build(img, face(), mm, 0.585, None)
        self.assertEqual(set(d), {"measurements", "fifths", "thirds", "symmetry_right", "symmetry_left"})
        self.assertTrue(all(len(v) > 1000 for v in d.values()))


if __name__ == "__main__":
    unittest.main()
