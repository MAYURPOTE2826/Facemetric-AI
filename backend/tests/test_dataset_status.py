"""Dataset skeletons and honest counting. Synthetic files only; verifies counting and the 'NOT MEASURED' defaults."""
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from evals import dataset_status as ds


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="dsroot-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Skeleton(Base):
    def test_init_creates_empty_skeletons_with_protocols_and_never_overwrites(self):
        created = ds.init(self.root)
        self.assertIn("landmarks/REFERENCE_STANDARD.md", created)
        self.assertIn("skin_masks/PROTOCOL.md", created)
        (self.root / "landmarks" / "REFERENCE_STANDARD.md").write_text("EDITED", encoding="utf-8")
        self.assertEqual(ds.init(self.root), [])  # second run creates nothing
        self.assertEqual((self.root / "landmarks" / "REFERENCE_STANDARD.md").read_text(encoding="utf-8"), "EDITED")

    def test_reference_standard_states_the_conventions(self):
        ds.init(self.root)
        t = (self.root / "landmarks" / "REFERENCE_STANDARD.md").read_text(encoding="utf-8")
        for must in ("ORIGINAL, un-mirrored", "y increases DOWNWARD", "IMAGE's left", "landmark_map.py", "visible=false", "WITHOUT showing the model"):
            self.assertIn(must, t)

    def test_refuses_a_root_inside_the_repository(self):
        repo = Path(__file__).resolve().parents[2]
        with self.assertRaises(SystemExit):
            ds.init(repo / "some_dataset")


class Counting(Base):
    def test_empty_skeleton_reports_zero_and_not_measured_everywhere(self):
        ds.init(self.root)
        s = ds.status(self.root)
        self.assertEqual((s["landmarks"]["images"], s["landmarks"]["landmark_annotations"], s["skin_masks"]["masks"], s["pose"]["images"]), (0, 0, 0, 0))
        self.assertEqual(s["measurements"]["paired_subject_measurements"], 0)
        for v in s["evidence_status"].values():
            self.assertIn("NOT MEASURED", v)

    def test_missing_dataset_is_zero_not_an_error(self):
        s = ds.status(self.root)
        self.assertEqual(s["landmarks"]["images"], 0)
        self.assertFalse(s["landmarks"]["valid"])

    def test_counts_reflect_only_what_exists(self):
        ds.init(self.root)
        d = self.root / "landmarks"
        items = []
        for k in range(2):
            iid = f"i{k}"
            cv2.imwrite(str(d / "images" / f"{iid}.png"), np.zeros((10, 10, 3), np.uint8))
            (d / "annotations" / f"{iid}.json").write_text(json.dumps({"image_id": iid, "annotation_source": "human:a", "annotation_version": "v1",
                                                                      "landmarks": {"468": {"xy": [1, 1], "visible": True}, "473": {"xy": [5, 1], "visible": True}, "1": {"xy": [3, 3], "visible": False}}}), encoding="utf-8")
            items.append({"image_id": iid, "subject_id": "s1" if k == 0 else "s2", "image_file": f"images/{iid}.png", "capture": {}, "consent_ref": "c",
                          "conditions": {"pose_group": "frontal", "lighting": "even", "occlusion": ["none"], "quality_group": "good"}})
        (d / "manifest.json").write_text(json.dumps({"dataset_version": "t", "annotation_protocol": "p", "items": items}), encoding="utf-8")
        s = ds.status(self.root)
        self.assertEqual((s["landmarks"]["subjects"], s["landmarks"]["images"], s["landmarks"]["landmark_annotations"]), (2, 2, 6))
        self.assertEqual(s["evidence_status"]["landmark_accuracy"], "MEASURABLE")
        self.assertIn("NOT MEASURED", s["evidence_status"]["skin_segmentation_accuracy"])

    def test_invalid_dataset_is_reported_with_zero_counts_not_counted(self):
        ds.init(self.root)
        m = self.root / "landmarks" / "manifest.json"
        m.write_text(json.dumps({"dataset_version": "t", "annotation_protocol": "p", "items": [{"image_id": "x"}]}), encoding="utf-8")
        s = ds.status(self.root)
        self.assertFalse(s["landmarks"]["valid"])
        self.assertEqual(s["landmarks"]["images"], 0)

    def test_measurement_pairs_are_counted_by_subject_and_measurement(self):
        ds.init(self.root)
        d = self.root / "measurements"
        with open(d / "reference.csv", "a", newline="") as f:
            w = csv.writer(f)
            w.writerow(["s1", "face_width", "o1", 1, 130, "caliper"]); w.writerow(["s1", "face_width", "o1", 2, 131, "caliper"]); w.writerow(["s2", "nose_width", "o1", 1, 38, "caliper"])
        with open(d / "automated.csv", "a", newline="") as f:
            csv.writer(f).writerow(["s1", "img1", "face_width", 128, "phone", "daylight", "v2"])
        m = ds.status(self.root)["measurements"]
        self.assertEqual((m["reference_readings"], m["automated_values"], m["subjects"], m["paired_subject_measurements"]), (3, 1, 2, 1))


if __name__ == "__main__":
    unittest.main()
