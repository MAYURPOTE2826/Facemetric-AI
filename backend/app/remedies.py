"""Desi nuskhe - popular home remedies, rated by evidence.

verdict: "works" | "okay" (harmless, mild/limited benefit) | "myth" | "harmful"
Tags link remedies to skin concerns so each report shows the relevant ones.
"""
from __future__ import annotations

REMEDIES = [
    {"name": "Lemon juice on the face", "verdict": "harmful", "tags": ["pigmentation", "uneven_tone", "dark_spots", "acne_marks"],
     "why": "Very acidic and phototoxic - it irritates skin and can cause burns and darker patches when you step into the sun."},
    {"name": "Toothpaste on pimples", "verdict": "harmful", "tags": ["blemishes"],
     "why": "Ingredients like SLS, menthol and baking soda irritate and can leave a dark mark. Use benzoyl peroxide or salicylic acid instead."},
    {"name": "Steroid / 'fairness' creams from the chemist", "verdict": "harmful", "tags": ["pigmentation", "uneven_tone", "blemishes", "general"],
     "why": "Creams with clobetasol, betamethasone or mometasone thin the skin, cause steroid acne and rebound pigmentation. Only use under a dermatologist."},
    {"name": "Bleach creams on the face", "verdict": "harmful", "tags": ["uneven_tone", "pigmentation"],
     "why": "Hides tan briefly but irritates and can worsen pigmentation, especially in melanin-rich skin."},
    {"name": "Multani mitti (fuller's earth) pack", "verdict": "works", "tags": ["shine", "blemishes", "texture"],
     "why": "Absorbs excess oil and temporarily tightens pores. Once a week for oily skin; skip it if your skin is dry or sensitive."},
    {"name": "Aloe vera gel (pure)", "verdict": "works", "tags": ["redness", "general", "uneven_tone"],
     "why": "Soothes and hydrates, helps after sun exposure. Patch-test first - some people react to it."},
    {"name": "Cold compress / chilled spoons for under-eyes", "verdict": "works", "tags": ["dark_circles"],
     "why": "Reduces puffiness and shadows for a few hours. It won't fix pigmentation-type dark circles."},
    {"name": "Besan + dahi (curd) ubtan", "verdict": "okay", "tags": ["uneven_tone", "texture"],
     "why": "Curd's lactic acid gently exfoliates and besan cleanses - fine once a week. Rub gently; scrubbing hard darkens skin."},
    {"name": "Haldi (turmeric) face pack", "verdict": "okay", "tags": ["blemishes", "uneven_tone", "acne_marks"],
     "why": "Some anti-inflammatory evidence, but it stains and can irritate. Small amounts, short contact, patch-test first."},
    {"name": "Raw potato or tomato for tan", "verdict": "myth", "tags": ["uneven_tone", "pigmentation", "dark_circles"],
     "why": "Harmless but no real evidence it removes tan or dark circles. Sunscreen and niacinamide do far more."},
    {"name": "Coconut oil as a face moisturiser", "verdict": "okay", "tags": ["general", "texture"],
     "why": "Great for dry body skin and hair, but it clogs pores on acne-prone or oily faces."},
    {"name": "Rose water as toner", "verdict": "okay", "tags": ["redness", "general"],
     "why": "Pleasant and mildly soothing - fine to use, but it doesn't treat any concern on its own."},
    {"name": "Drinking more water clears skin", "verdict": "myth", "tags": ["general", "blemishes"],
     "why": "Staying hydrated is good for health, but beyond normal intake it doesn't clear acne or marks."},
    {"name": "Sugar or salt scrubs on the face", "verdict": "harmful", "tags": ["texture", "blemishes", "uneven_tone"],
     "why": "Sharp crystals cause micro-tears and dark marks. Use a gentle chemical exfoliant instead."},
    {"name": "Kachi haldi + chandan for acne marks", "verdict": "myth", "tags": ["acne_marks", "dark_spots"],
     "why": "Smells lovely but won't fade marks meaningfully. Azelaic acid, niacinamide and daily SPF will."},
    {"name": "Ice cube on a fresh pimple", "verdict": "works", "tags": ["blemishes"],
     "why": "Wrapped in a cloth for a minute, it calms swelling and redness. Don't hold it on bare skin for long."},
    {"name": "Sleeping 7-8 hours", "verdict": "works", "tags": ["dark_circles", "general"],
     "why": "Less puffiness and better skin repair - free and evidence-backed."},
]

ORDER = {"harmful": 0, "works": 1, "okay": 2, "myth": 3}


def for_concerns(skin: dict, limit: int = 8) -> list[dict]:
    """Remedies relevant to this person's concerns (worst first), always including the big warnings."""
    concerns = [c["key"] for c in skin.get("concerns", []) if c["score"] < 85] if skin.get("available") else []
    picked, seen = [], set()

    def add(r):
        if r["name"] not in seen:
            seen.add(r["name"])
            picked.append({k: r[k] for k in ("name", "verdict", "why")})

    for key in concerns:
        for r in REMEDIES:
            if key in r["tags"]:
                add(r)
    for r in REMEDIES:  # always warn about the dangerous ones
        if r["verdict"] == "harmful" and "general" in r["tags"]:
            add(r)
    for r in REMEDIES:
        if len(picked) >= limit:
            break
        if "general" in r["tags"]:
            add(r)
    picked = picked[:limit]
    return sorted(picked, key=lambda r: ORDER[r["verdict"]])
