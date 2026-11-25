"""Turns measurements into a written, personalised report using Claude.

Falls back to a rule-based report when the API is unavailable so the app
still works offline / without a key.
"""
from __future__ import annotations

import json
import logging
import os

import re
from typing import Literal

import anthropic
from pydantic import BaseModel

from . import climate

log = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")


class Recommendation(BaseModel):
    title: str
    type: Literal["grooming", "makeup", "skincare", "lifestyle", "professional"]
    detail: str
    cost: str
    timeline: str


class FeatureSection(BaseModel):
    feature: str
    # Keys of the measurements / readings this section is based on (see "evidence_keys" in the payload).
    based_on: list[str]
    summary: str
    observations: list[str]
    recommendations: list[Recommendation]


class Report(BaseModel):
    headline: str
    overview: str
    strengths: list[str]
    sections: list[FeatureSection]
    priority_plan: list[str]
    disclaimer: str


SYSTEM = """You are a facial-aesthetics analyst writing a personal report for a client.
You are given objective landmark measurements of their face (already computed by our
measurement engine) from a front photo and, when provided, a side-profile photo
(category "profile": nose angles, lip position vs the E-line, chin and jaw-neck angles)
and a three-quarter photo (metric "gonial_angle": the jaw-corner angle),
their questionnaire answers, a curated list of candidate methods, and the front photo
for context.

Rules:
- Base every claim about proportions on the measurements provided. Never invent numbers.
- Use the photo only for things measurements cannot capture (hair, brows, grooming, skin
  appearance). Do not re-measure from the photo.
- Be warm, specific and honest. Lead with genuine strengths. Never insult, never rate
  attractiveness, never compare to celebrities, never mention race in a judgemental way.
- Recommend mainly from the candidate methods list. You may adapt wording to the client's
  goals, sex, age and budget. Prefer non-surgical, low-cost options first. Any
  "professional" option must say to consult a licensed provider.
- Respect the client's budget and goals. Skip methods that clearly don't fit (e.g. beard
  advice for someone who said they can't or won't grow one, makeup for someone who doesn't
  want it).
- Skin tone: never use "fair", "fairness", "whitening", "lightening" or "brightening skin colour" as a
  goal. Talk about even tone, healthy skin, tan and marks. Never recommend bleach, mercury, or creams
  containing steroids (clobetasol, betamethasone, mometasone, often sold OTC for pigmentation); when
  pigmentation comes up, warn against them. Use the skin "tone" advice for melanin-rich skin (avoid
  harsh scrubs and strong peels without a dermatologist).
- The client is likely in India: think about heat, humidity, pollution and strong sun. Prefer
  affordable, widely available options and mention approximate costs in rupees when helpful.
- If there is an upcoming_event (e.g. their wedding), make the priority_plan fit the time left and
  mention it warmly; a dated countdown is shown separately.
- Face shape with hairstyle/beard/glasses advice, a hair-fall screening and a city/season note are
  shown separately. Use them for consistency (e.g. grooming advice must match the face shape;
  if hair.see_doctor is true, the plan must include seeing a dermatologist). Never diagnose.
- A product routine and rated home remedies are shown separately in the report - keep your advice
  consistent with them and don't repeat them in full.
- Claims: say "helps reduce the look of", "evens tone", "fades marks over time" - never "cures",
  "treats", "removes", "guaranteed" or "permanent". Never call skin "dull" because it is dark.
- Facial exercises and mewing have little evidence and cannot change bone; if relevant, say so
  plainly. Posture and body-fat changes affect appearance, not skeletal structure.
- Hydroquinone and "triple combination" creams are prescription-only and short-term, under a
  dermatologist - never suggest them for self-use.
- Safety flags in client_profile.safety: pregnant/breastfeeding -> no retinoids, no professional
  procedures; isotretinoin -> no actives, peels, waxing or threading on the face; under 18 -> no
  professional/cosmetic procedures at all.
- Only use numbers that appear in the payload (measurements, scores, grades); don't invent any.
- 4 to 7 sections, one per feature area that matters most for this client. Each section's based_on
  lists the evidence_keys (from the payload) its observations rely on - at least one, only keys that
  exist. Don't write about a feature that has no evidence key.
- measurements_mm compares real sizes with typical adult ranges and eyes_and_brows gives brow-shaping
  guidance; use them for observations, never present being outside a typical range as a flaw.
- withheld_measurements were left out (e.g. a beard hides the jaw) - don't comment on those features
  as if they were measured.
- priority_plan: 3-6 short ordered steps for the next 90 days.
- disclaimer: one sentence noting this is educational, not medical advice."""


def _client() -> anthropic.Anthropic | None:
    try:
        return anthropic.Anthropic()
    except Exception:  # missing credentials
        return None


def generate(analysis: dict, profile: dict, candidates: list[dict], photo_b64: str) -> tuple[dict, str]:
    """Returns (report_dict, source) where source is 'claude' or 'rules'."""
    client = _client()
    if client is not None:
        try:
            return _claude_report(client, analysis, profile, candidates, photo_b64), "claude"
        except Exception as e:  # noqa: BLE001 - any API failure falls back to rules
            log.warning("Claude report failed, using rule-based report: %s", e)
    return rule_report(analysis, candidates), "rules"


def evidence_keys(analysis: dict) -> dict[str, str]:
    """Every key a report section may cite, with a short human label."""
    keys = {m["key"]: m["label"] for m in analysis.get("metrics", [])}
    skin = analysis.get("skin") or {}
    keys |= {c["key"]: c["label"] for c in skin.get("concerns", [])}
    if skin.get("tone"):
        keys["skin_tone"] = "Skin tone group (for safety)"
    neck = skin.get("neck") or {}
    if neck.get("available") or neck.get("finding") == "reported":
        keys["neck"] = "Neck vs face colour"
    hair = analysis.get("hair") or {}
    if hair.get("hairline"):
        keys["hairline"] = "Hairline"
    if hair.get("crown"):
        keys["crown"] = "Top of head / parting"
    if hair.get("questionnaire"):
        keys["hair_answers"] = "Your hair-fall answers"
    if analysis.get("style"):
        keys["face_shape"] = "Face shape"
    if analysis.get("anthropometry"):
        keys["measurements_mm"] = "Measurements in mm"
    if analysis.get("eyes"):
        keys["eyes_brows"] = "Eye & brow proportions"
    keys |= {"goals": "Your goals", "routine": "Your routine", "climate": "Your city & season"}
    return keys


def _payload(analysis: dict, profile: dict, candidates: list[dict]) -> dict:
    return {
        "client_profile": profile,
        "harmony_score": analysis["harmony_score"],
        "category_scores": analysis["category_scores"],
        "measurements": [
            {k: m[k] for k in ("key", "label", "category", "value", "unit", "ideal", "score", "status", "direction", "description")}
            for m in analysis["metrics"]
        ],
        "skin": {k: v for k, v in (analysis.get("skin") or {}).items() if k != "image"},
        "photo_quality_issues": [i["message"] for i in analysis["quality"]["issues"]] + analysis.get("profile_notes", []),
        "side_profile": "measured (category 'profile')" if "profile_image" in analysis else analysis.get("profile_error", "not provided"),
        "candidate_methods": candidates,
        "skincare_routine": [
            {"time": st["time"], "step": st["step"], "product_type": st["products"][0]["name"], "how": st["how"]}
            for st in ((analysis.get("routine") or {}).get("am", []) + (analysis.get("routine") or {}).get("pm", []))
        ],
        "upcoming_event": (lambda e: e and {"type": e.get("type"), "date": e.get("date")})((profile or {}).get("event")),
        "face_shape_and_styling": {k: v for k, v in (analysis.get("style") or {}).items() if k != "ratios"},
        "hair": {k: v for k, v in (analysis.get("hair") or {}).items() if k not in ("image", "top_image", "myths")},
        "climate_now": climate.context((profile or {}).get("city")),
        "home_remedies_rated": [{"name": r["name"], "verdict": r["verdict"]} for r in analysis.get("remedies") or []],
        "withheld_measurements": analysis.get("withheld_metrics", []),
        "measurements_mm": {k: v for k, v in (analysis.get("anthropometry") or {}).items() if k in ("rows", "ratios")},
        "eyes_and_brows": {k: v for k, v in (analysis.get("eyes") or {}).items() if k != "image"},
        "evidence_keys": evidence_keys(analysis),
    }


def _claude_report(client, analysis, profile, candidates, photo_b64) -> dict:
    payload = _payload(analysis, profile, candidates)
    content = []
    if photo_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": photo_b64}})
    content.append({"type": "text", "text": "Write the report for this client.\n\n" + json.dumps(payload, indent=1)})

    messages = [{"role": "user", "content": content}]
    for attempt in range(2):
        response = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            # Static system prompt is cached (cheap repeat reads across clients).
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=messages,
            output_format=Report,
        )
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            raise RuntimeError(f"No report produced (stop_reason={response.stop_reason})")
        result = response.parsed_output.model_dump()
        problems = validate(result, analysis, profile, payload)
        if not problems:
            return result
        log.warning("Claude report failed checks (attempt %d): %s", attempt + 1, problems)
        messages = messages + [
            {"role": "assistant", "content": json.dumps(result)},
            {"role": "user", "content": "Your report broke these rules - rewrite the whole report fixing them:\n- "
                                        + "\n- ".join(problems)},
        ]
    raise RuntimeError("Report failed validation twice")


BANNED = re.compile(r"\b(fair(ness|er)?|whiten\w*|lighten(ing)? (your )?(skin|complexion)|skin[- ]lightening|cures?|cured|"
                    r"guarantee[sd]?|permanent(ly)?|reshape (the )?bone)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d+\.\d+)(?!\.?\d)")


def _texts(report: dict) -> list[str]:
    out = [report["headline"], report["overview"], *report["strengths"], *report["priority_plan"]]
    for sec in report["sections"]:
        out += [sec["summary"], *sec["observations"]]
        for r in sec["recommendations"]:
            out += [r["title"], r["detail"]]
    return out


def _numbers(obj, out: list[float]) -> list[float]:
    """Every number anywhere in the payload (measurements, scores, grades, cm/mm, ages...)."""
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, str):
        out += [float(n) for n in NUMBER.findall(obj)]
    return out


# Ingredients/procedures that must not be suggested in some situations. A mention is fine when the
# same sentence tells the client to avoid it ("avoid retinol while pregnant").
RETINOID = r"retin(ol|oid|al|-?a)\w*|(?<!iso)tretinoin|adapalene|tazarotene"
UNSAFE = {
    "pregnant": (RETINOID + r"|salicylic peel|isotretinoin", "pregnant or breastfeeding"),
    "isotretinoin": (RETINOID + r"|peel|wax\w*|thread\w*|laser|scrub|\bAHA\b|\bBHA\b|glycolic|salicylic|microneedl\w*",
                     "on isotretinoin"),
    # Strong actives and procedures are not suggested on top of an existing skin condition or a prescribed treatment.
    "skin_condition": (RETINOID + r"|peel|scrub|laser|microneedl\w*|\bAHA\b|\bBHA\b|glycolic|salicylic|lactic|mandelic|exfoliat\w*",
                       "has eczema, psoriasis or rosacea"),
    "prescribed_skin_treatment": (RETINOID + r"|peel|scrub|laser|microneedl\w*|\bAHA\b|\bBHA\b|glycolic|salicylic|lactic|mandelic|exfoliat\w*",
                                  "uses a prescribed skin treatment"),
}
ALWAYS_UNSAFE = r"hydroquinone|clobetasol|betamethasone|mometasone|steroid cream|bleach\w*|mercury"
# Warning language: a unit (one recommendation, or one plan step) containing any of these is
# treated as advice *against* what it mentions ("Avoid bleach and 'fairness' creams").
NEGATED = re.compile(r"\b(avoid|don'?t|do not|never|skip|stop|not|no|pause|unsafe|without|instead of|steer clear|"
                     r"cause[sd]?|damage|harm\w*|risk\w*|danger\w*|warn\w*)\b", re.I)


def _units(report: dict) -> list[str]:
    """Self-contained pieces of advice: each recommendation (title + detail) and each plan step."""
    return [f"{r['title']}. {r['detail']}" for s in report["sections"] for r in s["recommendations"]] + \
        list(report["priority_plan"])


def _unsafe_mentions(units: list[str], pattern: str) -> list[str]:
    hits = []
    for unit in units:
        m = re.search(pattern, unit, re.I)
        if m and not NEGATED.search(unit):
            hits.append(m.group(0).lower())
    return hits


def validate(report: dict, analysis: dict, profile: dict | None, payload: dict | None = None) -> list[str]:
    """Deterministic checks on the model's report. Returns a list of problems (empty = OK)."""
    problems: list[str] = []
    profile = profile or {}
    texts = _texts(report)
    joined = " ".join(texts)
    banned = set()
    for t in texts:
        if NEGATED.search(t):  # "never use 'fairness' creams" is a warning, not a claim
            continue
        banned |= {m.group(0).lower() for m in BANNED.finditer(t)}
    for m in sorted(banned):
        if m.startswith("fair") and re.search(r"fair(ly)? (price|amount|bit)", joined, re.I):
            continue
        problems.append(f'Banned wording "{m}" - use evidence-safe, tone-neutral language.')
    # Signs are dropped: the number pattern reads "-6.3" as 6.3.
    allowed = [abs(v) for v in _numbers(payload if payload is not None else _payload(analysis, profile, []), [])]
    for t in texts:
        for n in NUMBER.findall(t):
            v = float(n)
            if not any(abs(v - a) <= max(0.02, 0.02 * abs(a)) for a in allowed):
                problems.append(f"The number {n} is not in the measurements - only quote measured values.")
    if (analysis.get("hair") or {}).get("see_doctor") and not re.search(r"dermatolog|doctor", " ".join(report["priority_plan"]), re.I):
        problems.append("The hair check flagged a doctor visit, so the priority_plan must include seeing a dermatologist.")
    try:
        minor = int(profile.get("age") or 99) < 18
    except ValueError:
        minor = False
    recs = [r for s in report["sections"] for r in s["recommendations"]]
    if minor and any(r["type"] == "professional" for r in recs):
        problems.append("The client is under 18 - remove all professional/cosmetic procedures.")
    safety = set(profile.get("safety") or [])
    units = _units(report)
    for flag, (pattern, who) in UNSAFE.items():
        if flag in safety or (flag == "pregnant" and "breastfeeding" in safety):
            for hit in sorted(set(_unsafe_mentions(units, pattern))):
                problems.append(f'The client is {who} - don\'t recommend "{hit}".')
            if flag == "pregnant" and any(r["type"] == "professional" for r in recs):
                problems.append("The client is pregnant or breastfeeding - no professional procedures.")
    for hit in sorted(set(_unsafe_mentions(units, ALWAYS_UNSAFE))):
        problems.append(f'Never suggest "{hit}" for self-use (prescription-only or unsafe).')
    keys = evidence_keys(analysis)
    for sec in report["sections"]:
        cited = sec.get("based_on") or []
        if not cited:
            problems.append(f'Section "{sec["feature"]}" must list the evidence_keys it is based on (based_on).')
        unknown = [k for k in cited if k not in keys]
        if unknown:
            problems.append(f'Section "{sec["feature"]}" cites unknown evidence keys {unknown} - use only evidence_keys.')
    return list(dict.fromkeys(problems))[:12]


def unsafe_for(profile: dict | None, method: dict) -> bool:
    """Would this candidate method break a safety rule for this client (age, pregnancy, isotretinoin)?"""
    profile = profile or {}
    safety = set(profile.get("safety") or [])
    try:
        minor = int(profile.get("age") or 99) < 18
    except ValueError:
        minor = False
    if method["type"] == "professional" and (minor or safety & {"pregnant", "breastfeeding"}):
        return True
    unit = f"{method['title']}. {method['detail']}"
    for flag, (pattern, _) in UNSAFE.items():
        if (flag in safety or (flag == "pregnant" and "breastfeeding" in safety)) and _unsafe_mentions([unit], pattern):
            return True
    return False


def rule_report(analysis: dict, candidates: list[dict], goals=None) -> dict:
    metrics = analysis["metrics"]
    strengths = [f"{m['label']} is in the ideal range." for m in metrics if m["status"] == "ideal"][:5]
    by_feature: dict[str, list[dict]] = {}
    for c in candidates:
        by_feature.setdefault(c["feature"], []).append(c)

    sections = []
    from .personalization import order_metrics
    for m in order_metrics(metrics, goals):  # worst measurement first; goal-related first within the same status tier
        if m["status"] == "ideal" or m["label"] not in by_feature:
            continue
        sections.append({
            "feature": m["label"],
            "based_on": [m["key"]],
            "summary": f"Measured {m['value']} {m['unit']} vs a reference of about {m['ideal']} ({m['status'].replace('_', ' ')}).",
            "observations": [m["description"]],
            "recommendations": [{k: c[k] for k in ("title", "type", "detail", "cost", "timeline")} for c in by_feature[m["label"]]],
        })
    sections = sections[:5]
    for feature in ("Skin", "General"):
        if feature in by_feature:
            concerns = [c["key"] for c in (analysis.get("skin") or {}).get("concerns", [])]
            sections.append({
                "feature": feature,
                "based_on": concerns[:3] if feature == "Skin" and concerns else ["goals"],
                "summary": "Foundational habits that improve every other result.",
                "observations": [],
                "recommendations": [{k: c[k] for k in ("title", "type", "detail", "cost", "timeline")} for c in by_feature[feature]],
            })

    return {
        "headline": f"Harmony score {analysis['harmony_score']}/100",
        "overview": "This report compares your facial proportions with commonly cited reference ranges and suggests non-surgical ways to bring out your best features.",
        "strengths": strengths or ["Your proportions are within a typical range overall."],
        "sections": sections,
        "priority_plan": [s["recommendations"][0]["title"] for s in sections[:5] if s["recommendations"]],
        "disclaimer": "This report is for educational purposes only and is not medical advice.",
    }
