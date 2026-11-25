"""Encrypted JSON-file storage for analyses (swap for Postgres + S3 later).

Every analysis (which embeds the user's photos as base64) is encrypted at rest with Fernet
(AES-128-CBC + HMAC-SHA256, from the `cryptography` package). Files start with the marker b"ENC1:".
Legacy plaintext files are still readable and are re-encrypted the next time they are saved, or all at once, with
verification, by `python -m app.store --migrate --backup-dir <dir>`.

Key management (what is actually implemented):
  1. DATA_ENCRYPTION_KEY env var (urlsafe-base64, 32 bytes) if set - preferred; keep it in a secret manager.
  2. Otherwise a key FILE: DATA_KEY_FILE if set, else ~/.alexendra/data.key - the legacy directory is retained so
     existing encryption keys remain available, deliberately OUTSIDE the project tree.
     Created once (O_EXCL), never overwritten, access restricted to the current user (mode 0600 / NTFS ACL).
  3. Safety guard: if encrypted reports already exist but no key can be found, the code REFUSES to generate a new
     key (that would silently strand every report) and raises instead.
A key file protects copied data files, NOT a host where the key file is also readable. Back the key up separately
(password manager): without it encrypted reports cannot be recovered. The key is never logged or returned by any
endpoint.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

log = logging.getLogger("facemetric_ai.store")

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
MAGIC = b"ENC1:"
# 12 hex = legacy ids, 32 hex = 128-bit ids (current)
ID_RE = re.compile(r"^(?:[0-9a-f]{12}|[0-9a-f]{32})$")

_fernet: Fernet | None = None


def restrict_to_current_user(p: Path) -> None:
    """Best-effort owner-only access: POSIX mode bits, or an NTFS ACL via icacls on Windows."""
    try:
        os.chmod(p, 0o700 if p.is_dir() else 0o600)
    except OSError:
        pass
    if os.name == "nt":
        user = os.environ.get("USERNAME")
        if user:
            grant = f"{user}:(OI)(CI)F" if p.is_dir() else f"{user}:F"
            subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", grant], capture_output=True, check=False)


def _secure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o700)  # no effect on Windows
    except OSError:
        pass


_secure_dir(DATA_DIR)


def valid_id(analysis_id: str) -> bool:
    return bool(isinstance(analysis_id, str) and ID_RE.match(analysis_id))


# --- key management ------------------------------------------------------------

def key_file_path() -> Path:
    # Keep the existing key location across the brand rename; a new key would strand encrypted reports.
    return Path(os.environ.get("DATA_KEY_FILE") or Path.home() / ".alexendra" / "data.key")


def _has_encrypted_reports() -> bool:
    return any(p.read_bytes()[:len(MAGIC)] == MAGIC for p in DATA_DIR.glob("*.json") if valid_id(p.stem))


def _key() -> bytes:
    env = os.environ.get("DATA_ENCRYPTION_KEY", "").strip()
    if env:
        return env.encode()
    keyfile = key_file_path()
    if keyfile.exists():
        return keyfile.read_bytes().strip()
    if _has_encrypted_reports():
        raise RuntimeError(
            f"Encrypted reports exist in {DATA_DIR} but no encryption key was found (DATA_ENCRYPTION_KEY unset, "
            f"{keyfile} missing). Refusing to generate a new key: it would make every encrypted report unreadable. "
            "Restore the original key.")
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    restrict_to_current_user(keyfile.parent)
    key = Fernet.generate_key()
    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # O_EXCL: never overwrite an existing key
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    restrict_to_current_user(keyfile)
    log.warning("Generated a data-encryption key file at %s. Back it up separately; set DATA_ENCRYPTION_KEY for production.", keyfile)
    return key


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _key()
        try:
            _fernet = Fernet(key)
        except (ValueError, TypeError):
            # Never include the key (or any part of it) in the message.
            raise RuntimeError("The data encryption key is not a valid Fernet key (corrupted or truncated). "
                               "Restore the original key; no report was modified.") from None
    return _fernet


def startup_check() -> dict:
    """Run at application start. Fails fast (the app does not start) if the key is missing, corrupted, or does not
    decrypt the reports that exist, instead of failing later on a user's request. Returns non-secret facts."""
    _cipher()  # raises RuntimeError for a missing / corrupted key; refuses to generate a key if reports are encrypted
    enc = [p for p in sorted(DATA_DIR.glob("*.json")) if valid_id(p.stem) and p.read_bytes().startswith(MAGIC)]
    for p in enc[:3]:  # a sample is enough to detect a wrong key
        try:
            _decode(p.read_bytes())
        except HTTPException:
            raise RuntimeError("The encryption key does not decrypt the stored reports. Refusing to start: restore the "
                               "original key (see docs/KEY_RECOVERY.md).") from None
    return {"encrypted_reports": len(enc), "key_source": "env" if os.environ.get("DATA_ENCRYPTION_KEY") else "file"}


def reset_cipher() -> None:
    """Forget the cached key (tests / key rotation)."""
    global _fernet
    _fernet = None


# --- storage -------------------------------------------------------------------

def path(analysis_id: str) -> Path:
    """Filesystem path for an id. Only hex ids are accepted, so no separators or '..' can ever reach the path."""
    if not valid_id(analysis_id):
        raise HTTPException(404, "Analysis not found")  # same response as a missing report: no enumeration signal
    p = (DATA_DIR / f"{analysis_id}.json").resolve()
    if p.parent != DATA_DIR.resolve():
        raise HTTPException(404, "Analysis not found")
    return p


def _decode(raw: bytes) -> dict:
    if raw.startswith(MAGIC):
        try:
            raw = _cipher().decrypt(raw[len(MAGIC):])
        except InvalidToken:
            raise HTTPException(500, "Stored report cannot be decrypted (wrong or missing encryption key).")
    return json.loads(raw.decode("utf-8"))


def _retry(fn, attempts: int = 40, delay: float = 0.02):
    """Windows briefly refuses to read or replace a file another thread is replacing (PermissionError / sharing violation).
    Retry for ~1 s instead of failing the request (measured: 5 of 50 concurrent consent requests returned HTTP 500)."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def lock(analysis_id: str):
    """Serialise read-modify-write updates of ONE report within this process (prevents lost updates between threads).
    NOT a cross-process lock: with several worker processes two updates of the same report can still race."""
    with _locks_guard:
        lk = _locks.setdefault(analysis_id, threading.Lock())
    with lk:
        yield


def load(analysis_id: str) -> dict:
    p = path(analysis_id)
    if not p.exists():
        raise HTTPException(404, "Analysis not found")
    try:
        return _decode(_retry(p.read_bytes))
    except FileNotFoundError:  # deleted between the exists() check and the read
        raise HTTPException(404, "Analysis not found")


def save(result: dict) -> None:
    p = path(result["id"])
    blob = MAGIC + _cipher().encrypt(json.dumps(result).encode("utf-8"))
    # Atomic write: a crash mid-write can never leave a truncated report behind.
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        _retry(lambda: os.replace(tmp, p))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def delete(analysis_id: str) -> bool:
    """Remove a report and everything embedded in it (photos, previews, try-ons are all inside the file)."""
    p = path(analysis_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def load_all() -> list[dict]:
    out = []
    for p in DATA_DIR.glob("*.json"):
        if not valid_id(p.stem):
            continue
        try:
            out.append(_decode(p.read_bytes()))
        except (OSError, json.JSONDecodeError, HTTPException):
            continue
    return sorted(out, key=lambda r: r.get("created_at", 0), reverse=True)


def purge_expired(retention_days: int, now: float | None = None) -> list[str]:
    """Delete reports with NO owner account that are older than `retention_days` (0 disables).
    Reports saved to an account are kept until the owner deletes them."""
    if retention_days <= 0:
        return []
    cutoff = (now or time.time()) - retention_days * 86400
    removed = []
    for r in load_all():
        if not r.get("_owner") and r.get("created_at", 0) < cutoff and delete(r["id"]):
            removed.append(r["id"])
    return removed


# --- migration of legacy plaintext reports ---------------------------------------

def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_backup(backup_dir: Path) -> dict:
    """A backup is accepted only if EVERY current report file exists in it, byte-identical (SHA-256)."""
    problems = []
    src = sorted(p for p in DATA_DIR.glob("*.json") if valid_id(p.stem))
    for p in src:
        q = backup_dir / p.name
        if not q.exists():
            problems.append(f"{p.name}: missing from backup")
        elif _sha256(q) != _sha256(p):
            problems.append(f"{p.name}: backup differs from source")
    return {"source_files": len(src), "problems": problems, "ok": not problems}


def migrate(dry_run: bool = False) -> dict:
    """Encrypt every plaintext report, VERIFYING each one. A single bad file never stops the run and is never skipped
    silently: every file gets a status. A plaintext file is replaced only after the encrypted bytes were decrypted and
    compared with the original document, and the file actually written was read back and compared again; after the
    replace it is verified once more. Idempotent: already-encrypted files are only verified, never rewritten."""
    results = []
    for p in sorted(DATA_DIR.glob("*.json")):
        rid = p.stem
        if not valid_id(rid):
            results.append({"id": rid, "status": "failed", "detail": "file name is not a valid report id; left untouched"})
            continue
        try:
            raw = p.read_bytes()
            if raw.startswith(MAGIC):
                doc = _decode(raw)
                ok = doc.get("id") == rid
                results.append({"id": rid, "status": "already_encrypted_verified" if ok else "failed",
                                **({} if ok else {"detail": "embedded id does not match file name"})})
                continue
            doc = json.loads(raw.decode("utf-8"))
            if doc.get("id") != rid:
                results.append({"id": rid, "status": "failed", "detail": "embedded id does not match file name; left untouched"})
                continue
            blob = MAGIC + _cipher().encrypt(json.dumps(doc).encode("utf-8"))
            if _decode(blob) != doc:
                results.append({"id": rid, "status": "failed", "detail": "encrypt/decrypt round trip differs; left untouched"})
                continue
            if dry_run:
                results.append({"id": rid, "status": "would_encrypt"})
                continue
            fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".tmp-", suffix=".part")
            replaced = False
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(blob)
                if _decode(Path(tmp).read_bytes()) != doc:  # verify what actually hit the disk BEFORE replacing
                    results.append({"id": rid, "status": "failed", "detail": "written file failed verification; left untouched"})
                    continue
                os.replace(tmp, p)
                replaced = True
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            if replaced:
                if _decode(p.read_bytes()) != doc:  # and once more after the replace
                    results.append({"id": rid, "status": "failed", "detail": "post-replace verification failed - restore from backup"})
                else:
                    results.append({"id": rid, "status": "encrypted"})
        except Exception as e:  # noqa: BLE001 - one bad file must not stop or hide the others
            results.append({"id": rid, "status": "failed", "detail": f"{type(e).__name__}: {e}"})
    counts: dict = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    plaintext_left = sum(1 for p in DATA_DIR.glob("*.json") if not p.read_bytes().startswith(MAGIC))
    return {"total": len(results), "counts": counts, "failed": [r for r in results if r["status"] == "failed"],
            "plaintext_remaining": plaintext_left, "results": results}


def migrate_plaintext() -> int:
    """Library helper kept for compatibility: number of files newly encrypted (verified)."""
    return migrate()["counts"].get("encrypted", 0)


def _cli(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m app.store")
    ap.add_argument("--migrate", action="store_true", help="encrypt legacy plaintext reports (verified, idempotent)")
    ap.add_argument("--backup-dir", help="REQUIRED with --migrate: a directory holding a byte-identical copy of the reports")
    ap.add_argument("--dry-run", action="store_true", help="verify what would be encrypted without writing anything")
    ap.add_argument("--status-file", help="write per-report status (ids and results only, no content) to this JSON file")
    args = ap.parse_args(argv)
    if not args.migrate:
        ap.print_help()
        return 0
    try:  # use the SAME settings (and therefore the same key) as the application
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass
    reset_cipher()
    # The backup gate only matters while plaintext reports remain. With none left, a re-run only VERIFIES the
    # encrypted files and changes nothing, so it needs no backup.
    pending = any(not p.read_bytes().startswith(MAGIC) for p in DATA_DIR.glob("*.json"))
    if not args.dry_run and pending:
        if not args.backup_dir:
            print("REFUSING: --backup-dir is required. Make a backup first so a failed migration can be undone.")
            return 2
        v = verify_backup(Path(args.backup_dir))
        print(f"backup check: {v['source_files']} source file(s), problems: {len(v['problems'])}")
        if not v["ok"]:
            print("REFUSING: backup is not a byte-identical copy:\n  " + "\n  ".join(v["problems"][:10]))
            return 2
    summary = migrate(dry_run=args.dry_run)
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    if args.status_file:
        Path(args.status_file).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
