"""Landmark accuracy evaluator: arithmetic and dataset-contract tests.

SYNTHETIC data only (blank images, a stub detector with known offsets). These tests check the evaluator's maths and the
dataset validation; they say NOTHING about the real model's accuracy, which has not been measured.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from evals import landmark_accuracy as la

IPD = 100.0  # px between the two iris centres in the synthetic reference


def ref_points():
    p = np.zeros((478, 3))
    p[:, 0], p[:, 1] = 300.0, 300.0
    p[468] = (250, 300, 0)
    p[473] = (350, 300, 0)
    for i in (33, 263, 1, 152, 61, 291, 70, 105):
        p[i, 0], p[i, 1] = 250 + i % 7 * 10, 280 + i % 5 * 10
    p[33], p[263] = (230, 295, 0), (370, 295, 0)
    return p


def make_item(root, iid, subject, pose="frontal", lighting="even", occ=("none",), quality="good", source="human:a1", landmarks=None, visible=None):
    (root / "images").mkdir(exist_ok=True)
    (root / "annotations").mkdir(exist_ok=True)
    cv2.imwrite(str(root / "images" / f"{iid}.png"), np.zeros((600, 600, 3), np.uint8))
    p = ref_points()
    idx = landmarks if landmarks is not None else [468, 473, 33, 263, 1, 152, 61, 291, 70, 105]
    visible = visible or {}
    ann = {"image_id": iid, "annotation_source": source, "annotation_version": "v1",
           "landmarks": {str(i): {"xy": [float(p[i, 0]), float(p[i, 1])], "visible": visible.get(i, True)} for i in idx}}
    (root / "annotations" / f"{iid}.json").write_text(json.dumps(ann), encoding="utf-8")
    return {"image_id": iid, "subject_id": subject, "image_file": f"images/{iid}.png",
            "capture": {"device": "synthetic", "format": "png", "width_px": 600, "height_px": 600},
            "conditions": {"pose": {"yaw_deg": 0, "pitch_deg": 0, "roll_deg": 0, "source": "synthetic"}, "pose_group": pose,
                           "lighting": lighting, "occlusion": list(occ), "expression": "neutral", "quality_group": quality},
            "consent_ref": "synthetic-test"}


def write_manifest(root, items):
    (root / "manifest.json").write_text(json.dumps({"dataset_version": "t1", "annotation_protocol": "synthetic", "items": items}), encoding="utf-8")


def shifted(dx_pct, which=None):
    """Detector returning the reference plus a known shift of dx_pct % of IPD on the x axis (to `which` indices, or all)."""
    def det(_img):
        p = ref_points()
        sel = which if which is not None else range(478)
        for i in sel:
            p[i, 0] += dx_pct / 100 * IPD
        return p
    return det


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lm-acc-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Statistics(unittest.TestCase):
    def test_describe_known_values(self):
        d = la.describe([1, 2, 3, 4, 100])
        self.assertEqual((d["n"], d["mean"], d["median"], d["max"]), (5, 22.0, 3.0, 100.0))
        self.assertAlmostEqual(d["p95"], float(np.percentile([1, 2, 3, 4, 100], 95)), places=3)
        self.assertIn("p95_note", d)  # n < 20

    def test_describe_empty_invents_nothing(self):
        self.assertEqual(la.describe([]), {"n": 0})

    def test_p95_note_disappears_with_enough_samples(self):
        self.assertNotIn("p95_note", la.describe(list(range(la.MIN_FOR_P95))))

    def test_normaliser_prefers_iris_then_eye_corners_and_fails_without_either(self):
        self.assertEqual(la.normaliser({468: (0, 0), 473: (100, 0)}), (100.0, "inter_pupil_distance"))
        self.assertEqual(la.normaliser({33: (0, 0), 263: (60, 0)}), (60.0, "outer_eye_corner_distance"))
        self.assertIsNone(la.normaliser({1: (0, 0)}))

    def test_regions_are_in_range_and_cover_the_expected_landmarks(self):
        for name, idx in la.REGIONS.items():
            self.assertTrue(all(0 <= i < 478 for i in idx), name)
            self.assertEqual(len(idx), len(set(idx)), f"duplicate index in {name}")
        self.assertEqual(la.REGIONS["iris"], list(range(468, 478)))
        self.assertTrue({33, 133, 362, 263} <= set(la.REGIONS["eyes"]))


class Evaluator(Base):
    def test_exact_error_values_for_a_known_shift(self):
        write_manifest(self.root, [make_item(self.root, "i1", "s1")])
        r = la.evaluate(self.root, detector=shifted(2.0))
        self.assertEqual(r["overall"]["n"], 10)
        for k in ("mean", "median", "p95", "max"):
            self.assertAlmostEqual(r["overall"][k], 2.0, places=4)  # every landmark off by exactly 2% of IPD
        self.assertEqual(r["normaliser"], ["inter_pupil_distance"])
        self.assertEqual(r["measurement"], "ACCURACY against reference annotations")

    def test_per_landmark_and_per_region_errors(self):
        write_manifest(self.root, [make_item(self.root, "i1", "s1")])
        r = la.evaluate(self.root, detector=shifted(5.0, which=[1, 4]))  # only nose-region landmark 1 is in the reference
        self.assertAlmostEqual(r["per_landmark"]["1"]["mean"], 5.0, places=4)
        self.assertEqual(r["per_landmark"]["152"]["mean"], 0.0)
        self.assertAlmostEqual(r["per_region"]["nose"]["mean"], 5.0, places=4)
        self.assertEqual(r["per_region"]["nose"]["n"], 1)
        self.assertEqual(r["per_region"]["iris"]["n"], 2)
        self.assertEqual(r["per_region"]["iris"]["mean"], 0.0)

    def test_groups_by_pose_lighting_occlusion_and_quality(self):
        items = [make_item(self.root, "a", "s1", pose="frontal", lighting="even", occ=("none",), quality="good"),
                 make_item(self.root, "b", "s2", pose="yaw_15_30", lighting="dim", occ=("glasses", "beard"), quality="blurred")]
        write_manifest(self.root, items)
        shifts = {"a": 1.0, "b": 4.0}
        calls = []

        def det(img):
            iid = ["a", "b"][len(calls)]
            calls.append(iid)
            return shifted(shifts[iid])(img)
        r = la.evaluate(self.root, detector=det)
        g = r["ROBUSTNESS_by_condition"]
        self.assertAlmostEqual(g["pose_group"]["frontal"]["mean"], 1.0, places=4)
        self.assertAlmostEqual(g["pose_group"]["yaw_15_30"]["mean"], 4.0, places=4)
        self.assertAlmostEqual(g["lighting"]["dim"]["mean"], 4.0, places=4)
        self.assertAlmostEqual(g["quality_group"]["blurred"]["mean"], 4.0, places=4)
        self.assertAlmostEqual(g["occlusion"]["glasses"]["mean"], 4.0, places=4)
        self.assertAlmostEqual(g["occlusion"]["beard"]["mean"], 4.0, places=4)  # an image counts in each of its occlusion labels
        self.assertAlmostEqual(g["occlusion"]["none"]["mean"], 1.0, places=4)
        self.assertAlmostEqual(r["overall"]["mean"], 2.5, places=4)

    def test_invisible_landmarks_are_excluded(self):
        write_manifest(self.root, [make_item(self.root, "i1", "s1", visible={152: False, 61: False})])
        r = la.evaluate(self.root, detector=shifted(3.0))
        self.assertEqual(r["overall"]["n"], 8)
        self.assertNotIn("152", r["per_landmark"])

    def test_detection_failures_are_counted_not_dropped(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1"), make_item(self.root, "b", "s2")])
        seq = iter([None, shifted(1.0)(None)])
        r = la.evaluate(self.root, detector=lambda img: next(seq))
        self.assertEqual(r["images_evaluated"], 1)
        self.assertEqual(r["detection_failures"], [{"image_id": "a", "reason": "no face detected"}])

    def test_image_without_a_normaliser_is_reported_as_skipped(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1", landmarks=[1, 152])])
        r = la.evaluate(self.root, detector=shifted(1.0))
        self.assertEqual(r["images_evaluated"], 0)
        self.assertEqual(r["skipped"][0]["image_id"], "a")
        self.assertEqual(r["overall"], {"n": 0})

    def test_eye_corner_fallback_normaliser(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1", landmarks=[33, 263, 1])])
        r = la.evaluate(self.root, detector=shifted(1.0))  # corners are 140 px apart, shift is 1 px
        self.assertEqual(r["normaliser"], ["outer_eye_corner_distance"])
        self.assertAlmostEqual(r["overall"]["mean"], 1.0 / 140 * 100, places=3)

    def test_model_generated_references_are_labelled_agreement_not_accuracy(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1", source="model:mediapipe")])
        r = la.evaluate(self.root, detector=shifted(0.0))
        self.assertIn("AGREEMENT", r["measurement"])
        self.assertIn("NOT accuracy", r["measurement"])

    def test_no_pass_fail_thresholds_are_applied_and_stability_is_not_claimed(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1")])
        r = la.evaluate(self.root, detector=shifted(9.0))
        self.assertIn("NOT DEFINED", r["acceptance_criteria"])
        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield str(k).lower()
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)
        self.assertFalse({"pass", "passed", "fail", "failed", "verdict", "meets_threshold", "ok"} & set(keys(r)))
        self.assertIn("not measured", r["STABILITY"])


class DatasetContract(Base):
    def test_valid_dataset_passes(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1"), make_item(self.root, "b", "s1")])
        self.assertEqual(la.validate(self.root), {"items": 2, "subjects": 1})

    def test_problems_are_reported_not_ignored(self):
        item = make_item(self.root, "a", "s1")
        item["conditions"]["pose_group"] = "sideways"
        del item["consent_ref"]
        write_manifest(self.root, [item, make_item(self.root, "a", "s2")])  # duplicate id too
        (self.root / "images" / "a.png").unlink()
        with self.assertRaises(la.DatasetError) as cm:
            la.validate(self.root)
        msg = str(cm.exception)
        for part in ("pose_group", "consent_ref", "duplicate", "image file not found"):
            self.assertIn(part, msg)

    def test_bad_landmark_entries_are_rejected(self):
        write_manifest(self.root, [make_item(self.root, "a", "s1")])
        p = self.root / "annotations" / "a.json"
        a = json.loads(p.read_text())
        a["landmarks"]["999"] = {"xy": [1, 2], "visible": True}
        a["landmarks"]["1"] = {"xy": [1], "visible": "yes"}
        p.write_text(json.dumps(a))
        with self.assertRaises(la.DatasetError) as cm:
            la.validate(self.root)
        self.assertIn("out of range", str(cm.exception))
        self.assertIn("needs xy", str(cm.exception))

    def test_missing_manifest_or_annotation(self):
        with self.assertRaises(la.DatasetError):
            la.validate(self.root)
        item = make_item(self.root, "a", "s1")
        write_manifest(self.root, [item])
        (self.root / "annotations" / "a.json").unlink()
        with self.assertRaises(la.DatasetError):
            la.validate(self.root)


if __name__ == "__main__":
    unittest.main()
