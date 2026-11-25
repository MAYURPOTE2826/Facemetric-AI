"""Isolated backend for the browser tests. NOT production code: it exists only to run the real application against a
temporary encrypted data directory with a counting stub in place of the paid image provider.

  * DATA_DIR is a fresh temp folder, the encryption key is random and lives only in this process's environment:
    your real reports and key are never read or written.
  * Every credential in backend/.env (Anthropic, Stripe, Razorpay, admin, image providers) is overridden with an empty
    value BEFORE the app loads, so a browser test can never spend money or call a real provider.
  * tryon.generate is replaced by a stub that refuses to run without the consent flag (like the real one), counts calls
    and returns a tiny image. The test-only /__test/* routes (seed, counters, existence check) exist only in this process.
"""
import base64
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
PORT = int(os.environ.get("PFI_BROWSER_API_PORT", "8100"))

tmp = Path(tempfile.mkdtemp(prefix="alex-browser-"))
from cryptography.fernet import Fernet  # noqa: E402

os.environ.update({
    "DATA_DIR": str(tmp / "data"),
    "DATA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "RETENTION_DAYS": "0",
    "FAL_KEY": "browser-test-stub-not-a-real-key",
    "TRYON_PROVIDER": "fal",
    "GEMINI_API_KEY": "",
    "CORS_ORIGINS": "http://127.0.0.1:3100,http://localhost:3100",
    # blank every credential that backend/.env might otherwise supply (load_dotenv never overrides an existing value)
    "ANTHROPIC_API_KEY": "", "STRIPE_SECRET_KEY": "", "STRIPE_WEBHOOK_SECRET": "", "RAZORPAY_KEY_ID": "",
    "RAZORPAY_KEY_SECRET": "", "RAZORPAY_WEBHOOK_SECRET": "", "ADMIN_TOKEN": "", "REVIEW_REQUIRED": "false",
})
os.environ.pop("DATA_KEY_FILE", None)
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Body  # noqa: E402

from app import accounts, main, recommendations, report, security, store, tryon  # noqa: E402

BASE = json.loads((BACKEND / "evals" / "base_analysis.json").read_text(encoding="utf-8"))
ok, buf = cv2.imencode(".jpg", np.full((16, 16, 3), 180, np.uint8))
TINY = base64.b64encode(buf.tobytes()).decode()
calls: list[dict] = []


def fake_generate(photo_b64, kind, style, *, consented=False):
    if not consented:
        raise tryon.ConsentRequired("stub: consent flag missing")
    calls.append({"kind": kind, "style": style, "at": time.time()})
    return {"image": TINY, "identity": 0.9, "provider": "fal", "kind": kind, "style": style}


tryon.generate = fake_generate
app = main.app


@app.post("/__test/seed")
def seed(owner_email: str | None = Body(None), paid: bool = Body(False), token_expired: bool = Body(False), hair: bool | str | None = Body(None)):
    analysis = copy.deepcopy(BASE)
    if hair:  # SYNTHETIC drawn heads run through the real engine (test fixtures only; they say nothing about real photographs)
        kind = "ok" if hair is True else str(hair)
        sys.path.insert(0, str(BACKEND / "tests"))
        import hair_fixtures as HF
        from app import hairline
        base_hair = {"available": True, "questionnaire": False, "hairline": None, "crown": None, "score": None, "plan": ["Gentle care."],
                     "causes": [], "tests": [], "myths": []}
        if kind == "legacy":  # an old report: no `analysis` key at all
            analysis["hair"] = base_hair
        elif kind == "engine_error":
            analysis["hair"] = base_hair | {"analysis": hairline._empty("Hairline engine error: RuntimeError")}
        else:
            _img, _cat, _pts = HF.scene(hairline=HF.mature(0.14), fringe=(kind == "hidden"))
            top = ({"scalp_pct": 6.0, "label": "Dense", "score": 92, "parting": None,
                    "regional": {"central_scalp_pct": 5.0, "outer_scalp_pct": 4.0, "hair_area_fraction": 0.5}} if kind == "front_top" else None)
            analysis["hair"] = base_hair | {"analysis": hairline.build(_img, _cat, _pts, top, None)}
    cands = recommendations.candidates(analysis["metrics"], analysis["skin"], analysis.get("profile"))
    result = {**analysis, "id": security.new_report_id(), "created_at": int(time.time()),
              "report": report.rule_report(analysis, cands), "report_source": "rules", "paid": paid, "_candidates": cands,
              "_photo": TINY}
    if paid:
        result["style"] = {"shape": "oval", "label": "Oval", "summary": "s", "hairstyles": ["Textured quiff"],
                           "beard": [], "glasses": [], "avoid": [], "notes": []}
    token = security.issue_access(result)
    if token_expired:  # simulate a token past its expiry
        result["_access_expires"] = int(time.time()) - 60
    if owner_email:
        uid = accounts._index()[owner_email.strip().lower()]
        accounts.attach(accounts._load(uid), result)
    store.save(result)
    return {"id": result["id"], "token": token, "headline": result["report"]["headline"]}


@app.get("/__test/exists/{rid}")
def exists(rid: str):
    return {"exists": store.valid_id(rid) and store.path(rid).exists(), "files": len(list(store.DATA_DIR.glob("*.json")))}


@app.get("/__test/raw/{rid}")
def raw(rid: str):
    """Is the on-disk file for this id encrypted (and not containing the marker text)?"""
    p = store.path(rid)
    b = p.read_bytes() if p.exists() else b""
    return {"exists": bool(b), "encrypted": b.startswith(store.MAGIC), "has_plain_profile": b'"profile"' in b}


@app.get("/__test/provider_calls")
def provider_calls():
    return {"count": len(calls), "calls": calls}


@app.post("/__test/reset")
def reset():
    calls.clear()
    security.limiter.reset()
    return {"ok": True}


if __name__ == "__main__":
    print(f"[browser-test backend] data dir {tmp / 'data'} (temporary); port {PORT}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
