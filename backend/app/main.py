"""FaceLab API - upload a frontal photo, get measurements + a personalised report."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid

import cv2
import numpy as np
import stripe
from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from . import (  # noqa: E402
    accounts, consent, medical, personalization, report_validator, security, spend_guard, admin, anthropometry, climate, countdown, diagrams, eyes, geometry, hair, imaging, jawline, landmarks, liveness, metrics, payments, previews, products, profile,
    recommendations, remedies, report, skin, store, styling, tryon,
)
from . import three_quarter as three_quarter_mod  # noqa: E402
from .admin import REVIEW_REQUIRED  # noqa: E402

MAX_UPLOAD = 15 * 1024 * 1024
# Measurements that depend on the jawline or chin, which a beard hides (front, three-quarter and
# the pogonion/menton-based side-profile ones).
BEARD_HIDDEN = {"jaw_zygo", "thirds_lower_mid", "lower_third_split", "gonial_angle", "nasofacial", "nasomental",
                "convexity", "e_line_upper", "e_line_lower", "mentocervical", "cervicomental", "total_convexity",
                "mentolabial", "submental_length"}

app = FastAPI(title="FaceLab API")
# The browser reaches the API through the Next.js /api proxy (same origin), so cross-origin access is not
# needed by default. Set CORS_ORIGINS="https://a.com,https://b.com" if a separate origin must call it.
_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_methods=["*"], allow_headers=["*"])


def _decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not read the image. Upload a JPG or PNG.")
    scale = 2000 / max(img.shape[:2])
    if scale < 1:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def _detect(img: np.ndarray) -> landmarks.FaceDetection:
    face = landmarks.detect(img)
    if face is None:
        raise HTTPException(422, "No face detected. Use a clear, well-lit, front-facing photo.")
    return face


@app.get("/api/health")
def health():
    return {"ok": True}


def _camera(face: landmarks.FaceDetection, img: np.ndarray, data: bytes, source: str) -> dict | None:
    """Camera distance/focal estimate - only when the focal length is known (EXIF, or our
    own live camera); otherwise a telephoto portrait would be 'corrected' wrongly."""
    f35 = geometry.exif_f35(data)
    if f35 is None and source != "camera":
        return None
    return geometry.camera(face.points, img.shape, f35)


@app.post("/api/check", dependencies=[Depends(security.rate_limit("check", 120, 600))])
async def check(front: UploadFile = File(...), source: str = Form("upload")):
    """Fast photo-quality check, used by the upload step before full analysis."""
    data = await front.read()
    img = _decode(data)
    face = _detect(img)
    return imaging.check_quality(img, face, _camera(face, img, data, source), hair.segment(img))


@app.post("/api/check-side", dependencies=[Depends(security.rate_limit("check", 120, 600))])
async def check_side(side: UploadFile = File(...), sex: str = Form("unspecified")):
    """Quick check that a side-profile photo can be traced."""
    img = _decode(await side.read())
    try:
        result = profile.analyze(img, sex)
    except profile.ProfileError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "notes": result["notes"], "annotated_image": result["annotated_image"]}


@app.post("/api/check-three-quarter", dependencies=[Depends(security.rate_limit("check", 120, 600))])
async def check_three_quarter(three_quarter: UploadFile = File(...), sex: str = Form("unspecified")):
    """Quick check that a three-quarter photo gives a usable jaw angle."""
    img = _decode(await three_quarter.read())
    try:
        result = three_quarter_mod.analyze(img, sex)
    except three_quarter_mod.ThreeQuarterError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "notes": [], "annotated_image": result["annotated_image"]}


@app.post("/api/check-top", dependencies=[Depends(security.rate_limit("check", 120, 600))])
async def check_top(top: UploadFile = File(...)):
    """Quick check that a top-of-head photo shows enough hair to measure."""
    img = _decode(await top.read())
    try:
        result = hair.analyze_top(img)
    except hair.HairError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "notes": [], "annotated_image": result["image"]}


@app.post("/api/analyze", dependencies=[Depends(security.rate_limit("analyze", 20, 3600))])
async def analyze(
    front: UploadFile = File(...),
    side: UploadFile | None = File(None),
    three_quarter: UploadFile | None = File(None),
    top: UploadFile | None = File(None),
    profile_json: str = Form("{}", alias="profile"),
    source: str = Form("upload"),
    frames: str = Form(""),
    blinks: str = Form(""),
    authorization: str | None = Header(None),
):
    owner = accounts.user_from_auth(authorization)
    data = await front.read()
    side_data = await side.read() if side is not None else b""
    tq_data = await three_quarter.read() if three_quarter is not None else b""
    top_data = await top.read() if top is not None else b""
    if max(len(data), len(side_data), len(tq_data), len(top_data)) > MAX_UPLOAD:
        raise HTTPException(413, "Image too large (max 15 MB).")
    try:
        user = json.loads(profile_json)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid profile JSON.")
    sex = user.get("sex", "unspecified")

    img = _decode(data)
    face = _detect(img)
    try:
        report_validator.check_landmarks(face.points, img.shape)  # rule G: never analyse an invalid landmark set
    except report_validator.LandmarkError as e:
        raise HTTPException(422, {"message": str(e), "quality": None})
    seg = hair.segment(img)
    cam = _camera(face, img, data, source)
    quality = imaging.check_quality(img, face, cam, seg)
    if not quality["ok"]:
        raise HTTPException(422, {"message": "Photo did not pass quality checks.", "quality": quality})

    # Proportions are measured on perspective-corrected landmarks (close selfies widen the nose).
    # Live-camera frames (if any) are median-averaged with the photo to cut landmark jitter.
    n_frames = 1
    shape_points = face.points
    if frames:
        try:
            shape_points, n_frames = geometry.average_frames(face.points, json.loads(frames), img.shape)
        except (ValueError, TypeError):
            pass
    # Optional SPIGA jaw corners (off unless ENABLE_SPIGA=1 - weights need a licence review).
    jaw = jawline.refine(img, face.points)
    if jaw:
        shape_points = shape_points.copy()
        for i in jawline.GONION_IDX:
            shape_points[i, :2] += jaw[0][i, :2] - face.points[i, :2]
    if cam:
        shape_points = geometry.undistort(shape_points, img.shape, cam)
    analysis = metrics.compute(shape_points, sex=sex)
    analysis["camera"] = cam
    analysis["landmark_frames"] = n_frames
    analysis["jaw_model"] = jaw[1] if jaw else {"model": "mediapipe"}
    analysis["quality"] = quality
    analysis["liveness"] = {"checked": False, "passed": False, "reason": "uploaded photo"}
    if source == "camera" and blinks:
        try:
            analysis["liveness"] = liveness.check(json.loads(blinks))
        except ValueError:
            pass
    analysis["skin"] = skin.analyze(img, face, seg)
    if analysis["skin"].get("available"):
        skin.neck_with_answers(analysis["skin"], user)

    side_result = None
    if side_data:
        try:
            side_result = profile.analyze(_decode(side_data), sex)
        except profile.ProfileError as e:
            analysis["profile_error"] = str(e)
    if side_result:
        analysis["metrics"] += side_result["metrics"]
        analysis["profile_notes"] = side_result["notes"]
        analysis["profile_image"] = side_result["annotated_image"]
    if tq_data:
        try:
            tq = three_quarter_mod.analyze(_decode(tq_data), sex)
            analysis["metrics"] += tq["metrics"]
            analysis["three_quarter_image"] = tq["annotated_image"]
        except three_quarter_mod.ThreeQuarterError as e:
            analysis["three_quarter_error"] = str(e)
    analysis["anthropometry"] = anthropometry.table(shape_points, sex)
    if any(i["code"] == "beard" for i in quality["issues"]):
        analysis["withheld_metrics"] = [m["label"] for m in analysis["metrics"] if m["key"] in BEARD_HIDDEN]
        analysis["metrics"] = [m for m in analysis["metrics"] if m["key"] not in BEARD_HIDDEN]
        analysis["withheld_metrics"] += anthropometry.withhold(analysis["anthropometry"], anthropometry.BEARD_HIDDEN)
    blink = max(face.blendshapes.get("eyeBlinkLeft", 0), face.blendshapes.get("eyeBlinkRight", 0))
    analysis["eyes"] = eyes.analyze(img, shape_points, face.points, blink)
    report_validator.apply_quality_rules(analysis, quality, geometry.mm_per_px(face.points), cam)  # rules A-E: withhold/flag what the photo can't support
    report_validator.apply_mm_rules(analysis["anthropometry"], geometry.mm_per_px(face.points), cam, analysis["validation"])  # rule B
    analysis["validation"]["modules"]["eyes"] = "ok" if analysis.get("eyes") else "unavailable"
    analysis.update(metrics.rescore(analysis["metrics"]))
    analysis["previews"] = previews.generate(img, face, analysis["metrics"], analysis["skin"],
                                         glasses=any(i["code"] == "glasses" for i in quality["issues"]))
    analysis["preview_status"] = previews.status(analysis["metrics"], analysis["skin"], any(i["code"] == "glasses" for i in quality["issues"]),
                                                 {i["key"] for i in (analysis["previews"] or {}).get("items", [])}, analysis.get("validation"))
    try:
        analysis["hair"] = hair.analyze(img, face, user, _decode(top_data) if top_data else None, seg)
    except Exception as e:  # noqa: BLE001 - hair is an add-on; never fail the whole analysis
        analysis["hair"] = {"available": False, "hairline_note": f"Hair analysis failed: {e}"}
    report_validator.apply_hair_rules(analysis["hair"], analysis["validation"])  # rule F (and H status)
    # Report figures (mm overlay, fifths, thirds, mirror faces) on the original photo.
    k_raw = geometry.mm_per_px(face.points)
    hl = (analysis["hair"] or {}).get("hairline") or {}
    hairline_y = face.points[9, 1] - hl["height_cm"] * 10 / k_raw if hl.get("height_cm") else None
    mm = {r["key"]: r["value"] for r in analysis["anthropometry"]["rows"]}
    analysis["diagrams"] = diagrams.build(img, face.points, mm, k_raw, hairline_y)
    analysis["style"] = styling.advice(styling.face_shape(shape_points), user, analysis["metrics"], analysis["hair"])
    if analysis.get("withheld_metrics"):
        analysis["style"]["confidence"] = round(analysis["style"]["confidence"] * 0.8, 2)
        analysis["style"]["notes"].append("Your beard hides the jawline, so your face shape is judged mostly from the "
                                          "forehead, cheekbones and face length.")
    analysis["routine"] = products.build(analysis["skin"], user, climate.context(user.get("city")))
    analysis["remedies"] = remedies.for_concerns(analysis["skin"])

    candidates, rec_audit = recommendations.candidates_audited(analysis["metrics"], analysis["skin"], user)
    # The Claude-written report is only generated after payment (see _unlock), so free
    # previews cost nothing. The rule-based report backs the preview.
    result = {
        "id": security.new_report_id(),
        "created_at": int(time.time()),
        "profile": user,
        **analysis,
        "report": report.rule_report(analysis, candidates, user.get("goals")),
        "report_source": "rules",
        "annotated_image": imaging.annotate(img, face),
        "paid": False,
        "_candidates": candidates,
        "recommendation_audit": {"suppressed": rec_audit},
        "medical": medical.build(analysis["metrics"], analysis.get("skin"), candidates, analysis.get("validation"), user),
        "goal_alignment": personalization.alignment(user.get("goals"), analysis["metrics"], analysis.get("skin"), candidates, analysis.get("validation")),
        "_photo": imaging.face_crop_b64(img, face),
        "_photo_thumb": imaging.face_crop_b64(img, face, max_side=240),
        "_aligned": imaging.aligned_b64(img, face.points),
    }
    access_token = security.issue_access(result)
    if owner:
        accounts.attach(owner, result)
    store.save(result)
    # The access token is returned exactly once, here; only its hash is stored. The browser keeps it and sends
    # it as X-Report-Token (anonymous users); a signed-in owner is authorised by their session instead.
    return {**_public(result), "access_token": access_token}


def _preview(data: dict) -> dict:
    metrics_all = data["metrics"]
    best = max(metrics_all, key=lambda m: m["score"])
    worst = min(metrics_all, key=lambda m: m["score"])
    rep = data["report"]
    data["metrics"] = [best, worst] if best is not worst else [best]
    data["report"] = {
        "headline": rep["headline"],
        "overview": rep["overview"],
        "strengths": rep["strengths"][:3],
        "sections": [],
        "priority_plan": [],
        "disclaimer": rep["disclaimer"],
    }
    data["skin"] = {"available": False}
    data["locked"] = {
        "metrics": len(metrics_all),
        "sections": max(len(rep["sections"]), 4),
        "plan_steps": max(len(rep["priority_plan"]), 3),
        "feature_names": [s["feature"] for s in rep["sections"]][:6],
        "previews": len((data.get("previews") or {}).get("items", [])),
        "routine": bool(data.get("routine")),
        "remedies": len(data.get("remedies") or []),
    }
    data["remedies"] = (data.get("remedies") or [])[:2]  # teaser
    anth = data.get("anthropometry")
    if anth:
        data["locked"]["mm_rows"] = len(anth["rows"]) + len(anth["ratios"])
        data["anthropometry"] = {**anth, "rows": anth["rows"][:3], "ratios": []}
    ey = data.get("eyes")
    if ey:
        data["locked"]["eyes"] = len(ey["advice"]) + len(ey["findings"])
        data["eyes"] = {"findings": ey["findings"][:1], "advice": [], "note": ey["note"]}
    if data.get("diagrams"):
        data["locked"]["diagrams"] = len(data["diagrams"])
        data["diagrams"] = {"fifths": data["diagrams"].get("fifths")}  # one figure as a teaser
    if data.get("style"):
        st = data["style"]
        data["locked"]["style"] = len(st["hairstyles"]) + len(st["beard"]) + len(st["glasses"])
        data["style"] = {k: st[k] for k in ("shape", "label", "summary")} | {"hairstyles": st["hairstyles"][:1]}
    h = data.get("hair") or {}
    if h.get("available"):
        # Doctor flags stay visible for free - that's safety information.
        data["locked"]["hair"] = len(h.get("causes", [])) + len(h.get("plan", []))
        data["hair"] = {k: h.get(k) for k in ("available", "analysis", "shedding_note", "hairline_limits", "hairline", "hairline_note", "crown", "score", "image",
                                              "top_image", "top_error", "see_doctor", "doctor_reasons")}
    if data.get("countdown"):
        data["locked"]["countdown_steps"] = sum(len(ph["items"]) for ph in data["countdown"]["phases"])
        data["countdown"]["phases"] = data["countdown"]["phases"][:1]
    for k in ("previews", "routine", "reviewer_note"):
        data.pop(k, None)
    return data


def _public(result: dict) -> dict:
    """What the browser may see: the full report once paid (and reviewed, if review is
    required), otherwise a preview."""
    data = report_validator.public_filter({k: v for k, v in result.items() if not k.startswith("_")})
    data["price"] = payments.price_info()
    data["saved"] = bool(result.get("_owner"))  # in someone's progress history
    # Recomputed on every read so "days left" is always current.
    prof = data.get("profile", {})
    data["countdown"] = countdown.build(prof.get("event"), prof, data.get("skin") or {})
    # Season changes over time, so the climate note and the routine are rebuilt on each read.
    data["climate"] = climate.context(prof.get("city"))
    if data.get("routine") is not None:
        data["routine"] = products.build(data.get("skin") or {}, prof, data["climate"], data.get("routine_feedback"))
    tries = data.get("tryons") or {}
    _prov = tryon.provider()
    data["tryon"] = {"available": _prov is not None, "quota": tryon.QUOTA, "used": len(tries),
                     "consent": consent.state(result, _prov), "disclosure": consent.disclosure(_prov) if _prov else None}
    if not data.get("paid"):
        data.pop("tryons", None)
        return _preview(data)
    if data.get("review_status") == "pending":
        data = _preview(data)
        data["in_review"] = True
    return data


# --- Payment -------------------------------------------------------------------

_unlock_locks: dict[str, threading.Lock] = {}
_unlock_guard = threading.Lock()


def _unlock(analysis_id: str, plan: str = "full") -> dict:
    """Mark paid and write the full Claude report. Safe to call twice (webhook + redirect)."""
    with _unlock_guard:
        lock = _unlock_locks.setdefault(analysis_id, threading.Lock())
    with lock:
        result = store.load(analysis_id)
        if result.get("paid"):
            return result
        written, source = report.generate(result, result["profile"], result.get("_candidates", []), result.get("_photo", ""))
        needs_review = REVIEW_REQUIRED or plan == "expert"
        result.update(paid=True, paid_at=int(time.time()), plan=plan, report=written, report_source=source,
                      review_status="pending" if needs_review else "not_required")
        store.save(result)
        return result


_tryon_lock = threading.Lock()


@app.post("/api/analyses/{analysis_id}/tryon", dependencies=[Depends(security.rate_limit("tryon", 20, 3600))])
async def try_on(analysis_id: str, kind: str = Body(...), style: str = Body(...),
                 result: dict = Depends(security.report_access)):
    """AI try-on of one of *this report's* recommended hairstyles / beards / glasses (paid reports only)."""
    if not result.get("paid"):
        raise HTTPException(402, "Try-on is part of the full report.")
    prov = tryon.provider()
    if prov is not None:  # (not configured -> generate() reports that itself and nothing is sent anywhere)
        consent.require(result, prov)  # server-side gate: no photo leaves without current consent
    st = result.get("style") or {}
    allowed = {"hair": st.get("hairstyles", []), "beard": st.get("beard", []), "glasses": st.get("glasses", [])}
    if style not in allowed.get(kind, []):
        raise HTTPException(400, "Pick one of the styles recommended in your report.")
    key = f"{kind}|{style}"

    def critical():
        # One generation per report at a time: identical simultaneous requests share ONE provider call (measured before this
        # fix: 8 concurrent identical requests made 3 provider calls), and the quota check cannot be raced.
        with store.lock(f"tryon-{analysis_id}"):
            fresh = store.load(analysis_id)  # state as of now, inside the lock
            if prov is not None:
                consent.require(fresh, prov)  # consent may have been withdrawn while this request waited
            tries = fresh.get("tryons") or {}
            if key in tries:
                return tries[key]
            if len(tries) >= tryon.QUOTA:
                raise HTTPException(429, f"You've used all {tryon.QUOTA} try-ons for this report.")
            ticket = spend_guard.reserve() if prov is not None else None  # GLOBAL daily cap + circuit breaker (not per-IP)
            try:
                out = tryon.generate(fresh.get("_photo", ""), kind, style, consented=True)
            except tryon.ProviderError as e:
                if ticket is not None:
                    spend_guard.finish(ticket, "provider_failure")
                raise HTTPException(502, str(e))
            except tryon.TryOnError as e:
                if ticket is not None:
                    spend_guard.finish(ticket, "rejected")
                raise HTTPException(503 if "isn't set up" in str(e) else 422, str(e))
            if ticket is not None:
                spend_guard.finish(ticket, "ok")
            with store.lock(analysis_id):
                latest = store.load(analysis_id)
                latest.setdefault("tryons", {})[key] = out
                store.save(latest)
            return out

    return await run_in_threadpool(critical)


@app.post("/api/analyses/{analysis_id}/token/rotate", dependencies=[Depends(security.rate_limit("token", 30, 600))])
def rotate_access_token(analysis_id: str, result: dict = Depends(security.report_access)):
    """Issue a new access token and invalidate the old one (e.g. if a link/token may have leaked)."""
    with store.lock(analysis_id):
        fresh = store.load(analysis_id)
        token = security.issue_access(fresh)
        store.save(fresh)
    return {"access_token": token, "expires_at": fresh.get("_access_expires")}


@app.delete("/api/analyses/{analysis_id}/token", dependencies=[Depends(security.rate_limit("token", 30, 600))])
def revoke_access_tokens(analysis_id: str, authorization: str | None = Header(None),
                         result: dict = Depends(security.report_access)):
    """Revoke every anonymous access token for a report. Only the signed-in OWNER may do this (a token holder
    cannot lock the owner out of their own sharing decisions)."""
    user = accounts.user_from_auth(authorization)
    if not user or str(result.get("_owner")) != str(user["id"]):
        raise HTTPException(404, "Analysis not found")
    with store.lock(analysis_id):
        fresh = store.load(analysis_id)
        security.revoke_access(fresh)
        store.save(fresh)
    return {"revoked": True}


@app.post("/api/analyses/{analysis_id}/consent/tryon", dependencies=[Depends(security.rate_limit("consent", 30, 600))])
def set_tryon_consent(analysis_id: str, accept: bool = Body(...), provider: str = Body(...), version: str = Body(...),
                      result: dict = Depends(security.report_access)):
    """Record (accept=true) or withdraw (accept=false) consent to send this report's photo to the try-on provider.
    The provider and consent-text version must match what the server is using now, so a stale or forged client
    cannot consent on the user's behalf to something else."""
    current = tryon.provider()
    if current is None:
        raise HTTPException(409, "Try-on is not set up, so there is nothing to consent to.")
    if accept:
        if provider != current or version != consent.VERSION:
            raise HTTPException(409, "The provider or consent text has changed. Please review and accept again.")
        with store.lock(analysis_id):  # reload inside the lock: concurrent requests must not overwrite each other
            fresh = store.load(analysis_id)
            consent.grant(fresh, current)
            store.save(fresh)
        return consent.state(fresh, current)
    with store.lock(analysis_id):
        fresh = store.load(analysis_id)
        consent.revoke(fresh)
        store.save(fresh)
    return consent.state(fresh, current)


@app.delete("/api/analyses/{analysis_id}/consent/tryon")
def withdraw_tryon_consent(analysis_id: str, result: dict = Depends(security.report_access)):
    with store.lock(analysis_id):
        fresh = store.load(analysis_id)
        consent.revoke(fresh)
        store.save(fresh)
    return consent.state(fresh, tryon.provider())


@app.get("/api/analyses/{analysis_id}")
def get_analysis(result: dict = Depends(security.report_access)):
    return _public(result)


@app.delete("/api/analyses/{analysis_id}", dependencies=[Depends(security.rate_limit("report-{analysis_id}", 30, 600))])
def delete_analysis(analysis_id: str, result: dict = Depends(security.report_access)):
    """Permanently delete a report and every photo/preview stored inside it. Requires the same credential as reading it."""
    owner_id = result.get("_owner")
    store.delete(analysis_id)
    if owner_id:
        accounts.detach(owner_id, analysis_id)
    return {"deleted": True}


@app.post("/api/analyses/{analysis_id}/checkout", dependencies=[Depends(security.rate_limit("report-checkout", 30, 600))])
def checkout(analysis_id: str, plan: str = Body("full", embed=True), result: dict = Depends(security.report_access)):
    if result.get("paid"):
        return {"url": None, "paid": True}
    if plan not in payments.PLANS:
        raise HTTPException(400, "Unknown plan")
    try:
        started = payments.create_checkout(analysis_id, plan, result.get("profile", {}))
    except (stripe.StripeError, payments.PaymentError) as e:
        raise HTTPException(502, f"Payment provider error: {getattr(e, 'user_message', None) or 'please try again'}")
    if "razorpay" in started:
        result["_order"] = {"id": started["razorpay"]["order_id"], "plan": plan}
        store.save(result)
    return started


@app.post("/api/analyses/{analysis_id}/confirm", dependencies=[Depends(security.rate_limit("report-confirm", 30, 600))])
def confirm(analysis_id: str, body: dict = Body(default={}), result: dict = Depends(security.report_access)):
    if result.get("paid"):
        return _public(result)
    try:
        plan = payments.verify_payment(analysis_id, body, result.get("_order"))
    except stripe.StripeError:
        raise HTTPException(502, "Could not verify the payment. Please refresh in a moment.")
    if not plan:
        raise HTTPException(402, "Payment not completed.")
    return _public(_unlock(analysis_id, plan))


@app.post("/api/{provider}/webhook")
async def payment_webhook(provider: str, request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature") or request.headers.get("x-razorpay-signature")
    try:
        paid = payments.paid_from_webhook(provider, payload, signature)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook")
    if paid and store.path(paid[0]).exists():
        await run_in_threadpool(_unlock, paid[0], paid[1])
    return {"received": True}


RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "90"))  # anonymous (no account) reports; 0 disables


@app.on_event("startup")
def _startup_key_check() -> None:
    info = store.startup_check()  # raises -> the app does not start with a missing/corrupt/wrong key
    logging.getLogger("facemetric_ai").info("storage: %d encrypted report(s), key from %s", info["encrypted_reports"], info["key_source"])


@app.on_event("startup")
def _protect_account_files() -> None:
    store.restrict_to_current_user(accounts.USERS_DIR)  # emails + password hashes: owner-only access to the folder


@app.on_event("startup")
def _retention_purge() -> None:
    removed = store.purge_expired(RETENTION_DAYS)
    if removed:
        logging.getLogger("facemetric_ai").info("retention: deleted %d expired anonymous report(s)", len(removed))


app.include_router(admin.router)
app.include_router(accounts.router)
