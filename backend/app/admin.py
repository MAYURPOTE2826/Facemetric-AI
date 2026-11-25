"""Expert review dashboard API. Every route needs the X-Admin-Token header."""
from __future__ import annotations

import os
import secrets
import time

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from . import report, security, store

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
# When true, paid reports stay hidden from the customer until a specialist approves them.
REVIEW_REQUIRED = os.getenv("REVIEW_REQUIRED", "false").lower() in ("1", "true", "yes")


ADMIN_FAIL_LIMIT, ADMIN_FAIL_WINDOW = 10, 600


def require_admin(request: Request, x_admin_token: str = Header("")) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Admin is disabled. Set ADMIN_TOKEN in backend/.env.")
    ip = security.client_ip(request)
    if security.limiter.count(f"adminfail:{ip}", ADMIN_FAIL_WINDOW) >= ADMIN_FAIL_LIMIT:  # brute-force guard
        raise HTTPException(429, "Too many failed attempts. Try again later.", headers={"Retry-After": str(ADMIN_FAIL_WINDOW)})
    if not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        security.limiter.hit(f"adminfail:{ip}", ADMIN_FAIL_LIMIT, ADMIN_FAIL_WINDOW)  # record the failure atomically (429 once full)
        raise HTTPException(401, "Invalid admin token")


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _summary(r: dict) -> dict:
    p = r.get("profile", {})
    return {
        "id": r["id"],
        "created_at": r.get("created_at"),
        "name": p.get("name") or "",
        "age": p.get("age") or "",
        "sex": p.get("sex") or "",
        "goals": p.get("goals") or [],
        "paid": bool(r.get("paid")),
        "review_status": r.get("review_status") or ("not_required" if r.get("paid") else "unpaid"),
        "harmony_score": r.get("harmony_score"),
        "report_source": r.get("report_source"),
        "photos": ["front"] + [k for k, f in (("side", "profile_image"), ("¾", "three_quarter_image")) if r.get(f)],
    }


@router.get("/analyses")
def list_analyses(status: str = "all"):
    rows = [_summary(r) for r in store.load_all()]
    if status == "pending":
        rows = [r for r in rows if r["review_status"] == "pending"]
    elif status == "paid":
        rows = [r for r in rows if r["paid"]]
    elif status == "unpaid":
        rows = [r for r in rows if not r["paid"]]
    return {"items": rows, "review_required": REVIEW_REQUIRED}


@router.get("/analyses/{analysis_id}")
def get_full(analysis_id: str):
    r = store.load(analysis_id)
    data = {k: v for k, v in r.items() if not k.startswith("_")}
    data["candidates"] = r.get("_candidates", [])
    data["review_status"] = _summary(r)["review_status"]
    return data


@router.put("/analyses/{analysis_id}/report")
def save_report(analysis_id: str, body: dict = Body(...)):
    r = store.load(analysis_id)
    try:
        edited = report.Report.model_validate(body["report"]).model_dump()
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"Invalid report: {e}")
    r["report"] = edited
    r["report_source"] = "edited"
    r["reviewer_note"] = (body.get("reviewer_note") or "").strip()
    r["edited_at"] = int(time.time())
    store.save(r)
    return get_full(analysis_id)


@router.post("/analyses/{analysis_id}/approve")
def approve(analysis_id: str):
    r = store.load(analysis_id)
    if not r.get("paid"):
        raise HTTPException(409, "Only paid reports can be approved.")
    r["review_status"] = "approved"
    r["reviewed_at"] = int(time.time())
    store.save(r)
    return get_full(analysis_id)


@router.post("/analyses/{analysis_id}/regenerate")
async def regenerate(analysis_id: str):
    r = store.load(analysis_id)
    written, source = await run_in_threadpool(
        report.generate, r, r.get("profile", {}), r.get("_candidates", []), r.get("_photo", "")
    )
    r["report"] = written
    r["report_source"] = source
    store.save(r)
    return get_full(analysis_id)
