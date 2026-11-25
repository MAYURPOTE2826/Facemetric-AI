"""User-goal personalization of recommendations.

The product already collects goals as preset chips (frontend analyze page): Sharper jawline, Better skin, Eye area,
Facial balance, Lips, Hair & grooming, Look less tired, Overall glow-up.

RULES (what a goal can and cannot do)
  * A goal only REORDERS recommendations that measurements already support. It never creates a recommendation.
  * It never moves a recommendation above one in a worse EVIDENCE TIER (tier 0 = measurement outside its reference range,
    tier 1 = near it, tier 2 = skin concerns, tier 3 = general habits). Within a tier, goal matches come first, then the
    original (measurement-severity) order.
  * It never resurrects anything the validator withheld or the conflict engine suppressed - those are not candidates.
  * With no goals (or only unknown goals, or only "Overall glow-up") the order is exactly what it was before.
  * Each goal also gets an honest ALIGNMENT status, including "your measurement is within range" and "we could not measure
    this reliably" - a goal is never answered with an invented problem.
  * No confidence number is attached: none has been validated.
"""
from __future__ import annotations

# goal -> what it relates to. metrics/skin keys, metric categories, recommendation types, exact baseline titles.
GOALS: dict[str, dict] = {
    "Sharper jawline": {"metrics": {"jaw_zygo", "gonial_angle", "cervicomental", "mentocervical", "submental_length"}, "categories": {"jaw"}},
    "Better skin": {"all_skin": True, "types": {"skincare"}},
    "Eye area": {"categories": {"eyes"}, "skin": {"dark_circles", "wrinkles"}},
    "Facial balance": {"categories": {"proportions", "symmetry"}},
    "Lips": {"categories": {"lips"}},
    "Hair & grooming": {"types": {"grooming"}},
    "Look less tired": {"categories": {"eyes"}, "skin": {"dark_circles"}, "titles": {"Sleep 7-9 hours consistently", "Hydration and lower sodium"}},
    "Overall glow-up": {},  # no specific preference: leaves the order alone
}


def known_goals(goals) -> list[str]:
    return [g for g in (goals or []) if isinstance(g, str) and g in GOALS and GOALS[g]]


def _category(metrics_by_key: dict, key: str) -> str | None:
    m = metrics_by_key.get(key)
    return m.get("category") if m else None


def matches(cand: dict, goals: list[str], metrics_by_key: dict) -> list[str]:
    out = []
    for g in known_goals(goals):
        spec = GOALS[g]
        key = cand.get("for")
        hit = (
            key in spec.get("metrics", ()) or _category(metrics_by_key, key) in spec.get("categories", ())
            or (cand.get("feature") == "Skin" and (spec.get("all_skin") or key in spec.get("skin", ())))
            or cand.get("type") in spec.get("types", ()) or cand.get("title") in spec.get("titles", ())
        )
        if hit:
            out.append(g)
    return out


def tier(cand: dict, metrics_by_key: dict) -> int:
    if cand.get("for") == "baseline":
        return 3
    if cand.get("feature") == "Skin":
        return 2
    m = metrics_by_key.get(cand.get("for"))
    return 0 if m and m.get("status") == "outside" else 1


def rank(cands: list[dict], metrics: list[dict], goals) -> list[dict]:
    """Stable reorder by (evidence tier, goal match, original position); annotates goal_match / ranking_reason.
    With no usable goals the list is returned unchanged (same order, annotations empty)."""
    by_key = {m["key"]: m for m in metrics}
    gl = known_goals(goals)
    out = []
    for i, c in enumerate(cands):
        hit = matches(c, gl, by_key) if gl else []
        out.append((tier(c, by_key), 0 if hit else 1, i, {**c, "goal_match": hit,
                    "ranking_reason": (f"Listed earlier within its evidence tier because it matches your goal: {', '.join(hit)}." if hit else None)}))
    if not gl:
        return [c for *_, c in out]
    return [c for *_, c in sorted(out, key=lambda t: (t[0], t[1], t[2]))]


def order_metrics(metrics: list[dict], goals) -> list[dict]:
    """Order for report sections: worst measurement first (as before); with goals, goal-related metrics first within the
    same status tier. Ideal metrics keep their place (they are skipped by the report anyway)."""
    gl = known_goals(goals)
    base = sorted(metrics, key=lambda m: m["score"])
    if not gl:
        return base
    by_key = {m["key"]: m for m in metrics}

    def related(m):
        return bool(matches({"for": m["key"], "feature": m["label"], "type": None, "title": None}, gl, by_key))
    return [m for _, _, _, m in sorted(((0 if m["status"] == "outside" else 1, 0 if related(m) else 1, i, m) for i, m in enumerate(base)), key=lambda t: t[:3])]


def alignment(goals, metrics: list[dict], skin: dict | None, candidates: list[dict], validation: dict | None = None) -> list[dict]:
    """One honest status per recognised goal. Never invents a problem to satisfy a goal."""
    by_key = {m["key"]: m for m in metrics}
    skin = skin or {}
    withheld = {s["item"] for s in (validation or {}).get("suppressed", [])}
    out = []
    for g in [x for x in (goals or []) if isinstance(x, str) and x in GOALS]:
        spec = GOALS[g]
        if not spec:
            out.append({"goal": g, "status": "no_specific_target", "supporting_metrics": []})
            continue
        related_metrics = [m for m in metrics if m["key"] in spec.get("metrics", ()) or m.get("category") in spec.get("categories", ())]
        related_skin = [c for c in skin.get("concerns", []) if spec.get("all_skin") or c["key"] in spec.get("skin", ())] if skin.get("available") else []
        goal_recs = [c for c in candidates if matches(c, [g], by_key)]
        specific = [c for c in goal_recs if c.get("for") != "baseline"]
        support = sorted({c["for"] for c in specific})
        withheld_related = sorted(w for w in withheld if w.startswith("skin:") and w.split(":", 1)[1] not in ("tone_group", "overall_score")
                                  and (spec.get("all_skin") or w.split(":", 1)[1] in spec.get("skin", ())))
        if specific:
            status = "recommendations_available"
        elif withheld_related:  # never say "nothing points to a change" when the readings were withheld, not clean
            status = "partly_unavailable" if related_metrics else "measurement_unavailable"
            support = withheld_related
        elif goal_recs:
            status = "general_recommendations_only"
        elif related_metrics or related_skin:
            status = "measurements_in_range"
            support = sorted([m["key"] for m in related_metrics] + [c["key"] for c in related_skin])
        else:
            lost = sorted(w for w in withheld if w.split(":", 1)[-1] in spec.get("skin", ()) or spec.get("all_skin") and w.startswith("skin") or w.startswith("metric:"))
            status = "measurement_unavailable"
            support = lost
        out.append({"goal": g, "status": status, "supporting_metrics": support})
    return out
