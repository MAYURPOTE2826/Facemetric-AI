"""Cohort tooling self-tests. All images here are SYNTHETIC drawings in temporary folders, and all labels are test inputs: they exercise the
workflow and its safety rules. NOTHING here is validation evidence and no accuracy is computed."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

import hair_fixtures as F
from evals import hairline_cohort as C
from evals import hairline_eval as E

REPO = Path(__file__).resolve().parent.parent.parent
GOOD = dict(view="front", source_type="volunteer_capture", source_category="volunteer", consent_status="consented", validation_use=True,
            consent_scope=["validation"], adult_confirmed=True, consent_ref="CONSENT-0001")


def jpg(path: Path, seed=0, gps=False):
    img = F.scene(seed=seed)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    if gps:
        from PIL import Image
        im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (12.0, 0.0, 0.0), 3: "E", 4: (77.0, 0.0, 0.0)}
        im.save(path, exif=exif)
    else:
        cv2.imwrite(str(path), img)
    return path


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "ws"
        C.init_workspace(self.root)
        self.src = self.base / "src"

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, name="a.jpg", seed=0, **over):
        kw = dict(GOOD)
        kw.update(over)
        return C.add_candidate(self.root, jpg(self.src / name, seed), kw["view"], kw["source_type"], kw["source_category"], kw["consent_status"],
                               kw["validation_use"], kw["consent_scope"], kw["adult_confirmed"], kw["consent_ref"])

    def approved(self, n=1):
        ids = []
        for i in range(n):
            rid = self.add(f"i{i}.jpg", seed=i)["validation_id"]
            C.include(self.root, rid)
            ids.append(rid)
        return ids

    def annotate(self, who, rid, vis="visible", attest=True, source=None, polyline=None, **front):
        f = {"hairline_visibility": vis, "hairline_polyline_px": polyline if polyline is not None else ([[10 * i, 100 + i] for i in range(6)] if vis in ("visible", "partial") else []),
             "temples": {s: {"visibility": "visible", "recession": "none"} for s in ("left", "right")}, "shape": "uncertain", "quality": "usable", "frontal_density": "uncertain"}
        f.update(front)
        rec = C.records(self.root)[rid]
        a = {"schema": E.SCHEMA, "annotation_source": source or f"human:SELFTEST-{who.upper()}", "image": f"approved/{rec['image_type']}/{rid}.jpg", "view": rec["image_type"], "front": f}
        if attest:
            a["independence"] = dict(C.ATTESTATION)
        d = self.root / "annotations" / f"annotator_{who}"
        (d / f"{rid}.json").write_text(json.dumps(a), encoding="utf-8")


class Workspace(unittest.TestCase):
    def test_refuses_inside_the_repository_and_inside_app_data_and_inside_a_git_tree(self):
        self.assertTrue(C.workspace_problems(REPO / "validation" / "hairline"))
        self.assertTrue(C.workspace_problems(REPO / "backend" / "data" / "x"))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            self.assertTrue(any("git" in w for w in C.workspace_problems(Path(d) / "ws")))
            with self.assertRaises(C.CohortError):
                C.init_workspace(Path(d) / "ws")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(C.workspace_problems(Path(d) / "ws"), [])

    def test_init_is_idempotent_and_creates_every_required_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "ws"
            C.init_workspace(root)
            self.assertEqual(C.init_workspace(root), [])
            for sub in ("candidates/front", "approved/top", "excluded", "annotations/annotator_a", "annotations/annotator_b", "annotations/consensus",
                        "machine_outputs", "overlays", "reports", "consent", "metadata"):
                self.assertTrue((root / sub).is_dir(), sub)


class Intake(Env):
    def test_pseudonymous_sequential_ids_byte_identical_copy_and_no_identity_fields(self):
        r1, r2 = self.add("a.jpg"), self.add("b.jpg", seed=1)
        self.assertEqual((r1["validation_id"], r2["validation_id"]), ("HLV-0001", "HLV-0002"))
        src = self.src / "a.jpg"
        dest = self.root / "candidates" / "front" / "HLV-0001.jpg"
        self.assertEqual(hashlib.sha256(src.read_bytes()).hexdigest(), hashlib.sha256(dest.read_bytes()).hexdigest())
        self.assertEqual(C.identity_fields(r1), [])
        self.assertEqual(r1["inclusion_decision"], "pending")
        self.assertNotIn("a.jpg", json.dumps(r1), "the original file name must not be stored")

    def test_every_missing_authorization_is_refused(self):
        bad = [dict(consent_status="pending"), dict(consent_status=""), dict(validation_use=False), dict(consent_scope=["marketing"]), dict(consent_scope=[]),
               dict(consent_ref="a@b.com"), dict(consent_ref="has space"), dict(consent_ref=""), dict(view="side"), dict(source_type="scraped")]
        for over in bad:
            with self.assertRaises(C.CohortError, msg=str(over)):
                self.add(**over)
        self.assertEqual(C.records(self.root), {})
        self.assertEqual(list((self.root / "candidates" / "front").iterdir()), [], "a refused image must not be copied anywhere")

    def test_no_validation_consent_means_not_eligible(self):
        rec = dict(self.add())
        rec["validation_use_authorized"] = False
        self.assertIn("no explicit validation-use authorization", C.eligibility(rec))

    def test_customer_report_needs_the_same_explicit_validation_consent(self):
        with self.assertRaises(C.CohortError):
            self.add(source_type="app_customer_report", source_category="app_customer_report", consent_scope=["marketing"], validation_use=False)
        ok = self.add("c.jpg", source_type="app_customer_report", source_category="app_customer_report", consent_scope=["validation"])
        self.assertEqual(C.eligibility(ok, self.root), [])

    def test_application_data_and_encrypted_files_are_never_ingested(self):
        data = self.base / "appdata"
        data.mkdir()
        img = jpg(data / "x.jpg")
        with mock.patch.object(C, "app_data_dirs", return_value=[data]):
            with self.assertRaises(C.CohortError) as cm:
                C.add_candidate(self.root, img, "front", "volunteer_capture", "volunteer", "consented", True, ["validation"], True, "CONSENT-9")
            self.assertIn("application's data folder", str(cm.exception))
        self.src.mkdir(parents=True, exist_ok=True)
        enc = self.src / "enc.jpg"
        enc.write_bytes(b"ENC1" + bytes(100))
        with self.assertRaises(C.CohortError):
            C.add_candidate(self.root, enc, "front", "volunteer_capture", "volunteer", "consented", True, ["validation"], True, "CONSENT-9")

    def test_eligibility_catches_identity_fields_tampering_gps_and_unconfirmed_adults(self):
        rid = self.add()["validation_id"]
        rec = C.records(self.root)[rid]
        self.assertEqual(C.eligibility(rec, self.root), [])
        self.assertTrue(any("identity" in w for w in C.eligibility(dict(rec, email="x@y.z"), self.root)))
        self.assertTrue(any("adult" in w for w in C.eligibility(dict(rec, adult_confirmed=False), self.root)))
        (self.root / "candidates" / "front" / f"{rid}.jpg").write_bytes(b"tampered")
        self.assertTrue(any("hash mismatch" in w or "decodable" in w for w in C.eligibility(rec, self.root)))

    def test_gps_in_exif_blocks_eligibility(self):
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("Pillow not installed")
        p = jpg(self.src / "g.jpg", gps=True)
        rec = C.add_candidate(self.root, p, "front", "volunteer_capture", "volunteer", "consented", True, ["validation"], True, "CONSENT-7")
        if rec["technical"]["exif_gps_present"] is not True:
            self.skipTest("this Pillow build did not write the GPS tag")
        self.assertTrue(any("GPS" in w for w in C.eligibility(rec, self.root)))
        with self.assertRaises(C.CohortError):
            C.include(self.root, rec["validation_id"])

    def test_include_moves_to_approved_and_exclude_records_reason_then_deletes_the_image(self):
        a, b = self.add("a.jpg")["validation_id"], self.add("b.jpg", seed=1)["validation_id"]
        C.include(self.root, a)
        self.assertTrue((self.root / "approved" / "front" / f"{a}.jpg").is_file())
        self.assertFalse((self.root / "candidates" / "front" / f"{a}.jpg").exists())
        with self.assertRaises(C.CohortError):
            C.exclude(self.root, b, "because")
        with self.assertRaises(C.CohortError):
            C.exclude(self.root, b, "other_documented")  # needs a note
        out = C.exclude(self.root, b, "out_of_scope_head_pitch")
        self.assertTrue(out["image_deleted"])
        self.assertFalse(list(self.root.rglob(f"{b}.jpg")))
        self.assertTrue((self.root / "excluded" / f"{b}.json").is_file())
        self.assertEqual(C.next_id(self.root), "HLV-0003", "ids are never reused after an exclusion")

    def test_an_annotated_image_cannot_be_silently_excluded(self):
        rid = self.approved()[0]
        self.annotate("a", rid)
        with self.assertRaises(C.CohortError):
            C.exclude(self.root, rid, "out_of_scope_head_pitch")


class Annotations(Env):
    def test_lifecycle_counts_come_from_real_files(self):
        ids = self.approved(2)
        self.assertEqual(C.counts(self.root) | {}, C.counts(self.root))
        c = C.counts(self.root)
        self.assertEqual((c["candidates"], c["consented"], c["eligible"], c["annotator_a"], c["annotator_b"]), (2, 2, 2, 0, 0))
        self.annotate("a", ids[0])
        self.annotate("b", ids[0])
        self.annotate("a", ids[1])
        c = C.counts(self.root)
        self.assertEqual((c["annotator_a"], c["annotator_b"], c["both_annotators"], c["consensus"], c["engine_run"], c["evaluated"]), (2, 1, 1, 0, 0, 0))

    def test_attestation_is_required_and_must_be_all_false(self):
        rid = self.approved()[0]
        self.annotate("a", rid, attest=False)
        self.assertEqual(C.counts(self.root)["annotator_a"], 0)
        self.annotate("a", rid)
        d = self.root / "annotations" / "annotator_a" / f"{rid}.json"
        a = json.loads(d.read_text())
        a["independence"]["engine_output_seen"] = True
        d.write_text(json.dumps(a))
        self.assertEqual(C.counts(self.root)["annotator_a"], 0)

    def test_one_person_cannot_be_both_annotators(self):
        rid = self.approved()[0]
        self.annotate("a", rid, source="human:P1")
        self.annotate("b", rid, source="human:P1")
        c = C.counts(self.root)
        self.assertEqual((c["annotator_a"], c["annotator_b"]), (1, 0))

    def test_model_or_report_sources_and_candidate_images_are_not_ground_truth(self):
        rid = self.approved()[0]
        for src in ("report:abc", "model:prefill", "claude", " "):
            self.annotate("a", rid, source=src)
            self.assertEqual(C.counts(self.root)["annotator_a"], 0, src)

    def test_annotation_made_after_engine_output_exists_is_contaminated(self):
        rid = self.approved()[0]
        (self.root / "machine_outputs" / f"{rid}.json").write_text("{}")
        import os, time
        old = time.time() - 100
        os.utime(self.root / "machine_outputs" / f"{rid}.json", (old, old))
        self.annotate("a", rid)  # written NOW, after the engine output: the human could have seen it
        self.assertEqual(C.counts(self.root)["annotator_a"], 0)
        g5 = [g for g in C.gates(self.root) if g["id"] == 5][0]
        self.assertEqual(g5["status"], C.NOT_SAT)
        self.assertIn(f"annotator_a/{rid}", g5["detail"])

    def test_queue_gives_only_ids_skips_machine_run_and_already_labelled_images(self):
        ids = self.approved(3)
        self.annotate("a", ids[0])
        (self.root / "machine_outputs" / f"{ids[1]}.json").write_text("{}")
        q = C.annotation_queue(self.root, "A01")
        self.assertEqual(q, [ids[2]])
        self.assertTrue(all(re.fullmatch(r"HLV-\d{4}", x) for x in q))
        self.assertEqual(set(C.annotation_queue(self.root, "B01")), {ids[0], ids[2]})


class Agreement(Env):
    def test_cohen_kappa_arithmetic(self):
        pairs = [("x", "x")] * 20 + [("y", "y")] * 5 + [("x", "y")] * 5
        self.assertAlmostEqual(C.cohen_kappa(pairs), 0.571, places=3)
        self.assertEqual(C.cohen_kappa([("a", "a")] * 10), None)  # no variation: undefined, not 1.0
        self.assertEqual(C.cohen_kappa([("a", "b"), ("b", "a")]), -1.0)

    def test_small_sets_are_insufficient_disagreements_are_listed_and_originals_untouched(self):
        ids = self.approved(2)
        self.annotate("a", ids[0], vis="visible")
        self.annotate("b", ids[0], vis="partial", polyline=[[10 * i, 130 + 3 * i] for i in range(6)])
        self.annotate("a", ids[1], vis="visible")
        self.annotate("b", ids[1], vis="visible", polyline=[[10 * i, 90 + 2 * i] for i in range(6)])
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "annotations").rglob("*.json")}
        ag = C.agreement(self.root, write=True)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.root / "annotations").rglob("*.json")}
        self.assertEqual(before, after, "both original annotations must be preserved untouched")
        self.assertEqual(ag["compared_images"], 2)
        self.assertEqual(ag["human_human_agreement"], "INSUFFICIENT SAMPLE SIZE")
        self.assertEqual(ag["fields"]["front.hairline_visibility"]["result"], E.INSUFFICIENT)
        self.assertEqual(ag["disagreements"], {ids[0]: ["front.hairline_visibility"]})
        self.assertIn("NOT DEFINED", ag["adjudication"])
        self.assertTrue((self.root / "reports" / "agreement.json").is_file())
        self.assertEqual(ag["polyline_distance_image_widths"]["result"], E.INSUFFICIENT)

    def test_identical_polylines_from_two_people_are_flagged_as_a_suspected_copy_and_not_counted(self):
        rid = self.approved()[0]
        poly = [[10 * i, 100 + i] for i in range(6)]
        self.annotate("a", rid, polyline=poly)
        self.annotate("b", rid, polyline=poly)
        ag = C.agreement(self.root)
        self.assertEqual(ag["suspected_copies_excluded"], [rid])
        self.assertEqual(ag["compared_images"], 0)
        self.assertEqual(ag["human_human_agreement"], "NOT MEASURED")

    def test_agreement_with_no_data_is_not_measured_and_never_uses_the_engine(self):
        self.assertEqual(C.agreement(self.root)["human_human_agreement"], "NOT MEASURED")
        self.assertFalse(list((self.root / "machine_outputs").iterdir()))


class Gates(Env):
    def status(self, gs, i):
        return [g for g in gs if g["id"] == i][0]["status"]

    def test_empty_workspace_is_not_ready_with_the_expected_gate_states(self):
        gs = C.gates(self.root)
        self.assertEqual(C.overall(gs), "NOT READY")
        self.assertEqual(self.status(gs, 1), C.PASS)       # lock matches the recorded baseline
        self.assertEqual(self.status(gs, 3), C.BLOCKED)    # acceptance thresholds not agreed
        self.assertEqual(self.status(gs, 4), C.NOT_SAT)    # no consented images
        self.assertEqual(self.status(gs, 5), C.NOT_SAT)    # no attested annotations
        self.assertEqual(self.status(gs, 6), C.BLOCKED)    # no second annotator / adjudication
        self.assertEqual(self.status(gs, 7), C.PASS)       # separated from repo and app data
        self.assertEqual(self.status(gs, 8), C.PASS)       # reproducibility capability

    def test_a_bare_decision_flag_without_name_and_date_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "dec.json"
            f.write_text(json.dumps({"acceptance_thresholds_agreed": {"value": True}}))
            with mock.patch.object(C, "DECISIONS_FILE", f):
                self.assertFalse(C.decision_agreed("acceptance_thresholds_agreed"))
                f.write_text(json.dumps({"acceptance_thresholds_agreed": {"value": True, "decided_by": "owner", "decided_on": "2026-01-01"}}))
                self.assertTrue(C.decision_agreed("acceptance_thresholds_agreed"))

    def test_algorithm_drift_blocks_gate_1(self):
        with tempfile.TemporaryDirectory() as d:
            lock = json.loads(C.LOCK_FILE.read_text())
            lock["files"]["backend/app/hairline.py"] = "0" * 64
            f = Path(d) / "lock.json"
            f.write_text(json.dumps(lock))
            with mock.patch.object(C, "LOCK_FILE", f):
                self.assertEqual(self.status(C.gates(self.root), 1), C.BLOCKED)
            lock = json.loads(C.LOCK_FILE.read_text())
            lock["thresholds"]["T_MILD"] = 0.05
            f.write_text(json.dumps(lock))
            with mock.patch.object(C, "LOCK_FILE", f):
                self.assertEqual(self.status(C.gates(self.root), 1), C.BLOCKED)

    def test_relocking_needs_a_reason_and_explicit_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(C, "LOCK_FILE", Path(d) / "lock.json"):
                with self.assertRaises(C.CohortError):
                    C.write_lock("  ")
                C.write_lock("first")
                with self.assertRaises(C.CohortError):
                    C.write_lock("again")
                C.write_lock("again", overwrite=True)

    def test_run_is_refused_and_writes_nothing_while_any_gate_is_not_passed(self):
        with self.assertRaises(C.CohortError) as cm:
            C.run(self.root)
        self.assertIn("REFUSED", str(cm.exception))
        self.assertEqual(C.main(["run", str(self.root)]), 2)
        self.assertFalse(list((self.root / "machine_outputs").iterdir()))
        self.assertFalse((self.root / "reports" / "run_manifest.json").exists())
        self.assertFalse((self.root / "reports" / "results.json").exists())

    def test_when_every_gate_passes_the_run_proceeds_with_a_verifiable_manifest_and_makes_no_accuracy_claim(self):
        """SIMULATION of the human decisions with synthetic data, only to exercise the gated flow. It proves nothing about the engine."""
        ids = self.approved(1)
        self.annotate("a", ids[0], source="human:P-A")
        self.annotate("b", ids[0], source="human:P-B", polyline=[[10 * i, 99 + 2 * i] for i in range(6)])
        dec = {k: {"value": True, "decided_by": "selftest", "decided_on": "2026-01-01"} for k in
               ("population_confirmed_by_owner", "acceptance_thresholds_agreed", "second_annotator_available", "adjudication_procedure_defined")}
        rec = C.records(self.root)[ids[0]]
        cons = {"schema": E.SCHEMA, "annotation_source": "human:ADJ", "image": f"approved/front/{ids[0]}.jpg", "view": "front", "basis": "adjudication",
                "front": json.loads((self.root / "annotations" / "annotator_a" / f"{ids[0]}.json").read_text())["front"]}
        (self.root / "annotations" / "consensus" / f"{ids[0]}.json").write_text(json.dumps(cons))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "dec.json"
            f.write_text(json.dumps(dec))
            with mock.patch.object(C, "DECISIONS_FILE", f), mock.patch.object(E, "real_runner", lambda *a, **k: {"error": "synthetic self-test: engine not run"}):
                gs = C.gates(self.root)
                self.assertEqual([g["status"] for g in gs], [C.PASS] * 8, gs)
                self.assertTrue(C.overall(gs).startswith("READY TO BEGIN"))
                res = C.run(self.root)
        self.assertNotEqual(res["status"], "MEASURED")
        man = json.loads((self.root / "reports" / "run_manifest.json").read_text())
        self.assertTrue(C.verify_manifest(self.root, man))
        (self.root / "annotations" / "annotator_a" / f"{ids[0]}.json").write_text("{}")  # any change to a recorded input breaks verification
        self.assertFalse(C.verify_manifest(self.root, man))
        self.assertEqual(rec["validation_id"], ids[0])

    def test_status_text_is_built_from_real_counts_and_states_not_measured(self):
        t = C.readiness_text(self.root)
        for needle in ("Candidate images:       0", "Eligible images:        0", "Human-human agreement:  NOT MEASURED", "Human-engine accuracy:  NOT MEASURED",
                       "Acceptance criteria:    NOT AGREED", "Overall:\nNOT READY"):
            self.assertIn(needle, t)


class LeakageProtections(unittest.TestCase):
    def test_no_jpeg_images_exist_anywhere_in_the_repository(self):
        self.assertEqual(C.repo_has_real_images(), [], "real-person photographs must never be in the repository")

    def test_gitignore_blocks_validation_data_and_credentials(self):
        gi = (REPO / ".gitignore").read_text()
        for needle in ("validation/", ".alexendra/", "backend/data/", "backend/.env"):
            self.assertIn(needle, gi)

    def test_the_application_cannot_reach_the_validation_workspace(self):
        for p in (REPO / "backend" / "app").glob("*.py"):
            text = p.read_text(encoding="utf-8")
            for needle in ("hairline_cohort", "validation/hairline", ".alexendra/validation", "hairline_eval"):
                self.assertNotIn(needle, text, f"{p.name} must not touch the validation workspace ({needle})")

    def test_test_fixtures_never_read_image_files_or_the_workspace(self):
        text = (REPO / "backend" / "tests" / "hair_fixtures.py").read_text(encoding="utf-8")
        for needle in ("imread", "open(", ".alexendra", "validation/"):
            self.assertNotIn(needle, text)

    def test_machine_output_overlays_reports_and_annotations_live_in_separate_folders(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "ws"
            C.init_workspace(root)
            dirs = {"annotations", "machine_outputs", "overlays", "reports", "consent", "metadata", "candidates", "approved", "excluded"}
            self.assertTrue(dirs <= {p.name for p in root.iterdir()})
            self.assertEqual(set(E.DEFAULT_LAYOUT) - {"annotations"}, {"machine", "overlays", "results", "index"})
            # the gated run writes engine output ONLY outside annotations/
            layout = {"annotations": "annotations/consensus", "machine": "machine_outputs", "overlays": "overlays", "results": "reports/results.json",
                      "index": "reports/overlay_index.json"}
            self.assertFalse(any(v.startswith("annotations") for k, v in layout.items() if k != "annotations"))

    def test_evaluator_default_layout_is_unchanged_for_existing_callers(self):
        self.assertEqual(E.DEFAULT_LAYOUT["annotations"], "annotations")
        self.assertEqual(E.DEFAULT_LAYOUT["machine"], "outputs/machine")

    def test_validation_data_cannot_be_imported_into_customer_reports_by_construction(self):
        # no code path in the app package imports the evals package at all
        for p in (REPO / "backend" / "app").glob("*.py"):
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"^\s*(from|import)\s+evals", p.name)


if __name__ == "__main__":
    unittest.main()
