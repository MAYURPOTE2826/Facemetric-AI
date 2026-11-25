"""Hair fall analysis.

Photo part (MediaPipe multiclass selfie segmenter: background, hair, body skin, face skin,
clothes, accessories):
- front photo: hairline height (upper third vs middle third) and temple recession (how
  much higher the hairline sits above the outer eyes than at the centre);
- optional top-of-head / parting photo: share of scalp showing through the hair.
Questionnaire part: daily shedding, duration, pattern, family history, recent triggers,
dandruff, diet, periods - mapped to the common causes seen in India and the blood tests a
dermatologist usually orders. Screening only - never a diagnosis.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

from . import geometry
from .imaging import _encode

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "selfie_multiclass.tflite"
BG, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHER = range(6)

_segmenter: vision.ImageSegmenter | None = None


class HairError(Exception):
    pass


def segment(bgr: np.ndarray) -> np.ndarray:
    """Multiclass category mask (0 bg, 1 hair, 2 body skin, 3 face skin, 4 clothes, 5 other)."""
    return _segment(bgr)


def _segment(bgr: np.ndarray) -> np.ndarray:
    global _segmenter
    if _segmenter is None:
        _segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=vision.RunningMode.IMAGE,
            output_category_mask=True,
        ))
    h, w = bgr.shape[:2]
    res = _segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
    cat = np.array(res.category_mask.numpy_view()).squeeze().astype(np.uint8)
    if cat.shape[:2] != (h, w):
        cat = cv2.resize(cat, (w, h), interpolation=cv2.INTER_NEAREST)
    return cat


def _scan_up(cat: np.ndarray, x: float, y_start: float, half_w: int) -> tuple[int, str]:
    """Walk up a narrow column from y_start until hair starts. Returns (y, what_was_hit)."""
    x0, x1 = max(0, int(x) - half_w), min(cat.shape[1], int(x) + half_w + 1)
    for y in range(int(y_start), -1, -1):
        row = cat[y, x0:x1]
        if (row == HAIR).mean() > 0.5:
            return y, "hair"
        if np.isin(row, (OTHER, CLOTHES)).mean() > 0.5:
            return y, "covered"
        if (row == BG).mean() > 0.5:
            return y, "background"
    return 0, "edge"


STAGES = [
    (0, "No visible recession", 95),
    (1, "Mature hairline (normal after the late teens)", 85),
    (2, "Mild temple recession", 70),
    (3, "Moderate recession", 50),
    (4, "Advanced recession", 30),
]


def _hairline(img: np.ndarray, cat: np.ndarray, pts: np.ndarray, sex: str = "") -> tuple[dict | None, str | None, dict]:
    """Returns (hairline result | None, reason if unavailable, drawing info)."""
    bz = float(np.linalg.norm(pts[234, :2] - pts[454, :2]))
    half = max(2, int(0.02 * bz))
    glab_y, sub_y = pts[9, 1], pts[2, 1]
    mid_third = sub_y - glab_y
    y_mid, hit_mid = _scan_up(cat, pts[9, 0], glab_y, half)
    if hit_mid in ("covered",):
        return None, "Hair is covered (cap, turban or dupatta), so the hairline can't be measured.", {}
    if hit_mid == "edge":
        return None, "The top of the head is cut off in the photo, so the hairline can't be measured.", {}
    if (glab_y - y_mid) < 0.45 * mid_third and hit_mid == "hair":
        return None, "Hair covers your forehead, so the hairline can't be measured. Pull it back for this check.", {}
    bald_top = hit_mid == "background"

    temples = []
    for eye_out, brow in ((33, 70), (263, 300)):
        # The frontotemporal corner sits above the OUTER end of the brow. The old position (just inside the outer eye corner) was
        # mid-forehead, where the hairline is almost never receded, so temple recession was systematically under-detected.
        tx = pts[brow, 0] * 0.9 + pts[9, 0] * 0.1  # NOT validated against labelled photos
        ty, hit = _scan_up(cat, tx, pts[brow, 1] - 0.05 * mid_third, half)
        temples.append((tx, ty, hit))
    temple_y = float(np.mean([t[1] for t in temples]))
    ratio = (glab_y - y_mid) / mid_third
    depth = (y_mid - temple_y) / mid_third  # >0: temples sit higher than the centre
    # Real-world size from the iris (11.7 mm). Norms: hairline-to-glabella ~6.5 cm in men and
    # women (Korean/Thai studies); a mature (Norwood II) hairline recedes ~1-1.5 cm at the temples.
    k = geometry.mm_per_px(pts) / 10
    height_cm = (glab_y - y_mid) * k
    recession_cm = max(0.0, (y_mid - temple_y) * k)
    male = sex.startswith("m")

    if bald_top or recession_cm >= 3.5:
        stage = 4
    elif recession_cm >= 2.5:
        stage = 3
    elif recession_cm >= 1.5 or height_cm >= (8.0 if male else 7.5):
        stage = 2
    elif recession_cm >= 0.8 or height_cm >= 7.0:
        stage = 1
    else:
        stage = 0
    _, label, score = STAGES[stage]
    if not male and stage == 1:
        label = "Slightly high hairline (within normal range)"
    if stage == 2 and recession_cm < 1.5:
        label = "High hairline"
    temples_txt = ("your temples are level with the centre of the hairline" if recession_cm < 0.5 else
                   f"your temples sit about {recession_cm:.1f} cm higher than the centre of the hairline")
    temples_txt = ("the temple corners are level with the centre of the hairline" if recession_cm < 0.5 else
                   "the temple corners sit higher than the centre of the hairline")
    detail = (f"Visible hairline sits about {ratio:.2f} times the glabella-to-nose-base height above the glabella; {temples_txt}. "
              "Ratios to face width only - not physically calibrated and not validated. See the Hair & Hairline Analysis section for confidence.")
    if bald_top:
        detail = "No hair was found along the centre of the scalp in the photo."
    return ({"stage": stage, "label": label, "score": score, "height_ratio": round(ratio, 2),
             "temple_depth": round(depth, 2), "height_cm": round(height_cm, 1), "recession_cm": round(recession_cm, 1),
             "detail": detail}, None,
            {"mid": (pts[9, 0], y_mid), "temples": [(t[0], t[1]) for t in temples], "glab": (pts[9, 0], glab_y)})


def _draw_front(img: np.ndarray, cat: np.ndarray, pts: np.ndarray, draw: dict) -> str:
    vis = img.copy()
    overlay = vis.copy()
    overlay[cat == HAIR] = (60, 160, 230)
    vis = cv2.addWeighted(overlay, 0.25, vis, 0.75, 0)
    bz = float(np.linalg.norm(pts[234, :2] - pts[454, :2]))
    t = max(2, int(bz / 120))
    if draw:
        mx, my = map(int, draw["mid"])
        gx, gy = map(int, draw["glab"])
        cv2.line(vis, (mx, my), (gx, gy), (255, 255, 255), t)
        for tx, ty in draw["temples"]:
            cv2.circle(vis, (int(tx), int(ty)), t * 3, (60, 60, 230), -1)
            cv2.line(vis, (int(tx), int(ty)), (mx, my), (60, 60, 230), t)
        cv2.circle(vis, (mx, my), t * 3, (255, 255, 255), -1)
    hair_rows = np.where((cat == HAIR).any(axis=1))[0]
    top = int(hair_rows.min()) if len(hair_rows) else int(pts[10, 1] - 0.6 * bz)
    y0 = max(0, min(top, int(pts[10, 1] - 0.4 * bz)) - int(0.1 * bz))
    y1 = min(img.shape[0], int(pts[1, 1] + 0.1 * bz))
    x0, x1 = max(0, int(pts[234, 0] - 0.35 * bz)), min(img.shape[1], int(pts[454, 0] + 0.35 * bz))
    crop = vis[y0:y1, x0:x1]
    scale = 640 / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return _encode(crop)


HEAD_BREADTH_MM = 145.0  # adult head breadth (Indian anthropometry ~140-150 mm), the scale for top photos


def _parting(scalp: np.ndarray, hull: np.ndarray) -> dict | None:
    """Width of the parting line - the clinical sign of female-pattern thinning (Sinclair/Ludwig
    grade it by how far the part has widened; it widens most at the front, a 'Christmas tree').
    The parting is the longest thin strip of scalp; there's no iris in a top photo, so the head's
    width across the parting (~145 mm) gives the scale; an unvalidated estimate."""
    comp = cv2.morphologyEx(scalp.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(comp)
    ys, xs = np.nonzero(hull)
    span = max(np.ptp(xs), np.ptp(ys)) if len(xs) else 0
    best = None
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 30:
            continue
        pts = np.column_stack(np.nonzero(labels == i)[::-1]).astype(np.float32)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(pts)
        length, width = max(rw, rh), max(1.0, min(rw, rh))
        if length >= 0.25 * span and length / width >= 4 and (best is None or length > best[0]):
            best = (length, i, (cx, cy), ang if rw >= rh else ang + 90)
    if best is None:
        return None
    length, i, (cx, cy), ang = best
    # Rotate so the parting runs along x; per-column pixel count is the local width.
    rot = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    h, w = scalp.shape
    strip = cv2.warpAffine((labels == i).astype(np.uint8), rot, (w, h), flags=cv2.INTER_NEAREST)
    cols = strip.sum(axis=0)
    cols = cols[cols > 0].astype(np.float32)
    if len(cols) < 10:
        return None
    core = cols[int(0.1 * len(cols)):int(0.9 * len(cols))]
    width_px = float(np.median(core))
    third = max(1, len(core) // 3)
    ends = sorted([float(np.median(core[:third])), float(np.median(core[-third:]))])
    widening = ends[1] / max(ends[0], 1.0)
    # Head width across the parting, from the hair-area hull, sets the mm scale.
    hull_rot = cv2.warpAffine(hull.astype(np.uint8), rot, (w, h), flags=cv2.INTER_NEAREST)
    across = np.nonzero(hull_rot.any(axis=1))[0]
    head_px = float(np.ptp(across)) if len(across) else 0.0
    mm = width_px * HEAD_BREADTH_MM / head_px if head_px > 10 * width_px else None
    if mm is None:
        return None
    if mm <= 3:
        label, score = "Normal parting width", 90
    elif mm <= 6:
        label, score = "Slightly wide parting", 70
    elif mm <= 10:
        label, score = "Widened parting", 50
    else:
        label, score = "Markedly widened parting", 35
    tree = widening >= 1.5 and mm > 3
    detail = (f"Your parting is about {mm:.0f} mm wide (up to about 3 mm is typical)"
              + (", and it widens towards one end - a 'Christmas-tree' pattern, which is typical of female-pattern "
                 "thinning" if tree else "") + ". Estimated from your head width and not validated against physical measurements, so treat it as approximate.")
    return {"width_mm": round(mm, 1), "widening": round(widening, 2), "christmas_tree": tree, "label": label,
            "score": score, "detail": detail, "_mask": labels == i}


def analyze_top(img: np.ndarray) -> dict:
    """Scalp show-through on a top-of-head / parting photo."""
    cat = _segment(img)
    hair = (cat == HAIR).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hair)
    if n <= 1 or stats[1:, cv2.CC_STAT_AREA].max() < 0.05 * hair.size:
        raise HairError("Couldn't find enough hair in the photo. Take it from above, in good light, with the parting visible.")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    blob = (labels == biggest).astype(np.uint8)
    hull = np.zeros_like(blob)
    cv2.fillPoly(hull, [cv2.convexHull(cv2.findNonZero(blob))], 1)
    hull = cv2.erode(hull, np.ones((15, 15), np.uint8))  # ignore the outline, where background leaks in

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0] * 100 / 255
    hair_L = float(np.median(L[blob > 0]))
    scalp = np.isin(cat, (BODY_SKIN, FACE_SKIN))
    if hair_L < 45:  # dark hair: bright, skin-coloured pixels inside the hair are scalp too
        a = lab[..., 1] - 128
        scalp |= (L > hair_L + 28) & (a > 4)
    scalp &= hull > 0
    pct = 100.0 * scalp.sum() / max(hull.sum(), 1)
    if pct < 8:
        label, score = "Dense - little scalp visible", 92
    elif pct < 16:
        label, score = "Slightly visible scalp", 75
    elif pct < 28:
        label, score = "Noticeable thinning", 55
    else:
        label, score = "Marked thinning", 35

    ys, xs = np.nonzero(hull)
    regional = None
    if len(xs):
        cy, cx = ys.mean(), xs.mean()
        rad = max(np.ptp(xs), np.ptp(ys)) / 2.0
        yy, xx = np.indices(hull.shape)
        r = np.hypot(yy - cy, xx - cx) / max(rad, 1.0)
        inner, outer = (hull > 0) & (r < 0.45), (hull > 0) & (r >= 0.45)
        regional = {"central_scalp_pct": round(100.0 * (scalp & inner).sum() / max(inner.sum(), 1), 1),
                    "outer_scalp_pct": round(100.0 * (scalp & outer).sum() / max(outer.sum(), 1), 1),
                    "hair_area_fraction": round(float(hair.sum()) / hair.size, 3)}
    parting = _parting(scalp, hull)
    vis = img.copy()
    vis[scalp] = (0.4 * vis[scalp] + 0.6 * np.array([60, 60, 230])).astype(np.uint8)
    if parting:
        part = parting.pop("_mask")
        vis[part] = (0.4 * vis[part] + 0.6 * np.array([230, 160, 40])).astype(np.uint8)
        score = min(score, parting["score"])
    scale = 640 / max(vis.shape[:2])
    if scale < 1:
        vis = cv2.resize(vis, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return {"scalp_pct": round(pct, 1), "label": label, "score": score, "parting": parting, "regional": regional,
            "detail": f"About {pct:.0f}% of the hair area shows scalp (red"
                      + ("; the parting is blue" if parting else "") + "). Under ~10% is typical in good light.",
            "image": _encode(vis)}


# --- Questionnaire -> likely causes ------------------------------------------------

FALL_LEVELS = {"normal": 0, "more": 1, "lot": 2, "clumps": 3}
# Hairs lost in one wash (refined wash test: ~28 normal, ~52 pattern loss, ~126 telogen effluvium).
WASH_LEVELS = {"under50": 0, "50to100": 1, "over100": 2}

RED_FLAGS = {
    "scalp_pain": "pain, burning or shiny smooth patches on the scalp can mean a scarring hair loss that needs urgent care",
    "brows_lashes": "losing eyebrow or eyelash hair as well points to alopecia areata or frontal fibrosing alopecia",
    "androgen": "fast hair loss with acne, extra facial/body hair or a deeper voice needs a hormone check",
    "weight_loss_fever": "hair loss with unexplained weight loss or fever needs a medical check-up",
    "new_medicine": "a new medicine may be the cause - don't stop it, but ask your doctor",
    "tight_styles": "tight buns, braids or extensions can cause traction hair loss - loosen them now",
}


def _fall_level(q: dict) -> int:
    if q.get("fall") == "clumps":
        return 3
    if q.get("wash") in WASH_LEVELS:
        return WASH_LEVELS[q["wash"]]
    return FALL_LEVELS.get(q.get("fall", ""), 0)


def _causes(q: dict, sex: str, hairline: dict | None, crown: dict | None) -> tuple[list[dict], list[str], bool, list[str]]:
    male = sex.startswith("m")
    fall = _fall_level(q)
    pattern = set(q.get("pattern") or [])
    triggers = set(q.get("triggers") or [])
    flags = set(q.get("flags") or [])
    duration = {"years": "long"}.get(q.get("duration", ""), q.get("duration", ""))
    causes, tests, reasons = [], [], []

    patterned = (hairline and hairline["stage"] >= 2) or (crown and crown["score"] <= 55) or \
        pattern & {"temples", "crown", "parting"} or ((crown or {}).get("parting") or {}).get("christmas_tree")
    if q.get("short_hairs"):
        pattern.add("miniaturising")
    if patterned or (q.get("family") and duration == "long") or (q.get("short_hairs") and q.get("family")):
        causes.append({
            "key": "pattern",
            "title": "Pattern hair loss (androgenetic alopecia)" if male else "Female-pattern thinning",
            "why": ("Recession at the temples/crown" if male else "Thinning along the parting or crown")
                   + (" plus a family history" if q.get("family") else "") + " fits a genetic, hormone-driven pattern. "
                   "It is slow and progressive, so starting early matters most.",
            "actions": ["See a dermatologist - topical minoxidil is the first-line, evidence-based option; prescription "
                        "treatments are also available. Don't start or stop these without medical advice.",
                        "Take the same photos every 3 months to track it honestly."],
        })
    if triggers & {"illness", "childbirth", "crash_diet", "surgery", "stress"}:
        names = {"illness": "a recent fever or illness (dengue, typhoid, COVID)", "childbirth": "childbirth",
                 "crash_diet": "a crash diet or fast weight loss", "surgery": "surgery", "stress": "major stress"}
        what = ", ".join(names[t] for t in sorted(triggers) if t in names)
        causes.append({
            "key": "telogen",
            "title": "Shock shedding (telogen effluvium)",
            "why": f"Heavy, all-over shedding 2-3 months after {what} is very common and usually recovers by itself "
                   "in 3-6 months once the trigger is gone. If it lasts longer than 6 months, see a doctor.",
            "actions": ["Eat enough protein (dal, paneer, eggs, curd) - about 1 g per kg of body weight a day.",
                        "Be gentle: no tight buns, heat styling or chemical treatments while it settles."],
        })
    veg = q.get("diet") in ("veg", "vegan")
    if veg or fall >= 1 or (q and not causes):
        causes.append({
            "key": "nutrition",
            "title": "Nutrient gaps (iron, vitamin D" + (", vitamin B12)" if veg else ")"),
            "why": "Low iron stores (ferritin) are the most consistent finding in Indian studies of chronic shedding, and "
                   "vitamin D deficiency was found in ~80% of young Indians with hair fall."
                   + (" Vegetarian and vegan diets also raise the risk of low B12." if veg else ""),
            "actions": ["Get a blood test before taking supplements; take them only if you're low. Many hair specialists "
                        "aim for ferritin above ~40 µg/L - discuss your result with your doctor.",
                        "Iron-rich foods: green leafy vegetables, chana, rajma, jaggery with vitamin C (amla, lemon)."],
        })
    if q:
        # Baseline panel for diffuse shedding (Indian prevalence data): CBC, ferritin, TSH, vitamin D.
        tests += ["CBC (haemoglobin)", "Serum ferritin", "TSH (thyroid)", "Vitamin D (25-OH)"]
        if veg:
            tests.append("Vitamin B12")
    if fall >= 2 or "thyroid" in triggers:
        causes.append({
            "key": "thyroid",
            "title": "Thyroid imbalance",
            "why": "Both under- and over-active thyroid cause diffuse thinning and are common, especially in women.",
            "actions": ["A simple TSH blood test rules it out."],
        })
    if not male and (q.get("periods") or "androgen" in flags):
        causes.append({
            "key": "pcos",
            "title": "Hormonal (PCOS)",
            "why": "Irregular periods with thinning at the parting can point to PCOS, which affects many Indian women.",
            "actions": ["See a gynaecologist or dermatologist - PCOS is very treatable."],
        })
        tests += ["Total & free testosterone", "DHEAS", "Prolactin", "Fasting insulin / HbA1c"]
    if q.get("dandruff"):
        causes.append({
            "key": "scalp",
            "title": "Dandruff / scalp inflammation",
            "why": "An itchy, flaky scalp adds to shedding and gets worse in monsoon and winter.",
            "actions": ["Ketoconazole 2% shampoo twice a week - leave on for 5 minutes, then rinse.",
                        "Don't leave hair oil on overnight if you have dandruff; it feeds the yeast."],
        })
    if "patches" in pattern:
        reasons.append("round bald patches can be alopecia areata, which needs a dermatologist")
    if fall >= 3:
        reasons.append("hair is coming out in clumps")
    if duration == "long" and fall >= 1:
        reasons.append("shedding for more than 6 months (chronic shedding needs a proper work-up)")
    reasons += [RED_FLAGS[f] for f in RED_FLAGS if f in flags and f not in ("tight_styles", "new_medicine")]
    if hairline and hairline["stage"] >= 3:
        reasons.append("your hairline shows moderate or advanced recession")
    if crown and crown["score"] <= 55:
        reasons.append("scalp is clearly visible through the hair")
    if "tight_styles" in flags:
        causes.append({"key": "traction", "title": "Traction (tight hairstyles)", "why": RED_FLAGS["tight_styles"].capitalize() + ".",
                       "actions": ["Wear hair loose or in low, soft styles; avoid extensions and tight rubber bands."]})
    if "new_medicine" in flags:
        causes.append({"key": "medicine", "title": "A medicine side effect", "why": RED_FLAGS["new_medicine"].capitalize() + ".",
                       "actions": ["Some blood-pressure, thyroid, acne (isotretinoin) and mood medicines can cause shedding."]})
    return causes, list(dict.fromkeys(tests)), bool(reasons), reasons


MYTHS = [
    {"name": "Oiling stops hair fall", "verdict": "myth",
     "why": "Oil conditions hair and reduces breakage, but it can't stop shedding from the root. Fine to use - just not overnight with dandruff."},
    {"name": "Onion juice regrows hair", "verdict": "myth",
     "why": "One small study in patchy hair loss; no good evidence for common thinning, and it can irritate the scalp."},
    {"name": "Washing hair often causes hair fall", "verdict": "myth",
     "why": "Hairs that come out in the shower had already shed. A clean scalp is healthier - wash as often as you need."},
    {"name": "Rice water for growth", "verdict": "okay",
     "why": "May make hair feel smoother; no evidence it regrows hair. Rinse it out well."},
    {"name": "Hard water causes hair fall", "verdict": "okay",
     "why": "It can make hair rough and break more, but it doesn't cause hair loss at the root. A shower filter or a good conditioner helps it feel softer."},
    {"name": "Biotin gummies for everyone", "verdict": "myth",
     "why": "Only helps if you're actually deficient (rare), and high doses can upset thyroid blood tests."},
    {"name": "Shaving the head makes hair thicker", "verdict": "myth",
     "why": "It doesn't change the follicles; regrowing hair just has a blunt tip that feels coarser."},
]


def analyze(img: np.ndarray, face, profile: dict, top_img: np.ndarray | None = None, cat: np.ndarray | None = None) -> dict:
    sex = (profile.get("sex") or "").lower()
    q = profile.get("hair") or {}
    out: dict = {"available": True, "questionnaire": bool(q)}

    # A tighter head crop was tried and is worse: the selfie model needs the whole head and shoulders.
    cat = _segment(img) if cat is None else cat
    hairline, reason, draw = _hairline(img, cat, face.points, sex)
    out["hairline"] = hairline
    if reason:
        out["hairline_note"] = reason
    out["image"] = _draw_front(img, cat, face.points, draw)

    crown = None
    if top_img is not None:
        try:
            crown = analyze_top(top_img)
        except HairError as e:
            out["top_error"] = str(e)
    crown_raw = dict(crown) if crown else None
    if crown:
        out["top_image"] = crown.pop("image")
    out["crown"] = crown

    scores = [x["score"] for x in (hairline, crown) if x]
    fall = _fall_level(q)
    if q:
        scores.append([90, 75, 55, 35][fall])
    out["score"] = round(sum(scores) / len(scores)) if scores else None

    causes, tests, see_doctor, reasons = _causes(q, sex, hairline, crown)
    out.update(causes=causes, tests=tests, see_doctor=see_doctor, doctor_reasons=reasons, myths=MYTHS)
    plan = ["Take a front and top-of-head photo in the same light every 3 months - it's the only honest way to track hair.",
            "Gentle care: wide-tooth comb on wet hair, no tight hairstyles, minimal heat and chemical treatments."]
    if tests:
        plan.insert(0, "Get these blood tests (about ₹1,500-3,000 as a package at most labs): " + ", ".join(tests) + ".")
    if see_doctor:
        plan.insert(0, "See a dermatologist soon: " + "; ".join(reasons) + ".")
    out["plan"] = plan
    if not q:
        out["shedding_note"] = ("Hair fall (shedding) was NOT assessed: a photo cannot count the hairs you lose. You did not answer the hair questions, "
                                "so this section only shows what the photo can show. If you are losing a lot of hair, answer the hair questions "
                                "on the analysis form and see a dermatologist - do not rely on the hairline reading alone.")
    if hairline:
        out["hairline_limits"] = ("The hairline reading only looks for a receded hairline in this one photo. It can miss recession when hair is "
                                  "swept forward or up, the head is tilted, or the light is poor. 'No visible recession' is not a statement that you "
                                  "have no hair loss. Thresholds are not validated against labelled photos.")
    from . import hairline as hairline_engine  # dedicated hairline engine (additive: every legacy key above is unchanged)
    try:
        out["analysis"] = hairline_engine.build(img, cat, face.points, crown_raw, out.get("top_error"))
    except Exception as e:  # noqa: BLE001 - never fail the report; say so instead
        out["analysis"] = hairline_engine._empty(f"Hairline engine error: {type(e).__name__}")
    return out
