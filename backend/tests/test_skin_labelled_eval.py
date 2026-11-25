"""Labelled skin-mask evaluator: arithmetic and dataset-contract tests on SYNTHETIC label maps and stub predictions.
They verify the maths only. No segmentation accuracy has been measured; no real labels exist in this repository."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from evals import skin_labelled_eval as sl

H = W = 20


def labels_map():
    """20x20: top 10 rows skin (1); rows 10-14 beard (2); rows 15-16 glasses (4); rows 17-19 background (0)."""
    m = np.zeros((H, W), np.uint8)
    m[0:10] = 1
    m[10:15] = 2
    m[15:17] = 4
    return m


def make(root, iid, lighting="even", tags=(), source="human:a"):
    (root / "images").mkdir(exist_ok=True)
    (root / "labels").mkdir(exist_ok=True)
    cv2.imwrite(str(root / "images" / f"{iid}.png"), np.zeros((H, W, 3), np.uint8))
    cv2.imwrite(str(root / "labels" / f"{iid}.png"), labels_map())
    return {"image_id": iid, "subject_id": f"s-{iid}", "image_file": f"images/{iid}.png", "labels_file": f"labels/{iid}.png",
            "conditions": {"lighting": lighting, "tags": list(tags)}, "consent_ref": "synthetic"}


def manifest(root, items, source="human:a"):
    (root / "manifest.json").write_text(json.dumps({"dataset_version": "t", "label_protocol": "synthetic", "label_source": source, "items": items}), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="skin-lab-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_eval(self, pred_fn, items=None, source="human:a"):
        items = items or [make(self.root, "a")]
        manifest(self.root, items, source)
        return sl.evaluate(self.root, predict=lambda bgr, lab: (pred_fn(lab), lab))


class Arithmetic(Base):
    def test_perfect_mask(self):
        r = self.run_eval(lambda lab: lab == 1)
        o = r["overall_pixel_pooled"]
        self.assertEqual((o["iou"], o["dice"], o["precision"], o["recall"], o["false_positive_rate"], o["false_negative_rate"]), (1.0, 1.0, 1.0, 1.0, 0.0, 0.0))

    def test_known_overlap_values(self):
        def pred(lab):  # keeps the top 5 skin rows (half the skin) and wrongly includes the 5 beard rows
            m = np.zeros_like(lab, bool); m[0:5] = True; m[10:15] = True
            return m
        o = self.run_eval(pred)["overall_pixel_pooled"]
        self.assertEqual((o["tp"], o["fp"], o["fn"], o["tn"]), (100, 100, 100, 100))
        self.assertEqual((o["iou"], o["dice"], o["precision"], o["recall"]), (round(100 / 300, 4), round(200 / 400, 4), 0.5, 0.5))
        self.assertEqual((o["false_positive_rate"], o["false_negative_rate"]), (0.5, 0.5))

    def test_per_region_contamination_and_recall(self):
        def pred(lab):  # whole skin + half the beard + all glasses frame row 15 + nothing else
            m = lab == 1
            m[10:12] = True   # 2 of 5 beard rows
            m[15] = True      # 1 of 2 glasses rows
            return m
        reg = self.run_eval(pred)["per_region"]
        self.assertEqual(reg["skin"]["recall (share of true skin kept)"], 1.0)
        self.assertEqual(reg["beard"]["contamination (share wrongly inside the mask)"], 0.4)
        self.assertEqual(reg["glasses"]["contamination (share wrongly inside the mask)"], 0.5)
        self.assertEqual(reg["background"]["contamination (share wrongly inside the mask)"], 0.0)
        self.assertNotIn("hair", reg)  # a class absent from the labels is not reported with an invented number

    def test_undefined_rates_are_none_not_zero(self):
        m = sl.metrics(np.zeros((4, 4), bool), np.zeros((4, 4), bool))
        self.assertIsNone(m["iou"])
        self.assertIsNone(m["recall"])
        self.assertIsNone(m["false_negative_rate"])

    def test_pooling_sums_counts_not_averages_ratios(self):
        a = {"pixels": 100, "tp": 10, "fp": 0, "fn": 0, "tn": 90}
        b = {"pixels": 100, "tp": 50, "fp": 50, "fn": 0, "tn": 0}
        p = sl.pool([a, b])
        self.assertEqual(p["images"], 2)
        self.assertAlmostEqual(p["iou"], 60 / 110, places=4)  # pooled, not (1.0 + 0.5)/2

    def test_groups_by_lighting_and_tag(self):
        items = [make(self.root, "a", lighting="even", tags=["beard"]), make(self.root, "b", lighting="dim", tags=["beard", "glasses"])]
        calls = []

        def pred(lab):
            calls.append(1)
            return (lab == 1) if len(calls) == 1 else np.ones_like(lab, bool)  # 2nd image: mask everything (all wrong)
        manifest(self.root, items)
        r = sl.evaluate(self.root, predict=lambda bgr, lab: (pred(lab), lab))
        self.assertEqual(r["by_lighting"]["even"]["iou"], 1.0)
        self.assertEqual(r["by_lighting"]["dim"]["false_positive_rate"], 1.0)
        self.assertEqual(r["by_tag"]["beard"]["images"], 2)
        self.assertEqual(r["by_tag"]["glasses"]["images"], 1)

    def test_prediction_failures_are_counted_not_dropped(self):
        manifest(self.root, [make(self.root, "a"), make(self.root, "b")])
        seq = iter([None, (labels_map() == 1, labels_map())])
        r = sl.evaluate(self.root, predict=lambda bgr, lab: next(seq))
        self.assertEqual(r["images_evaluated"], 1)
        self.assertEqual(r["failures"][0]["image_id"], "a")

    def test_model_generated_labels_are_not_called_accuracy(self):
        r = self.run_eval(lambda lab: lab == 1, source="model:x")
        self.assertIn("NOT accuracy", r["measurement"])
        self.assertTrue(self.run_eval(lambda lab: lab == 1, source="human:a")["measurement"].startswith("ACCURACY"))

    def test_empty_dataset_reports_accuracy_not_measured(self):
        manifest(self.root, [])
        r = sl.evaluate(self.root)
        self.assertIn("ACCURACY NOT MEASURED", r["status"])
        self.assertNotIn("overall_pixel_pooled", r)

    def test_no_threshold_or_pass_fail_in_output(self):
        r = self.run_eval(lambda lab: lab == 1)
        self.assertIn("NOT DEFINED", r["acceptance_criteria"])
        self.assertFalse({"pass", "passed", "fail", "verdict"} & set(json.dumps(r).lower().replace('"', " ").replace(":", " ").replace(",", " ").split()))


class Contract(Base):
    def test_valid(self):
        manifest(self.root, [make(self.root, "a")])
        self.assertEqual(sl.validate(self.root), {"items": 1, "subjects": 1})

    def test_missing_pieces_are_reported(self):
        it = make(self.root, "a")
        del it["consent_ref"]
        manifest(self.root, [it, make(self.root, "a")])
        (self.root / "labels" / "a.png").unlink()
        with self.assertRaises(sl.DatasetError) as cm:
            sl.validate(self.root)
        self.assertIn("duplicate", str(cm.exception))
        self.assertIn("consent_ref", str(cm.exception))

    def test_missing_manifest(self):
        with self.assertRaises(sl.DatasetError):
            sl.validate(self.root)

    def test_class_table_matches_the_documented_regions(self):
        self.assertEqual(sl.CLASSES[1], "skin")
        for name in ("beard", "moustache", "glasses", "hair", "background"):
            self.assertIn(name, sl.CLASSES.values())


if __name__ == "__main__":
    unittest.main()
