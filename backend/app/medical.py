"""Medical and professional-care content that is shown in EVERY report, whatever the photo shows.

CONTENT STATUS: **GENERAL INFORMATION - NOT CLINICALLY REVIEWED.** The red-flag lists follow widely published general dermatology
guidance in plain language, but they were written by the software's author and have not been reviewed or signed off by a clinician. They
are not a diagnosis, triage tool or treatment plan. A clinician should review this file before the report is offered to the public.

Four parts (all built here, rendered by the report page):
  1. limits      what this report cannot do.
  2. red_flags   when to seek care, in three urgency levels, independent of the photograph.
  3. consults    every professional consult type the report can suggest, each with an explicit status:
                   indicated | not indicated by your measurements | could not assess | not offered for you (safety).
  4. history     the health answers the user gave and exactly what each one changed (nothing is collected without being used).
"""
from __future__ import annotations

CONTENT_STATUS = "GENERAL INFORMATION - NOT CLINICALLY REVIEWED"

LIMITS = [
    "This report is made from one photograph by software. It is not a medical examination and it cannot diagnose any condition.",
    "It cannot see under the skin, check moles for cancer, assess scarring, infection, hormones, nutrition or medicines, or replace a doctor.",
    "Photo quality changes the result. Where the photo was blurry, filtered, too bright or too dark, or had a colour cast, the affected readings were withheld rather than guessed.",
    "Reference ranges and thresholds used in the measurements are placeholders that have not been validated; millimetre sizes are estimates.",
    "Suggested professional consults are options to discuss with a licensed provider, not recommendations to have a procedure. Results of any treatment vary and have risks.",
    "If you are worried about your skin, hair or health, see a doctor - do not wait for a report.",
]

RED_FLAGS = {
    "urgent": {
        "title": "Get urgent medical help",
        "items": [
            "Swelling of the face, lips or tongue, or trouble breathing or swallowing (possible severe allergic reaction).",
            "A fast-spreading red, hot, painful area of skin with fever or feeling very unwell (possible infection).",
            "Severe pain, blistering or a widespread rash after starting a new medicine or product.",
        ],
    },
    "soon": {
        "title": "See a doctor soon (within days to a couple of weeks)",
        "items": [
            "A mole or spot that is changing in size, shape or colour, has uneven edges or several colours, bleeds, itches or crusts.",
            "A sore or scab that has not healed within about 4 weeks.",
            "New, quickly growing, or unusually shaped lumps in the skin.",
            "Hair loss in round bald patches, hair loss with unexplained weight loss, fever or tiredness, or hair loss after starting a new medicine (do not stop a prescribed medicine on your own).",
            "Skin thinning, stretch marks, acne or lightening/darkening on the face after using steroid or 'fairness' creams.",
        ],
    },
    "dermatologist": {
        "title": "Consider a dermatologist",
        "items": [
            "Acne that is deep, painful, leaves scars or marks, or has not improved after about 8-12 weeks of consistent over-the-counter care.",
            "Persistent facial redness, flushing, or bumps that come and go (possible rosacea).",
            "New dark patches on the face, especially in pregnancy or when starting hormonal medicine (possible melasma).",
            "Itchy, dry, flaking or cracked skin that keeps returning (possible eczema, psoriasis or dermatitis).",
            "Any skin concern that is getting worse, spreading or affecting your sleep, work or confidence.",
        ],
    },
}

# consult title -> how it is decided. ("metric", key, direction) or ("skin", concern key)
CONSULTS = [
    ("Brow-lift neuromodulator consult", "metric", "canthal_tilt", "low"),
    ("Chin projection consult", "metric", "convexity", "low"),
    ("Non-surgical rhinoplasty consult", "metric", "nasofacial", "high"),
    ("Upper lip filler consult", "metric", "lip_ratio", "high"),
    ("Jawline filler consult", "metric", "jaw_zygo", "low"),
    ("Masseter neuromodulator consult", "metric", "gonial_angle", "low"),
    ("Submental fat treatment consult", "metric", "cervicomental", "high"),
    ("Jaw-angle filler consult", "metric", "gonial_angle", "high"),
    ("Neuromodulator consult for expression lines", "skin", "wrinkles", None),
    ("Dermatologist for persistent acne", "skin", "blemishes", None),
    ("See a dermatologist if persistent", "skin", "redness", None),
    ("Dermatologist for melasma", "skin", "pigmentation", None),
]

# What each health answer changes (these ids are the options on the analysis form).
HISTORY_EFFECTS = {
    "pregnant": "Professional procedures and retinoid/peel-type products are not suggested; please ask your doctor before using any active.",
    "breastfeeding": "Professional procedures and retinoid/peel-type products are not suggested; please ask your doctor before using any active.",
    "isotretinoin": "Peels, waxing, threading, scrubs, acids and other strong actives are not suggested while you take it.",
    "steroid_history": "The report warns against steroid/'fairness' creams and lists the thinning/acne signs that should prompt a doctor visit.",
    "skin_condition": "Exfoliating acids, retinoids, scrubs, peels and procedures are not suggested; please ask your dermatologist before adding any active.",
    "prescribed_skin_treatment": "Strong actives are not suggested on top of a prescribed treatment; please check with whoever prescribed it first.",
}


def _status(kind, key, direction, title, metrics, skin, titles, validation, profile) -> tuple[str, str]:
    from .report import unsafe_for  # local import: report imports recommendations
    if unsafe_for(profile, {"type": "professional", "title": title, "detail": ""}):
        return "not_offered_safety", "Not offered for you because of your age or the health answers you gave."
    withheld = {s.get("item") for s in (validation or {}).get("suppressed", [])}
    if kind == "metric":
        m = next((x for x in metrics if x["key"] == key), None)
        if m is None:
            return "could_not_assess", "This measurement was not available or was withheld because of the photo."
        if title in titles:
            return "indicated", f"Your {m.get('label', key)} measurement is outside its reference range, so a consult is an option to discuss. This is not a recommendation to have a procedure."
        return "not_indicated", "Your measurement for this is not outside its reference range."
    c = next((x for x in (skin or {}).get("concerns", []) if x["key"] == key), None) if (skin or {}).get("available") else None
    if f"skin:{key}" in withheld or c is None:
        return "could_not_assess", "The skin reading for this was withheld or unavailable because of the photo, so nothing is implied either way. If you have this concern, see a dermatologist regardless."
    if title in titles:
        return "indicated", "Your skin reading suggests this is worth discussing with a dermatologist. This is not a diagnosis."
    return "not_indicated", "Your skin reading for this did not point to a concern."


def build(metrics: list[dict], skin: dict | None, candidates: list[dict], validation: dict | None, profile: dict | None) -> dict:
    titles = {c["title"] for c in candidates}
    consults = []
    for title, kind, key, direction in CONSULTS:
        status, why = _status(kind, key, direction, title, metrics, skin, titles, validation, profile or {})
        consults.append({"title": title, "status": status, "why": why})
    given = [f for f in ((profile or {}).get("safety") or []) if f in HISTORY_EFFECTS]
    return {
        "content_status": CONTENT_STATUS,
        "limits": LIMITS,
        "red_flags": RED_FLAGS,
        "consults": consults,
        "history": [{"answer": f, "effect": HISTORY_EFFECTS[f]} for f in given],
        "history_note": ("You did not give any health answers, so none of the advice was adjusted. Adding them on the analysis form changes which products and procedures are suggested."
                         if not given else "These are the health answers you gave and what each one changed."),
    }
