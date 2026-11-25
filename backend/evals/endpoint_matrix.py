"""Endpoint security matrix, generated from the running application's routes.

    python -m evals.endpoint_matrix            # print the matrix
    python -m evals.endpoint_matrix --write    # write docs/ENDPOINT_MATRIX.md

Introspected from the code: every route, its route-level and router-level dependencies, and the rate-limit parameters
attached to them. NOT introspectable (declared by hand below): authentication done inside a function body, what is
sensitive, and the consequence of abuse. tests/test_endpoint_matrix.py fails if a route exists that is not classified
here, so a new endpoint cannot silently ship without a security decision.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

LIMITER = "SQLite file in the data dir; survives restart; shared by processes on this machine; NOT shared between machines"

# "METHOD path": (authentication, sensitive operation, abuse consequence, why-unlimited-if-no-limiter)
MANUAL = {
    "GET /api/health": ("none", "no", "none (static response)", "reveals nothing; no state"),
    "POST /api/{provider}/webhook": ("provider signature (Stripe / Razorpay)", "unlocks a paid report", "forged calls fail signature verification; a flood only costs CPU", "unauthenticated by design (the provider calls it); body is signature-verified before any action"),
    "POST /api/analyze": ("none (anonymous allowed) or signed-in owner", "runs the full CV pipeline, stores encrypted photos", "CPU and disk consumption; storage of unwanted photos", ""),
    "POST /api/check": ("none", "CPU photo-quality check", "CPU consumption", ""),
    "POST /api/check-side": ("none", "CPU photo-quality check", "CPU consumption", ""),
    "POST /api/check-three-quarter": ("none", "CPU photo-quality check", "CPU consumption", ""),
    "POST /api/check-top": ("none", "CPU photo-quality check", "CPU consumption", ""),
    "GET /api/analyses/{analysis_id}": ("owner session OR report access token", "reads a report incl. photos", "id/token guessing (128/256-bit: infeasible); cut off after 20 failures / 10 min / IP", ""),
    "DELETE /api/analyses/{analysis_id}": ("owner session OR report access token", "permanently deletes a report", "data loss for a token holder; needs a credential", ""),
    "POST /api/analyses/{analysis_id}/checkout": ("owner session OR report access token", "starts a payment", "payment-provider API calls", ""),
    "POST /api/analyses/{analysis_id}/confirm": ("owner session OR report access token", "marks a report paid / generates the paid report (LLM call)", "LLM spend if a payment were spoofed; payment is verified server-side", ""),
    "POST /api/analyses/{analysis_id}/consent/tryon": ("owner session OR report access token", "records consent to send the photo to a third party", "none beyond writing a small record", ""),
    "DELETE /api/analyses/{analysis_id}/consent/tryon": ("owner session OR report access token", "withdraws consent", "none (it only removes access)", "withdrawal must never be blockable; the generic 240/min/IP report ceiling still applies"),
    "POST /api/analyses/{analysis_id}/token/rotate": ("owner session OR report access token", "replaces the access token (revokes the old)", "a leaked token holder can rotate and lock out the legitimate token holder (owner session still works)", ""),
    "DELETE /api/analyses/{analysis_id}/token": ("owner session only", "revokes every access token", "none (owner-only)", ""),
    "POST /api/analyses/{analysis_id}/tryon": ("owner session OR report token + current consent", "sends the photo to a PAID third-party model", "money; mitigated by: per-IP 20/h, per-report quota 6, GLOBAL daily cap + circuit breaker (spend_guard)", ""),
    "POST /api/auth/signup": ("none", "creates an account (PBKDF2 hash)", "CPU (600k-iteration hash), account spam", ""),
    "POST /api/auth/login": ("none", "authenticates", "password guessing; CPU", ""),
    "POST /api/auth/logout": ("signed-in session", "revokes that session", "none", "revokes only the caller's own session; protected by possession of the session token"),
    "GET /api/me": ("signed-in session", "returns the caller's own profile", "none", "needs a valid session; returns only the caller's data"),
    "GET /api/me/progress": ("signed-in session", "lists the caller's own reports", "none", "needs a valid session; returns only the caller's data"),
    "POST /api/me/checkin": ("signed-in session + ownership of the report", "writes feedback to the caller's own report", "small writes", "needs a valid session and ownership"),
    "POST /api/me/progress/clear": ("signed-in session; only reports the account owns", "PERMANENTLY deletes every report (photos included) in the caller's own account", "5 per hour per client", "needs a valid session; body must contain confirm=DELETE"),
    "POST /api/me/analyses/{analysis_id}/claim": ("signed-in session AND report access token (or already owner)", "moves an unowned report into an account", "report theft if a token leaks", ""),
    "GET /api/admin/analyses": ("admin token (header)", "lists every report", "bulk data exposure if the admin token leaks", ""),
    "GET /api/admin/analyses/{analysis_id}": ("admin token (header)", "reads any report", "data exposure if the admin token leaks", ""),
    "PUT /api/admin/analyses/{analysis_id}/report": ("admin token (header)", "edits a report", "tampering if the admin token leaks", ""),
    "POST /api/admin/analyses/{analysis_id}/approve": ("admin token (header)", "approves a report", "tampering if the admin token leaks", ""),
    "POST /api/admin/analyses/{analysis_id}/regenerate": ("admin token (header)", "regenerates a report (LLM call)", "LLM spend if the admin token leaks", ""),
}


def _walk(routes, extra_deps=()):
    for r in routes:
        if hasattr(r, "dependant") and hasattr(r, "path"):
            yield r, list(extra_deps)
        else:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from _walk(inner.routes, [d.dependency for d in getattr(inner, "dependencies", [])])


def collect() -> list[dict]:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import main
    rows = []
    for route, router_deps in _walk(main.app.routes):
        calls = [d.call for d in route.dependant.dependencies] + router_deps
        limits = [c.rate_limit for c in calls if hasattr(c, "rate_limit")]
        names = [getattr(c, "__name__", "?") for c in calls]
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": method, "path": route.path, "key": f"{method} {route.path}", "limits": limits,
                         "report_access": "report_access" in names, "admin": "require_admin" in names})
    return sorted(rows, key=lambda r: (r["path"], r["method"]))


def _limit_text(row: dict) -> tuple[str, str]:
    parts = [f"{n.replace('{analysis_id}', 'delete')}: {lim} / {int(w)}s / IP" for n, lim, w in row["limits"]]
    if row["report_access"]:
        parts.append("report ceiling: 240 / 60s / IP; failed lookups: 20 / 600s / IP")
    if row["admin"]:
        parts.append("failed admin token: 10 / 600s / IP, then 429 even for the right token")
    if "tryon" in row["path"] and row["method"] == "POST":
        parts.append("GLOBAL: daily cap + circuit breaker (spend_guard)")
    return ("; ".join(parts) if parts else "none", "yes (per machine)" if parts else "n/a")


def render() -> str:
    rows = collect()
    out = ["# Endpoint security matrix", "",
           "Generated by `python -m evals.endpoint_matrix --write` from the application's real routes. Limits are read from the "
           "code; authentication details, sensitivity and abuse consequences are declared in `evals/endpoint_matrix.py` and a test "
           "fails if a route is not classified.", "",
           f"**Limiter storage:** {LIMITER}. **Distributed across machines: NO.** Survives process restart: yes. "
           "Counted per client IP (`X-Forwarded-For` ignored unless `TRUST_PROXY=1`).", "",
           "| Endpoint | Authentication | Sensitive operation | Limiter (scope: per IP unless stated) | Survives restart / shared on this machine | Abuse consequence | If unlimited, why |",
           "|---|---|---|---|---|---|---|"]
    for r in rows:
        authn, sens, abuse, why = MANUAL.get(r["key"], ("UNCLASSIFIED", "", "", ""))
        lim, shared = _limit_text(r)
        out.append(f"| `{r['method']} {r['path']}` | {authn} | {sens} | {lim} | {shared} | {abuse} | {why if lim == 'none' or not r['limits'] else ''} |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    text = render()
    if a.write:
        p = Path(__file__).resolve().parents[2] / "docs" / "ENDPOINT_MATRIX.md"
        p.write_text(text, encoding="utf-8")
        print("wrote", p)
    else:
        print(text)
