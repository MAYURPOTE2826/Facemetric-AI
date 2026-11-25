"""Global protection for the paid external try-on model. Independent of IP addresses and of any one report.

Per-IP limits and the per-report quota do not stop an attacker who rotates IP addresses and creates many reports from
making the server pay for generations without end. This guard is GLOBAL:

  * DAILY CAP  - at most TRYON_DAILY_CAP external generations in any rolling 24 hours (default 100). A COUNT, because
                 Alexandra has no verified provider pricing; convert it to money yourself with the provider's price.
  * BREAKER    - after TRYON_BREAKER_FAILS (default 5) consecutive provider FAILURES, external calls pause for
                 TRYON_BREAKER_PAUSE seconds (default 600). Quality rejections (identity / skin-colour checks) are not
                 provider failures and do not trip it.

State is stored in SQLite in the data directory, so it survives restarts and is shared by all worker processes on this
machine. It is NOT shared between machines. Every attempt is counted when it is RESERVED (before the provider is called),
so a crash mid-call cannot hide spend.
"""
from __future__ import annotations

import os
import sqlite3
import time

from fastapi import HTTPException

from . import store

DAILY_CAP = int(os.environ.get("TRYON_DAILY_CAP", "100"))
BREAKER_FAILS = int(os.environ.get("TRYON_BREAKER_FAILS", "5"))
BREAKER_PAUSE = int(os.environ.get("TRYON_BREAKER_PAUSE", "600"))


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(store.DATA_DIR / ".ratelimit.sqlite3", timeout=10, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    # outcome: NULL = reserved/in flight, 1 = success, 0 = provider failure, 2 = quality rejection (provider was paid)
    c.execute("CREATE TABLE IF NOT EXISTS tryon_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, outcome INTEGER)")
    return c


def reset() -> None:
    c = _db()
    try:
        c.execute("DELETE FROM tryon_calls")
    finally:
        c.close()


def usage(now: float | None = None) -> dict:
    t = now if now is not None else time.time()
    c = _db()
    try:
        used = c.execute("SELECT COUNT(*) FROM tryon_calls WHERE ts > ?", (t - 86400,)).fetchone()[0]
    finally:
        c.close()
    return {"used_24h": used, "daily_cap": DAILY_CAP, "breaker_fails": BREAKER_FAILS, "breaker_pause_s": BREAKER_PAUSE}


def reserve(now: float | None = None) -> int:
    """Atomically check the cap and the breaker and record one attempt. Raises 429 / 503; returns a ticket id."""
    t = now if now is not None else time.time()
    c = _db()
    try:
        c.execute("BEGIN IMMEDIATE")
        used = c.execute("SELECT COUNT(*) FROM tryon_calls WHERE ts > ?", (t - 86400,)).fetchone()[0]
        if used >= DAILY_CAP:
            c.execute("ROLLBACK")
            raise HTTPException(429, {"code": "tryon_capacity", "message": "Try-on is at capacity for today. Please try again tomorrow."})
        recent = c.execute("SELECT outcome, ts FROM tryon_calls WHERE outcome IS NOT NULL ORDER BY id DESC LIMIT ?", (BREAKER_FAILS,)).fetchall()
        if len(recent) == BREAKER_FAILS and all(o == 0 for o, _ in recent) and t - recent[0][1] < BREAKER_PAUSE:
            c.execute("ROLLBACK")
            raise HTTPException(503, {"code": "tryon_paused", "message": "Try-on is temporarily paused because the image service is failing. Please try again later."})
        cur = c.execute("INSERT INTO tryon_calls (ts, outcome) VALUES (?, NULL)", (t,))
        ticket = cur.lastrowid
        c.execute("COMMIT")
        return int(ticket)
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


def finish(ticket: int, outcome: str, now: float | None = None) -> None:
    """outcome: 'ok' | 'provider_failure' | 'rejected'."""
    code = {"ok": 1, "provider_failure": 0, "rejected": 2}[outcome]
    c = _db()
    try:
        c.execute("UPDATE tryon_calls SET outcome = ?, ts = ts WHERE id = ?", (code, ticket))
    finally:
        c.close()
