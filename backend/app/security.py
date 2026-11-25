"""Report access control and rate limiting.

Model
-----
A report is reachable only with a CREDENTIAL, never with its id alone:
  * the signed-in OWNER (Bearer session, see accounts.py), or
  * the per-report ACCESS TOKEN returned once by /api/analyze (sent as `X-Report-Token`).
Only the SHA-256 of the access token is stored (`_access_hash`), so a copy of the data files does not yield tokens.
Report ids are 128-bit random (secrets.token_hex(16)) so they cannot be enumerated, but they are an identifier,
not a secret: possessing an id grants nothing.

Every failure - malformed id, unknown id, wrong token, someone else's report - returns the same 404, so the API
does not reveal which ids exist. Repeated failures from one client are throttled.

Legacy reports (12-hex id, no `_access_hash`) are reachable only by their owner account or an admin.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time

from fastapi import Header, HTTPException, Request

from . import store

NOT_FOUND = "Analysis not found"


# --- identifiers and tokens ----------------------------------------------------

def new_report_id() -> str:
    return secrets.token_hex(16)  # 128 bits


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


ACCESS_TOKEN_DAYS = int(os.environ.get("ACCESS_TOKEN_DAYS", "90"))  # 0 = tokens never expire


def issue_access(result: dict) -> str:
    """Create the report's access token, store only its hash (and expiry), and return the token (shown once).
    Calling this again ROTATES the token: the previous one stops working immediately."""
    token = secrets.token_urlsafe(32)  # 256 bits
    result["_access_hash"] = token_hash(token)
    result["_access_expires"] = int(time.time()) + ACCESS_TOKEN_DAYS * 86400 if ACCESS_TOKEN_DAYS > 0 else None
    return token


def revoke_access(result: dict) -> None:
    """Invalidate every access token for this report (the owner's session still works)."""
    result["_access_hash"] = None
    result["_access_expires"] = None


def can_access(result: dict, user: dict | None, report_token: str | None) -> bool:
    if user and result.get("_owner") and hmac.compare_digest(str(result["_owner"]), str(user["id"])):
        return True
    stored = result.get("_access_hash")
    expires = result.get("_access_expires")  # absent on legacy reports = no expiry
    if stored and report_token and (not expires or expires > time.time()):
        return hmac.compare_digest(stored, token_hash(report_token.strip()))
    return False


# --- rate limiting (SQLite-backed sliding window) ---------------------------------------------------------------
# Counters live in <data dir>/.ratelimit.sqlite3, so they survive a restart and are SHARED by every worker process on
# the same machine (SQLite serialises the writers). They are NOT shared between machines: running several servers
# behind a load balancer would need a central store (Redis etc.), which this project does not have.

class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _db():
        c = sqlite3.connect(store.DATA_DIR / ".ratelimit.sqlite3", timeout=10, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("CREATE TABLE IF NOT EXISTS hits (key TEXT NOT NULL, ts REAL NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS hits_key_ts ON hits(key, ts)")
        return c

    def reset(self) -> None:
        with self._lock:
            c = self._db()
            try:
                c.execute("DELETE FROM hits")
            finally:
                c.close()

    def count(self, key: str, window: float) -> int:
        c = self._db()
        try:
            return c.execute("SELECT COUNT(*) FROM hits WHERE key = ? AND ts > ?", (key, time.time() - window)).fetchone()[0]
        finally:
            c.close()

    def hit(self, key: str, limit: int, window: float) -> None:
        """Record an event; raise 429 once `limit` events already happened in the last `window` seconds."""
        now = time.time()
        c = self._db()
        try:
            c.execute("BEGIN IMMEDIATE")  # take the write lock: the check and the insert are one atomic step
            c.execute("DELETE FROM hits WHERE key = ? AND ts <= ?", (key, now - window))
            if c.execute("SELECT COUNT(*) FROM hits WHERE key = ?", (key,)).fetchone()[0] >= limit:
                c.execute("ROLLBACK")
                raise HTTPException(429, "Too many requests. Please wait and try again.", headers={"Retry-After": str(int(window))})
            c.execute("INSERT INTO hits (key, ts) VALUES (?, ?)", (key, now))
            if int(now) % 97 == 0:  # occasional housekeeping of long-dead keys
                c.execute("DELETE FROM hits WHERE ts <= ?", (now - 2 * 86400,))
            c.execute("COMMIT")
        except HTTPException:
            raise
        except Exception:
            try:
                c.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            c.close()


limiter = RateLimiter()
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")


def client_ip(request: Request) -> str:
    # X-Forwarded-For is client-controlled unless a trusted proxy sets it, so it is ignored by default.
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, limit: int, window: float):
    """FastAPI dependency: at most `limit` calls per `window` seconds per client IP for this route group."""
    def dep(request: Request) -> None:
        limiter.hit(f"{name}:{client_ip(request)}", limit, window)
    dep.rate_limit = (name, limit, window)  # read by evals/endpoint_matrix.py
    return dep


DENIED_LIMIT, DENIED_WINDOW = 20, 600  # failed report lookups per client per 10 minutes


# --- the report-access dependency ---------------------------------------------

def report_access(
    analysis_id: str,
    request: Request,
    authorization: str | None = Header(None),
    x_report_token: str | None = Header(None),
) -> dict:
    """FastAPI dependency: the report for `analysis_id` if (and only if) the caller holds a credential for it."""
    from . import accounts  # local import: accounts imports this module

    ip = client_ip(request)
    limiter.hit(f"report:{ip}", 240, 60)  # generic request ceiling
    if limiter.count(f"denied:{ip}", DENIED_WINDOW) >= DENIED_LIMIT:
        raise HTTPException(429, "Too many requests. Please wait and try again.", headers={"Retry-After": "600"})

    result = None
    if store.valid_id(analysis_id):
        try:
            result = store.load(analysis_id)
        except HTTPException:
            result = None
    user = accounts.user_from_auth(authorization)
    if result is None or not can_access(result, user, x_report_token):
        # Record the failure ATOMICALLY against the limit: a separate check-then-record let concurrent requests overshoot
        # (measured: 23 failures allowed against a limit of 20 with 8 concurrent clients). hit() raises 429 once the limit is full.
        limiter.hit(f"denied:{ip}", DENIED_LIMIT, DENIED_WINDOW)
        raise HTTPException(404, NOT_FOUND)
    return result
