"""Personal AM/PM skincare routine with products available in India.

Ingredient-first: each step is chosen from the person's skin concerns, skin type and
budget, then filled with well-known products sold in India. Prices are shown as bands,
not exact MRPs (they change often) - keep this catalogue reviewed. Links go to
Nykaa / Amazon search; set AMAZON_ASSOCIATE_TAG to earn affiliate commission.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus

AMAZON_TAG = os.getenv("AMAZON_ASSOCIATE_TAG", "")

BANDS = {"budget": "Under ₹400", "mid": "₹400–900", "premium": "₹900+"}
TIER_ORDER = ["budget", "mid", "premium"]

# (name, tier) per ingredient/product type. Names are search terms as much as products.
CATALOGUE: dict[str, list[tuple[str, str]]] = {
    "cleanser_gentle": [("Simple Refreshing Facial Wash", "budget"), ("Cetaphil Gentle Skin Cleanser", "mid"),
                        ("CeraVe Hydrating Cleanser", "premium")],
    "cleanser_oily": [("Minimalist Salicylic Acid + LHA 2% Cleanser", "budget"), ("Cetaphil Oily Skin Cleanser", "mid"),
                      ("CeraVe Foaming Cleanser", "premium")],
    "sunscreen_matte": [("Minimalist SPF 50 Sunscreen", "budget"), ("Re'equil Ultra Matte Dry Touch Sunscreen Gel SPF 50", "mid"),
                        ("La Roche-Posay Anthelios UVMune 400 Invisible Fluid", "premium")],
    # Iron-oxide tinted sunscreens block visible light, which darkens melasma/pigmentation in brown skin
    # (RCT 2025). Most brands don't state iron-oxide content - search terms more than exact products.
    "sunscreen_tinted": [("Tinted sunscreen SPF 50 PA++++ iron oxides", "budget"), ("ISDIN Fusion Water Color SPF 50", "premium"),
                         ("La Roche-Posay Anthelios Tinted SPF 50", "premium")],
    "sunscreen_hydrating": [("The Derma Co 1% Hyaluronic Sunscreen Aqua Gel SPF 50", "budget"), ("La Shield Sunscreen Gel SPF 40", "mid"),
                            ("Bioderma Photoderm Cream SPF 50+", "premium")],
    "moisturiser_gel": [("Plum Green Tea Oil-Free Moisturizer", "budget"), ("Neutrogena Hydro Boost Water Gel", "mid"),
                        ("CeraVe Oil Control Moisturising Gel-Cream", "premium")],
    "moisturiser_cream": [("Simple Kind to Skin Hydrating Light Moisturiser", "budget"), ("Cetaphil Moisturising Cream", "mid"),
                          ("CeraVe Moisturising Cream", "premium")],
    "niacinamide": [("Minimalist Niacinamide 10% Serum", "budget"), ("The Derma Co 10% Niacinamide Serum", "budget"),
                    ("The Ordinary Niacinamide 10% + Zinc 1%", "mid")],
    "vitamin_c": [("Minimalist Vitamin C 10% Serum", "budget"), ("Plum 15% Vitamin C Face Serum", "mid"),
                  ("La Roche-Posay Pure Vitamin C10 Serum", "premium")],
    "salicylic": [("Minimalist Salicylic Acid 2% Serum", "budget"), ("The Derma Co 2% Salicylic Acid Serum", "budget"),
                  ("Paula's Choice 2% BHA Liquid Exfoliant", "premium")],
    "azelaic": [("Minimalist Azelaic Acid 10% Serum", "budget"), ("The Ordinary Azelaic Acid Suspension 10%", "mid")],
    "pigment": [("Minimalist Alpha Arbutin 2% Serum", "budget"), ("Minimalist Tranexamic Acid 3% Serum", "budget"),
                ("The Ordinary Alpha Arbutin 2% + HA", "mid")],
    "retinol": [("Minimalist Retinol 0.3% Serum", "budget"), ("The Ordinary Retinol 0.5% in Squalane", "mid"),
                ("La Roche-Posay Retinol B3 Serum", "premium")],
    "lactic": [("Minimalist Lactic Acid 10% Serum", "budget"), ("The Ordinary Lactic Acid 10% + HA", "mid")],
    "eye": [("mCaffeine Coffee Under Eye Cream", "budget"), ("The Ordinary Caffeine Solution 5% + EGCG", "mid")],
    "spot": [("Benzoyl peroxide 2.5% gel (pharmacy)", "budget")],
}

BUDGET_TIER = {
    "Minimal (under ₹500/month)": "budget",
    "₹500–1,500/month": "budget",
    "₹1,500–3,000/month": "mid",
    "₹3,000+/month": "premium",
}


def _links(name: str) -> dict:
    q = quote_plus(name)
    amazon = f"https://www.amazon.in/s?k={q}" + (f"&tag={AMAZON_TAG}" if AMAZON_TAG else "")
    return {"nykaa": f"https://www.nykaa.com/search/result/?q={q}", "amazon": amazon}


def _picks(kind: str, tier: str) -> list[dict]:
    """Best match for the budget tier, plus a cheaper swap when there is one."""
    items = CATALOGUE[kind]
    rank = TIER_ORDER.index(tier)
    within = [i for i in items if TIER_ORDER.index(i[1]) <= rank] or items[:1]
    main = within[-1]
    picks = [main]
    cheaper = [i for i in items if TIER_ORDER.index(i[1]) < TIER_ORDER.index(main[1])]
    if cheaper:
        picks.append(cheaper[0])
    return [{"name": n, "tier": t, "price_band": BANDS[t], "swap": i > 0, "links": _links(n)} for i, (n, t) in enumerate(picks)]


def _step(time: str, step: str, kind: str, why: str, tier: str, how: str = "Daily") -> dict:
    return {"time": time, "step": step, "kind": kind, "why": why, "how": how, "products": _picks(kind, tier)}


# Steps a person can report as irritating at a check-in; cleanser/moisturiser/SPF are swapped, not dropped.
ACTIVE_KINDS = {"niacinamide", "vitamin_c", "salicylic", "azelaic", "pigment", "retinol", "lactic", "spot", "eye"}


REMOVAL_STATUS = "GENERAL INFORMATION - NOT CLINICALLY REVIEWED"


def removals(am: list[dict], pm: list[dict], safety: set, on_isotretinoin: bool, barrier_reset: bool) -> dict:
    """What to take OUT of the routine. `stop_now`: things that clash with the products above (drop them when you start).
    `step_down`: things to reduce later, once the skin has settled. Built only from steps actually in this routine."""
    kinds = {s["kind"] for s in am + pm}
    has = lambda *k: bool(kinds & set(k))  # noqa: E731
    stop = [{"item": "Harsh scrubs and face brushes", "why": "They strip the barrier your routine is trying to protect and make actives sting."},
            {"item": "Extra cleansing (more than twice a day)", "why": "Over-washing dries skin and can make oil and breakouts worse."},
            {"item": "Old products you used before, with the same active", "why": "Doubling up (for example two acids) is the commonest cause of irritation. Keep one product per job."}]
    if has("retinol"):
        stop.append({"item": "Acid toners, peels and exfoliating pads on retinol nights", "why": "Retinol and acids on the same night irritate; alternate nights."})
    if has("salicylic", "lactic"):
        stop.append({"item": "Other exfoliating acids or scrubs", "why": "Your routine already has one exfoliating step."})
    if has("vitamin_c", "pigment", "azelaic"):
        stop.append({"item": "Home lemon, toothpaste or baking-soda remedies", "why": "They burn skin and can leave darker marks."})
    if "steroid_history" in safety:
        stop.append({"item": "Steroid or 'fairness' creams", "why": "Stop gradually with a dermatologist's help - stopping suddenly can cause a flare."})
    step = []
    if has("retinol", "salicylic", "lactic", "azelaic", "pigment", "vitamin_c"):
        step.append({"item": "Treatment serums, once skin is clear and steady", "when": "After about 8-12 weeks of daily use with good results",
                     "why": "Cut back to fewer nights (or one serum) to maintain results; keep cleanser, moisturiser and sunscreen."})
    if has("spot"):
        step.append({"item": "Spot treatment", "when": "When no active pimples remain", "why": "Use only on new pimples; it is not a daily step."})
    if has("eye"):
        step.append({"item": "Under-eye product", "when": "If you see no change after about 8 weeks", "why": "Dark circles often come from sleep, genes or pigment that cream will not shift; see a doctor if worried."})
    if len(am) + len(pm) > 8:
        step.append({"item": "Any step you skip most days", "when": "Anytime", "why": "A shorter routine you keep up beats a long one you do not."})
    never = "Sunscreen, gentle cleanser and moisturiser are not removed - they stay in every stage."
    note = None
    if on_isotretinoin or barrier_reset:
        note = "Your routine is already reduced for safety right now; do not add anything back until your dermatologist or the check-in says so."
    return {"status": REMOVAL_STATUS, "stop_now": stop, "step_down": step, "keep": never, "note": note}


def build(skin: dict, profile: dict, climate: dict | None = None, feedback: dict | None = None) -> dict | None:
    """`feedback`: the latest 6-8 week check-in for this report ({irritation, irritating: [kinds],
    progress: better|same|worse, consistency: daily|sometimes|stopped, weeks})."""
    if not skin.get("available"):
        return None
    c = {x["key"]: x["score"] for x in skin.get("concerns", [])}
    bad = lambda k, t=70: c.get(k, 100) < t  # noqa: E731
    tier = BUDGET_TIER.get(profile.get("budget", ""), "budget")
    skin_type = (profile.get("skin_type") or "").lower()
    if not skin_type:
        skin_type = "oily" if bad("shine", 80) else "normal"
    oily = skin_type in ("oily", "combination")
    sensitive = skin_type == "sensitive" or bad("redness")
    climate = climate or {}
    # Season decides texture: gel in heat/humidity, cream in dry winters (dry skin never gets a gel).
    moist = {"gel": "moisturiser_gel", "cream": "moisturiser_cream"}.get(climate.get("moisturiser") or "")
    if not moist or (moist == "moisturiser_gel" and skin_type == "dry"):
        moist = "moisturiser_gel" if oily else "moisturiser_cream"
    spf = {"matte": "sunscreen_matte", "hydrating": "sunscreen_hydrating"}.get(climate.get("sunscreen") or "")
    if not spf:
        spf = "sunscreen_matte" if oily else "sunscreen_hydrating"
    light = moist == "moisturiser_gel"
    safety = set(profile.get("safety") or [])
    pregnant = bool(safety & {"pregnant", "breastfeeding"})
    on_isotretinoin = "isotretinoin" in safety
    pigment = bad("pigmentation") or bad("dark_spots") or bad("acne_marks")
    if pigment:
        spf = "sunscreen_tinted"
    fb = feedback or {}
    irritating = set(fb.get("irritating") or []) & ACTIVE_KINDS
    # Irritation without knowing which product: pause every active and repair the barrier first.
    barrier_reset = bool(fb.get("irritation")) and not irritating
    if fb.get("irritation"):
        sensitive = True

    am = [
        _step("AM", "Cleanse", "cleanser_oily" if oily and not sensitive else "cleanser_gentle",
              "Clears overnight oil without stripping." if oily else "Gentle cleanse that protects your skin barrier.", tier),
    ]
    if on_isotretinoin:
        pass  # actives are managed by the dermatologist during isotretinoin
    elif pigment or (bad("uneven_tone") and sensitive):
        # Niacinamide has better, gentler evidence for marks/pigmentation than vitamin C.
        am.append(_step("AM", "Even tone & protect", "niacinamide",
                        "Helps fade marks and patches and calms skin - well tolerated on melanin-rich skin.", tier))
    elif bad("uneven_tone"):
        am.append(_step("AM", "Even tone & protect", "vitamin_c",
                        "Antioxidant that helps tan fade and boosts your sunscreen.", tier))
    elif oily or bad("blemishes") or bad("texture"):
        am.append(_step("AM", "Balance", "niacinamide", "Controls oil, refines pores and evens tone.", tier))
    if barrier_reset or (len(am) > 1 and am[1]["kind"] in irritating):
        am = am[:1]
    am.append(_step("AM", "Moisturise", moist,
                    "Lightweight hydration for heat and humidity." if light else "Keeps the barrier strong.", tier))
    am.append(_step("AM", "Sunscreen", spf,
                    ("Tinted SPF 50, PA+++ or PA++++: the tint (iron oxides) also blocks visible light, which darkens "
                     "pigmentation in brown skin. " if spf == "sunscreen_tinted" else
                     "SPF 50, PA+++ or PA++++: the most important step for tan, marks and ageing in Indian sun. ") +
                    "Use two finger-lengths for face and neck; reapply every 2-3 hours outdoors.", tier))

    # One strong active per night, chosen by the biggest concern.
    actives = []
    if bad("blemishes"):
        actives.append(("salicylic", "Clear pores", "Unclogs pores and calms breakouts.", "2-3 nights a week"))
    if bad("pigmentation") or bad("acne_marks") or bad("dark_spots"):
        kind = "azelaic" if (bad("acne_marks") or sensitive) else "pigment"
        actives.append((kind, "Fade marks", "Fades pigmentation and post-acne marks - gentle on melanin-rich skin.", "Every night"))
    if (bad("wrinkles") or bad("texture")) and not sensitive and not pregnant:
        actives.append(("retinol", "Renew", "Smooths texture and fine lines. Start slowly; never on the same night as acids.", "2-3 nights a week"))
    if pregnant:
        actives = [a for a in actives if a[0] not in ("salicylic", "retinol")]
        if bad("blemishes") and not any(a[0] == "azelaic" for a in actives):
            actives.insert(0, ("azelaic", "Clear pores", "Azelaic acid is considered safe in pregnancy and helps breakouts and marks.", "Every night"))
    if on_isotretinoin:
        actives = []
    if bad("uneven_tone") and not actives and not on_isotretinoin:
        actives.append(("lactic", "Gentle exfoliation", "Helps tan fade faster without harsh scrubbing.", "1-2 nights a week"))
    actives = [a for a in actives if a[0] not in irritating]
    if barrier_reset:
        actives = []
    # Tolerating everything, using it daily, but no visible change yet: add the next waiting active.
    level_up = (fb.get("progress") == "same" and not fb.get("irritation") and fb.get("consistency") == "daily"
                and len(actives) > 2)
    n_actives = 3 if level_up else 2

    pm = [_step("PM", "Cleanse", "cleanser_gentle", "Removes sunscreen, sweat and pollution.", tier,
                "Daily - double-cleanse with micellar water first on high-pollution days"
                if climate.get("pollution") else "Daily (double-cleanse with oil or micellar water if you wore makeup)")]
    for kind, step, why, how in actives[:n_actives]:
        pm.append(_step("PM", step, kind, why, tier, how))
    if bad("blemishes", 60) and not on_isotretinoin and not barrier_reset and "spot" not in irritating:
        pm.append(_step("PM", "Spot treat", "spot", "On active pimples only, never the whole face.", tier, "As needed"))
    if bad("dark_circles") and "eye" not in irritating:
        pm.append(_step("PM", "Under-eyes", "eye", "Caffeine reduces puffiness and shadows.", tier))
    pm.append(_step("PM", "Moisturise", moist, "Repairs overnight.", tier))

    notes = [
        "Introduce one new product every 1-2 weeks and patch-test behind the ear first.",
        "If you use two actives, alternate nights instead of layering them.",
    ]
    if pregnant:
        notes.insert(0, "Pregnancy/breastfeeding: we left out retinol and salicylic acid serums. Check every new product with your doctor.")
    if on_isotretinoin:
        notes.insert(0, "You're on isotretinoin: keep to a gentle cleanser, rich moisturiser, lip balm and sunscreen - no acids, "
                        "retinol or scrubs. Your dermatologist manages the acne.")
    if "steroid_history" in safety:
        notes.append("You've used steroid or 'fairness' creams before: stop them gradually with a dermatologist's help - "
                     "stopping suddenly can cause a flare. Never restart them for pigmentation.")
    if profile.get("sun") in ("two_wheeler", "outdoor"):
        notes.append("You're out in the sun a lot: reapply sunscreen every 2-3 hours, and use a full-face helmet visor, "
                     "cap or dupatta - sunscreen alone isn't enough.")
    if len(actives) > n_actives:
        notes.append("You have several concerns - we started with the two biggest. Add the next one after 6-8 weeks.")
    if fb:
        if barrier_reset:
            notes.insert(0, "Updated after your check-in: something irritated your skin, so we paused all serums and "
                            "treatments. Use only cleanser, moisturiser and sunscreen for 2 weeks, then add back one "
                            "product at a time, every 1-2 weeks.")
        elif irritating:
            notes.insert(0, "Updated after your check-in: we removed what irritated your skin ("
                            + ", ".join(sorted(k.replace("_", " ") for k in irritating)) + ") and switched to gentler "
                            "options. If redness, burning or peeling continues after stopping, see a dermatologist.")
        if level_up:
            notes.insert(0, "Updated after your check-in: your skin is handling the routine well, so we added the next "
                            "treatment. Introduce it 2-3 nights a week first.")
        if fb.get("progress") == "worse":
            notes.insert(0, "You said your skin is getting worse. Please see a dermatologist - and stop any product that "
                            "stings, burns or makes you break out.")
        elif fb.get("progress") == "same" and fb.get("consistency") != "daily":
            notes.insert(0, "Most routines need 8-12 weeks of daily use to show results - consistency matters more "
                            "than adding products.")
    if climate.get("season_label"):
        notes.insert(0, f"Tuned for {climate['season_label'].lower()} in {climate['city']} - "
                        "this routine updates automatically when the season changes.")
    return {
        "skin_type": skin_type,
        "tier": tier,
        "am": am,
        "pm": pm,
        "notes": notes,
        "removals": removals(am, pm, safety, on_isotretinoin, barrier_reset),
        "disclaimer": "Price bands are approximate and change often - check before buying. We are brand-neutral; "
                      "links may earn us a small commission at no cost to you.",
    }
