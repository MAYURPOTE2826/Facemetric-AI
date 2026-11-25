"""Explicit consent for sending a user's photo to an external image-generation provider (try-on).

Enforced on the SERVER: the try-on endpoint calls `require()` before any photo leaves the machine, and
`tryon.generate()` itself refuses to run without a consent flag, so a direct API request cannot skip the UI.

What is stored (minimum for auditability, on the report, encrypted with the rest of it):
    {"version": "tryon-consent-v1", "provider": "fal", "granted_at": <unix>, "expires_at": <unix>}
No copy of the photo and no IP address / user agent is stored for consent.

What is deliberately NOT claimed: the provider's own retention or training policy. Alexandra has not verified it,
so the disclosure says exactly that.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

VERSION = "tryon-consent-v1"
VALID_DAYS = 30  # engineering choice: consent is per report, per provider, and lapses after 30 days
PROVIDERS = {"fal": "fal.ai (FLUX.1 Kontext image-editing model)", "gemini": "Google (Gemini image model)"}


def disclosure(provider: str) -> dict:
    name = PROVIDERS.get(provider, provider)
    return {
        "version": VERSION,
        "provider": provider,
        "provider_name": name,
        "leaves_infrastructure": f"Your front-face photo (a cropped, resized copy, up to 768 px) leaves Alexandra's "
                                 f"servers and is sent over the internet to {name}.",
        "why": "To generate a picture of you with the hairstyle, beard or glasses you choose.",
        "processing": "An image-editing model is asked to change only the chosen style and keep your face, skin "
                      "colour, pose and background the same.",
        "retention": f"Alexandra does not keep an extra copy of your photo for this: the generated picture is saved inside "
                     f"your encrypted report. What {name} does with the photo you send - how long it keeps it and "
                     "whether it uses it to improve its models - has NOT been verified by Alexandra. Read the "
                     "provider's own privacy policy before you agree.",
        "optional": "Your facial analysis and report do not need this. You can decline and everything else works as normal.",
        "duration": f"Your choice applies to this report for {VALID_DAYS} days. You can withdraw it at any time.",
    }


def state(result: dict, provider: str | None, now: float | None = None) -> dict:
    """Current consent for `provider` on this report (consent given for another provider does not count)."""
    c = (result.get("_consent") or {}).get("tryon_external")
    t = now if now is not None else time.time()
    ok = bool(c and provider and c.get("provider") == provider and c.get("version") == VERSION
              and c.get("expires_at", 0) > t)
    return {"granted": ok, "provider": provider, "expires_at": c.get("expires_at") if ok else None}


def grant(result: dict, provider: str, now: float | None = None) -> dict:
    t = int(now if now is not None else time.time())
    rec = {"version": VERSION, "provider": provider, "granted_at": t, "expires_at": t + VALID_DAYS * 86400}
    result.setdefault("_consent", {})["tryon_external"] = rec
    return rec


def revoke(result: dict) -> None:
    (result.get("_consent") or {}).pop("tryon_external", None)


def require(result: dict, provider: str | None, now: float | None = None) -> None:
    """Raise 403 unless the user has a current consent for exactly this provider."""
    if not state(result, provider, now)["granted"]:
        raise HTTPException(403, {"code": "consent_required", "message":
                                  "Please review and accept how your photo is shared before using try-on.",
                                  "disclosure": disclosure(provider) if provider else None})
