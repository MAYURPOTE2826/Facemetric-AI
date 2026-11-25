"""Payments for unlocking the full report: Razorpay (India, UPI/cards/netbanking),
Stripe (international), or dev mode.

Provider is picked from the keys in backend/.env: Razorpay if RAZORPAY_KEY_ID is set,
else Stripe if STRIPE_SECRET_KEY is set, else "dev" - checkout is skipped and reports
unlock without payment so the flow can be tried locally. Never deploy in dev mode.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

import httpx
import stripe

log = logging.getLogger(__name__)

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
CURRENCY = os.getenv("REPORT_CURRENCY", "inr").lower()
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:3000").rstrip("/")

MODE = "razorpay" if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET else "stripe" if STRIPE_SECRET_KEY else "dev"
if MODE == "razorpay":
    CURRENCY = "inr"
if MODE == "stripe":
    stripe.api_key = STRIPE_SECRET_KEY
if MODE == "dev":
    log.warning("No payment keys set - payments run in DEV mode and reports unlock for free.")

# Prices in the smallest currency unit (paise for INR).
PLANS = {
    "full": {
        "name": "Full report",
        "amount": int(os.getenv("PRICE_FULL", "29900")),
        "features": ["Every measurement explained", "Feature-by-feature plan", "Your skincare routine in ₹",
                     "Desi nuskhe: what works, what doesn't", "Before/after previews", "PDF report"],
    },
    "expert": {
        "name": "Full report + expert review",
        "amount": int(os.getenv("PRICE_EXPERT", "79900")),
        "features": ["Everything in Full report", "Checked and personalised by a specialist",
                     "Personal note from your specialist", "Usually within 24 hours"],
    },
}


class PaymentError(Exception):
    pass


def price_info() -> dict:
    return {
        "mode": MODE,
        "currency": CURRENCY,
        "plans": [{"id": k, "name": p["name"], "amount": p["amount"] / 100, "features": p["features"]} for k, p in PLANS.items()],
        "razorpay_key_id": RAZORPAY_KEY_ID if MODE == "razorpay" else None,
    }


def create_checkout(analysis_id: str, plan: str, customer: dict) -> dict:
    """Starts a payment. Returns {"url"} to redirect to (Stripe/dev) or
    {"razorpay": {...}} options for Razorpay's in-page checkout."""
    p = PLANS[plan]
    if MODE == "dev":
        return {"url": f"{PUBLIC_URL}/report/{analysis_id}?dev_paid={plan}"}
    if MODE == "stripe":
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {"currency": CURRENCY, "unit_amount": p["amount"],
                               "product_data": {"name": f"Facemetric-AI - {p['name']}"}},
                "quantity": 1,
            }],
            client_reference_id=analysis_id,
            metadata={"analysis_id": analysis_id, "plan": plan},
            success_url=f"{PUBLIC_URL}/report/{analysis_id}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{PUBLIC_URL}/report/{analysis_id}",
        )
        return {"url": session.url}

    try:
        res = httpx.post(
            "https://api.razorpay.com/v1/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={"amount": p["amount"], "currency": "INR", "receipt": analysis_id,
                  "notes": {"analysis_id": analysis_id, "plan": plan}},
            timeout=20,
        )
        res.raise_for_status()
    except httpx.HTTPError as e:
        raise PaymentError(f"Could not start payment: {e}") from e
    order = res.json()
    return {"razorpay": {
        "key": RAZORPAY_KEY_ID, "order_id": order["id"], "amount": p["amount"], "currency": "INR",
        "name": "Facemetric-AI", "description": p["name"],
        "prefill": {"name": customer.get("name", "")},
    }}


def verify_payment(analysis_id: str, body: dict, pending_order: dict | None) -> str | None:
    """Checks a completed payment. Returns the plan paid for, or None."""
    if MODE == "dev":
        plan = body.get("plan") or "full"
        return plan if plan in PLANS else "full"
    if MODE == "stripe":
        session_id = body.get("session_id")
        if not session_id:
            return None
        s = stripe.checkout.Session.retrieve(session_id)
        meta = s.metadata or {}
        if s.payment_status == "paid" and meta.get("analysis_id") == analysis_id:
            return meta.get("plan", "full")
        return None

    order_id, payment_id, signature = (body.get(k) for k in ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature"))
    if not (order_id and payment_id and signature and pending_order and pending_order.get("id") == order_id):
        return None
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return pending_order["plan"] if hmac.compare_digest(expected, signature) else None


def paid_from_webhook(provider: str, payload: bytes, signature: str | None) -> tuple[str, str] | None:
    """Validates a provider webhook. Returns (analysis_id, plan) for a successful payment."""
    if provider == "stripe" and MODE == "stripe" and STRIPE_WEBHOOK_SECRET:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
        if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            s = event["data"]["object"]
            meta = s.get("metadata") or {}
            if s.get("payment_status") == "paid" and meta.get("analysis_id"):
                return meta["analysis_id"], meta.get("plan", "full")
        return None

    if provider == "razorpay" and MODE == "razorpay" and RAZORPAY_WEBHOOK_SECRET:
        expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise ValueError("Bad Razorpay signature")
        event = json.loads(payload)
        if event.get("event") not in ("order.paid", "payment.captured"):
            return None
        p = event.get("payload", {})
        notes = (p.get("order", {}).get("entity", {}).get("notes")
                 or p.get("payment", {}).get("entity", {}).get("notes") or {})
        if notes.get("analysis_id"):
            return notes["analysis_id"], notes.get("plan", "full")
    return None
