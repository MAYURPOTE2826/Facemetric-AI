"""EVALUATOR SELF-TEST. These tests check that the validation pipeline computes what it claims to compute (annotation rules, metric
arithmetic, sample-size guards, false-reassurance detection, outputs). The 'annotations' here are derived from the synthetic generator and
are labelled human:SELFTEST-synthetic only so the loader accepts them. NOTHING here is real-photo validation or an accuracy figure."""
import json
import tempfile
import unittest
from pathlib import Path

import cv2

import hair_fixtures as F
from app import hairline
from evals import hairline_eval as E

SRC = "human:SELFTEST-synthetic"
POSSIBLE = {s: {"visibility": "visible", "recession": "possible"} for s in ("left", "right")}


def write_intake(root: Path, name: str, view="front", **over):
    (root / "metadata").mkdir(exist_ok=True)
    meta = {"validation_id": f"SELFTEST-{name}", "consent_status": "consented", "image_type": view, "source_category": "volunteer",
            "annotation_status": "annotated"}
    meta.update(over)
    (root / "metadata" / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")


def make_front(root: Path, name, hairline_fn=F.straight, label=None, **scene_kw):
    img, cat, pts = F.scene(hairline=hairline_fn, **scene_kw)
    (root / "real" / "front").mkdir(parents=True, exist_ok=True)
    (root / "annotations").mkdir(exist_ok=True)
    cv2.imwrite(str(root / "real" / "front" / f"{name}.jpg"), img)
    xs = [F.CX + F.BZ * (x / 20 - 0.5) for x in range(21)]
    poly = [[x, 400 - F.BZ * hairline_fn(max(-0.5, min(0.5, (x - F.CX) / F.BZ)))] for x in xs]
    front = {"hairline_visibility": "visible", "hairline_polyline_px": poly,
             "temples": {s: {"visibility": "visible", "recession": "none"} for s in ("left", "right")},
             "shape": "uncertain", "quality": "usable", "frontal_density": "uncertain"}
    if label:
        front.update(label)
    write_intake(root, name)
    (root / "annotations" / f"{name}.json").write_text(json.dumps({
        "schema": E.SCHEMA, "annotation_source": SRC, "image": f"real/front/{name}.jpg", "view": "front", "tags": [], "front": front}), encoding="utf-8")
    return cat, pts


def runner_for(store):
    def run(root, ann, meta):
        if ann["view"] == "top":
            return {"crown": hairline.crown_view(None, "unusable")}
        cat, pts = store[ann["_id"]]
        img = cv2.imread(str(root / ann["image"]))
        return {"analysis": hairline.build(img, cat, pts), "frame": hairline.Frame(pts), "image_shape": img.shape[:2]}
    return run


class AnnotationRules(unittest.TestCase):
    def write(self, root, name, data, image=True):
        (root / "annotations").mkdir(exist_ok=True)
        (root / "real" / "front").mkdir(parents=True, exist_ok=True)
        if image:
            (root / "real" / "front" / "a.jpg").write_bytes(b"x")
        (root / "annotations" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        write_intake(root, name)

    def base(self, **front):
        f = {"hairline_visibility": "visible", "hairline_polyline_px": [[i * 10, 50] for i in range(6)]}
        f.update(front)
        return {"schema": E.SCHEMA, "annotation_source": SRC, "image": "real/front/a.jpg", "view": "front", "front": f}

    def test_valid_and_each_invalid_case(self):
        cases = {
            "ok": (self.base(), True),
            "uncertain_needs_no_polyline": (self.base(hairline_visibility="uncertain", hairline_polyline_px=[]), True),
            "model_source": (dict(self.base(), annotation_source="model:prefill"), False),
            "no_source": (dict(self.base(), annotation_source=""), False),
            "visible_without_polyline": (self.base(hairline_polyline_px=[[0, 0]]), False),
            "x_goes_backwards": (self.base(hairline_polyline_px=[[50, 1], [40, 1], [30, 1], [20, 1], [10, 1]]), False),
            "unknown_visibility": (self.base(hairline_visibility="maybe"), False),
            "unknown_shape": (self.base(shape="wavy"), False),
            "wrong_view_folder": (dict(self.base(), view="top", top={"assessable": "yes"}), False),
        }
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, (data, _) in cases.items():
                self.write(root, name, data)
            good, rejected = E.load_annotations(root)
        ok_ids = {a["_id"] for a in good}
        for name, (_, expect_ok) in cases.items():
            self.assertEqual(name in ok_ids, expect_ok, name)
        self.assertEqual(len(rejected), sum(1 for _, ok in cases.values() if not ok))

    def test_missing_image_is_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            self.write(Path(d), "a", self.base(), image=False)
            good, rejected = E.load_annotations(Path(d))
        self.assertEqual(good, [])
        self.assertIn("image file missing", rejected[0])

    def test_legacy_v1_file_is_still_read(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.write(root, "a", {"image": "real/front/a.jpg", "annotation_source": SRC, "hairline_visible": True,
                                   "hairline_polyline_px": [[i * 10, 5] for i in range(6)]})
            good, _ = E.load_annotations(root)
        self.assertEqual(len(good), 1)


class IntakeAndConsent(unittest.TestCase):
    """No intake record / no consent -> no ground truth. Existing customer images are not admitted by default."""

    def one(self, **intake_over):
        d = tempfile.TemporaryDirectory()
        root = Path(d.name)
        make_front(root, "a")
        if intake_over == {"__delete__": True}:
            (root / "metadata" / "a.json").unlink()
        else:
            write_intake(root, "a", **intake_over)
        good, rejected = E.load_annotations(root)
        d.cleanup()
        return good, rejected

    def test_valid_intake_is_accepted(self):
        self.assertEqual(len(self.one()[0]), 1)

    def test_missing_intake_is_rejected(self):
        good, rejected = self.one(__delete__=True)
        self.assertEqual(good, [])
        self.assertIn("intake record", rejected[0])

    def test_each_bad_intake_value_is_rejected(self):
        for over in ({"consent_status": "pending"}, {"consent_status": ""}, {"validation_id": ""}, {"image_type": "top"},
                     {"source_category": "scraped"}, {"annotation_status": "done"}):
            good, rejected = self.one(**over)
            self.assertEqual(good, [], over)
            self.assertIn("intake", rejected[0], over)

    def test_customer_report_images_need_explicit_validation_consent(self):
        self.assertEqual(self.one(source_category="app_customer_report")[0], [])
        self.assertEqual(self.one(source_category="app_customer_report", consent_scope=["marketing"])[0], [])
        self.assertEqual(len(self.one(source_category="app_customer_report", consent_scope=["validation"])[0]), 1)


class Arithmetic(unittest.TestCase):
    def test_prf_values_and_the_sample_size_guard(self):
        r = E.prf(tp=20, fp=5, fn=10, tn=15)
        self.assertEqual(r["result"], "MEASURED")
        self.assertAlmostEqual(r["precision"], 0.8)
        self.assertAlmostEqual(r["recall"], 0.667, places=3)
        self.assertAlmostEqual(r["f1"], 0.727, places=3)
        small = E.prf(tp=3, fp=1, fn=0, tn=2)
        self.assertEqual(small["result"], E.INSUFFICIENT)
        self.assertNotIn("f1", small)
        self.assertEqual(small["tp"], 3)  # raw counts are still reported
        self.assertEqual(E.prf(tp=2, fp=0, fn=1, tn=60)["result"], E.INSUFFICIENT)  # too few positives

    def test_empty_dataset_is_not_measured_and_invents_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            r = E.evaluate(Path(d))
        self.assertEqual(r["status"], "NOT MEASURED")
        for k in ("precision", "recall", "f1", "accuracy", "mean_boundary_error_bz"):
            self.assertNotIn(k, r)

    def test_skeleton_and_status_count_only_what_exists(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "ds"
            made = E.init_skeleton(root)
            self.assertTrue(any("front" in m for m in made))
            self.assertEqual(E.init_skeleton(root), [], "never overwrites / recreates")
            s = E.status(root)
        self.assertEqual(s["images"], {"front": 0, "top": 0})
        self.assertEqual(s["verdict"], "NOT MEASURED")


class PipelineOnSyntheticScenes(unittest.TestCase):
    """Evaluator mechanics on drawn scenes with generator-derived labels. NOT accuracy evidence."""

    def build_set(self, root, n=20):
        store = {}
        for i in range(n):
            store[f"m{i}"] = make_front(root, f"m{i}", F.mature(0.14), label={"temples": POSSIBLE, "shape": "m_shaped"}, seed=i)
            store[f"s{i}"] = make_front(root, f"s{i}", F.straight, label={"shape": "relatively_straight"}, seed=100 + i)
        return store

    def test_boundary_error_visibility_and_temples_are_computed_with_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = self.build_set(root)
            r = E.evaluate(root, runner_for(store))
        self.assertEqual(r["status"], "MEASURED")
        self.assertEqual(r["counts"]["front"], 40)
        self.assertEqual(r["hairline_visibility"]["tp"], 40)
        self.assertLess(r["boundary_error"]["centre"]["mean_bz"], 0.02)
        self.assertEqual(r["boundary_error"]["left_temple"]["n_images"], 40)
        tp = r["temple_pattern"]
        self.assertEqual((tp["tp"], tp["fn"], tp["fp"], tp["tn"]), (40, 0, 0, 40))  # 20 images x 2 sides each way
        self.assertEqual(tp["result"], "MEASURED")
        self.assertEqual(r["shape"]["n"], 40)
        self.assertEqual(r["frontal_density"]["result"], "FRONTAL DENSITY ACCURACY: NOT MEASURED")
        self.assertIn("NOT MEASURED", r["longitudinal"])
        self.assertEqual(r["crown_front_only_violations"]["count"], 0)
        self.assertEqual(r["false_reassurance"]["count"], 0)

    def test_small_sets_say_insufficient_sample_size(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = {"a": make_front(root, "a"), "b": make_front(root, "b", F.mature(0.14), label={"temples": POSSIBLE})}
            r = E.evaluate(root, runner_for(store))
        self.assertEqual(r["temple_pattern"]["result"], E.INSUFFICIENT)
        self.assertEqual(r["hairline_visibility"]["result"], E.INSUFFICIENT)
        self.assertIn(E.INSUFFICIENT, r["boundary_error"]["centre"]["result"])
        self.assertEqual(r["shape"]["result"], E.INSUFFICIENT)

    def test_false_reassurance_is_detected_when_the_human_says_the_hairline_is_not_visible(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = {"x": make_front(root, "x", label={"hairline_visibility": "occluded", "hairline_polyline_px": [], "quality": "unusable"})}
            r = E.evaluate(root, runner_for(store))
        self.assertEqual(r["false_reassurance"]["count"], 1)
        self.assertIn("hairline detected", r["false_reassurance"]["cases"][0]["engine_claims"])
        self.assertIn("false_reassurance", r["per_image"][0]["buckets"])

    def test_uncertain_and_partial_labels_are_excluded_not_forced(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = {"u": make_front(root, "u", label={"hairline_visibility": "uncertain", "hairline_polyline_px": []}),
                     "p": make_front(root, "p")}
            a = json.loads((root / "annotations" / "p.json").read_text())
            a["front"]["hairline_visibility"] = "partial"
            (root / "annotations" / "p.json").write_text(json.dumps(a))
            r = E.evaluate(root, runner_for(store))
        v = r["hairline_visibility"]
        self.assertEqual(v["tp"] + v["fp"] + v["fn"] + v["tn"], 0)
        self.assertEqual(r["counts"]["uncertain_or_partial_excluded"], 2)

    def test_front_photo_that_infers_the_crown_is_reported_as_a_violation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = {"a": make_front(root, "a")}

            def bad_runner(root_, ann, meta):
                res = runner_for(store)(root_, ann, meta)
                res["analysis"]["crown"]["status"] = "assessed"
                return res
            r = E.evaluate(root, bad_runner)
        self.assertEqual(r["crown_front_only_violations"]["ids"], ["a"])

    def test_top_view_crown_assessability(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "real" / "top").mkdir(parents=True)
            (root / "annotations").mkdir()
            cv2.imwrite(str(root / "real" / "top" / "t.jpg"), F.scene()[0])
            write_intake(root, "t", view="top")
            (root / "annotations" / "t.json").write_text(json.dumps({
                "schema": E.SCHEMA, "annotation_source": SRC, "image": "real/top/t.jpg", "view": "top",
                "top": {"assessable": "yes", "crown_density": "uncertain", "parting_visible": "uncertain"}}))
            r = E.evaluate(root, runner_for({}))
        self.assertEqual(r["crown_assessability"]["fn"], 1)  # human: assessable; engine: inconclusive -> a miss, reported as a miss

    def test_outputs_machine_json_overlays_and_index_are_written_separately(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = {"a": make_front(root, "a"), "b": make_front(root, "b", label={"hairline_visibility": "not_visible", "hairline_polyline_px": []})}
            E.evaluate(root, runner_for(store), write_outputs=True)
            out = root / "outputs"
            self.assertTrue((out / "machine" / "a.json").is_file())
            self.assertTrue((out / "overlays" / "a.jpg").is_file())
            idx = json.loads((out / "overlay_index.json").read_text())
            self.assertIn("false_detection", idx)
            self.assertFalse(list((root / "annotations").glob("*machine*")), "machine output must never land in annotations/")
            self.assertTrue((out / "results.json").is_file())


if __name__ == "__main__":
    unittest.main()
