"""Encryption recovery gate: prove an OFF-MACHINE key copy works before the plaintext photo backup is deleted.

The historical alexendra-backups path below is the location of existing backups and is not renamed.
    python tools/recovery_gate.py verify --key-file E:\\path\\data.key.copy --backup C:\\Users\\Admin\\alexendra-backups\\data-YYYYMMDD-HHMMSS
    python tools/recovery_gate.py delete-backup --key-file E:\\path\\data.key.copy --backup <dir> --confirm-delete

`verify` is READ-ONLY. It reads the key from the file you name (never prints it), decrypts every report in backend/data with ONLY that key,
compares each decrypted document with the plaintext backup, and prints counts. It also reports what kind of drive the key copy is on.
`delete-backup` runs the same verification first and refuses unless ALL of these hold:
  * the key copy is on a REMOVABLE or NETWORK drive (not a fixed local disk, so it is not "on this machine's own disk");
  * the key copy is not inside the project folder, the backup folder, or a known cloud-sync folder (OneDrive, Dropbox, Google Drive, iCloud);
  * the key copy decrypts 100% of the reports and every document equals the backup;
  * --confirm-delete was passed explicitly.
Deletion overwrites each backup file with random bytes, flushes, then removes it and the folder, and verifies nothing is left. On SSD/NVMe an
overwrite cannot guarantee the old blocks are gone (wear levelling); full-disk encryption is the reliable protection for deleted data.
The key itself is never printed, logged, or written anywhere by this tool.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE = 2, 3, 4
CLOUD_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync", "mega")


def drive_type(path: Path) -> int:
    """Windows GetDriveTypeW for the drive holding `path`; 0 = unknown (non-Windows)."""
    if os.name != "nt":
        return 0
    root = os.path.splitdrive(str(path.resolve()))[0] + "\\"
    return int(ctypes.windll.kernel32.GetDriveTypeW(root))


def classify_key_copy(key_file: Path, backup: Path, project_root: Path | None = None, dtype=None) -> dict:
    """Is this key copy a genuine off-machine copy? Returns the reasons it is not."""
    project_root = (project_root or BACKEND.parent).resolve()
    kf = key_file.resolve()
    problems = []
    dt = (dtype or drive_type)(kf)  # looked up at call time so it can be replaced
    if dt not in (DRIVE_REMOVABLE, DRIVE_REMOTE):
        problems.append({DRIVE_FIXED: "key copy is on a fixed local disk, not removable/network media", 0: "drive type could not be determined"}.get(dt, f"drive type {dt} is not removable/network"))
    for parent, label in ((project_root, "the project folder"), (backup.resolve(), "the plaintext backup folder")):
        if parent in kf.parents:
            problems.append(f"key copy is inside {label}")
    low = str(kf).lower()
    if any(m in low for m in CLOUD_MARKERS):
        problems.append("key copy is in a cloud-sync folder (ordinary cloud storage is not allowed for the key)")
    return {"drive_type": dt, "off_machine": not problems, "problems": problems}


def verify(key_file: Path, backup: Path, data_dir: Path | None = None) -> dict:
    """Decrypt every report using ONLY the key in key_file and compare with the plaintext backup. Never returns the key."""
    from cryptography.fernet import Fernet, InvalidToken
    data_dir = data_dir or BACKEND / "data"
    try:
        cipher = Fernet(key_file.read_bytes().strip())
    except Exception:
        return {"ok": False, "error": "the key file is missing or is not a valid key", "reports": 0}
    magic = b"ENC1:"
    files = sorted(p for p in data_dir.glob("*.json") if len(p.stem) in (12, 32))
    ok = bad_key = missing_backup = different = unreadable_backup = plaintext = 0
    for p in files:
        raw = p.read_bytes()
        if not raw.startswith(magic):
            plaintext += 1
            continue
        try:
            doc = json.loads(cipher.decrypt(raw[len(magic):]).decode("utf-8"))
        except InvalidToken:
            bad_key += 1
            continue
        b = backup / p.name
        if not b.exists():
            missing_backup += 1
            continue
        try:
            orig = json.loads(b.read_text(encoding="utf-8"))
        except Exception:
            unreadable_backup += 1
            continue
        if doc == orig:
            ok += 1
        else:
            different += 1
    total = len(files)
    return {"ok": total > 0 and ok == total, "reports": total, "decrypted_and_equal_to_backup": ok, "cannot_decrypt_with_this_key": bad_key,
            "missing_from_backup": missing_backup, "differ_from_backup": different, "unreadable_backup": unreadable_backup, "still_plaintext": plaintext}


def secure_delete(folder: Path) -> dict:
    """Overwrite each file once with random bytes, flush, remove; then remove the folders. Verifies nothing is left."""
    n = 0
    for p in sorted(folder.rglob("*"), key=lambda q: len(str(q)), reverse=True):
        if p.is_file():
            size = p.stat().st_size
            with open(p, "r+b") as f:
                f.write(os.urandom(size))
                f.flush()
                os.fsync(f.fileno())
            p.unlink()
            n += 1
        elif p.is_dir():
            p.rmdir()
    folder.rmdir()
    return {"files_overwritten_and_removed": n, "folder_exists_after": folder.exists()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "delete-backup"):
        s = sub.add_parser(name)
        s.add_argument("--key-file", required=True)
        s.add_argument("--backup", required=True)
        s.add_argument("--data-dir")
    sub.choices["delete-backup"].add_argument("--confirm-delete", action="store_true")
    a = ap.parse_args(argv)
    key, backup = Path(a.key_file), Path(a.backup)
    data_dir = Path(a.data_dir) if a.data_dir else None
    where = classify_key_copy(key, backup)
    result = verify(key, backup, data_dir)
    print(json.dumps({"key_copy_location": where, "decryption_check": result}, indent=2))
    if a.cmd == "verify":
        return 0 if result["ok"] else 1
    if not (where["off_machine"] and result["ok"]):
        print("REFUSING to delete: the key copy is not a verified off-machine copy that decrypts every report.")
        return 2
    if not a.confirm_delete:
        print("REFUSING to delete: --confirm-delete was not passed.")
        return 2
    print(json.dumps(secure_delete(backup), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
