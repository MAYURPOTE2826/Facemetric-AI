"""Hairline & hair-density SCREENING engine (classical computer vision; no new model, no new dependency).

NOT a medical tool. It describes what is visible in a photograph. It never diagnoses, never names a condition, never says
"healthy hair" or "no hair loss", and every number carries a confidence or is marked NOT ASSESSABLE.

PIPELINE (front photo)
  1. FACE FRAME     Landmarks anchor a resolution-independent frame: origin = glabella, unit = bizygomatic width (bz),
                    u axis along the line through the outer eye corners (so head roll is removed), v axis up. Landmarks are
                    only the frame; they are never used to place the hairline.
  2. QUALITY GATE   resolution, blur, exposure, skin/hair contrast, head turn, fringe / covered forehead, hairline outside frame.
  3. BOUNDARY       For 25 columns across the forehead, scan upwards from just above the brow and find the hair<->skin boundary
                    with TWO independent cues: (A) the selfie multiclass segmenter (hair vs face skin) and (B) colour: where
                    pixels become closer to the hair colour than to the forehead-skin colour. Agreement -> high confidence;
                    disagreement or an unusable cue (hair colour close to skin) -> lower confidence. Columns with no boundary
                    (covered / off-frame) are left out; nothing is invented.
  4. CURVE          The valid columns form the hairline curve in face-frame coordinates (u, v) - comparable across photos.
  5. TEMPLES        left/right: depth of the hairline above the centre (normalised by bz), local angle, density, confidence.
  6. SHAPE          descriptive only (straight / rounded / mature / M / V / irregular / asymmetric / insufficient visibility).
  7. SYMMETRY       mirrored columns compared; small asymmetry is normal and is not called a finding.
  8. DENSITY        in a band just above the hairline (frontal, left temple, right temple): share of pixels that are scalp.
  9. CROWN          only from a top-of-head photo; from a front photo the crown is NOT_ASSESSABLE (never inferred).
 10. LONGITUDINAL   compare(): curves of two analyses in the face frame, refused unless capture conditions are comparable.

ALL THRESHOLDS BELOW ARE PLACEHOLDERS. No labelled hairline data exists, so detection accuracy is NOT MEASURED
(docs/HAIRLINE_VALIDATION.md). No millimetres or centimetres are reported: ratios to face width only.
"""
from __future__ import annotations

import cv2
import numpy as np

from .imaging import _encode

BG, HAIR, BODY_SKIN, FACE_SKIN, CLOTHES, OTHER = range(6)
ENGINE_VERSION = "hairline-engine-v1"
VALIDATION_STATUS = "Hairline detection accuracy: NOT MEASURED (no labelled dataset; thresholds are placeholders)"

COLUMNS = np.linspace(-0.5, 0.5, 25)
# PLACEHOLDER thresholds, in units of bizygomatic width (bz ~ 13.5 cm, so 0.1 ~ 1.4 cm). Unvalidated.
T_MILD, T_POSSIBLE, T_PRONOUNCED = 0.06, 0.11, 0.185
MIN_CONTRAST_DE = 18.0
FORBIDDEN_WORDS = ("alopecia", "androgenetic", "telogen", "diagnos", "minoxidil", "finasteride", "deficien", "hormon",
                   "healthy hair", "no hair loss", "you have")


# --------------------------------------------------------------------------- face frame
class Frame:
    def __init__(self, pts: np.ndarray):
        p = np.asarray(pts, dtype=np.float64)[:, :2]
        self.p = p
        self.o = p[9]
        self.bz = float(np.linalg.norm(p[234] - p[454]))
        eu = p[263] - p[33]
        n = float(np.linalg.norm(eu))
        self.eu = eu / n if n > 1e-6 else np.array([1.0, 0.0])
        self.ev = np.array([self.eu[1], -self.eu[0]])  # "up"
        self.roll_deg = float(np.degrees(np.arctan2(self.eu[1], self.eu[0])))

    def xy(self, u, v):
        u, v = np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)
        return (self.o[0] + self.bz * (u * self.eu[0] + v * self.ev[0]), self.o[1] + self.bz * (u * self.eu[1] + v * self.ev[1]))

    def uv(self, idx):
        d = (self.p[idx] - self.o) / self.bz
        return float(d @ self.eu), float(d @ self.ev)

    def yaw_proxy(self) -> float:
        a, b = self.p[1, 0] - self.p[234, 0], self.p[454, 0] - self.p[1, 0]
        return float(abs(a - b) / self.bz)


def _sample(arr: np.ndarray, x: np.ndarray, y: np.ndarray, fill=-1):
    h, w = arr.shape[:2]
    xi, yi = np.rint(x).astype(int), np.rint(y).astype(int)
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    out = np.full(x.shape + arr.shape[2:], fill, dtype=arr.dtype)
    out[ok] = arr[yi[ok], xi[ok]]
    return out, ok


def _de(lab: np.ndarray, ref: np.ndarray) -> np.ndarray:
    return np.linalg.norm(lab.astype(np.float32) - ref.astype(np.float32), axis=-1)


def _run_start(flag: np.ndarray, r: int) -> int | None:
    """Index where `flag` is True for r consecutive samples (first such index)."""
    if len(flag) < r:
        return None
    c = np.convolve(flag.astype(int), np.ones(r, int), mode="valid")
    hit = np.nonzero(c >= r)[0]
    return int(hit[0]) if len(hit) else None


# --------------------------------------------------------------------------- references
def _references(img_lab: np.ndarray, cat: np.ndarray, fr: Frame):
    """Skin colour from forehead skin pixels, hair colour from hair pixels (both Lab). None when unavailable."""
    uu, vv = np.meshgrid(np.linspace(-0.3, 0.3, 24), np.linspace(0.0, 0.22, 12))
    x, y = fr.xy(uu, vv)
    lab, ok = _sample(img_lab, x, y)
    cl, _ = _sample(cat, x, y, fill=255)
    skin_px = lab[(cl == FACE_SKIN) & ok]
    skin = np.median(skin_px, axis=0) if len(skin_px) >= 40 else None
    hair_px = img_lab[cat == HAIR]
    hair = np.median(hair_px, axis=0) if len(hair_px) >= 200 else None
    return skin, hair


# --------------------------------------------------------------------------- boundary detection
def _brow_v(fr: Frame, u: float) -> float:
    pts = sorted(fr.uv(i) for i in (70, 105, 334, 300))
    us, vs = zip(*pts)
    return float(np.interp(u, us, vs))


def detect_boundary(img: np.ndarray, cat: np.ndarray, fr: Frame):
    """Per-column hairline estimate. Returns (columns, context)."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    skin_ref, hair_ref = _references(lab, cat, fr)
    contrast = float(np.linalg.norm(skin_ref - hair_ref)) if skin_ref is not None and hair_ref is not None else 0.0
    cue_b = contrast >= MIN_CONTRAST_DE
    r = max(3, int(0.02 * fr.bz))
    step = 1.0 / fr.bz
    vs = np.arange(0.0, 1.6, step)
    cols = []
    for u in COLUMNS:
        v0 = max(0.10, _brow_v(fr, float(u)) + 0.04)
        v = vs[vs >= v0]
        x, y = fr.xy(np.full_like(v, u), v)
        lbl, ok = _sample(cat, x, y, fill=255)
        outside = ~ok
        col = {"u": float(u), "v": None, "conf": 0.0, "hit": None, "cue_a": None, "cue_b": None, "agree": None}
        first_out = int(np.argmax(outside)) if outside.any() else None
        lim = first_out if first_out is not None else len(v)
        l_ = lbl[:lim]
        # covered by cap / cloth / accessory
        cov = _run_start(np.isin(l_, (OTHER, CLOTHES)), r)
        ia = _run_start(l_ == HAIR, r)
        if cov is not None and (ia is None or cov < ia):
            col["hit"] = "covered"
            cols.append(col)
            continue
        ib = None
        if cue_b and lim > r:
            sl, _ = _sample(lab, x[:lim], y[:lim])
            hairlike = (_de(sl, hair_ref) < _de(sl, skin_ref))
            hairlike = cv2.medianBlur(hairlike.astype(np.uint8).reshape(-1, 1), 3).ravel().astype(bool) if lim >= 3 else hairlike
            ib = _run_start(hairlike, r)
        if ia is None and ib is None:
            col["hit"] = "edge" if first_out is not None else "none"
            cols.append(col)
            continue
        va = float(v[ia]) if ia is not None else None
        vb = float(v[ib]) if ib is not None else None
        col["cue_a"], col["cue_b"] = va, vb
        if va is not None and vb is not None:
            col["agree"] = abs(va - vb) <= 0.035
            col["v"], col["conf"] = ((va + vb) / 2, 0.9) if col["agree"] else (va, 0.4)
        elif va is not None:
            col["v"], col["conf"] = va, (0.55 if not cue_b else 0.4)
        else:
            col["v"], col["conf"] = vb, 0.4
        col["hit"] = "boundary"
        cols.append(col)
    # one-column outliers are replaced by the neighbours' median (and lose confidence)
    for i in range(1, len(cols) - 1):
        a, b, c = cols[i - 1], cols[i], cols[i + 1]
        if b["v"] is not None and a["v"] is not None and c["v"] is not None:
            med = float(np.median([a["v"], b["v"], c["v"]]))
            if abs(b["v"] - med) > 0.08:
                b["v"], b["conf"] = med, min(b["conf"], 0.3)
    return cols, {"skin_ref": skin_ref, "hair_ref": hair_ref, "contrast": contrast, "cue_b_usable": bool(cue_b), "lab": lab}


def _curve(cols):
    return [c for c in cols if c["v"] is not None and c["conf"] > 0]


def _vat(curve, u):
    return float(np.interp(u, [c["u"] for c in curve], [c["v"] for c in curve]))


# --------------------------------------------------------------------------- quality gate
def quality_gate(img: np.ndarray, cat: np.ndarray, fr: Frame, cols, ctx, curve) -> dict:
    flags: list[str] = []
    res = float(np.clip(fr.bz / 300.0, 0, 1))
    if fr.bz < 150:
        flags.append("low_resolution")
    # blur: Laplacian variance of the head crop rescaled so bz = 300 px (scale independent)
    xs = [fr.xy(u, v) for u in (-0.7, 0.7) for v in (-0.2, 1.0)]
    px = [int(np.clip(a, 0, img.shape[1] - 1)) for a, _ in xs]
    py = [int(np.clip(b, 0, img.shape[0] - 1)) for _, b in xs]
    crop = cv2.cvtColor(img[min(py):max(py) + 1, min(px):max(px) + 1], cv2.COLOR_BGR2GRAY)
    if crop.size > 100:
        s = 300.0 / fr.bz
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        lapv = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    else:
        lapv = 0.0
    blur = float(np.clip((lapv - 15) / 45, 0, 1))
    if blur < 0.35:
        flags.append("blurry")
    # exposure on the forehead + head
    uu, vv = np.meshgrid(np.linspace(-0.3, 0.3, 20), np.linspace(0.05, 0.3, 10))
    x, y = fr.xy(uu, vv)
    L, ok = _sample(ctx["lab"][..., 0], x, y)
    L = L[ok]
    blown = float((L > 235).mean()) if L.size else 0.0
    dark = float((L < 25).mean()) if L.size else 0.0
    mean_L = float(L.mean()) if L.size else 0.0
    expo = float(np.clip(1 - 2.5 * max(blown, dark), 0, 1))
    if blown > 0.12:
        flags.append("overexposed")
    if dark > 0.12 or mean_L < 60:
        flags.append("too_dark")
    hair_L = ctx["lab"][..., 0][cat == HAIR]
    glossy = float((hair_L > np.median(hair_L) + 80).mean()) if hair_L.size else 0.0
    if glossy > 0.04:
        flags.append("glossy_or_wet_hair_or_strong_overhead_light")
    contrast = ctx["contrast"]
    if not ctx["cue_b_usable"]:
        flags.append("hair_colour_close_to_skin")
    yaw = fr.yaw_proxy()
    if yaw > 0.15:
        flags.append("head_turned")
    # forehead visibility / fringe
    band_u, band_v = np.meshgrid(np.linspace(-0.35, 0.35, 20), np.linspace(0.14, 0.34, 10))
    bx, by = fr.xy(band_u, band_v)
    bl, bok = _sample(cat, bx, by, fill=255)
    skin_frac = float(((bl == FACE_SKIN) | (bl == BODY_SKIN))[bok].mean()) if bok.any() else 0.0
    fringe = skin_frac < 0.5
    if fringe:
        flags.append("fringe_or_hair_over_forehead")
    covered = sum(1 for c in cols if c["hit"] == "covered")
    if covered >= 6:
        flags.append("headwear_or_covering")
    off = sum(1 for c in cols if c["hit"] == "edge")
    if off >= 6:
        flags.append("hairline_outside_frame")
    # boundary roughness (curly / textured / clumped hair)
    if len(curve) >= 8:
        vv_ = np.array([c["v"] for c in curve])
        rough = float(np.std(np.diff(vv_, 2)))
        if rough > 0.045:
            flags.append("irregular_boundary_textured_or_styled_hair")
    valid_frac = len(curve) / len(cols)
    hairline_visible = (valid_frac >= 0.6 and not fringe and "headwear_or_covering" not in flags
                        and "hairline_outside_frame" not in flags and bool(curve))
    side = lambda lo, hi: [c for c in curve if lo <= abs(c["u"]) <= hi]  # noqa: E731
    t_left = [c for c in side(0.28, 0.5) if c["u"] > 0]
    t_right = [c for c in side(0.28, 0.5) if c["u"] < 0]
    temples_visible = {"left": len(t_left) >= 3 and hairline_visible, "right": len(t_right) >= 3 and hairline_visible}
    cscore = float(np.clip(contrast / 30.0, 0, 1)) if ctx["cue_b_usable"] else 0.5
    conf = min(res, max(blur, 0.05), expo) * (0.5 + 0.5 * cscore) * (1.0 if hairline_visible else 0.3)
    if yaw > 0.15:
        conf *= 0.5
    if "irregular_boundary_textured_or_styled_hair" in flags:
        conf *= 0.7
    overall = round(100 * (0.35 * res + 0.30 * blur + 0.20 * expo + 0.15 * cscore) * (1.0 if hairline_visible else 0.4))
    return {"overall_score": int(overall), "confidence": round(float(np.clip(conf, 0, 1)), 2), "hairline_visible": bool(hairline_visible),
            "temples_visible": temples_visible, "crown_visible": False, "flags": flags,
            "occlusion": {"forehead_skin_visible_fraction": round(skin_frac, 2), "fringe": bool(fringe),
                          "covered_columns": covered, "off_frame_columns": off},
            "components": {"resolution": round(res, 2), "sharpness": round(blur, 2), "exposure": round(expo, 2),
                           "skin_hair_contrast": round(float(contrast), 1), "head_turn_proxy": round(yaw, 3)},
            "mean_forehead_lightness": round(mean_L, 1)}


# --------------------------------------------------------------------------- shape / temples / symmetry
def _side_depth(curve, sign):
    vc = float(np.median([c["v"] for c in curve if abs(c["u"]) <= 0.12])) if any(abs(c["u"]) <= 0.12 for c in curve) else None
    lat = [c for c in curve if 0.28 <= c["u"] * sign <= 0.46]
    if vc is None or len(lat) < 3:
        return None, None, vc
    v_lat = float(np.median([c["v"] for c in lat]))
    ordered = sorted(lat, key=lambda c: c["u"] * sign)
    slope = (ordered[-1]["v"] - ordered[0]["v"]) / max(1e-6, abs(ordered[-1]["u"] - ordered[0]["u"]))
    return v_lat - vc, float(np.degrees(np.arctan(slope))), vc


def _recession_status(depth):
    if depth is None:
        return "not_assessable"
    if depth >= T_PRONOUNCED:
        return "pronounced_possible_recession_pattern"
    if depth >= T_POSSIBLE:
        return "possible_recession_pattern"
    if depth >= T_MILD:
        return "mildly_mature_temple_shape"
    return "no_obvious_recession"


STATUS_TEXT = {
    "no_obvious_recession": "No obvious recession detected in this image.",
    "mildly_mature_temple_shape": "Mildly higher temple corner - a common, mature-looking hairline shape.",
    "possible_recession_pattern": "Possible temple recession pattern detected.",
    "pronounced_possible_recession_pattern": "Possible temple recession pattern detected (more pronounced).",
    "not_assessable": "Not assessable in this image.",
}


def classify_shape(curve, d_left, d_right, visible: bool) -> dict:
    if not visible or len(curve) < 8 or d_left is None or d_right is None:
        return {"label": "insufficient_visibility", "text": "Hairline shape cannot be described: too little of it is visible."}
    vs = np.array([c["v"] for c in curve if abs(c["u"]) <= 0.42])
    centre = _vat(curve, 0.0)
    near = np.mean([_vat(curve, -0.12), _vat(curve, 0.12)])
    lat = np.mean([_vat(curve, -0.40), _vat(curve, 0.40)])
    rng = float(vs.max() - vs.min())
    both = min(d_left, d_right)
    if abs(d_left - d_right) > 0.08:
        label = "asymmetric"
    elif both >= T_POSSIBLE:
        label = "m_shaped"
    elif both >= T_MILD:
        label = "mildly_mature"
    elif centre - near >= 0.04 and centre - lat >= 0.04:
        label = "v_shaped"
    elif centre - lat >= 0.06:
        label = "rounded"
    elif rng < 0.05:
        label = "relatively_straight"
    else:
        label = "irregular"
    text = {"relatively_straight": "Relatively straight hairline.", "rounded": "Rounded hairline.",
            "mildly_mature": "Mildly mature / temple-shaped hairline.", "m_shaped": "M-shaped appearance.",
            "v_shaped": "V-shaped appearance (central peak).", "irregular": "Irregular outline.",
            "asymmetric": "Left and right sides differ."}[label]
    return {"label": label, "text": text + " This describes shape only; a mature hairline is common and is not by itself hair loss."}


def symmetry(curve, conf) -> dict:
    pairs = []
    for c in curve:
        if c["u"] > 0.05:
            m = [k for k in curve if abs(k["u"] + c["u"]) < 1e-6]
            if m:
                pairs.append(abs(c["v"] - m[0]["v"]))
    if len(pairs) < 4:
        return {"score": None, "left_right_difference": None, "confidence": 0.0, "note": "Not enough of both sides is visible."}
    d = float(np.mean(pairs))
    return {"score": int(round(100 * (1 - min(1.0, d / 0.15)))), "left_right_difference": round(d, 3), "confidence": round(conf, 2),
            "note": "Small left/right differences are normal; this is not a finding by itself."}


# --------------------------------------------------------------------------- density
def region_density(cat, lab, fr: Frame, curve, u0, u1, dv0=0.01, dv1=0.13, skin_ref=None, hair_ref=None) -> dict | None:
    if not curve:
        return None
    uu = np.linspace(u0, u1, 28)
    dv = np.linspace(dv0, dv1, 12)
    U, D = np.meshgrid(uu, dv)
    base = np.array([_vat(curve, float(u)) for u in uu])
    V = base[None, :] + D
    x, y = fr.xy(U, V)
    lbl, ok = _sample(cat, x, y, fill=255)
    if ok.sum() < 0.6 * ok.size:
        return None
    lbl = lbl[ok]
    hair = float((lbl == HAIR).mean())
    scalp = float(np.isin(lbl, (FACE_SKIN, BODY_SKIN)).mean())
    L, _ = _sample(lab[..., 0], x, y)
    return {"hair_coverage": round(hair, 3), "scalp_visibility": round(scalp, 3), "local_contrast": round(float(L[ok].std()), 1)}


def _density_view(reg, qconf, flags, short):
    if reg is None:
        return {"status": "not_assessable", "score": None, "scalp_visibility": None, "confidence": 0.0}
    sv = reg["scalp_visibility"]
    score = int(round(100 * (1 - min(1.0, sv / 0.4))))
    conf = qconf
    if short:
        conf *= 0.4
    if "glossy_or_wet_hair_or_strong_overhead_light" in flags:
        conf *= 0.6
    if "hair_colour_close_to_skin" in flags:
        conf *= 0.6
    if sv < 0.08:
        status = "no_reduced_visible_density_detected"
    elif sv < 0.2:
        status = "slightly_reduced_visible_density"
    else:
        status = "reduced_visible_density_detected"
    if conf < 0.25:
        status = "inconclusive"
    return {"status": status, "score": score, "scalp_visibility": round(sv, 3), "hair_coverage": reg["hair_coverage"],
            "local_contrast": reg["local_contrast"], "confidence": round(float(np.clip(conf, 0, 1)), 2)}


DENSITY_TEXT = {
    "no_reduced_visible_density_detected": "No reduced visible density detected in this region of this image.",
    "slightly_reduced_visible_density": "Slightly more scalp visible than expected in this region.",
    "reduced_visible_density_detected": "Reduced visible density detected in this region.",
    "inconclusive": "Inconclusive: the photo conditions do not allow a reliable density reading.",
    "not_assessable": "Not assessable.",
}


# --------------------------------------------------------------------------- crown
def crown_view(top: dict | None, top_error: str | None) -> dict:
    """The crown is assessed ONLY from a top-of-head photo. A front photo never produces a crown reading."""
    if top is None and not top_error:
        return {"status": "not_assessable", "reason": "No top-of-head photo was provided; the crown cannot be inferred from a front photo.",
                "density": None, "confidence": 0.0}
    if top is None:
        return {"status": "inconclusive", "reason": f"The top-of-head photo could not be used: {top_error}", "density": None, "confidence": 0.0}
    pct = float(top.get("scalp_pct", 0))
    reg = top.get("regional") or {}
    conf = 0.7 if not reg.get("hair_area_fraction", 1) < 0.1 else 0.3
    status = "assessed"
    parting = top.get("parting")
    out = {"status": status, "scalp_visibility_pct": round(pct, 1),
           "density": {"score": int(round(100 * (1 - min(1.0, pct / 40.0)))),
                       "text": ("No reduced visible density detected at the crown in this image." if pct < 10 else
                                "Slightly more scalp visible at the crown." if pct < 20 else
                                "Reduced visible density detected at the crown.")},
           "confidence": round(conf, 2), "regional": reg or None,
           "parting": ({"visible": True, "relative_width_of_head": round(parting.get("width_mm", 0) / 145.0, 3),
                        "widens_towards_one_end": bool(parting.get("christmas_tree")), "confidence": 0.4,
                        "note": "Width relative to head width; not a calibrated measurement."} if parting else
                       {"visible": False, "confidence": conf})}
    return out


# --------------------------------------------------------------------------- guidance
def guidance(a: dict) -> list[str]:
    g: list[str] = []
    q = a["image_quality"]
    if not q["hairline_visible"]:
        g.append("The hairline could not be seen clearly. Retake in daylight with dry hair in its natural position, forehead uncovered and no cap.")
    flags = set(q["flags"])
    if flags & {"fringe_or_hair_over_forehead", "headwear_or_covering", "glossy_or_wet_hair_or_strong_overhead_light", "irregular_boundary_textured_or_styled_hair"}:
        g.append("Styling or lighting reduced confidence. Repeat the photo with natural dry hair, no styling product and soft daylight.")
    sym = a["hairline"].get("symmetry") or {}
    if sym.get("score") is not None and sym["score"] < 75:
        g.append("Some left/right difference is visible. Mild asymmetry is common; track it with repeat photos in the same conditions rather than acting on one image.")
    t = a["temples"]
    if any(t[s]["status"] in ("possible_recession_pattern", "pronounced_possible_recession_pattern") for s in ("left", "right")):
        g.append("A possible temple recession pattern was seen. If hair loss is persistent or getting worse, consider discussing it with a dermatologist.")
    d = a["frontal_density"]
    if d["status"] in ("slightly_reduced_visible_density", "reduced_visible_density_detected") and d["confidence"] >= 0.3:
        g.append("Reduced visible density was seen at the front. Monitor with repeat photos; if it persists or progresses, consider professional evaluation.")
    if a["crown"]["status"] == "not_assessable":
        g.append("Add a top-of-head photo for crown and parting assessment.")
    g.append("Take a front and a top-of-head photo in the same light every 3 months to track change.")
    return g


LIMITATIONS = [
    "This is a screening of one photograph, not a medical assessment. It does not diagnose any condition.",
    "A hairline reading says nothing about hair fall (shedding): a photo cannot count the hairs you lose.",
    "Hair styling, fringe, product, wet hair, lighting and head angle change the result; these lower confidence rather than count as findings.",
    "Distances are ratios to face width, not physically calibrated measurements. Thresholds are unvalidated placeholders.",
    "Hairline detection accuracy: NOT MEASURED. Angled temple photos are recommended but are not analysed yet (NOT IMPLEMENTED).",
]


# --------------------------------------------------------------------------- orchestration
def _empty(reason: str, flags=None) -> dict:
    q = {"overall_score": 0, "confidence": 0.0, "hairline_visible": False, "temples_visible": {"left": False, "right": False},
         "crown_visible": False, "flags": flags or [], "occlusion": {}, "components": {}}
    a = {"engine": ENGINE_VERSION, "status": "inconclusive", "reason": reason, "validation_status": VALIDATION_STATUS,
         "hairline": {"status": "not_detected", "confidence": 0.0, "points": [], "shape": {"label": "insufficient_visibility", "text": reason},
                      "symmetry": {"score": None, "left_right_difference": None, "confidence": 0.0}, "ratios": None},
         "temples": {s: {"status": "not_assessable", "text": STATUS_TEXT["not_assessable"], "depth_normalized": None, "angle_deg": None,
                         "density": None, "confidence": 0.0} for s in ("left", "right")},
         "frontal_density": {"status": "not_assessable", "score": None, "scalp_visibility": None, "confidence": 0.0},
         "crown": crown_view(None, None), "image_quality": q, "longitudinal": {"status": "not_available"},
         "capture": {"front": True, "top": False, "angled_temples": "recommended - not analysed yet"}, "limitations": LIMITATIONS}
    a["guidance"] = guidance(a)
    return a


def build(img: np.ndarray, cat: np.ndarray, pts: np.ndarray | None, top: dict | None = None, top_error: str | None = None) -> dict:
    """Full screening result. Never raises for bad input: it returns an inconclusive result instead."""
    if pts is None or len(pts) < 468 or img is None or img.size == 0:
        return _empty("No usable face was found, so the hairline cannot be assessed.")
    fr = Frame(pts)
    if fr.bz < 40:
        return _empty("The face is too small in the photo to assess the hairline.", ["low_resolution"])
    cols, ctx = detect_boundary(img, cat, fr)
    curve = _curve(cols)
    q = quality_gate(img, cat, fr, cols, ctx, curve)
    flags = q["flags"]
    qconf = q["confidence"]
    if not curve:
        out = _empty("No hairline boundary could be found in the photo.", flags)
        out["image_quality"] = q | {"overall_score": q["overall_score"]}
        out["crown"] = crown_view(top, top_error)
        out["guidance"] = guidance(out)
        return out
    d_left, ang_left, vc = _side_depth(curve, +1)
    d_right, ang_right, _ = _side_depth(curve, -1)
    dens_ref = dict(skin_ref=ctx["skin_ref"], hair_ref=ctx["hair_ref"])
    short = False
    if vc is not None:  # thickness of hair above the centre hairline
        x, y = fr.xy(np.zeros(60), vc + np.linspace(0.02, 0.6, 60))
        l_, ok = _sample(cat, x, y, fill=255)
        run = np.nonzero((l_ != HAIR) | (~ok))[0]
        thick = (run[0] if len(run) else 60) * (0.58 / 60)
        short = bool(thick < 0.10)
        if short:
            flags.append("very_short_hair")
    visible = q["hairline_visible"]
    side_conf = {}
    for name, sign, ok_ in (("left", +1, q["temples_visible"]["left"]), ("right", -1, q["temples_visible"]["right"])):
        cs = [c["conf"] for c in curve if 0.28 <= c["u"] * sign <= 0.46]
        side_conf[name] = float(np.mean(cs)) * qconf / 0.9 if cs and ok_ else 0.0
        side_conf[name] = float(np.clip(side_conf[name], 0, 1))
    temples = {}
    for name, depth, ang, ulo, uhi in (("left", d_left, ang_left, 0.28, 0.5), ("right", d_right, ang_right, -0.5, -0.28)):
        assessable = q["temples_visible"][name] and depth is not None
        st = _recession_status(depth) if assessable else "not_assessable"
        reg = region_density(cat, ctx["lab"], fr, curve, min(ulo, uhi), max(ulo, uhi), **dens_ref) if assessable else None
        temples[name] = {"status": st, "text": STATUS_TEXT[st], "depth_normalized": round(depth, 3) if assessable else None,
                         "angle_deg": round(ang, 1) if assessable and ang is not None else None,
                         "density": _density_view(reg, side_conf[name], flags, short), "confidence": round(side_conf[name], 2)}
    front_reg = region_density(cat, ctx["lab"], fr, curve, -0.3, 0.3, **dens_ref) if visible else None
    frontal = _density_view(front_reg, qconf, flags, short)
    # a temple much emptier than the front is reported as a local pattern, never as a diagnosis
    for n in ("left", "right"):
        td, fd = temples[n]["density"], frontal
        if td and td.get("scalp_visibility") is not None and fd.get("scalp_visibility") is not None:
            td["relative_to_front"] = round(td["scalp_visibility"] - fd["scalp_visibility"], 3)
    shape = classify_shape(curve, d_left, d_right, visible)
    sym = symmetry(curve, qconf)
    h_ratio = vc
    face_h = (vc * fr.bz + float(np.linalg.norm(fr.p[152] - fr.p[9]))) if vc is not None else None
    ratios = ({"hairline_to_glabella_ratio": round(vc, 3), "hairline_to_face_height_ratio": round(vc * fr.bz / face_h, 3),
               "temple_recession_ratio": {"left": temples["left"]["depth_normalized"], "right": temples["right"]["depth_normalized"]},
               "unit": "ratios to face width (bizygomatic); not physically calibrated"} if vc is not None else None)
    hl_conf = float(np.mean([c["conf"] for c in curve])) * (len(curve) / len(cols)) * (qconf / 0.9 if qconf < 0.9 else 1.0)
    hl_status = "detected" if visible else "not_reliably_visible"
    crown = crown_view(top, top_error)
    q["crown_visible"] = crown["status"] == "assessed"
    n_temples = sum(1 for s in ("left", "right") if temples[s]["status"] != "not_assessable")
    if not visible:
        status = "inconclusive"
    elif crown["status"] == "assessed" and n_temples == 2:
        status = "complete"
    else:
        status = "partial"
    result = {
        "engine": ENGINE_VERSION, "status": status, "validation_status": VALIDATION_STATUS,
        "hairline": {"status": hl_status, "confidence": round(float(np.clip(hl_conf, 0, 1)), 2),
                     "points": [{"u": round(c["u"], 3), "v": round(c["v"], 3), "confidence": round(c["conf"], 2)} for c in curve],
                     "shape": shape, "symmetry": sym, "ratios": ratios,
                     "observation": ("Visible hairline boundary traced across the forehead." if visible else
                                     "The hairline could not be traced reliably in this photo.")},
        "temples": temples, "frontal_density": frontal | {"text": DENSITY_TEXT[frontal["status"]]},
        "crown": crown, "image_quality": q, "longitudinal": {"status": "not_available"},
        "capture": {"front": True, "top": top is not None, "angled_temples": "recommended - not analysed yet"},
        "frame": {"roll_deg": round(fr.roll_deg, 1), "unit": "u,v in bizygomatic widths; origin glabella; v up"},
        "limitations": LIMITATIONS,
    }
    for n in ("left", "right"):
        result["temples"][n]["density"]["text"] = DENSITY_TEXT[result["temples"][n]["density"]["status"]]
    result["guidance"] = guidance(result)
    result["image"] = draw(img, fr, cols, curve, result)
    return result


# --------------------------------------------------------------------------- visualisation
GREEN, YELLOW, GREY, RED, BLUE = (80, 170, 70), (30, 200, 240), (150, 150, 150), (60, 60, 230), (230, 160, 60)


def draw(img, fr: Frame, cols, curve, res) -> str:
    vis = img.copy()
    t = max(2, int(fr.bz / 140))
    # The overlay must never look more certain than the verdict: when the quality gate says the hairline is not reliably visible, the
    # curve is drawn GREY ("not assessable") and no analysis region is shown. (Found by PDF QA: a green "high-confidence" line was drawn
    # under a "Not reliably visible, 29 %" verdict.) Drawing only - no detection or threshold is affected.
    gated = bool(res["image_quality"]["hairline_visible"])
    if res["frontal_density"]["status"] != "not_assessable":
        reg = []
        for u in (-0.3, 0.3):
            for dv in (0.01, 0.13):
                reg.append(fr.xy(u, _vat(curve, u) + dv))
        box = np.array([reg[0], reg[2], reg[3], reg[1]], dtype=np.int32)
        ov = vis.copy()
        cv2.fillPoly(ov, [box], BLUE)
        vis = cv2.addWeighted(ov, 0.18, vis, 0.82, 0)
    # temple regions: neutral unless the screening result is pronounced
    for name, (a, b) in (("left", (0.28, 0.5)), ("right", (-0.5, -0.28))):
        lo, hi = min(a, b), max(a, b)
        quad = []
        for u, dv in ((lo, 0.0), (hi, 0.0), (hi, 0.13), (lo, 0.13)):
            quad.append(fr.xy(u, _vat(curve, u) + dv))
        st = res["temples"][name]["status"]
        col = GREY if st == "not_assessable" else RED if st == "pronounced_possible_recession_pattern" else YELLOW if st == "possible_recession_pattern" else GREEN
        ov = vis.copy()
        cv2.fillPoly(ov, [np.array(quad, dtype=np.int32)], col)
        vis = cv2.addWeighted(ov, 0.28, vis, 0.72, 0)
    # hairline curve, coloured by per-column confidence
    for a, b in zip(curve[:-1], curve[1:]):
        c = min(a["conf"], b["conf"])
        col = GREY if not gated else GREEN if c >= 0.7 else YELLOW if c >= 0.4 else GREY
        cv2.line(vis, tuple(int(z) for z in fr.xy(a["u"], a["v"])), tuple(int(z) for z in fr.xy(b["u"], b["v"])), col, t + 1)
    for c in curve:
        cv2.circle(vis, tuple(int(z) for z in fr.xy(c["u"], c["v"])), t, (255, 255, 255), -1)
    x0, x1 = int(fr.xy(-0.85, 0)[0]), int(fr.xy(0.85, 0)[0])
    y0 = int(max(0, min(fr.xy(0, 1.25)[1], fr.xy(0, _vat(curve, 0.0) + 0.4)[1])))
    y1 = int(fr.xy(0, -0.5)[1])
    crop = vis[max(0, y0):max(1, y1), max(0, min(x0, x1)):max(x0, x1)]
    if crop.size == 0:
        crop = vis
    s = 640 / max(crop.shape[:2])
    if s < 1:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return _encode(crop)


# --------------------------------------------------------------------------- longitudinal
NOISE_FLOOR_V = 0.03   # PLACEHOLDER: no test-retest data exists
CHANGE_V = 0.06        # PLACEHOLDER
NOISE_FLOOR_DENSITY = 0.05


def comparable(a: dict, b: dict) -> tuple[bool, list[str]]:
    why = []
    for name, x in (("baseline", a), ("follow-up", b)):
        if not x or x.get("hairline", {}).get("status") != "detected":
            why.append(f"The {name} hairline was not reliably visible.")
        elif x["image_quality"]["confidence"] < 0.4:
            why.append(f"The {name} photo quality is too low to compare.")
        elif {"fringe_or_hair_over_forehead", "headwear_or_covering", "hairline_outside_frame"} & set(x["image_quality"]["flags"]):
            why.append(f"The {name} photo had styling or framing that hides the hairline.")
    if why:
        return False, why
    qa, qb = a["image_quality"], b["image_quality"]
    if abs(qa["components"].get("head_turn_proxy", 0) - qb["components"].get("head_turn_proxy", 0)) > 0.08 or \
       max(qa["components"].get("head_turn_proxy", 0), qb["components"].get("head_turn_proxy", 0)) > 0.15:
        why.append("The head angle differs too much between the photos.")
    if abs(qa["mean_forehead_lightness"] - qb["mean_forehead_lightness"]) > 18:
        why.append("The lighting differs too much between the photos.")
    sa, sb = set(qa["flags"]) & {"very_short_hair", "glossy_or_wet_hair_or_strong_overhead_light"}, set(qb["flags"]) & {"very_short_hair", "glossy_or_wet_hair_or_strong_overhead_light"}
    if sa != sb:
        why.append("Hair length or wetness differs between the photos.")
    return (not why), why


def compare(base: dict | None, follow: dict | None) -> dict:
    """Compare two hair analyses in the landmark-anchored face frame. Refuses unless the conditions are comparable."""
    if not base or not follow:
        return {"status": "not_available", "reason": "Two analyses with hair results are needed."}
    ok, why = comparable(base, follow)
    if not ok:
        return {"status": "inconclusive", "reasons": why,
                "note": "Photos are not comparable, so no change is claimed in either direction."}
    ca = {p["u"]: p["v"] for p in base["hairline"]["points"]}
    cb = {p["u"]: p["v"] for p in follow["hairline"]["points"]}
    common = sorted(set(ca) & set(cb))
    if len(common) < 10:
        return {"status": "inconclusive", "reasons": ["Too little of the hairline is visible in both photos."]}
    dv = np.array([cb[u] - ca[u] for u in common])
    dv_med = float(np.median(dv))
    worst = float(dv[np.argmax(np.abs(dv))])
    temple = {}
    for s in ("left", "right"):
        a_, b_ = base["temples"][s]["depth_normalized"], follow["temples"][s]["depth_normalized"]
        temple[s] = None if a_ is None or b_ is None else round(b_ - a_, 3)
    dens = None
    if base["frontal_density"]["scalp_visibility"] is not None and follow["frontal_density"]["scalp_visibility"] is not None:
        dens = round(follow["frontal_density"]["scalp_visibility"] - base["frontal_density"]["scalp_visibility"], 3)
    mag = max(abs(worst), *(abs(x) for x in temple.values() if x is not None))
    dmag = abs(dens) if dens is not None else 0.0
    if mag < NOISE_FLOOR_V and dmag < NOISE_FLOOR_DENSITY:
        status = "stable"
    elif mag >= CHANGE_V or dmag >= 2 * NOISE_FLOOR_DENSITY:
        status = "measurable_change"
    else:
        status = "possible_change"
    wording = {"stable": "No change beyond normal photo-to-photo variation was detected in the visible hairline.",
               "possible_change": "A possible small change in the visible hairline was detected; repeat photos in the same conditions before drawing conclusions.",
               "measurable_change": "A change in the visible hairline was detected between these photos. Consider discussing a persistent or progressing change with a dermatologist."}[status]
    return {"status": status, "text": wording, "median_hairline_shift": round(dv_med, 3), "largest_column_shift": round(worst, 3),
            "temple_depth_change": temple, "frontal_scalp_visibility_change": dens,
            "note": "Thresholds are unvalidated placeholders (no test-retest data). Change is relative to face width; positive = hairline higher."}
