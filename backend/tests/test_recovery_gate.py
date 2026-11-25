"""Recovery gate: verification and the refusal logic around deleting the plaintext backup. TEMP folders only - the real backup is never touched."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from tools import recovery_gate as rg

RID = ["0123456789ab", "ba9876543210", "c" * 32]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-"))
        self.data, self.backup, self.keys = self.tmp / "data", self.tmp / "backup", self.tmp / "keys"
        for d in (self.data, self.backup, self.keys):
            d.mkdir()
        self.key = Fernet.generate_key()
        self.cipher = Fernet(self.key)
        self.docs = {r: {"id": r, "_photo": "P" + r, "profile": {"age": 30}} for r in RID}
        for r, doc in self.docs.items():
            (self.data / f"{r}.json").write_bytes(b"ENC1:" + self.cipher.encrypt(json.dumps(doc).encode()))
            (self.backup / f"{r}.json").write_text(json.dumps(doc), encoding="utf-8")
        self.keyfile = self.keys / "copy.key"
        self.keyfile.write_bytes(self.key)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Verify(Base):
    def test_correct_key_decrypts_everything_and_matches_the_backup(self):
        r = rg.verify(self.keyfile, self.backup, self.data)
        self.assertEqual((r["ok"], r["reports"], r["decrypted_and_equal_to_backup"]), (True, 3, 3))

    def test_wrong_key_is_reported_and_never_ok(self):
        other = self.keys / "other.key"
        other.write_bytes(Fernet.generate_key())
        r = rg.verify(other, self.backup, self.data)
        self.assertFalse(r["ok"])
        self.assertEqual(r["cannot_decrypt_with_this_key"], 3)

    def test_missing_or_garbage_key_file(self):
        self.assertFalse(rg.verify(self.keys / "nope.key", self.backup, self.data)["ok"])
        junk = self.keys / "junk.key"
        junk.write_bytes(b"not a key")
        self.assertFalse(rg.verify(junk, self.backup, self.data)["ok"])

    def test_a_report_that_differs_from_the_backup_is_not_ok(self):
        (self.backup / f"{RID[0]}.json").write_text(json.dumps({"id": RID[0], "tampered": True}), encoding="utf-8")
        r = rg.verify(self.keyfile, self.backup, self.data)
        self.assertFalse(r["ok"])
        self.assertEqual(r["differ_from_backup"], 1)

    def test_a_report_missing_from_the_backup_is_not_ok(self):
        (self.backup / f"{RID[1]}.json").unlink()
        r = rg.verify(self.keyfile, self.backup, self.data)
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing_from_backup"], 1)

    def test_remaining_plaintext_reports_are_flagged(self):
        (self.data / f"{RID[2]}.json").write_text(json.dumps(self.docs[RID[2]]), encoding="utf-8")
        r = rg.verify(self.keyfile, self.backup, self.data)
        self.assertEqual(r["still_plaintext"], 1)
        self.assertFalse(r["ok"])

    def test_the_result_never_contains_the_key(self):
        r = json.dumps(rg.verify(self.keyfile, self.backup, self.data))
        self.assertNotIn(self.key.decode(), r)
        self.assertNotIn(self.key.decode()[:12], r)

    def test_empty_data_dir_is_not_ok(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertFalse(rg.verify(self.keyfile, self.backup, empty)["ok"])


class OffMachineClassification(Base):
    def test_only_removable_or_network_drives_count(self):
        for dt, expected in ((rg.DRIVE_REMOVABLE, True), (rg.DRIVE_REMOTE, True), (rg.DRIVE_FIXED, False), (0, False)):
            c = rg.classify_key_copy(self.keyfile, self.backup, project_root=self.tmp / "elsewhere", dtype=lambda p, dt=dt: dt)
            self.assertEqual(c["off_machine"], expected, dt)

    def test_key_inside_the_project_or_backup_folder_is_refused_even_on_a_removable_drive(self):
        inside_backup = self.backup / "k.key"
        inside_backup.write_bytes(self.key)
        c = rg.classify_key_copy(inside_backup, self.backup, project_root=self.tmp / "x", dtype=lambda p: rg.DRIVE_REMOVABLE)
        self.assertFalse(c["off_machine"])
        self.assertTrue(any("backup folder" in p for p in c["problems"]))
        c2 = rg.classify_key_copy(self.keyfile, self.backup, project_root=self.tmp, dtype=lambda p: rg.DRIVE_REMOVABLE)
        self.assertTrue(any("project folder" in p for p in c2["problems"]))

    def test_cloud_sync_folders_are_refused(self):
        for name in ("OneDrive", "Dropbox", "Google Drive"):
            d = self.tmp / name
            d.mkdir()
            k = d / "k.key"
            k.write_bytes(self.key)
            c = rg.classify_key_copy(k, self.backup, project_root=self.tmp / "x", dtype=lambda p: rg.DRIVE_REMOVABLE)
            self.assertFalse(c["off_machine"], name)
            self.assertTrue(any("cloud" in p for p in c["problems"]))


class DeleteRefusal(Base):
    def run_cli(self, *extra, dtype=rg.DRIVE_FIXED):
        import io, contextlib
        from unittest import mock
        out = io.StringIO()
        with mock.patch.object(rg, "drive_type", lambda p: dtype), contextlib.redirect_stdout(out):
            code = rg.main(["delete-backup", "--key-file", str(self.keyfile), "--backup", str(self.backup), "--data-dir", str(self.data), *extra])
        return code, out.getvalue()

    def test_refuses_when_the_key_copy_is_on_a_fixed_disk_even_with_confirm(self):
        code, out = self.run_cli("--confirm-delete", dtype=rg.DRIVE_FIXED)
        self.assertEqual(code, 2)
        self.assertIn("REFUSING", out)
        self.assertEqual(len(list(self.backup.glob("*.json"))), 3)  # nothing deleted

    def test_refuses_without_the_explicit_confirm_flag_even_when_everything_else_passes(self):
        code, out = self.run_cli(dtype=rg.DRIVE_REMOVABLE)
        self.assertEqual(code, 2)
        self.assertIn("--confirm-delete", out)
        self.assertEqual(len(list(self.backup.glob("*.json"))), 3)

    def test_refuses_when_the_copy_cannot_decrypt_every_report(self):
        self.keyfile.write_bytes(Fernet.generate_key())
        code, _ = self.run_cli("--confirm-delete", dtype=rg.DRIVE_REMOVABLE)
        self.assertEqual(code, 2)
        self.assertEqual(len(list(self.backup.glob("*.json"))), 3)

    def test_deletes_only_when_every_condition_holds(self):
        code, out = self.run_cli("--confirm-delete", dtype=rg.DRIVE_REMOVABLE)
        self.assertEqual(code, 0, out)
        self.assertFalse(self.backup.exists())
        self.assertEqual(len(list(self.data.glob("*.json"))), 3)  # the encrypted live reports are untouched

    def test_secure_delete_overwrites_before_removing(self):
        f = self.backup / "x.bin"
        f.write_bytes(b"A" * 4096)
        seen = {}
        real_unlink = Path.unlink

        def spy(self_, *a, **k):
            if self_ == f:
                seen["content"] = f.read_bytes()
            return real_unlink(self_, *a, **k)
        from unittest import mock
        with mock.patch.object(Path, "unlink", spy):
            rg.secure_delete(self.backup)
        self.assertEqual(len(seen["content"]), 4096)
        self.assertNotEqual(seen["content"], b"A" * 4096)  # the content had been overwritten when it was removed


if __name__ == "__main__":
    unittest.main()
