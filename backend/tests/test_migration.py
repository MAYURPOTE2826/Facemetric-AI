"""Tests for the plaintext -> encrypted report migration and key safety. Temporary directories only; no real data.

Run from backend/:  python -m unittest discover -s tests -v
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet

from app import store

BACKEND = Path(__file__).resolve().parent.parent
RID = ["0123456789ab", "ba9876543210", "a" * 32]


def doc(rid, **extra):
    return {"id": rid, "created_at": 1700000000, "_owner": "user1", "_photo": "PHOTO_" + rid, "profile": {"age": 30},
            "previews": {"before": "B64", "items": [{"key": "skin", "image": "IMG"}]}, "unicode": "नमस्ते ☃", **extra}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="alex-mig-"))
        self._saved = (store.DATA_DIR, {k: os.environ.get(k) for k in ("DATA_ENCRYPTION_KEY", "DATA_KEY_FILE")})
        store.DATA_DIR = self.tmp / "data"
        store.DATA_DIR.mkdir()
        self.keyfile = self.tmp / "keys" / "data.key"
        os.environ.pop("DATA_ENCRYPTION_KEY", None)
        os.environ["DATA_KEY_FILE"] = str(self.keyfile)
        store.reset_cipher()

    def tearDown(self):
        store.DATA_DIR, env = self._saved
        for k, v in env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        store.reset_cipher()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plant(self, rids=RID):
        for r in rids:
            (store.DATA_DIR / f"{r}.json").write_text(json.dumps(doc(r)), encoding="utf-8")

    def sha(self, rid):
        return hashlib.sha256((store.DATA_DIR / f"{rid}.json").read_bytes()).hexdigest()

    def backup(self):
        b = self.tmp / "backup"
        shutil.copytree(store.DATA_DIR, b)
        return b

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = store._cli(list(args))
        return code, out.getvalue()


class Migration(Base):
    def test_encrypts_all_and_preserves_ids_and_every_field(self):
        self.plant()
        before = {r: json.loads((store.DATA_DIR / f"{r}.json").read_text(encoding="utf-8")) for r in RID}
        s = store.migrate()
        self.assertEqual(s["counts"], {"encrypted": 3})
        self.assertEqual((s["failed"], s["plaintext_remaining"]), ([], 0))
        for r in RID:
            self.assertTrue((store.DATA_DIR / f"{r}.json").read_bytes().startswith(store.MAGIC))
            self.assertEqual(store.load(r), before[r])  # identical: id, owner, photo, previews, unicode

    def test_no_plaintext_remains_on_disk(self):
        self.plant()
        store.migrate()
        for r in RID:
            raw = (store.DATA_DIR / f"{r}.json").read_bytes()
            self.assertNotIn(b"PHOTO_", raw)
            self.assertNotIn(b'"_owner"', raw)

    def test_idempotent_second_run_changes_nothing(self):
        self.plant()
        store.migrate()
        hashes = {r: self.sha(r) for r in RID}
        s2 = store.migrate()
        self.assertEqual(s2["counts"], {"already_encrypted_verified": 3})
        self.assertEqual({r: self.sha(r) for r in RID}, hashes)  # byte-identical: not re-encrypted

    def test_a_bad_file_is_reported_never_skipped_and_does_not_stop_the_rest(self):
        self.plant(RID[:2])
        (store.DATA_DIR / f"{RID[2]}.json").write_text("{not json", encoding="utf-8")
        (store.DATA_DIR / "ffffffffffff.json").write_text(json.dumps(doc("eeeeeeeeeeee")), encoding="utf-8")  # id mismatch
        (store.DATA_DIR / "not-a-report.json").write_text("{}", encoding="utf-8")
        s = store.migrate()
        self.assertEqual(s["counts"].get("encrypted"), 2)
        self.assertEqual(len(s["failed"]), 3)
        self.assertEqual(s["total"], 5)  # every file accounted for
        self.assertEqual(s["plaintext_remaining"], 3)
        for r in s["failed"]:
            self.assertIn("detail", r)
        # the failed originals were left exactly as they were
        self.assertEqual((store.DATA_DIR / f"{RID[2]}.json").read_text(encoding="utf-8"), "{not json")

    def test_interruption_leaves_the_file_intact_and_a_rerun_completes(self):
        self.plant()
        real, calls = os.replace, {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("simulated crash / disk full")
            return real(src, dst)

        with mock.patch.object(store.os, "replace", flaky):
            s = store.migrate()
        self.assertEqual(s["counts"], {"encrypted": 2, "failed": 1})
        self.assertEqual(list(store.DATA_DIR.glob(".tmp-*")), [])  # no stray temp files
        for r in RID:  # every report is still readable, encrypted or not
            self.assertEqual(store.load(r)["id"], r)
        s2 = store.migrate()  # resume
        self.assertEqual(s2["counts"], {"encrypted": 1, "already_encrypted_verified": 2})
        self.assertEqual(s2["plaintext_remaining"], 0)

    def test_verification_failure_leaves_plaintext_untouched(self):
        self.plant(RID[:1])
        original = (store.DATA_DIR / f"{RID[0]}.json").read_bytes()
        with mock.patch.object(store, "_decode", return_value={"id": "wrong"}):
            s = store.migrate()
        self.assertEqual(s["counts"], {"failed": 1})
        self.assertEqual((store.DATA_DIR / f"{RID[0]}.json").read_bytes(), original)

    def test_dry_run_writes_nothing(self):
        self.plant()
        hashes = {r: self.sha(r) for r in RID}
        s = store.migrate(dry_run=True)
        self.assertEqual(s["counts"], {"would_encrypt": 3})
        self.assertEqual({r: self.sha(r) for r in RID}, hashes)
        self.assertFalse((store.DATA_DIR / ".tmp-x").exists())

    def test_users_subdirectory_is_not_touched(self):
        self.plant()
        u = store.DATA_DIR / "users"
        u.mkdir()
        (u / "u1.json").write_text('{"email": "a@b.c"}', encoding="utf-8")
        store.migrate()
        self.assertEqual((u / "u1.json").read_text(encoding="utf-8"), '{"email": "a@b.c"}')


class BackupGate(Base):
    def test_cli_refuses_without_a_backup(self):
        self.plant()
        code, out = self.cli("--migrate")
        self.assertEqual(code, 2)
        self.assertIn("--backup-dir is required", out)
        self.assertEqual(store.migrate(dry_run=True)["counts"], {"would_encrypt": 3})  # nothing was encrypted

    def test_cli_refuses_a_backup_that_differs_or_is_incomplete(self):
        self.plant()
        b = self.backup()
        (b / f"{RID[0]}.json").write_text("tampered", encoding="utf-8")
        (b / f"{RID[1]}.json").unlink()
        code, out = self.cli("--migrate", "--backup-dir", str(b))
        self.assertEqual(code, 2)
        self.assertIn("differs", out)
        self.assertIn("missing", out)
        self.assertEqual(store.migrate(dry_run=True)["counts"], {"would_encrypt": 3})

    def test_cli_migrates_with_a_verified_backup_and_returns_success(self):
        self.plant()
        b = self.backup()
        code, out = self.cli("--migrate", "--backup-dir", str(b))
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out[out.index("{"):])["plaintext_remaining"], 0)
        # the backup stays plaintext and untouched
        self.assertEqual(json.loads((b / f"{RID[0]}.json").read_text(encoding="utf-8"))["id"], RID[0])

    def test_rerun_after_success_needs_no_backup_and_changes_nothing(self):
        """Regression: the backup gate must not block a harmless re-run once everything is encrypted."""
        self.plant()
        b = self.backup()
        self.assertEqual(self.cli("--migrate", "--backup-dir", str(b))[0], 0)
        hashes = {r: self.sha(r) for r in RID}
        code, out = self.cli("--migrate")  # no --backup-dir
        self.assertEqual(code, 0, out)
        self.assertIn("already_encrypted_verified", out)
        self.assertEqual({r: self.sha(r) for r in RID}, hashes)

    def test_new_plaintext_after_a_migration_is_still_gated(self):
        self.plant(RID[:2])
        store.migrate()
        (store.DATA_DIR / f"{RID[2]}.json").write_text(json.dumps(doc(RID[2])), encoding="utf-8")  # a new legacy file
        code, out = self.cli("--migrate")
        self.assertEqual(code, 2)
        self.assertIn("--backup-dir is required", out)

    def test_cli_exit_code_signals_failures(self):
        self.plant(RID[:1])
        (store.DATA_DIR / f"{RID[1]}.json").write_text("{bad", encoding="utf-8")
        b = self.backup()
        code, _ = self.cli("--migrate", "--backup-dir", str(b))
        self.assertEqual(code, 1)


class KeySafety(Base):
    def test_default_key_location_is_outside_the_project(self):
        os.environ.pop("DATA_KEY_FILE", None)
        p = store.key_file_path().resolve()
        self.assertNotIn(BACKEND.resolve(), p.parents)
        self.assertEqual(p.name, "data.key")

    def test_key_is_generated_once_and_persists_across_restarts(self):
        self.plant(RID[:1])
        store.migrate()
        key1 = self.keyfile.read_bytes()
        store.reset_cipher()  # "restart"
        self.assertEqual(store.load(RID[0])["id"], RID[0])
        self.assertEqual(self.keyfile.read_bytes(), key1)

    def test_an_existing_key_is_never_overwritten(self):
        self.keyfile.parent.mkdir(parents=True)
        key = Fernet.generate_key()
        self.keyfile.write_bytes(key)
        self.plant(RID[:1])
        store.migrate()
        self.assertEqual(self.keyfile.read_bytes(), key)
        with self.assertRaises(FileExistsError):  # the O_EXCL creation path refuses to clobber a key
            os.close(os.open(self.keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))

    def test_missing_key_with_encrypted_reports_refuses_to_generate_a_new_one(self):
        self.plant(RID[:1])
        store.migrate()
        self.keyfile.unlink()
        store.reset_cipher()
        with self.assertRaises(RuntimeError) as cm:
            store._cipher()
        self.assertIn("Refusing to generate a new key", str(cm.exception))
        self.assertFalse(self.keyfile.exists())  # and nothing was created

    def test_wrong_key_cannot_read_and_does_not_corrupt(self):
        self.plant(RID[:1])
        store.migrate()
        before = self.sha(RID[0])
        os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        store.reset_cipher()
        with self.assertRaises(Exception):
            store.load(RID[0])
        self.assertEqual(self.sha(RID[0]), before)

    def test_env_key_takes_precedence_and_cli_loads_the_same_settings(self):
        self.plant(RID[:1])
        k = Fernet.generate_key().decode()
        os.environ["DATA_ENCRYPTION_KEY"] = k
        store.reset_cipher()
        store.migrate()
        self.assertFalse(self.keyfile.exists())  # env key used, no file generated
        self.assertEqual(store.load(RID[0])["id"], RID[0])


if __name__ == "__main__":
    unittest.main()
