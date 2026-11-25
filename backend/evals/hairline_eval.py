"""Hairline engine validation against HUMAN annotations (real photographs).

    python -m evals.hairline_eval --init   <root>     # create the empty dataset skeleton + README (never overwrites)
    python -m evals.hairline_eval --status <root>     # count what really exists (images, valid human annotations, uncertain, rejected)
    python -m evals.hairline_eval --run    <root>     # run the PRODUCTION engine on every annotated image and write results

<root> MUST be outside the repository (real-person photographs never go into git).

    <root>/real/front/<id>.jpg        <root>/real/top/<id>.jpg
    <root>/annotations/<id>.json      human ground truth (schema below)
    <root>/metadata/<id>.json         REQUIRED intake record: {"validation_id", "consent_status": "consented|authorized", "image_type": "front|top",
                                      "source_category": "volunteer|staff|licensed_dataset|public_domain_licensed|app_customer_report|other_documented",
                                      "annotation_status": "pending|annotated|second_annotated|rejected", "consent_scope": ["validation"],
                                      optional "sex", "device"}  - an annotation without a valid intake record is REJECTED
    <root>/outputs/machine/<id>.json  engine output (written by --run; NEVER read back as ground truth)
    <root>/outputs/overlays/*.jpg     human (solid) vs engine (dashed) overlays      <root>/outputs/results.json

ANNOTATION SCHEMA  hairline-annotation-v2   (all enumerations allow "uncertain": a human who cannot tell must NOT be forced to guess)
    {"schema": "hairline-annotation-v2", "annotation_source": "human:<annotator id>", "image": "real/front/a.jpg", "view": "front|top",
     "subject_id": "...", "consent_ref": "...", "tags": ["fringe", "wet", "curly", ...],
     "front": {"hairline_visibility": "visible|partial|not_visible|uncertain|occluded|outside_frame",
               "hairline_polyline_px": [[x, y], ...],            # left-to-right in the ORIGINAL image; required for visible/partial
               "temples": {"left":  {"visibility": "visible|partial|not_visible|uncertain|occluded|outside_frame",
                                     "recession": "none|mild|possible|pronounced|uncertain"},
                           "right": {...}},                       # left = the SUBJECT's left = the image's right
               "shape": "relatively_straight|rounded|mildly_mature|m_shaped|v_shaped|asymmetric|irregular|insufficient_visibility|uncertain",
               "quality": "usable|marginal|unusable|uncertain",
               "frontal_density": "no_reduction|slight|reduced|uncertain"},
     "top":   {"assessable": "yes|no|uncertain", "crown_density": "no_reduction|slight|reduced|uncertain", "parting_visible": "yes|no|uncertain"}}
    A legacy v1 file ({"hairline_visible": true, "hairline_polyline_px": [...]}) is still read as a front annotation.

VALID  : annotation_source starts with "human:"; the image file exists; every enumeration value is in its list; polyline has >= 5 points in
         non-decreasing x for visible/partial; the view matches the image folder.
INVALID: model-assisted or unlabelled source (it would measure agreement, not accuracy); missing image; unknown value; visible/partial without a
         usable polyline. Invalid files are counted and listed, never silently fixed.
UNCERTAIN / partial / not_visible / occluded / outside_frame are honoured: those labels are never turned into ground truth for the item they
         cover (they are reported as counts and excluded from that item's metric).

METRICS  boundary error (distance to the human polyline / bizygomatic width; centre, left temple, right temple); P/R/F1 for hairline visibility,
         temple pattern, crown assessability and the quality gate; shape agreement; density agreement; false-reassurance cases; confidence bins.
         Any statistic with fewer than MIN_N labelled items (or MIN_POS positives) is printed as "INSUFFICIENT SAMPLE SIZE" with the raw counts.
         Nothing is reported in millimetres. With no valid annotation the whole result is "NOT MEASURED".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SCHEMA = "hairline-annotation-v2"
MIN_N, MIN_POS = 30, 8
INSUFFICIENT = "INSUFFICIENT SAMPLE SIZE"
VIS = {"visible", "partial", "not_visible", "uncertain", "occluded", "outside_frame"}
NOT_SEEN = {"not_visible", "occluded", "outside_frame"}
RECESSION = {"none", "mild", "possible", "pronounced", "uncertain"}
SHAPES = {"relatively_straight", "rounded", "mildly_mature", "m_shaped", "v_shaped", "asymmetric", "irregular", "insufficient_visibility", "uncertain"}
QUALITY = {"usable", "marginal", "unusable", "uncertain"}
DENSITY = {"no_reduction", "slight", "reduced", "uncertain"}
YNU = {"yes", "no", "uncertain"}
ENGINE_DENSITY = {"no_reduced_visible_density_detected": "no_reduction", "slightly_reduced_visible_density": "slight",
                  "reduced_visible_density_detected": "reduced"}
TAXONOMY = {  # engine flag / human tag -> candidate cause (a hint for the human reviewer, NOT a finding)
    "hair_colour_close_to_skin": "colour_cue_error", "blurry": "image_quality", "low_resolution": "image_quality", "overexposed": "lighting_error",
    "too_dark": "lighting_error", "glossy_or_wet_hair_or_strong_overhead_light": "lighting_error", "head_turned": "head_pose_issue",
    "fringe_or_hair_over_forehead": "hairstyle_error", "headwear_or_covering": "occlusion", "hairline_outside_frame": "occlusion",
    "irregular_boundary_textured_or_styled_hair": "hairstyle_error", "very_short_hair": "hairstyle_error",
    "fringe": "hairstyle_error", "wet": "lighting_error", "curly": "hairstyle_error", "cap": "occlusion", "glare": "lighting_error",
}
REVIEW_TRIGGER_BZ = 0.06  # a REVIEW trigger for the error analysis only; it is not an acceptance criterion (none is defined)


# --------------------------------------------------------------------------- intake / consent
CONSENT_OK = {"consented", "authorized"}
SOURCE_CATEGORIES = {"volunteer", "staff", "licensed_dataset", "public_domain_licensed", "app_customer_report", "other_documented"}
ANNOTATION_STATUS = {"pending", "annotated", "second_annotated", "rejected"}


def validate_intake(meta: dict | None, a: dict) -> list[str]:
    """Every image needs an intake record (metadata/<id>.json). No record, no ground truth - existing app/customer images are NOT
    admitted merely because they exist locally: category app_customer_report additionally needs consent_scope to include 'validation'."""
    if not meta:
        return ["intake record (metadata/<id>.json) missing"]
    why = []
    if not str(meta.get("validation_id", "")).strip():
        why.append("intake: validation_id missing")
    if meta.get("consent_status") not in CONSENT_OK:
        why.append("intake: consent_status must be 'consented' or 'authorized'")
    if meta.get("image_type") != a.get("view"):
        why.append("intake: image_type must equal the annotation view")
    cat = meta.get("source_category")
    if cat not in SOURCE_CATEGORIES:
        why.append("intake: source_category unknown")
    elif cat == "app_customer_report" and "validation" not in (meta.get("consent_scope") or []):
        why.append("intake: app_customer_report images need consent_scope to include 'validation'")
    if meta.get("annotation_status") not in ANNOTATION_STATUS:
        why.append("intake: annotation_status unknown")
    return why


# --------------------------------------------------------------------------- annotations
def _normalise(a: dict) -> dict:
    """Read a legacy v1 file as a front annotation."""
    if a.get("schema") == SCHEMA:
        return a
    vis = "visible" if a.get("hairline_visible") else "not_visible"
    return {"schema": "hairline-annotation-v1", "annotation_source": a.get("annotation_source", ""), "image": a.get("image", ""), "view": "front",
            "tags": a.get("tags", []), "front": {"hairline_visibility": vis, "hairline_polyline_px": a.get("hairline_polyline_px") or [],
                                                 "temples": {s: {"visibility": "visible" if (a.get("temple_visible") or {}).get(s) else "uncertain",
                                                                  "recession": "uncertain"} for s in ("left", "right")}}}


def validate_annotation(a: dict, root: Path) -> list[str]:
    why: list[str] = []
    if not str(a.get("annotation_source", "")).startswith("human:"):
        why.append("annotation_source must start with 'human:' (model-assisted labels measure agreement, not accuracy)")
    img = a.get("image", "")
    if not img or not (root / img).is_file():
        why.append("image file missing")
    view = a.get("view")
    if view not in ("front", "top"):
        why.append("view must be 'front' or 'top'")
    elif img and f"/{view}/" not in "/" + img.replace("\\", "/"):
        why.append("view does not match the image folder")
    if view == "front":
        f = a.get("front") or {}
        v = f.get("hairline_visibility")
        if v not in VIS:
            why.append("front.hairline_visibility invalid")
        if v in ("visible", "partial"):
            pl = f.get("hairline_polyline_px") or []
            xs = [p[0] for p in pl if isinstance(p, (list, tuple)) and len(p) == 2]
            if len(xs) != len(pl) or len(pl) < 5 or any(b < a_ for a_, b in zip(xs, xs[1:])):
                why.append("visible/partial needs >=5 [x,y] points with non-decreasing x")
        for s in ("left", "right"):
            t = (f.get("temples") or {}).get(s) or {}
            if t and (t.get("visibility", "uncertain") not in VIS or t.get("recession", "uncertain") not in RECESSION):
                why.append(f"temples.{s} has an unknown value")
        if f.get("shape", "uncertain") not in SHAPES or f.get("quality", "uncertain") not in QUALITY or f.get("frontal_density", "uncertain") not in DENSITY:
            why.append("shape / quality / frontal_density has an unknown value")
    elif view == "top":
        t = a.get("top") or {}
        if t.get("assessable") not in YNU or t.get("crown_density", "uncertain") not in DENSITY or t.get("parting_visible", "uncertain") not in YNU:
            why.append("top.* has an unknown or missing value")
    return why


def load_annotations(root: Path, subdir: str = "annotations") -> tuple[list[dict], list[str]]:
    good, rejected = [], []
    d = root / subdir
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            a = _normalise(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            rejected.append(f"{f.name}: unreadable")
            continue
        why = validate_annotation(a, root)
        mf = root / "metadata" / f"{f.stem}.json"
        try:
            meta = json.loads(mf.read_text(encoding="utf-8")) if mf.is_file() else None
        except ValueError:
            meta = None
        why += validate_intake(meta, a)
        if why:
            rejected.append(f"{f.name}: " + "; ".join(why))
        else:
            a["_id"] = f.stem
            good.append(a)
    return good, rejected


# --------------------------------------------------------------------------- statistics
def prf(tp: int, fp: int, fn: int, tn: int = 0) -> dict:
    n = tp + fp + fn + tn
    out = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "n": n}
    if n < MIN_N or (tp + fn) < MIN_POS:
        out["result"] = INSUFFICIENT
        return out
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    out.update(precision=None if p is None else round(p, 3), recall=None if r is None else round(r, 3),
               f1=None if not p or not r else round(2 * p * r / (p + r), 3), result="MEASURED")
    return out


def boundary_error(pred_px: np.ndarray, truth_px: np.ndarray, bz: float) -> float:
    """Mean distance from each predicted point to the nearest point on the annotated polyline, in bizygomatic widths."""
    return float(point_errors(pred_px, truth_px, bz).mean())


def point_errors(pred_px: np.ndarray, truth_px: np.ndarray, bz: float) -> np.ndarray:
    dense = [np.linspace(p, q, max(2, int(np.hypot(*(q - p))))) for p, q in zip(truth_px[:-1], truth_px[1:])]
    dense = np.vstack(dense)
    d = np.sqrt(((pred_px[:, None, :] - dense[None, :, :]) ** 2).sum(-1)).min(axis=1)
    return d / bz


def _summ(vals: list[float], n_images: int) -> dict:
    if not vals:
        return {"result": "NOT MEASURED", "n_images": n_images, "n_points": 0}
    v = np.array(vals)
    out = {"n_images": n_images, "n_points": len(v), "mean_bz": round(float(v.mean()), 4), "median_bz": round(float(np.median(v)), 4),
           "p95_bz": round(float(np.percentile(v, 95)), 4), "result": "MEASURED" if n_images >= MIN_N else INSUFFICIENT + f" (n_images={n_images} < {MIN_N})"}
    return out


# --------------------------------------------------------------------------- the real engine (production entry points)
def real_runner(root: Path, ann: dict, meta: dict) -> dict:
    """Run the PRODUCTION code paths: hair.analyze (front) / hair.analyze_top (top). Heavy imports only when there is data."""
    import cv2
    from app import hair, hairline, landmarks
    img = cv2.imread(str(root / ann["image"]))
    if img is None:
        return {"error": "image could not be decoded"}
    if ann["view"] == "top":
        try:
            top = hair.analyze_top(img)
            top.pop("image", None)
            return {"crown": hairline.crown_view(top, None), "top_raw": top}
        except hair.HairError as e:
            return {"crown": hairline.crown_view(None, str(e))}
    face = landmarks.detect(img)
    if face is None:
        return {"error": "no face found", "image_shape": img.shape[:2]}
    seg = hair.segment(img)
    out = hair.analyze(img, face, {"sex": (meta.get("sex") or "")}, None, seg)
    return {"analysis": out.get("analysis"), "frame": hairline.Frame(face.points), "image_shape": img.shape[:2]}


# --------------------------------------------------------------------------- evaluation
def _pred_px(analysis: dict, fr) -> np.ndarray:
    pts = analysis["hairline"]["points"]
    return np.array([[float(fr.xy(p["u"], p["v"])[0]), float(fr.xy(p["u"], p["v"])[1])] for p in pts]).reshape(-1, 2)


def _engine_reliable(a: dict) -> bool:
    return bool(a["image_quality"]["hairline_visible"] and a["image_quality"]["confidence"] >= 0.4)


DEFAULT_LAYOUT = {"annotations": "annotations", "machine": "outputs/machine", "overlays": "outputs/overlays", "results": "outputs/results.json",
                  "index": "outputs/overlay_index.json"}


def evaluate(root: Path, runner=None, write_outputs: bool = False, layout: dict | None = None) -> dict:
    L = DEFAULT_LAYOUT | (layout or {})
    runner = runner or real_runner
    annotations, rejected = load_annotations(root, L["annotations"])
    if not annotations:
        return {"status": "NOT MEASURED", "annotations": 0, "rejected": rejected,
                "reason": "No valid human annotations exist. No precision, recall, F1 or error figure is reported or implied."}
    counts = {"front": 0, "top": 0, "uncertain_or_partial_excluded": 0}
    errs = {"centre": [], "left_temple": [], "right_temple": []}
    img_n = {"centre": 0, "left_temple": 0, "right_temple": 0}
    per_image: list[dict] = []
    vis = dict(tp=0, fp=0, fn=0, tn=0)
    temp = dict(tp=0, fp=0, fn=0, tn=0)
    crown = dict(tp=0, fp=0, fn=0, tn=0)
    gate = dict(tp=0, fp=0, fn=0, tn=0)   # positive class = "photo is unusable -> engine should refuse"
    temple_abstain = {"engine_not_assessable_when_human_visible": 0, "human_visible_temples": 0}
    shape_pairs, density_pairs, conf_bins = [], [], {"high": [], "moderate": [], "low": []}
    false_reassurance, crown_violations, failures, skipped = [], [], [], []
    for a in annotations:
        meta = {}
        mf = root / "metadata" / f"{a['_id']}.json"
        if mf.is_file():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except ValueError:
                meta = {}
        res = runner(root, a, meta)
        counts[a["view"]] += 1
        rec = {"id": a["_id"], "view": a["view"], "buckets": [], "tags": a.get("tags", [])}
        if "error" in res:
            skipped.append(f"{a['_id']}: {res['error']}")
            continue
        if a["view"] == "top":
            c = res["crown"]
            h = (a.get("top") or {}).get("assessable")
            if h in ("yes", "no"):
                eng = c["status"] == "assessed"
                key = ("tp" if eng else "fn") if h == "yes" else ("fp" if eng else "tn")
                crown[key] += 1
                if h == "no" and eng:
                    false_reassurance.append({"id": a["_id"], "why": "human: crown not assessable; engine: assessed"})
                    rec["buckets"].append("crown_error")
                if h == "yes" and not eng:
                    rec["buckets"].append("crown_error")
            else:
                counts["uncertain_or_partial_excluded"] += 1
            rec["engine"] = {"crown": c}
            per_image.append(rec)
            continue
        an = res.get("analysis")
        rec["engine"] = an
        if an is None:
            skipped.append(f"{a['_id']}: engine returned no analysis")
            continue
        if an["crown"]["status"] != "not_assessable":
            crown_violations.append(a["_id"])
            rec["buckets"].append("crown_error")
        f = a["front"]
        hv = f["hairline_visibility"]
        engine_pos = an["hairline"]["status"] == "detected"
        if hv in ("visible", "not_visible", "occluded", "outside_frame"):
            pos = hv == "visible"
            k = ("tp" if engine_pos else "fn") if pos else ("fp" if engine_pos else "tn")
            vis[k] += 1
            if pos and not engine_pos:
                rec["buckets"].append("missed")
            if not pos and engine_pos:
                rec["buckets"].append("false_detection")
        else:
            counts["uncertain_or_partial_excluded"] += 1
            if hv == "partial":
                rec["buckets"].append("partial")
        if not engine_pos and an["status"] == "inconclusive":
            rec["buckets"].append("inconclusive")
        # boundary
        fr = res.get("frame")
        if fr is not None and hv in ("visible", "partial") and an["hairline"]["points"]:
            truth = np.array(f["hairline_polyline_px"], dtype=np.float64)
            pts = an["hairline"]["points"]
            pred = _pred_px(an, fr)
            rec["_engine_px"] = pred.tolist()
            lo, hi = truth[:, 0].min() - 0.01 * fr.bz, truth[:, 0].max() + 0.01 * fr.bz
            inside = (pred[:, 0] >= lo) & (pred[:, 0] <= hi)
            if inside.any():
                e = point_errors(pred[inside], truth, fr.bz)
                us = np.array([p["u"] for p in pts])[inside]
                groups = {"centre": np.abs(us) <= 0.12, "left_temple": us >= 0.28, "right_temple": us <= -0.28}
                img_err = float(e.mean())
                rec["boundary_error_bz"] = round(img_err, 4)
                for g, m in groups.items():
                    if m.any():
                        errs[g].extend(e[m].tolist())
                        img_n[g] += 1
                conf = an["hairline"]["confidence"]
                conf_bins["high" if conf >= 0.7 else "moderate" if conf >= 0.4 else "low"].append(img_err)
                if img_err > REVIEW_TRIGGER_BZ:
                    rec["buckets"].append("boundary_error")
        # temples
        for s in ("left", "right"):
            t = (f.get("temples") or {}).get(s) or {}
            rc, tv = t.get("recession", "uncertain"), t.get("visibility", "uncertain")
            if tv == "visible" and rc in ("none", "mild", "possible", "pronounced"):
                temple_abstain["human_visible_temples"] += 1
                es = an["temples"][s]["status"]
                if es == "not_assessable":
                    temple_abstain["engine_not_assessable_when_human_visible"] += 1
                    continue
                pos = rc in ("possible", "pronounced")
                ep = es in ("possible_recession_pattern", "pronounced_possible_recession_pattern")
                temp["tp" if pos and ep else "fn" if pos else "fp" if ep else "tn"] += 1
                if pos != ep:
                    rec["buckets"].append("temple_error")
        # shape / density / quality
        if f.get("shape", "uncertain") != "uncertain":
            shape_pairs.append((f["shape"], an["hairline"]["shape"]["label"]))
        hd = f.get("frontal_density", "uncertain")
        ed = ENGINE_DENSITY.get(an["frontal_density"]["status"])
        if hd != "uncertain" and ed:
            density_pairs.append((hd, ed))
            if hd != ed:
                rec["buckets"].append("density_error")
        q = f.get("quality", "uncertain")
        if q in ("usable", "unusable"):
            refuse = not _engine_reliable(an)
            gate["tp" if q == "unusable" and refuse else "fn" if q == "unusable" else "fp" if refuse else "tn"] += 1
        # false reassurance: strong/clean claims where the human says there is not enough evidence
        weak = hv in NOT_SEEN or q == "unusable"
        claims = []
        if engine_pos:
            claims.append("hairline detected")
        if any(an["temples"][s]["status"] in ("no_obvious_recession", "mildly_mature_temple_shape") for s in ("left", "right")):
            claims.append("'no obvious recession' / mature temple")
        if an["frontal_density"]["status"] == "no_reduced_visible_density_detected" and an["frontal_density"]["confidence"] >= 0.25:
            claims.append("'no reduced visible density'")
        if weak and claims:
            false_reassurance.append({"id": a["_id"], "human": {"visibility": hv, "quality": q}, "engine_claims": claims,
                                      "engine_confidence": an["image_quality"]["confidence"]})
            rec["buckets"].append("false_reassurance")
        per_image.append(rec)
    # taxonomy: candidate causes from engine flags and human tags, for images that failed in some way
    bad = [r for r in per_image if r["buckets"] and set(r["buckets"]) - {"partial", "inconclusive"}]
    taxonomy: dict[str, list[str]] = {}
    for r in bad:
        causes = set()
        for flag in (r.get("engine") or {}).get("image_quality", {}).get("flags", []) if isinstance(r.get("engine"), dict) and "image_quality" in r["engine"] else []:
            causes.add(TAXONOMY.get(flag, flag))
        for t in r["tags"]:
            causes.add(TAXONOMY.get(t, t))
        if not causes:
            causes.add("unexplained (segmentation / threshold / annotation ambiguity - needs human review)")
        for c in causes:
            taxonomy.setdefault(c, []).append(r["id"])
    shape_n = len(shape_pairs)
    dens_n = len(density_pairs)
    result = {
        "status": "MEASURED" if (img_n["centre"] or vis["tp"] + vis["fn"] + vis["fp"] + vis["tn"]) else "NOT MEASURED",
        "engine_version": None, "annotations": len(annotations), "rejected": rejected, "skipped": skipped, "counts": counts,
        "boundary_error": {g: _summ(errs[g], img_n[g]) for g in errs} | {"unit": "bizygomatic widths (not millimetres)"},
        "hairline_visibility": prf(**vis), "temple_pattern": prf(**temp) | {"engine_not_assessable_when_human_visible": temple_abstain},
        "crown_assessability": prf(**crown), "quality_gate_refusal": prf(**gate) | {"definition": "positive = human says unusable; engine refuses when hairline_visible is false or confidence < 0.4"},
        "shape": ({"n": shape_n, "agreement": round(sum(a == b for a, b in shape_pairs) / shape_n, 3), "result": "MEASURED"} if shape_n >= MIN_N
                  else {"n": shape_n, "result": INSUFFICIENT}),
        "frontal_density": ({"n": dens_n, "agreement": round(sum(a == b for a, b in density_pairs) / dens_n, 3), "result": "MEASURED",
                             "caveat": "agreement with a human regional rating of VISIBLE density; not follicle density"} if dens_n >= MIN_N else
                            {"n": dens_n, "result": "FRONTAL DENSITY ACCURACY: NOT MEASURED" if dens_n == 0 else INSUFFICIENT,
                             "reason": "a photograph cannot give follicle counts; only human regional ratings of visible density can be compared"}),
        "crown_front_only_violations": {"ids": crown_violations, "rule": "a front photo must always give crown.status = not_assessable", "count": len(crown_violations)},
        "false_reassurance": {"count": len(false_reassurance), "cases": false_reassurance},
        "confidence_bins": {k: _summ(v, len(v)) for k, v in conf_bins.items()},
        "error_taxonomy_candidates": taxonomy,
        "longitudinal": "NOT MEASURED (no repeat-photo ground truth; change thresholds are placeholders)",
        "per_image": [{k: v for k, v in r.items() if k != "engine" and not k.startswith("_")} for r in per_image],
    }
    if write_outputs:
        _write_outputs(root, annotations, per_image, result, L)
    return result


# --------------------------------------------------------------------------- outputs and overlays
def _write_outputs(root: Path, annotations: list[dict], per_image: list[dict], result: dict, L: dict) -> None:
    import cv2
    machine, overlays = root / L["machine"], root / L["overlays"]
    machine.mkdir(parents=True, exist_ok=True)
    overlays.mkdir(parents=True, exist_ok=True)
    ann = {a["_id"]: a for a in annotations}
    index = {}
    for r in per_image:
        a = ann[r["id"]]
        eng = r.get("engine")
        (machine / f"{r['id']}.json").write_text(json.dumps(eng, indent=1, default=str), encoding="utf-8")
        img = cv2.imread(str(root / a["image"]))
        if img is None:
            continue
        vis = img.copy()
        if a["view"] == "front":
            pl = np.array((a["front"].get("hairline_polyline_px") or []), dtype=np.int32).reshape(-1, 1, 2)
            if len(pl) >= 2:
                cv2.polylines(vis, [pl], False, (255, 255, 0), 3)       # HUMAN: solid cyan
            if isinstance(eng, dict) and eng.get("hairline", {}).get("points"):
                p = eng["hairline"]["points"]
                eng_px = [(int(x), int(y)) for x, y in r.get("_engine_px", [])]
                for (x0, y0), (x1, y1) in zip(eng_px[:-1:2], eng_px[1::2]):  # ENGINE: dashed orange
                    cv2.line(vis, (x0, y0), (x1, y1), (0, 140, 255), 2)
        cv2.putText(vis, "HUMAN solid cyan | ENGINE dashed orange", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imwrite(str(overlays / f"{r['id']}.jpg"), vis)
        for b in r["buckets"] or ["no_issue"]:
            index.setdefault(b, []).append(r["id"])
    (root / L["index"]).write_text(json.dumps(index, indent=1), encoding="utf-8")
    (root / L["results"]).parent.mkdir(parents=True, exist_ok=True)
    (root / L["results"]).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- dataset skeleton and status
README = """# Hairline validation dataset (OUTSIDE the repository)
Real-person photographs are never committed, pushed or uploaded to a third party. Every subject needs a consent record (`consent_ref`).
Annotate WITHOUT looking at the engine's output. Allow "uncertain" - never guess. Schema and rules: backend/evals/hairline_eval.py docstring.
Composition to aim for (record what you actually have in metadata): clear / rounded / straight hairlines, temple asymmetry, possible recession,
fringe, side part, curly, short, long, wet, glossy, different lighting and hair/skin contrast, partly obscured, top-of-head (crown visible and obscured).
A dataset with many images is not automatically representative: stratify by skin tone, hair colour/texture, age, sex, device.
Second annotator on >= 20 % of images to measure inter-annotator error. Acceptance criteria must be written BEFORE running --run.
"""


def init_skeleton(root: Path) -> list[str]:
    made = []
    for sub in ("real/front", "real/top", "annotations", "metadata", "outputs"):
        d = root / sub
        if not d.exists():
            d.mkdir(parents=True)
            made.append(str(d))
    r = root / "README.md"
    if not r.exists():
        r.write_text(README, encoding="utf-8")
        made.append(str(r))
    return made


def status(root: Path) -> dict:
    imgs = {v: len([p for p in (root / "real" / v).glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")]) if (root / "real" / v).is_dir() else 0 for v in ("front", "top")}
    good, rejected = load_annotations(root)
    return {"root": str(root), "images": imgs, "valid_human_annotations": {v: sum(1 for a in good if a["view"] == v) for v in ("front", "top")},
            "rejected_annotations": len(rejected), "rejected": rejected,
            "verdict": "NOT MEASURED" if not good else f"{len(good)} valid human annotation(s); statistics need >= {MIN_N} labelled items each"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--init", type=Path)
    g.add_argument("--status", type=Path)
    g.add_argument("--run", type=Path)
    a = ap.parse_args(argv)
    if a.init:
        print(json.dumps({"created": init_skeleton(a.init)}, indent=2))
    elif a.status:
        print(json.dumps(status(a.status), indent=2))
    else:
        from app import hairline
        res = evaluate(a.run, write_outputs=True)
        res["engine_version"] = hairline.ENGINE_VERSION
        print(json.dumps({k: v for k, v in res.items() if k != "per_image"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
