"""Accounts (email + password) and progress tracking.

Users live in data/users/<uid>.json with a small email index. Passwords are hashed with
PBKDF2-SHA256; session tokens are random and stored only as SHA-256 hashes. Analyses get
an `_owner` field and the user keeps an ordered list of their analysis ids.
Phone OTP login (MSG91 / Twilio) can be added later on the same token model.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from fastapi import APIRouter, Body, Depends, Header, HTTPException

from . import hairline, security, store

USERS_DIR = store.DATA_DIR / "users"
USERS_DIR.mkdir(exist_ok=True)
INDEX = USERS_DIR / "_index.json"
SESSION_DAYS = 60
CHECKIN_DAYS = (42, 56)  # routine check-in window: 6-8 weeks after the latest analysis
_lock = threading.Lock()

router = APIRouter(prefix="/api")


# --- storage -------------------------------------------------------------------

def _index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def _load(uid: str) -> dict:
    return json.loads((USERS_DIR / f"{uid}.json").read_text(encoding="utf-8"))


def _save(user: dict) -> None:
    (USERS_DIR / f"{user['id']}.json").write_text(json.dumps(user), encoding="utf-8")


LEGACY_ITERS = 200_000   # what existing accounts were created with
PBKDF2_ITERS = 600_000   # OWASP password-storage guidance for PBKDF2-HMAC-SHA256; applied to new/upgraded accounts
_DUMMY_SALT = bytes(16)


def _hash_pw(password: str, salt: bytes, iters: int = LEGACY_ITERS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters).hex()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    user["sessions"] = [s for s in user.get("sessions", []) if s["expires"] > now][-9:]
    user["sessions"].append({"hash": _token_hash(token), "expires": now + SESSION_DAYS * 86400})
    _save(user)
    return token


def user_from_auth(authorization: str | None) -> dict | None:
    """The signed-in user for an `Authorization: Bearer <token>` header, or None."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    uid = token_uid = None
    if "." in token:
        token_uid, token = token.split(".", 1)
    if not token_uid or not token_uid.isalnum() or not (USERS_DIR / f"{token_uid}.json").exists():
        return None
    user = _load(token_uid)
    h = _token_hash(token)
    now = int(time.time())
    if any(hmac.compare_digest(s["hash"], h) and s["expires"] > now for s in user.get("sessions", [])):
        uid = user["id"]
    return user if uid else None


def require_user(authorization: str | None) -> dict:
    user = user_from_auth(authorization)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


def detach(user_id: str, analysis_id: str) -> None:
    """Remove a deleted report from its owner's list."""
    with _lock:
        try:
            u = _load(user_id)
        except OSError:
            return
        u["analyses"] = [x for x in u.get("analyses", []) if x != analysis_id]
        _save(u)


def attach(user: dict, analysis: dict) -> None:
    """Record that `user` owns `analysis` (both saved by the caller / here)."""
    analysis["_owner"] = user["id"]
    with _lock:
        fresh = _load(user["id"])
        if analysis["id"] not in fresh["analyses"]:
            fresh["analyses"].append(analysis["id"])
        _save(fresh)


def _public_user(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "name": user.get("name", ""), "created_at": user["created_at"]}


def _session_response(user: dict) -> dict:
    return {"token": f"{user['id']}.{_new_session(user)}", "user": _public_user(user)}


# --- endpoints -----------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/auth/signup", dependencies=[Depends(security.rate_limit("signup", 10, 3600))])
def signup(email: str = Body(...), password: str = Body(...), name: str = Body("")):
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    with _lock:
        idx = _index()
        if email in idx and (USERS_DIR / f"{idx[email]}.json").exists():
            raise HTTPException(409, "An account with this email already exists. Sign in instead.")
        salt = secrets.token_bytes(16)
        user = {"id": secrets.token_hex(8), "email": email, "name": name.strip()[:60], "created_at": int(time.time()),
                "salt": salt.hex(), "iters": PBKDF2_ITERS, "pw": _hash_pw(password, salt, PBKDF2_ITERS),
                "analyses": [], "sessions": []}
        idx[email] = user["id"]
        INDEX.write_text(json.dumps(idx), encoding="utf-8")
        return _session_response(user)


@router.post("/auth/login", dependencies=[Depends(security.rate_limit("login", 10, 300))])
def login(email: str = Body(...), password: str = Body(...)):
    uid = _index().get(email.strip().lower())
    if not uid:
        _hash_pw(password, _DUMMY_SALT, PBKDF2_ITERS)  # same work as a real check: response time doesn't reveal whether the email exists
        raise HTTPException(401, "Wrong email or password.")
    try:
        user = _load(uid)
    except (OSError, ValueError):  # index entry whose user file is missing/corrupt: behave exactly like an unknown email
        _hash_pw(password, _DUMMY_SALT, PBKDF2_ITERS)
        raise HTTPException(401, "Wrong email or password.")
    iters = user.get("iters", LEGACY_ITERS)
    if hmac.compare_digest(user["pw"], _hash_pw(password, bytes.fromhex(user["salt"]), iters)):
        with _lock:
            fresh = _load(uid)
            if fresh.get("iters", LEGACY_ITERS) < PBKDF2_ITERS:  # upgrade an old hash now that we hold the password
                fresh["pw"] = _hash_pw(password, bytes.fromhex(fresh["salt"]), PBKDF2_ITERS)
                fresh["iters"] = PBKDF2_ITERS
                _save(fresh)
            return _session_response(_load(uid))
    raise HTTPException(401, "Wrong email or password.")


@router.post("/auth/logout")
def logout(authorization: str | None = Header(None)):
    user = user_from_auth(authorization)
    if user:
        h = _token_hash(authorization[7:].strip().split(".", 1)[1])
        with _lock:
            fresh = _load(user["id"])
            fresh["sessions"] = [s for s in fresh.get("sessions", []) if s["hash"] != h]
            _save(fresh)
    return {"ok": True}


@router.get("/me")
def me(authorization: str | None = Header(None)):
    return {"user": _public_user(require_user(authorization))}


@router.post("/me/analyses/{analysis_id}/claim", dependencies=[Depends(security.rate_limit("claim", 30, 600))])
def claim(analysis_id: str, authorization: str | None = Header(None),
          result: dict = Depends(security.report_access)):
    """Save an analysis made while signed out to this account. The caller must already hold a credential for it
    (its access token, or be its owner) - knowing the id is not enough - and nobody else may own it."""
    user = require_user(authorization)
    with store.lock(analysis_id):  # reload inside the lock: two concurrent claims must not both win
        fresh = store.load(analysis_id)
        if fresh.get("_owner") not in (None, user["id"]):
            raise HTTPException(403, "This report belongs to another account.")
        attach(user, fresh)
        store.save(fresh)
    return {"ok": True}


def _snapshot(r: dict) -> dict:
    skin = r.get("skin") or {}
    hair = r.get("hair") or {}
    crown = hair.get("crown") or {}
    light = (r.get("quality") or {}).get("lighting") or {}
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "paid": bool(r.get("paid")),
        "harmony_score": r.get("harmony_score"),
        "skin_score": skin.get("score") if skin.get("available") else None,
        "hair_score": hair.get("score"),
        "hairline_cm": (hair.get("hairline") or {}).get("height_cm"),
        "acne_grade": (skin.get("grades") or {}).get("acne"),
        "concerns": {c["key"]: {"label": c["label"], "score": c["score"]} for c in skin.get("concerns", [])},
        "tone_spread": (skin.get("tone") or {}).get("spread"),
        "face_shape": (r.get("style") or {}).get("label"),
        "photo": r.get("_photo_thumb", ""),
        "aligned": r.get("_aligned", ""),
        "scalp_pct": crown.get("scalp_pct"),
        "parting_mm": (crown.get("parting") or {}).get("width_mm"),
        "skin_L": light.get("skin_L"),
        "cast": (r.get("quality") or {}).get("colour_cast"),
        "_hair_engine": {k: v for k, v in ((hair.get("analysis") or {}).items()) if k != "image"} or None,
    }


# Smallest change we treat as real for each photo measurement (its typical repeat error).
NOISE = {"hairline_cm": (0.5, "cm", "Hairline height"), "parting_mm": (1.5, "mm", "Parting width"),
         "scalp_pct": (4.0, "%", "Scalp showing on top")}


def _hair_changes(first: dict, last: dict) -> list[dict]:
    """Hair measurements that are in both check-ins, each marked real or within measurement error."""
    out = []
    for key, (noise, unit, label) in NOISE.items():
        a, b = first.get(key), last.get(key)
        if a is None or b is None:
            continue
        d = round(b - a, 1)
        if key == "parting_mm":
            noise = max(noise, 0.25 * a)
        worse = d > 0  # a higher hairline, wider parting or more scalp is worse
        out.append({"key": key, "label": label, "from": a, "to": b, "change": d, "unit": unit,
                    "real": abs(d) >= noise, "better": None if abs(d) < noise else not worse})
    return out


def _comparability(first: dict, last: dict) -> list[str]:
    notes = []
    if first.get("skin_L") is not None and last.get("skin_L") is not None and abs(first["skin_L"] - last["skin_L"]) > 8:
        notes.append("The light was quite different between these photos (one is brighter), so skin colour and tan "
                     "changes may be the lighting, not your skin.")
    fc, lc = first.get("cast") or {}, last.get("cast") or {}
    if fc and lc and max(abs(fc[k] - lc[k]) for k in ("b", "g", "r")) > 0.08:
        notes.append("The colour of the light differs between these photos (e.g. daylight vs a bulb).")
    return notes


@router.get("/me/progress")
def progress(authorization: str | None = Header(None)):
    """Every check-in for this user, oldest first, plus the change from the first to the latest."""
    user = require_user(authorization)
    snaps = []
    for aid in user["analyses"]:
        try:
            snaps.append(_snapshot(store.load(aid)))
        except HTTPException:
            continue
    snaps.sort(key=lambda s: s["created_at"])
    changes = None
    if len(snaps) >= 2:
        first, last = snaps[0], snaps[-1]

        def delta(a, b):
            return round(b - a, 1) if a is not None and b is not None else None

        changes = {
            "days": round((last["created_at"] - first["created_at"]) / 86400),
            "skin_score": delta(first["skin_score"], last["skin_score"]),
            "hair_score": delta(first["hair_score"], last["hair_score"]),
            "hairline_cm": delta(first["hairline_cm"], last["hairline_cm"]),
            "harmony_score": delta(first["harmony_score"], last["harmony_score"]),
            "hair": _hair_changes(first, last),
            "hair_visible": hairline.compare(first.get("_hair_engine"), last.get("_hair_engine")),
            "comparability": _comparability(first, last),
            "concerns": sorted(
                [{"key": k, "label": v["label"], "from": first["concerns"][k]["score"], "to": v["score"],
                  "change": delta(first["concerns"][k]["score"], v["score"])}
                 for k, v in last["concerns"].items() if k in first["concerns"]],
                key=lambda c: -(c["change"] or 0)),
        }
    for sn in snaps:
        sn.pop("_hair_engine", None)  # used only for the comparison above; keep the payload small
    return {"user": _public_user(user), "checkins": snaps, "changes": changes, "routine_checkin": _checkin_status(user, snaps)}


def _checkin_status(user: dict, snaps: list[dict]) -> dict | None:
    """Is the 6-8 week routine check-in due for the latest analysis?"""
    if not snaps:
        return None
    latest = snaps[-1]
    days = (int(time.time()) - latest["created_at"]) // 86400
    done = [f for f in user.get("feedback", []) if f["analysis_id"] == latest["id"]]
    return {"analysis_id": latest["id"], "days_since": days, "due_in_days": max(0, CHECKIN_DAYS[0] - days),
            "due": days >= CHECKIN_DAYS[0] and not done, "overdue": days > CHECKIN_DAYS[1] and not done,
            "due_at": latest["created_at"] + CHECKIN_DAYS[0] * 86400, "last": done[-1] if done else None}


@router.post("/me/checkin")
def routine_checkin(body: dict = Body(...), authorization: str | None = Header(None)):
    """6-8 week routine check-in: did anything irritate, is it working, are you using it?
    The answers are stored on the report and its routine is rebuilt from them."""
    user = require_user(authorization)
    aid = str(body.get("analysis_id", ""))
    if aid not in user["analyses"]:
        raise HTTPException(404, "Report not found in your account.")
    fb = {
        "at": int(time.time()),
        "analysis_id": aid,
        "irritation": bool(body.get("irritation")),
        "irritating": [str(k)[:30] for k in (body.get("irritating") or [])][:10],
        "progress": body.get("progress") if body.get("progress") in ("better", "same", "worse") else None,
        "consistency": body.get("consistency") if body.get("consistency") in ("daily", "sometimes", "stopped") else None,
        "note": str(body.get("note") or "")[:500],
    }
    result = store.load(aid)
    result["routine_feedback"] = fb
    store.save(result)
    with _lock:
        fresh = _load(user["id"])
        fresh.setdefault("feedback", []).append(fb)
        _save(fresh)
    return {"ok": True, "feedback": fb}


@router.post("/me/progress/clear", dependencies=[Depends(security.rate_limit("clear-progress", 5, 3600))])
def clear_progress(body: dict = Body(...), authorization: str | None = Header(None)):
    """Permanently delete EVERY report in this account (photos, previews, try-ons are inside each report) and the
    routine check-in answers. Irreversible. Requires {"confirm": "DELETE"}. Only this user's own reports are touched."""
    user = require_user(authorization)
    if body.get("confirm") != "DELETE":
        raise HTTPException(400, 'Send {"confirm": "DELETE"} to confirm.')
    deleted = 0
    for aid in list(user.get("analyses", [])):
        try:
            if store.valid_id(aid) and store.load(aid).get("_owner") == user["id"]:
                with store.lock(aid):
                    deleted += 1 if store.delete(aid) else 0
        except HTTPException:
            store.delete(aid) if store.valid_id(aid) else None  # unreadable file that this account lists: remove it
    with _lock:
        fresh = _load(user["id"])
        fresh["analyses"] = []
        fresh["feedback"] = []
        _save(fresh)
    return {"cleared": True, "reports_deleted": deleted}
