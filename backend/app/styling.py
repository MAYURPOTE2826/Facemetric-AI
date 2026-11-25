"""Face shape + hairstyle, beard and glasses advice.

Face shape comes from four landmark ratios (all divided by cheekbone width): face length
(mesh forehead point to chin), jaw width, forehead width and chin width. Each shape has a
prototype in z-score space; the nearest prototypes give the shape and a runner-up.
Typical values below are starting points - calibrate on real photos before launch.
"""
from __future__ import annotations

import math

import numpy as np

from . import metrics as metrics_mod

# ratio -> (typical value, spread)
TYPICAL = {"length": (1.22, 0.07), "jaw": (0.82, 0.04), "forehead": (0.84, 0.03), "chin": (0.32, 0.025)}

PROTOTYPES = {
    "oval": {"length": 0.5, "jaw": -0.3, "forehead": 0.0, "chin": -0.3},
    "round": {"length": -1.5, "jaw": 0.3, "forehead": 0.0, "chin": 0.5},
    "square": {"length": -0.7, "jaw": 1.5, "forehead": 0.3, "chin": 1.2},
    "oblong": {"length": 1.8, "jaw": 0.3, "forehead": 0.0, "chin": 0.0},
    "heart": {"length": 0.0, "jaw": -1.2, "forehead": 1.0, "chin": -1.2},
    "diamond": {"length": 0.3, "jaw": -1.2, "forehead": -1.3, "chin": -0.8},
}

SHAPES = {
    "oval": {
        "label": "Oval",
        "summary": "Balanced length and width with a softly tapering jaw - the most versatile shape.",
        "hair_m": ["Textured quiff or pompadour", "Classic side part", "Medium-length layered flow", "Short crop with a fade"],
        "hair_f": ["Long layers or a lob", "Curtain bangs", "Sleek middle part", "Soft waves at any length"],
        "avoid": ["Heavy fringes that hide your balanced proportions"],
        "beard": ["Short boxed beard", "Light stubble (3-5 mm)", "Classic full beard kept tidy at the cheeks"],
        "glasses": ["Most frames suit you - try wayfarers or rectangular frames slightly wider than your face"],
    },
    "round": {
        "label": "Round",
        "summary": "Width and length are similar with soft, curved cheeks and jaw.",
        "hair_m": ["Volume on top with short, tight sides (undercut / high fade)", "Textured quiff", "Side-swept faux hawk"],
        "hair_f": ["Long layers that fall below the chin", "Side part with face-framing layers", "High ponytail or top knot for height"],
        "avoid": ["Chin-length bobs and blunt fringes", "Volume at the sides"],
        "beard": ["Goatee or anchor beard to lengthen the face", "Boxed beard with short sides and a longer chin",
                  "Keep cheek lines sharp and high-angled"],
        "glasses": ["Rectangular or square frames to add angles", "Avoid small round frames"],
    },
    "square": {
        "label": "Square",
        "summary": "Strong, wide jaw with a forehead and cheekbones of similar width.",
        "hair_m": ["Short textured crop", "Side part with a low fade", "Slightly longer, messy top to soften the jaw"],
        "hair_f": ["Soft waves and layers around the jaw", "Side-swept bangs", "Long layers past the shoulders"],
        "avoid": ["Very blunt, geometric cuts at jaw level"],
        "beard": ["Rounded full beard or circle beard to soften corners", "Stubble that follows your natural jawline"],
        "glasses": ["Round or oval frames to soften strong angles"],
    },
    "oblong": {
        "label": "Oblong (long)",
        "summary": "Face is noticeably longer than it is wide, with fairly straight sides.",
        "hair_m": ["Side part with some fullness at the sides", "Fringe or short crop brushed forward", "Avoid tall quiffs"],
        "hair_f": ["Curtain bangs or a full fringe", "Shoulder-length waves with volume at the sides", "Lob with soft curls"],
        "avoid": ["Extra height on top", "Very long, flat, straight hair"],
        "beard": ["Fuller sides with a shorter chin (mutton-chop style or chin strap)", "Avoid long, pointed goatees"],
        "glasses": ["Deep frames or oversized frames to shorten the face"],
    },
    "heart": {
        "label": "Heart",
        "summary": "Wider forehead and cheekbones that taper to a narrower chin.",
        "hair_m": ["Medium-length side-swept styles", "Textured fringe", "Avoid very short sides with tall tops"],
        "hair_f": ["Chin-length bob or lob to add width at the jaw", "Side-swept bangs", "Waves from the mid-lengths down"],
        "avoid": ["Lots of volume at the crown and temples"],
        "beard": ["Full beard or garibaldi to add width at the jaw", "Avoid goatees that narrow the chin further"],
        "glasses": ["Bottom-heavy or rimless frames; light-coloured frames", "Avoid heavy top-line browline frames"],
    },
    "diamond": {
        "label": "Diamond",
        "summary": "Cheekbones are the widest point, with a narrower forehead and jaw.",
        "hair_m": ["Fringe or textured crop to widen the forehead", "Side-swept medium styles"],
        "hair_f": ["Side-swept bangs", "Chin-length bob", "Deep side part with volume near the jaw"],
        "avoid": ["Slicked-back styles that expose a narrow forehead", "Middle parts with flat sides"],
        "beard": ["Fuller chin beard to widen the jaw", "Keep cheeks trimmed"],
        "glasses": ["Oval or cat-eye frames; browline frames add forehead width"],
    },
}

RECEDING_HAIR = ["Short textured crop or French crop", "Buzz cut or skin fade", "Avoid slicked-back styles that show the temples"]


def _ratios(points: np.ndarray) -> dict[str, float]:
    frontal, _ = metrics_mod.frontalize(points)
    p = metrics_mod._level(frontal)
    d = lambda a, b: float(np.linalg.norm(p[a] - p[b]))  # noqa: E731
    bz = d(234, 454)
    return {"length": d(10, 152) / bz, "jaw": d(172, 397) / bz, "forehead": d(54, 284) / bz, "chin": d(176, 400) / bz}


def face_shape(points: np.ndarray) -> dict:
    r = _ratios(points)
    z = {k: (r[k] - TYPICAL[k][0]) / TYPICAL[k][1] for k in TYPICAL}
    dist = {s: math.sqrt(sum((z[k] - proto[k]) ** 2 for k in proto)) for s, proto in PROTOTYPES.items()}
    weights = {s: math.exp(-0.5 * v * v) for s, v in dist.items()}
    total = sum(weights.values()) or 1.0
    ranked = sorted(((w / total, s) for s, w in weights.items()), reverse=True)
    (p1, s1), (p2, s2) = ranked[0], ranked[1]
    return {
        "shape": s1,
        "label": SHAPES[s1]["label"],
        "secondary": s2 if p2 > 0.25 else None,
        "confidence": round(p1, 2),
        "ratios": {k: round(v, 3) for k, v in r.items()},
    }


def advice(shape: dict, profile: dict, metric_list: list[dict], hair: dict | None) -> dict:
    s = SHAPES[shape["shape"]]
    male = (profile.get("sex") or "").lower().startswith("m")
    by_key = {m["key"]: m for m in metric_list}
    hair_styles = list(s["hair_m"] if male else s["hair_f"])
    avoid = list(s["avoid"])
    beard = list(s["beard"]) if male else []
    notes = []

    receding = bool(hair and (hair.get("hairline") or {}).get("stage", 0) >= 2)
    if receding and male:
        hair_styles = RECEDING_HAIR + hair_styles[:1]
        notes.append("Your temples show some recession, so we picked cuts that keep it low-key - shorter sides and "
                     "texture on top look fuller than length.")
    jaw = by_key.get("jaw_zygo")
    if male and jaw and jaw["direction"] == "low":
        beard.insert(0, "A boxed beard with a crisp jawline edge adds width and definition to a slimmer jaw")
    if male:  # chin-length advice must agree with the measurements and with the grooming recommendations
        from .consistency import reconcile_beard_styles
        beard, chin_notes = reconcile_beard_styles(beard, metric_list)
        notes.extend(chin_notes)
    if male:
        notes.append("Patchy beard? Give it 6-8 weeks of growth before judging; keep the neckline a finger-width above "
                     "the Adam's apple and the cheek line natural or slightly lowered.")
    if shape.get("secondary"):
        notes.append(f"Your shape also leans {SHAPES[shape['secondary']]['label'].lower()}, so tips for that shape can work too.")
    return {
        **shape,
        "summary": s["summary"],
        "hairstyles": hair_styles,
        "avoid": avoid,
        "beard": beard,
        "glasses": s["glasses"],
        "notes": notes,
    }
