"""Deterministic recommendation consistency engine (no LLM involved).

1. ENRICH: every recommendation gets a stable id, category, supporting metric ids, preconditions, limitations,
   priority and conflict group, so each one is traceable to the measurement that triggered it.
2. RESOLVE CONFLICTS: advice that pulls in opposite directions is never shown together. Currently one conflict
   group is defined, `chin_length` (grow the chin hair longer vs keep it short). The measurement with the larger
   deviation from its reference wins; if the evidence is too close to call, BOTH sides are suppressed and the
   reason is recorded in the audit trail.

Only measured evidence is used. (User goals are not yet an input - see docs/RECOMMENDATION_CONSISTENCY.md.)
"""
from __future__ import annotations

import hashlib
import re

# Recommendations (by exact title in recommendations.LIBRARY) and which way they push chin length.
# tests/test_consistency.py asserts every title here still exists, so this table cannot silently drift.
CHIN_STANCE = {
    "Elongate the lower face": "long",
    "Soften lower-face length": "short",
    "Balance lip-to-chin height": "short",
    "Soften a straight or concave profile": "short",
}
# Free-text beard styles (styling.py) that lengthen / shorten the chin.
LONG_RE = re.compile(r"anchor|longer chin|lengthen the face", re.I)
SHORT_RE = re.compile(r"keep the chin short|shorter chin", re.I)

# Metrics that carry chin-length evidence: (key, direction) -> stance it supports.
CHIN_EVIDENCE = {("thirds_lower_mid", "high"): "short", ("thirds_lower_mid", "low"): "long",
                 ("lower_third_split", "low"): "short", ("lower_third_split", "high"): None}
TIE_MARGIN = 10.0  # score points; closer than this = unresolved


def chin_decision(metrics: list[dict]) -> dict:
    """Which way should chin-length advice go? -> {stance: short|long|unresolved|None, reason, evidence}"""
    ev = {"short": [], "long": []}
    for m in metrics:
        stance = CHIN_EVIDENCE.get((m["key"], m["direction"]))
        if stance and m["status"] != "ideal":
            ev[stance].append(m)
    best = {k: min(v, key=lambda m: m["score"]) for k, v in ev.items() if v}
    if not best:
        return {"stance": None, "reason": "no chin-length evidence", "evidence": {}}
    shown = {k: {"metric": m["key"], "score": m["score"]} for k, m in best.items()}
    if len(best) == 1:
        k = next(iter(best))
        return {"stance": k, "reason": f"only {best[k]['key']} indicates chin length", "evidence": shown}
    gap = abs(best["short"]["score"] - best["long"]["score"])
    if gap < TIE_MARGIN:
        return {"stance": "unresolved", "evidence": shown,
                "reason": f"measurements disagree (score gap {gap:.1f} < {TIE_MARGIN})"}
    win = "short" if best["short"]["score"] < best["long"]["score"] else "long"
    return {"stance": win, "evidence": shown, "reason": f"{best[win]['key']} deviates most (gap {gap:.1f})"}


def _enrich(c: dict, priority: int) -> dict:
    t, typ = c["title"], c["type"]
    pre, lim = [], []
    if "beard" in (t + c["detail"]).lower() or "moustache" in (t + c["detail"]).lower():
        pre.append("facial hair that can be grown or shaped")
    if typ == "professional":
        pre.append("consultation with a licensed provider")
        lim.append("Requires clinical assessment; outcome and risks depend on the provider.")
    elif typ == "skincare":
        lim.append("Individual results vary; patch-test new products and stop if irritated.")
    elif typ in ("grooming", "makeup"):
        lim.append("Cosmetic effect only - it changes how proportions read, not underlying bone structure.")
    else:
        lim.append("General habit; effects are gradual and vary between people.")
    return {**c,
            "id": "rec_" + hashlib.sha1(f"{c['feature']}|{t}".encode()).hexdigest()[:10],
            "category": typ,
            "supporting_metrics": [] if c["for"] == "baseline" else [c["for"]],
            "preconditions": pre, "limitations": lim, "priority": priority,
            "conflict_group": "chin_length" if t in CHIN_STANCE else None}


def resolve(cands: list[dict], metrics: list[dict]) -> tuple[list[dict], list[dict]]:
    """-> (kept recommendations enriched with traceability fields, audit records of suppressed ones)."""
    decision = chin_decision(metrics)
    kept, suppressed = [], []
    for c in cands:
        stance = CHIN_STANCE.get(c["title"])
        if stance and decision["stance"] in ("short", "long", "unresolved") and stance != decision["stance"]:
            suppressed.append({"id": _enrich(c, 0)["id"], "title": c["title"], "group": "chin_length",
                               "reason": f"conflicts with the chin-length decision ({decision['stance']}): {decision['reason']}"})
            continue
        kept.append(c)
    return [_enrich(c, i + 1) for i, c in enumerate(kept)], suppressed


def reconcile_beard_styles(beard: list[str], metrics: list[dict]) -> tuple[list[str], list[str]]:
    """Make the face-shape beard list agree with the chin-length decision. -> (beard styles, notes)."""
    d = chin_decision(metrics)
    notes: list[str] = []
    if d["stance"] == "short":
        beard = [b for b in beard if not LONG_RE.search(b)]
        beard.append("Keep the chin short - your measurements show the lower face is already long, so extra length at the chin isn't needed")
    elif d["stance"] == "long":
        beard = [b for b in beard if not SHORT_RE.search(b)]
    elif d["stance"] == "unresolved":
        beard = [b for b in beard if not LONG_RE.search(b) and not SHORT_RE.search(b)]
        notes.append("Chin length: your measurements point in different directions, so we are not giving chin-length "
                     "beard advice. A barber can judge this in person.")
    return beard, notes
