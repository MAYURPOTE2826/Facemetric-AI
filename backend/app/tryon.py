"""Hairstyle / beard try-on images through a hosted image-editing model (paid, ~₹3-4 per image).

Providers (set one key; TRYON_PROVIDER picks if both are set):
- fal.ai FLUX.1 Kontext [pro]  - FAL_KEY       (https://fal.ai/models/fal-ai/flux-pro/kontext)
- Google Gemini 2.5 Flash Image - GEMINI_API_KEY

Every result is checked before we show it:
- identity: SFace cosine similarity to the original photo must be >= 0.363 (OpenCV's
  same-person threshold) - edits that turned the client into someone else are rejected;
- skin colour: mean cheek L*/b* must stay within a small band of the original, so a "try-on"
  can never quietly lighten skin.
Only paid reports can generate try-ons; each report gets a small quota, and results are cached.
"""
from __future__ import annotations

import base64
import os

import cv2
import httpx
import numpy as np

from . import faceid, landmarks

QUOTA = int(os.getenv("TRYON_QUOTA", "6"))  # images per paid report
TIMEOUT = 120
MAX_SKIN_SHIFT = 4.0  # L* / b* units on the cheeks


class TryOnError(Exception):
    pass


def provider() -> str | None:
    want = os.getenv("TRYON_PROVIDER", "").lower()
    keys = {"fal": os.getenv("FAL_KEY"), "gemini": os.getenv("GEMINI_API_KEY")}
    if want in keys and keys[want]:
        return want
    return next((p for p, k in keys.items() if k), None)


def prompt_for(kind: str, style: str) -> str:
    what = {"hair": f"Change only the hairstyle to: {style}.",
            "beard": f"Change only the facial hair to: {style}.",
            "glasses": f"Add glasses: {style}."}[kind]
    return (f"{what} Keep the same person: identical face, facial features, skin tone and skin colour, expression, "
            "head pose, lighting, background and clothing. Photorealistic, natural result, no makeup or retouching.")


def _fal(img_b64: str, prompt: str) -> bytes:
    r = httpx.post("https://fal.run/fal-ai/flux-pro/kontext",
                   headers={"Authorization": f"Key {os.environ['FAL_KEY']}"},
                   json={"prompt": prompt, "image_url": f"data:image/jpeg;base64,{img_b64}", "output_format": "jpeg",
                         "safety_tolerance": "2", "sync_mode": True},
                   timeout=TIMEOUT)
    if r.status_code >= 400:
        raise ProviderError(f"fal.ai error {r.status_code}: {r.text[:200]}")
    url = r.json()["images"][0]["url"]
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    return httpx.get(url, timeout=TIMEOUT).content


def _gemini(img_b64: str, prompt: str) -> bytes:
    model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                   headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                   json={"contents": [{"parts": [{"text": prompt},
                                                 {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}]}]},
                   timeout=TIMEOUT)
    if r.status_code >= 400:
        raise ProviderError(f"Gemini error {r.status_code}: {r.text[:200]}")
    for part in r.json()["candidates"][0]["content"]["parts"]:
        data = part.get("inlineData") or part.get("inline_data")
        if data:
            return base64.b64decode(data["data"])
    raise ProviderError("Gemini returned no image.")


def _cheeks_lab(bgr: np.ndarray, pts: np.ndarray) -> np.ndarray:
    bz = float(np.linalg.norm(pts[234, :2] - pts[454, :2]))
    m = np.zeros(bgr.shape[:2], np.uint8)
    for i in (50, 280):
        cv2.circle(m, (int(pts[i, 0]), int(pts[i, 1])), max(3, int(0.07 * bz)), 1, -1)
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    return np.array([lab[..., 0][m > 0].mean() * 100 / 255, lab[..., 2][m > 0].mean() - 128])


class ConsentRequired(TryOnError):
    pass


class ProviderError(TryOnError):
    """The external provider failed (HTTP error / unreadable response). Counts toward the spend circuit breaker;
    quality rejections (identity / skin-colour checks) do not."""


def generate(photo_b64: str, kind: str, style: str, *, consented: bool = False) -> dict:
    """Returns {"image": b64 jpeg, "identity": similarity}. Raises TryOnError if not configured or rejected.
    `consented` must be True: the photo is sent to a third party, so this function refuses to run without the
    caller having verified consent (defence in depth - the endpoint also checks it before spending any quota)."""
    if not consented:
        raise ConsentRequired("The user has not consented to sending their photo to the image provider.")
    p = provider()
    if p is None:
        raise TryOnError("Try-on isn't set up yet (no FAL_KEY or GEMINI_API_KEY).")
    if kind not in ("hair", "beard", "glasses"):
        raise TryOnError("Unknown try-on type.")
    original = cv2.imdecode(np.frombuffer(base64.b64decode(photo_b64), np.uint8), cv2.IMREAD_COLOR)
    face0 = landmarks.detect(original)
    if face0 is None:
        raise TryOnError("Couldn't find the face in your photo.")
    raw = (_fal if p == "fal" else _gemini)(photo_b64, prompt_for(kind, style))
    out = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if out is None:
        raise ProviderError("The image service returned an unreadable image.")
    if out.shape[:2] != original.shape[:2]:
        out = cv2.resize(out, (original.shape[1], original.shape[0]), interpolation=cv2.INTER_AREA)
    face1 = landmarks.detect(out)
    if face1 is None:
        raise TryOnError("The generated image lost the face - try another style.")
    sim = faceid.same_person(faceid.embedding(original, face0.points), faceid.embedding(out, face1.points))
    if sim < faceid.SAME_PERSON:
        raise TryOnError("The generated image didn't look enough like you, so we didn't show it. Try again.")
    shift = np.abs(_cheeks_lab(out, face1.points) - _cheeks_lab(original, face0.points))
    if shift.max() > MAX_SKIN_SHIFT:
        raise TryOnError("The generated image changed your skin colour, so we didn't show it. Try again.")
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return {"image": base64.b64encode(buf.tobytes()).decode(), "identity": round(sim, 3),
            "provider": p, "kind": kind, "style": style}
