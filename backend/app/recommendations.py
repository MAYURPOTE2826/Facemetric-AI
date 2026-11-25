"""Curated library of non-surgical methods, keyed by metric + direction.

This is the core IP of the product - expand it with expert input. Each entry:
(title, type, detail, cost, timeline). type: grooming | makeup | skincare | lifestyle | professional
"""
from __future__ import annotations

Method = tuple[str, str, str, str, str]

LIBRARY: dict[str, dict[str, list[Method]]] = {
    "canthal_tilt": {
        "low": [
            ("Lift the outer brow with grooming", "grooming", "Shape brows so the tail sits slightly higher than the head; brow lamination can help hold it.", "$", "1-2 weeks"),
            ("Upswept eyeliner / lash curling", "makeup", "A subtle upward flick at the outer corner visually raises the eye's tilt.", "$", "Immediate"),
            ("Reduce under-eye puffiness", "lifestyle", "7-9h sleep, lower evening salt and alcohol, cold compress in the morning.", "$", "2-4 weeks"),
            ("Brow-lift neuromodulator consult", "professional", "A small dose of neuromodulator can lift the brow tail. Discuss with a licensed injector.", "$$$", "2 weeks, lasts 3-4 months"),
        ],
    },
    "eye_aspect": {
        "low": [
            ("Curl lashes and tightline", "makeup", "Opens the eye visually and adds apparent height.", "$", "Immediate"),
            ("Treat allergies and sleep debt", "lifestyle", "Puffy lids and squinting reduce visible eye height.", "$", "1-4 weeks"),
        ],
        "high": [
            ("Soft lower-lash definition", "makeup", "Balances very round eyes by elongating the outer third.", "$", "Immediate"),
        ],
    },
    "intercanthal_eye": {
        "low": [("Brighten inner corners", "makeup", "Light shimmer at inner corners and brow heads spaced slightly apart makes eyes read wider-set.", "$", "Immediate")],
        "high": [("Define inner brows and corners", "grooming", "Bring brow heads slightly closer and darken inner lash line to visually close the gap.", "$", "1-2 weeks")],
    },
    "esr": {
        "low": [("Widen upper-face framing", "grooming", "Hairstyles with volume at the temples balance close-set features.", "$", "Next haircut")],
        "high": [("Frame centre of the face", "grooming", "Defined brow heads and a centre-weighted hairstyle balance wide-set eyes.", "$", "Next haircut")],
    },
    "fwhr": {
        "low": [
            ("Add width at the cheekbones", "makeup", "Highlight high on the cheekbones; for men, keep beard sides fuller.", "$", "Immediate"),
            ("Build facial definition through body composition", "lifestyle", "Reaching a healthy body-fat range sharpens cheekbones and jaw.", "$", "2-6 months"),
        ],
        "high": [("Add vertical emphasis", "grooming", "Hairstyles with height on top and shorter sides elongate a wide face.", "$", "Next haircut")],
    },
    "midface_ratio": {
        "low": [
            ("Hairstyle with side volume", "grooming", "A long midface looks more compact with volume at the sides and a soft fringe.", "$", "Next haircut"),
            ("Moustache / beard styling (men)", "grooming", "A well-groomed moustache visually shortens the space between nose and lip.", "$", "4-8 weeks"),
        ],
    },
    "thirds_lower_mid": {
        "low": [
            ("Elongate the lower face", "grooming", "A beard with length at the chin (men) or contour under the chin adds lower-third height.", "$", "4-8 weeks"),
            ("Chin projection consult", "professional", "Chin filler can add lower-third length. Discuss with a licensed provider.", "$$$", "Immediate, lasts 12-18 months"),
        ],
        "high": [("Soften lower-face length", "grooming", "Keep beard short at the chin and fuller at the sides; contour the chin tip.", "$", "2-4 weeks")],
    },
    "lower_third_split": {
        # value < 0.5 means the mouth-to-chin section is LONG relative to nose-to-mouth, so the fix is to avoid extra
        # chin length and add balance above the mouth (this entry previously advised adding chin height - backwards).
        "low": [("Balance lip-to-chin height", "grooming", "Your mouth-to-chin section is long relative to the nose-to-mouth section. Keep beard length at the chin short; a fuller moustache or well-defined upper lip adds balance above the mouth.", "$", "2-8 weeks")],
        "high": [("Balance upper lip area", "makeup", "Slight overline of the upper lip's cupid's bow reduces apparent philtrum length.", "$", "Immediate")],
    },
    "nose_intercanthal": {
        "high": [
            ("Nose contouring", "makeup", "Soft shading along the sides of the nose narrows its apparent width.", "$", "Immediate"),
            ("Non-surgical rhinoplasty consult", "professional", "Filler can refine nose shape in some cases. Licensed provider only.", "$$$", "Immediate, lasts 9-18 months"),
        ],
    },
    "mouth_nose": {
        "low": [("Extend the lip line", "makeup", "Lip liner slightly past the natural corners widens the smile.", "$", "Immediate")],
    },
    "lip_ratio": {
        "low": [
            ("Define lower lip volume", "makeup", "Gloss or a lighter shade at the centre of the lower lip adds fullness.", "$", "Immediate"),
            ("Lip hydration routine", "skincare", "Nightly occlusive balm and gentle exfoliation keep lips plump.", "$", "1-2 weeks"),
        ],
        "high": [
            ("Balance the upper lip", "makeup", "Define the cupid's bow and slightly overline the upper lip.", "$", "Immediate"),
            ("Upper lip filler consult", "professional", "A small amount of upper-lip filler balances the ratio. Licensed provider only.", "$$$", "Immediate, lasts 6-12 months"),
        ],
    },
    "jaw_zygo": {
        "low": [
            ("Lower body-fat to reveal jawline", "lifestyle", "Jaw definition improves noticeably at a healthy body-fat %.", "$", "2-6 months"),
            ("Beard shaping for width (men)", "grooming", "Keep beard fuller at the jaw angles and tighter on the cheeks.", "$", "4-8 weeks"),
            ("Jaw contouring makeup", "makeup", "Shade under the jaw and highlight the jaw angle.", "$", "Immediate"),
            ("Jawline filler consult", "professional", "Filler at the jaw angle can add width. Licensed provider only.", "$$$$", "Immediate, lasts 12-18 months"),
        ],
        "high": [
            ("Soften jaw width", "grooming", "Longer hair around the jaw and a beard tapered at the sides soften a wide jaw.", "$", "Next haircut"),
            ("Masseter neuromodulator consult", "professional", "Can slim a wide jaw caused by masseter bulk. Licensed provider only.", "$$$", "4-8 weeks, lasts 4-6 months"),
        ],
    },
    # --- Side profile -------------------------------------------------------
    "convexity": {
        "low": [
            ("Chin-forward grooming (men)", "grooming", "A beard kept slightly longer and squared at the chin adds forward chin projection.", "$", "4-8 weeks"),
            ("Chin contouring", "makeup", "Highlight the centre of the chin and shade beneath it to bring the chin forward visually.", "$", "Immediate"),
            ("Upright head and neck posture", "lifestyle", "Forward-head posture makes the chin look recessed. Strengthen the upper back and keep ears over shoulders.", "$", "4-8 weeks"),
            ("Chin projection consult", "professional", "Chin filler or an implant can balance a convex profile. Discuss with a licensed provider.", "$$$", "Immediate, filler lasts 12-18 months"),
        ],
        "high": [
            ("Soften a straight or concave profile", "grooming", "Keep chin hair short; a fuller moustache or volume at the crown balances a strong chin.", "$", "2-4 weeks"),
        ],
    },
    "nasolabial": {
        "low": [("Nose-tip contouring", "makeup", "A touch of highlight on the nose tip and shading under it visually lifts a drooping tip.", "$", "Immediate")],
        "high": [("Soften an upturned tip", "makeup", "Light shading on the underside of the tip reduces how upturned it looks.", "$", "Immediate")],
    },
    "nasofrontal": {
        "low": [("Soften a deep nasal bridge", "makeup", "Light highlight on the bridge between the eyes softens a deep nasion.", "$", "Immediate")],
        "high": [
            ("Define the nasal bridge", "makeup", "Shade either side of the upper bridge to add definition between brow and nose.", "$", "Immediate"),
            ("Glasses with a defined bridge", "grooming", "Frames with a higher, structured bridge add visual depth.", "$$", "Immediate"),
        ],
    },
    "nasofacial": {
        "high": [
            ("Balance a prominent nose", "grooming", "Fuller hair volume at the back of the head and a defined chin balance nasal projection.", "$", "Next haircut"),
            ("Non-surgical rhinoplasty consult", "professional", "Filler can smooth a dorsal hump and balance projection. Licensed provider only.", "$$$", "Immediate, lasts 9-18 months"),
        ],
        "low": [("Add nasal definition", "makeup", "Highlight down the bridge and on the tip to increase apparent projection.", "$", "Immediate")],
    },
    "nasomental": {
        "low": [("Balance nose and chin", "grooming", "Strengthening the chin's look (beard shaping or contouring) reduces how prominent the nose appears.", "$", "2-8 weeks")],
    },
    "e_line_upper": {
        "high": [("Balance fuller lips", "makeup", "Matte, mid-tone lip colours and liner just inside the lip line soften lip projection.", "$", "Immediate")],
        "low": [
            ("Add lip definition", "makeup", "Lip liner on the border and a gloss at the centre add apparent projection.", "$", "Immediate"),
            ("Lip hydration routine", "skincare", "Nightly balm and gentle exfoliation keep lips full and smooth.", "$", "1-2 weeks"),
        ],
    },
    "e_line_lower": {
        "high": [("Balance a forward lower lip", "makeup", "Use a slightly deeper shade on the lower lip and keep the upper lip brighter.", "$", "Immediate")],
    },
    "cervicomental": {
        "high": [
            ("Reduce body-fat for jaw-neck definition", "lifestyle", "The under-chin area is one of the first places definition returns at a healthier body-fat %.", "$", "2-6 months"),
            ("Posture: chin slightly forward, neck long", "lifestyle", "Standing tall with the head stacked over the shoulders sharpens the jaw-neck angle in photos and everyday life.", "$", "Immediate"),
            ("Beard neckline (men)", "grooming", "Set the beard neckline about a finger-width above the Adam's apple to create a crisp jaw-neck edge.", "$", "1 week"),
            ("Submental fat treatment consult", "professional", "Injectable fat-reduction or radiofrequency treatments can define the under-chin area. Licensed provider only.", "$$$$", "2-4 months"),
        ],
    },
    "gonial_angle": {
        "high": [
            ("Lower body-fat to sharpen the jaw corner", "lifestyle", "The jaw angle looks steeper and softer with fat over the jaw corner; a healthy body-fat range sharpens it.", "$", "2-6 months"),
            ("Beard shaped to square the jaw (men)", "grooming", "Keep the beard fuller and squarer at the jaw corners and short on the cheeks to create a more defined angle.", "$", "4-8 weeks"),
            ("Contour the jaw corner", "makeup", "Shade just below the jaw corner and along the jawline; highlight the angle itself.", "$", "Immediate"),
            ("Jaw-angle filler consult", "professional", "Filler at the jaw corner can create a sharper angle. Licensed provider only.", "$$$$", "Immediate, lasts 12-18 months"),
        ],
        "low": [
            ("Soften a very square jaw", "grooming", "Longer, textured hair around the jaw and rounder frames soften a sharp jaw angle.", "$", "Next haircut"),
            ("Masseter neuromodulator consult", "professional", "If jaw muscles are bulky, a neuromodulator can soften the jaw corner. Licensed provider only.", "$$$", "4-8 weeks, lasts 4-6 months"),
        ],
    },
    "mentocervical": {
        "low": [("Lengthen the jaw-neck line", "lifestyle", "Neck posture and a lean under-chin area open this angle.", "$", "4-12 weeks")],
    },
    "symmetry": {
        "high": [
            ("Balance with brow shaping and hair parting", "grooming", "Shaping each brow to match and parting hair to the fuller side reduces visible asymmetry.", "$", "1-2 weeks"),
            ("Photo angles that flatter", "grooming", "Turn slightly towards your fuller side in photos. Habits like chewing on one side "
             "may help photos but don't change bone structure.", "$", "Immediate"),
        ],
    },
}

SKIN: dict[str, list[Method]] = {
    "wrinkles": [
        ("Retinoid at night", "skincare", "Start 2-3 nights a week with a low-strength retinoid (or bakuchiol if sensitive); the best-evidenced topical for fine lines.", "$$", "8-12 weeks"),
        ("Daily SPF 30-50", "skincare", "UV causes most visible skin ageing; daily sunscreen stops lines deepening.", "$", "Ongoing"),
        ("Neuromodulator consult for expression lines", "professional", "Forehead and crow's-feet lines soften with a neuromodulator. Licensed provider only.", "$$$", "2 weeks, lasts 3-4 months"),
    ],
    "blemishes": [
        ("Salicylic acid (BHA) 2-3x a week", "skincare", "Clears pores and calms breakouts; pair with a non-comedogenic moisturiser.", "$", "4-8 weeks"),
        ("Benzoyl peroxide spot treatment", "skincare", "Use 2.5-5% on active spots only, at night.", "$", "1-2 weeks per spot"),
        ("Dermatologist for persistent acne", "professional", "Recurring or cystic acne responds well to prescription treatment.", "$$", "Varies"),
    ],
    "dark_spots": [
        ("Daily SPF 30-50", "skincare", "The single most effective step against new and darkening spots.", "$", "8-12 weeks"),
        ("Vitamin C, niacinamide or azelaic acid", "skincare", "Brighten and even out spots over time.", "$$", "8-12 weeks"),
    ],
    "dark_circles": [
        ("Sleep, hydration and allergy control", "lifestyle", "Fatigue, dehydration and allergies all darken the under-eye area.", "$", "2-4 weeks"),
        ("Caffeine or vitamin C eye cream", "skincare", "Can reduce puffiness and brighten mild pigmentation.", "$", "4-8 weeks"),
        ("Colour-correcting concealer", "makeup", "A peach or orange corrector under concealer neutralises blue-purple shadows.", "$", "Immediate"),
    ],
    "redness": [
        ("Barrier-repair routine", "skincare", "Gentle cleanser, niacinamide serum, ceramide moisturiser; avoid harsh scrubs and fragrance.", "$", "4-8 weeks"),
        ("See a dermatologist if persistent", "professional", "Ongoing redness can be rosacea or dermatitis and may need prescription care.", "$$", "Varies"),
    ],
    "texture": [
        ("Chemical exfoliation (AHA/BHA)", "skincare", "1-2x weekly to smooth texture and clear pores.", "$", "4-6 weeks"),
        ("Retinoid at night", "skincare", "Refines texture and pore appearance over time.", "$$", "8-12 weeks"),
    ],
    "uneven_tone": [
        ("SPF 50 PA++++ every morning, reapplied outdoors", "skincare", "Tan and uneven tone are mostly UV; a broad-spectrum sunscreen (two finger-lengths for face and neck) is the single biggest fix.", "$", "4-8 weeks"),
        ("Niacinamide 5-10% serum", "skincare", "Evens tone and fades tan gently; suits oily and humid-climate skin.", "$", "6-10 weeks"),
        ("Gentle exfoliation 1-2x a week", "skincare", "A mild AHA (lactic/mandelic) helps tan fade faster - avoid harsh scrubs, which darken melanin-rich skin.", "$", "4-6 weeks"),
        ("Avoid bleach and 'fairness' creams", "lifestyle", "Bleach and unlabelled fairness creams can contain steroids or mercury and cause thinning, rebound pigmentation and acne.", "$", "Ongoing"),
    ],
    "pigmentation": [
        ("Daily SPF 50 + reapply", "skincare", "Pigmentation and melasma worsen with every unprotected day in the sun - including through windows and screens.", "$", "Ongoing"),
        ("Azelaic acid, alpha arbutin or tranexamic acid", "skincare", "Evidence-backed, gentle pigment fighters that suit Indian skin; introduce one at a time.", "$$", "8-12 weeks"),
        ("Never use steroid creams on your face", "lifestyle", "Creams with clobetasol, betamethasone or mometasone (often sold OTC for pigmentation) cause steroid damage, rebound marks and acne.", "$", "Ongoing"),
        ("Dermatologist for melasma", "professional", "Persistent patches may be melasma, which needs a supervised plan (e.g. prescription triple-combination cream for a limited time).", "$$", "Varies"),
    ],
    "acne_marks": [
        ("Don't pick or squeeze", "lifestyle", "Picking is the biggest cause of dark marks in melanin-rich skin.", "$", "Ongoing"),
        ("Azelaic acid 10% or niacinamide", "skincare", "Fade post-acne marks (PIH) while calming new breakouts.", "$", "8-12 weeks"),
        ("Daily sunscreen", "skincare", "UV darkens existing marks - SPF makes every other treatment work faster.", "$", "Ongoing"),
    ],
    "shine": [
        ("Gel moisturiser + niacinamide", "skincare", "Lightweight hydration and niacinamide help regulate oil.", "$", "2-4 weeks"),
        ("Blotting papers / mattifying primer", "makeup", "Controls shine through the day without stripping skin.", "$", "Immediate"),
    ],
}

BASELINE: list[Method] = [
    ("Sleep 7-9 hours consistently", "lifestyle", "Reduces puffiness and dark circles and improves skin tone.", "$", "2-4 weeks"),
    ("Daily sunscreen", "skincare", "Prevents premature ageing and pigmentation.", "$", "Ongoing"),
    ("Hydration and lower sodium", "lifestyle", "Less facial water retention and puffiness.", "$", "1-2 weeks"),
]


def _as_dict(m: Method) -> dict:
    title, type_, detail, cost, timeline = m
    return {"title": title, "type": type_, "detail": detail, "cost": cost, "timeline": timeline}


def candidates(metrics: list[dict], skin: dict, profile: dict | None = None) -> list[dict]:
    return candidates_audited(metrics, skin, profile)[0]


def candidates_audited(metrics: list[dict], skin: dict, profile: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Methods relevant to this person's measurements, ordered by priority, minus anything unsafe
    for them (procedures for under-18s, retinoids in pregnancy, peels on isotretinoin...)."""
    from .report import unsafe_for
    out = []
    for m in sorted(metrics, key=lambda m: m["score"]):
        if m["status"] == "ideal":
            continue
        for method in LIBRARY.get(m["key"], {}).get(m["direction"], []):
            out.append({"for": m["key"], "feature": m["label"], "direction": m["direction"],
                        "rationale": f"{m.get('label', m['key'])} measured {m.get('value')} {m.get('unit', '')} vs a reference of about {m.get('ideal', '?')} ({str(m['status']).replace('_', ' ')}).",
                        **_as_dict(method)})
    if skin.get("available"):
        for c in skin.get("concerns", []):  # worst first
            if c["score"] < 70:
                out.extend({"for": c["key"], "feature": "Skin", "direction": None,
                            "rationale": f"{c.get('label', c['key'])} scored {c['score']}/100 ({c.get('severity', '')}).", **_as_dict(x)} for x in SKIN.get(c["key"], []))
    out.extend({"for": "baseline", "feature": "General", "direction": None,
                "rationale": "General foundation habit - not tied to one of your measurements.", **_as_dict(x)} for x in BASELINE)
    # The same method can help several concerns (e.g. a retinoid); list it once per feature.
    seen: set[tuple[str, str]] = set()
    unique = []
    for c in out:
        if (c["feature"], c["title"]) not in seen and not unsafe_for(profile, c):
            seen.add((c["feature"], c["title"]))
            unique.append(c)
    from .consistency import resolve  # deterministic conflict resolution + traceability fields
    from .personalization import rank
    kept, suppressed = resolve(unique, metrics)            # conflicts first: a goal can never bring a suppressed item back
    ranked = rank(kept, metrics, (profile or {}).get("goals"))  # goals only reorder what the measurements already support
    for i, c in enumerate(ranked):
        c["priority"] = i + 1
    return ranked, suppressed
