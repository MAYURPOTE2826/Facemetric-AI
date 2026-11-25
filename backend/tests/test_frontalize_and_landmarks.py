"""frontalize() behaviour (synthetic, always runs) and real-photo landmark robustness (runs only when you provide an
authorised photo).

Real-photo part:   PFI_TEST_IMAGE=path1[,path2] python -m unittest discover -s tests -v
No photograph is ever stored in the repository. Without PFI_TEST_IMAGE those tests are skipped, not faked.

THRESHOLD PROVENANCE (real-photo tests): they are ENGINEERING REGRESSION GUARDS, not accuracy claims. Each is about 2x the
largest value measured by `python -m evals.landmark_validation` on two photographs (see docs/LANDMARK_VALIDATION.md for
the measured numbers). They detect a pipeline change that makes landmarks noticeably less stable; they say nothing
about error against ground truth, which has not been measured.
"""
import os
import unittest
from pathlib import Path

import cv2
import numpy as np

from app import imaging, landmarks, metrics, report_validator as rv
from test_measurements import face

IMAGES = [p for p in os.environ.get("PFI_TEST_IMAGE", "").split(",") if p.strip() and Path(p.strip()).exists()]


class FrontalizeSynthetic(unittest.TestCase):
    def test_recovers_a_known_yaw_exactly_on_a_symmetric_3d_face(self):
        f = face()
        for applied in (-25, -15, -5, 0, 5, 15, 25):
            _, est, status = metrics.frontalize_with_status(metrics._yaw_rotate(f, applied))
            self.assertAlmostEqual(est, -applied, delta=0.2, msg=f"applied {applied}")
            self.assertEqual(status, "ok")

    def test_flat_landmarks_are_undetermined_not_an_arbitrary_rotation(self):
        """Regression: with no depth every rotation scores the same and the tie used to resolve to -30 degrees."""
        f = face()
        f[:, 2] = 0
        pts, est, status = metrics.frontalize_with_status(f)
        self.assertEqual((est, status), (0.0, "undetermined"))
        self.assertTrue(np.array_equal(pts, f))  # nothing was rotated

    def test_a_turn_beyond_the_search_range_is_reported_saturated_never_ok(self):
        f = face()
        for applied in (-45, -35, 35, 45):
            _, est, status = metrics.frontalize_with_status(metrics._yaw_rotate(f, applied))
            self.assertEqual(status, "saturated", f"applied {applied} -> {est}")
            self.assertGreaterEqual(abs(est), metrics.YAW_SEARCH_LIMIT - 0.5)

    def test_saturated_result_is_never_presented_as_a_normal_frontalised_face(self):
        a = metrics.compute(metrics._yaw_rotate(face(), 40), "male")
        self.assertEqual(a["yaw_correction_status"], "saturated")
        v = {"metrics": a["metrics"], "yaw_correction": a["yaw_correction"], "yaw_correction_status": a["yaw_correction_status"],
             "skin": {"available": False}}
        self.assertIn("symmetry", {m["key"] for m in v["metrics"]})
        rv.apply_quality_rules(v, {"issues": []}, 0.2, None)
        self.assertNotIn("symmetry", {m["key"] for m in v["metrics"]})
        self.assertTrue(any(s["item"] == "metric:symmetry" for s in v["validation"]["suppressed"]))

    def test_wrapper_matches_the_status_version(self):
        f = metrics._yaw_rotate(face(), 10)
        p1, y1 = metrics.frontalize(f)
        p2, y2, _ = metrics.frontalize_with_status(f)
        self.assertEqual(y1, y2)
        self.assertTrue(np.array_equal(p1, p2))

    def test_compute_records_the_status(self):
        self.assertEqual(metrics.compute(face(), "male")["yaw_correction_status"], "ok")

    def test_undetermined_pose_is_flagged_by_the_validator_not_hidden(self):
        a = {"metrics": [], "yaw_correction": 0.0, "yaw_correction_status": "undetermined", "skin": {"available": False}}
        audit = rv.apply_quality_rules(a, {"issues": []}, 0.2, None)
        self.assertTrue(any(f["item"] == "pose" for f in audit["flagged"]))


class FacesAreNotSilentlyMixedUp(unittest.TestCase):
    def fake_face(self, n, ratio):
        return landmarks.FaceDetection(points=np.zeros((478, 3)), pose={"yaw": 0.0, "pitch": 0.0, "roll": 0.0}, blendshapes={},
                                       num_faces=n, second_face_ratio=ratio)

    def codes(self, f):
        img = np.full((300, 300, 3), 120, np.uint8)
        f.points[:, :2] = 150 + np.random.default_rng(0).normal(0, 20, (478, 2))
        q = imaging.check_quality(img, f)
        return {(i["code"], i["level"]) for i in q["issues"]}

    def test_two_similar_sized_faces_is_an_error(self):
        self.assertIn(("multiple_faces", "error"), self.codes(self.fake_face(2, 0.95)))
        self.assertIn(("multiple_faces", "error"), self.codes(self.fake_face(2, imaging.MULTI_FACE_AMBIGUOUS)))

    def test_a_clearly_smaller_background_face_is_only_a_warning(self):
        c = self.codes(self.fake_face(2, 0.3))
        self.assertIn(("multiple_faces", "warning"), c)
        self.assertNotIn(("multiple_faces", "error"), c)

    def test_single_face_has_no_multiple_face_issue(self):
        self.assertFalse([c for c in self.codes(self.fake_face(1, 0.0)) if c[0] == "multiple_faces"])


@unittest.skipUnless(IMAGES, "set PFI_TEST_IMAGE to an authorised photograph to run real-photo landmark tests")
class RealPhotoLandmarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = []
        for p in IMAGES:
            img = cv2.imread(p.strip())
            f = landmarks.detect(img)
            assert f is not None, "no face in the supplied test photograph"
            cls.cases.append((img, f))

    @staticmethod
    def disp(a, b, ipd):
        from evals.landmark_validation import SUBSET
        d = np.linalg.norm(a[:, :2] - b[:, :2], axis=1) / ipd * 100
        return float(d[SUBSET].mean()), float(d[SUBSET].max())

    def each(self, fn):
        for img, f in self.cases:
            fn(img, f, float(np.linalg.norm(f.points[468, :2] - f.points[473, :2])))

    def test_model_returns_478_finite_landmarks_in_pixel_coordinates(self):
        def check(img, f, ipd):
            h, w = img.shape[:2]
            self.assertEqual(f.points.shape, (478, 3))
            self.assertTrue(np.isfinite(f.points).all())
            self.assertTrue((f.points[:, 0].min() > -0.05 * w) and (f.points[:, 0].max() < 1.05 * w))
            self.assertTrue((f.points[:, 1].min() > -0.05 * h) and (f.points[:, 1].max() < 1.05 * h))
        self.each(check)

    def test_same_image_gives_identical_landmarks(self):
        self.each(lambda img, f, ipd: self.assertLess(float(np.abs(landmarks.detect(img).points - f.points).max()), 1e-6))

    def test_lossless_copy_gives_identical_landmarks(self):
        def check(img, f, ipd):
            _, png = cv2.imencode(".png", img)
            g = landmarks.detect(cv2.imdecode(png, cv2.IMREAD_COLOR))
            self.assertLess(float(np.abs(g.points - f.points).max()), 1e-6)
        self.each(check)

    def test_jpeg_recompression_moves_landmarks_little(self):
        def check(img, f, ipd):
            for q in (95, 70, 50):
                _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
                mean, mx = self.disp(f.points, landmarks.detect(cv2.imdecode(buf, cv2.IMREAD_COLOR)).points, ipd)
                self.assertLess(mean, 1.0, f"q{q}")
                self.assertLess(mx, 3.0, f"q{q}")
        self.each(check)

    def test_resolution_change_moves_landmarks_little(self):
        def check(img, f, ipd):
            for s in (0.5, 0.75, 1.25):
                g = landmarks.detect(cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC))
                p = g.points / s
                mean, mx = self.disp(f.points, p, ipd)
                self.assertLess(mean, 1.5, f"x{s}")
                self.assertLess(mx, 4.0, f"x{s}")
        self.each(check)

    def test_in_plane_rotation_is_followed_by_the_landmarks(self):
        def check(img, f, ipd):
            h, w = img.shape[:2]
            for deg in (5, 10, 20):
                m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
                g = landmarks.detect(cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE))
                inv = cv2.invertAffineTransform(m)
                p = g.points.copy()
                p[:, :2] = g.points[:, :2] @ inv[:, :2].T + inv[:, 2]
                mean, mx = self.disp(f.points, p, ipd)
                self.assertLess(mean, 2.0, f"{deg} deg")
                self.assertLess(mx, 6.0, f"{deg} deg")
        self.each(check)

    def test_left_right_pair_table_is_correct_on_the_real_model(self):
        """Mirror the photo: each pair (R,L) must swap and x must reflect. A wrong table gives errors of 40%+ of IPD
        (measured: 44% minimum / 132% mean when the pairs are NOT swapped) versus ~2-3% when correct."""
        from app import landmark_map as LM

        def check(img, f, ipd):
            g = landmarks.detect(cv2.flip(img, 1))
            W = img.shape[1]
            errs = []
            for r, l in LM.SYMMETRY_PAIRS:
                e = max(np.linalg.norm(np.array([W - g.points[l, 0], g.points[l, 1]]) - f.points[r, :2]),
                        np.linalg.norm(np.array([W - g.points[r, 0], g.points[r, 1]]) - f.points[l, :2])) / ipd * 100
                errs.append(e)
            self.assertLess(max(errs), 8.0)
        self.each(check)

    def test_two_equal_faces_are_rejected_as_ambiguous(self):
        def check(img, f, ipd):
            two = np.hstack([img, img])
            g = landmarks.detect(two)
            self.assertEqual(g.num_faces, 2)
            self.assertGreaterEqual(g.second_face_ratio, imaging.MULTI_FACE_AMBIGUOUS)
            q = imaging.check_quality(two, g)
            self.assertIn("multiple_faces", {i["code"] for i in q["issues"] if i["level"] == "error"})
            self.assertFalse(q["ok"])
        self.each(check)

    def test_frontalize_on_real_landmarks_recovers_a_known_extra_turn_until_it_saturates(self):
        def check(img, f, ipd):
            _, base, st0 = metrics.frontalize_with_status(f.points)
            self.assertEqual(st0, "ok")
            for applied in (-10, -5, 5, 10):
                _, est, st = metrics.frontalize_with_status(metrics._yaw_rotate(f.points, applied))
                if st == "ok":
                    self.assertAlmostEqual(est, base - applied, delta=0.3)
                else:
                    self.assertGreaterEqual(abs(est), metrics.YAW_SEARCH_LIMIT - 0.5)
            _, est, st = metrics.frontalize_with_status(metrics._yaw_rotate(f.points, 45))
            self.assertEqual(st, "saturated")
        self.each(check)


def roll_points(P, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    Q = P.copy()
    ctr = Q[:, :2].mean(0)
    Q[:, :2] = (P[:, :2] - ctr) @ np.array([[c, -s], [s, c]]).T + ctr
    return Q


class FrontalizeRollIndependence(unittest.TestCase):
    """Regression for a defect shown with EXACT geometry: in-plane roll used to leak into the yaw estimate
    (a symmetric face with true yaw 0 and 2 deg of roll returned -7.3 deg; 10 deg of roll saturated the search)."""

    def test_roll_alone_gives_zero_yaw_at_every_roll(self):
        for deg in (0, 2, 5, 10, 20, 30, -15):
            _, est, status = metrics.frontalize_with_status(roll_points(face(), deg))
            self.assertAlmostEqual(est, 0.0, delta=0.05, msg=f"roll {deg}")
            self.assertEqual(status, "ok", f"roll {deg}")

    def test_known_yaw_is_recovered_exactly_with_roll_present(self):
        for yaw in (-20, -10, 10, 20):
            for deg in (0, 5, 20):
                _, est, status = metrics.frontalize_with_status(roll_points(metrics._yaw_rotate(face(), yaw), deg))
                self.assertAlmostEqual(est, -yaw, delta=0.1, msg=f"yaw {yaw} roll {deg}")
                self.assertEqual(status, "ok")

    def test_pipeline_yaw_correction_does_not_depend_on_roll(self):
        a = metrics.compute(metrics._yaw_rotate(face(), 8), "male")["yaw_correction"]
        for deg in (5, 20):
            self.assertAlmostEqual(metrics.compute(roll_points(metrics._yaw_rotate(face(), 8), deg), "male")["yaw_correction"], a, delta=0.2)

    def test_roll_alone_never_suppresses_symmetry(self):
        a = metrics.compute(roll_points(face(), 25), "male")
        self.assertEqual(a["yaw_correction_status"], "ok")
        self.assertIn("symmetry", {m["key"] for m in a["metrics"]})


@unittest.skipUnless(IMAGES, "set PFI_TEST_IMAGE to an authorised photograph to run real-photo frontalize comparison tests")
class FrontalizeVsMediaPipeRealPhotos(unittest.TestCase):
    """DETERMINISTIC COMPARISON, NOT A TRUTH TEST. There is no ground-truth head pose, so these pin the measured
    relationship (engineering regression guards at ~1.4x the measured values) and the established conventions."""

    @classmethod
    def setUpClass(cls):
        cls.cases = [(cv2.imread(p.strip()),) for p in IMAGES]

    def test_both_estimators_agree_in_sign_and_stay_within_the_measured_gap(self):
        for (img,) in self.cases:
            f = landmarks.detect(img)
            est = metrics.frontalize_with_status(f.points)[1]
            self.assertEqual(np.sign(est), np.sign(f.pose["yaw"]))
            self.assertLess(abs(est - f.pose["yaw"]), 8.0)  # measured 2.6 - 5.7 deg on two photos

    def test_mediapipe_yaw_is_mirror_exact_and_frontalize_is_mirror_consistent_within_the_measured_gap(self):
        for (img,) in self.cases:
            a, b = landmarks.detect(img), landmarks.detect(cv2.flip(img, 1))
            self.assertLess(abs(a.pose["yaw"] + b.pose["yaw"]), 0.5)  # measured 0.06 - 0.08
            ya, yb = metrics.frontalize_with_status(a.points)[1], metrics.frontalize_with_status(b.points)[1]
            self.assertLess(abs(ya + yb), 2.5)  # measured 0.75 - 1.25

    def test_pose_matrix_balances_the_landmarks_under_the_x_flipped_convention(self):
        """Establishes the coordinate convention: de-posing with MediaPipe's matrix, x axis flipped, makes the landmarks far
        more left/right balanced than the raw ones (measured imbalance ratio 0.27 and 0.16)."""
        from evals.frontalize_investigation import pose_matrix_study
        for (img,) in self.cases:
            s = pose_matrix_study(img)
            self.assertEqual(s["best_convention"]["flips"] in ([-1, 1, 1], [1, -1, -1]), True)
            self.assertLess(s["best_convention"]["imbalance"], 0.6 * s["imbalance_of_raw_landmarks"])

    def test_saturation_still_explicit_beyond_the_range(self):
        for (img,) in self.cases:
            f = landmarks.detect(img)
            self.assertEqual(metrics.frontalize_with_status(metrics._yaw_rotate(f.points, 45))[2], "saturated")


if __name__ == "__main__":
    unittest.main()
