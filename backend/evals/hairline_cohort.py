"""Validation COHORT tooling for the hairline engine: workspace, pseudonymous intake, lifecycle, two independent annotators, human-human
agreement, leakage guards, go/no-go gates. It contains NO accuracy computation of its own and never runs the engine unless every gate passes.

    python -m evals.hairline_cohort init     <root>
    python -m evals.hairline_cohort add      <root> --image F --view front|top --source-type S --source-category C --consent-status consented|authorized
                                             --validation-use yes --consent-scope validation[,..] --adult yes --consent-ref REF
    python -m evals.hairline_cohort include  <root> HLV-0001          # eligibility check, then move to approved/
    python -m evals.hairline_cohort exclude  <root> HLV-0001 --reason CODE [--note TEXT]
    python -m evals.hairline_cohort queue    <root> --annotator A01   # images this annotator may label (IDs only, randomised, never engine output)
    python -m evals.hairline_cohort agreement <root>                  # human A vs human B (never the engine)
    python -m evals.hairline_cohort status   <root>                   # counts from real files only
    python -m evals.hairline_cohort gates    <root>                   # go / no-go
    python -m evals.hairline_cohort run      <root>                   # refuses unless every gate passes
    python -m evals.hairline_cohort lock --reason TEXT                # record the algorithm lock (refuses to overwrite)

LIFECYCLE (derived from files that exist, never from a stored flag):
    candidate -> consent_verified -> eligible -> annotator_a_complete -> annotator_b_complete -> agreement_checked -> consensus_ready
              -> engine_run -> evaluated                                    (excluded at any point before annotation)
ORDER IS A SAFETY RULE: humans annotate FIRST; the engine runs only after consensus exists. An annotation whose image already has engine output
older than the annotation is treated as contaminated and is not ground truth.

The workspace MUST be outside the repository, outside any git work tree and outside the application's own data. Real-person photographs are never
committed. The tool never reads the application's encrypted reports. Records carry pseudonymous ids (HLV-0001...) and no names, emails, phones or addresses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from . import hairline_eval as E

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
LOCK_FILE = HERE / "hairline_lock.json"
DECISIONS_FILE = HERE / "hairline_validation_decisions.json"
INTAKE_VERSION = "hairline-cohort-intake-v1"
DIRS = ["candidates/front", "candidates/top", "approved/front", "approved/top", "excluded", "annotations/annotator_a", "annotations/annotator_b",
        "annotations/consensus", "machine_outputs", "overlays", "reports", "consent", "metadata"]
IMAGE_EXT = {".jpg", ".jpeg", ".png"}
ID_RE = re.compile(r"^HLV-\d{4,}$")
REF_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
IDENTITY_KEYS = {"name", "full_name", "first_name", "last_name", "email", "phone", "mobile", "address", "dob", "date_of_birth", "ip", "ip_address",
                 "account", "user_id", "username", "report_id", "analysis_id"}
SOURCE_TYPES = {"volunteer_capture", "staff_capture", "licensed_dataset", "public_domain_licensed", "app_customer_report", "other_documented"}
EXCLUSION_REASONS = {"out_of_scope_head_pitch", "out_of_scope_angled_photo", "out_of_scope_other_view", "not_decodable", "consent_withdrawn",
                     "consent_missing", "duplicate_of_other_id", "other_documented"}
LIFECYCLE = ["candidate", "consent_verified", "eligible", "annotator_a_complete", "annotator_b_complete", "agreement_checked", "consensus_ready",
             "engine_run", "evaluated"]
ATTESTATION = {"engine_output_seen": False, "report_seen": False, "other_annotator_seen": False}
PASS, BLOCKED, NOT_SAT = "PASS", "BLOCKED", "NOT SATISFIED"


class CohortError(Exception):
    pass


# --------------------------------------------------------------------------- helpers
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def app_data_dirs() -> list[Path]:
    dirs = [REPO / "backend" / "data"]
    import os
    if os.environ.get("DATA_DIR"):
        dirs.append(Path(os.environ["DATA_DIR"]))
    return dirs


def workspace_problems(root: Path) -> list[str]:
    """Why this folder must NOT be used as the validation workspace (empty list = acceptable)."""
    root = root.resolve()
    why = []
    if _inside(root, REPO) or _inside(REPO, root):
        why.append("workspace is inside (or contains) the repository")
    for d in app_data_dirs():
        if _inside(root, d) or _inside(d, root):
            why.append(f"workspace overlaps the application's data folder ({d})")
    for anc in [root, *root.parents]:
        if (anc / ".git").exists():
            why.append(f"workspace is inside a git work tree ({anc})")
            break
    key_dir = Path.home() / ".alexendra"
    if root == key_dir or root == key_dir.parent:
        why.append("workspace may not be the key/credential folder itself")
    return why


def init_workspace(root: Path) -> list[str]:
    root = Path(root)
    why = workspace_problems(root)
    if why:
        raise CohortError("refusing to create the validation workspace: " + "; ".join(why))
    made = []
    for sub in DIRS:
        d = root / sub
        if not d.exists():
            d.mkdir(parents=True)
            made.append(str(d))
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text("# Hairline validation workspace (OUTSIDE the repository)\nNever commit, push, upload or publish anything here. "
                          "Annotators receive images and blank templates ONLY - never engine output, reports or another annotator's labels.\n"
                          "See docs/HAIRLINE_VALIDATION_COHORT_INTAKE.md.\n", encoding="utf-8")
        made.append(str(readme))
    return made


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def records(root: Path) -> dict[str, dict]:
    out = {}
    d = root / "metadata"
    for f in sorted(d.glob("HLV-*.json")) if d.is_dir() else []:
        r = _read(f)
        if isinstance(r, dict):
            out[f.stem] = r
    return out


def _image_path(root: Path, rid: str, rec: dict) -> Path | None:
    for stage in ("approved", "candidates"):
        for ext in IMAGE_EXT:
            p = root / stage / str(rec.get("image_type")) / f"{rid}{ext}"
            if p.is_file():
                return p
    return None


# --------------------------------------------------------------------------- intake
def technical_check(path: Path) -> dict:
    """Objective, engine-independent facts only: decodable, size, and whether EXIF carries GPS (personal location data)."""
    info = {"decodable": False, "width": None, "height": None, "exif_gps_present": None}
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            info.update(decodable=True, width=im.width, height=im.height)
            try:
                exif = im.getexif()
                info["exif_gps_present"] = bool(exif.get_ifd(0x8825)) if exif else False
            except Exception:  # noqa: BLE001
                info["exif_gps_present"] = None  # could not be checked
    except Exception:  # noqa: BLE001
        pass
    return info


def next_id(root: Path) -> str:
    nums = [int(k.split("-")[1]) for k in records(root)]
    ex = root / "excluded"
    if ex.is_dir():
        nums += [int(f.stem.split("-")[1]) for f in ex.glob("HLV-*.json")]
    return f"HLV-{(max(nums) + 1 if nums else 1):04d}"


def identity_fields(rec: dict) -> list[str]:
    return sorted(k for k in rec if k.lower() in IDENTITY_KEYS)


def add_candidate(root: Path, image: Path, view: str, source_type: str, source_category: str, consent_status: str, validation_use: bool,
                  consent_scope: list[str], adult_confirmed: bool, consent_ref: str, captured_on: str | None = None) -> dict:
    root, image = Path(root), Path(image)
    if workspace_problems(root):
        raise CohortError("unsafe workspace: " + "; ".join(workspace_problems(root)))
    if not (root / "metadata").is_dir():
        raise CohortError("workspace not initialised (run init)")
    if view not in ("front", "top"):
        raise CohortError("view must be front or top")
    if source_type not in SOURCE_TYPES or source_category not in E.SOURCE_CATEGORIES:
        raise CohortError("unknown source_type / source_category")
    if not image.is_file() or image.suffix.lower() not in IMAGE_EXT:
        raise CohortError("image missing or not .jpg/.jpeg/.png")
    # production / customer data is never pulled in silently
    for d in app_data_dirs():
        if _inside(image, d):
            raise CohortError("refusing to read from the application's data folder; export an image only with the person's explicit validation consent")
    if image.read_bytes()[:4] == b"ENC1":
        raise CohortError("this is an encrypted application file, not an image")
    if not REF_RE.match(consent_ref or "") or "@" in consent_ref:
        raise CohortError("consent_ref must be an opaque reference (letters, digits, . _ -); no names, emails or phone numbers")
    if consent_status not in E.CONSENT_OK:
        raise CohortError("consent_status must be 'consented' or 'authorized' - without it the image cannot enter intake")
    if not validation_use or "validation" not in (consent_scope or []):
        raise CohortError("no validation-use authorization: NO VALIDATION CONSENT -> NOT ELIGIBLE FOR VALIDATION")
    if source_category == "app_customer_report" and source_type != "app_customer_report":
        raise CohortError("source_type and source_category disagree for a customer report")
    rid = next_id(root)
    dest = root / "candidates" / view / f"{rid}{image.suffix.lower()}"
    shutil.copyfile(image, dest)  # byte-for-byte copy: no re-encoding, no cropping, no enhancement
    rec = {"validation_id": rid, "intake_version": INTAKE_VERSION, "source_type": source_type, "source_category": source_category,
           "consent_status": consent_status, "validation_use_authorized": True, "consent_scope": list(consent_scope), "adult_confirmed": bool(adult_confirmed),
           "consent_ref": consent_ref, "image_type": view, "capture_type": view, "captured_on": captured_on,
           "technical": technical_check(dest), "image_sha256": sha256(dest), "inclusion_decision": "pending", "exclusion_reason": None,
           "annotation_status": "pending", "added_at": time.strftime("%Y-%m-%d")}
    (root / "metadata" / f"{rid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def eligibility(rec: dict, root: Path | None = None) -> list[str]:
    """Reasons an image is NOT eligible (empty = eligible). Engine output is never consulted."""
    why = []
    if identity_fields(rec):
        why.append(f"record contains identity fields: {identity_fields(rec)}")
    if not ID_RE.match(str(rec.get("validation_id", ""))):
        why.append("validation_id is not of the form HLV-0001")
    if rec.get("consent_status") not in E.CONSENT_OK:
        why.append("consent_status is not consented/authorized")
    if rec.get("validation_use_authorized") is not True or "validation" not in (rec.get("consent_scope") or []):
        why.append("no explicit validation-use authorization")
    if rec.get("adult_confirmed") is not True:
        why.append("adult (18+) not confirmed")
    if rec.get("image_type") not in ("front", "top") or rec.get("capture_type") != rec.get("image_type"):
        why.append("capture/image type invalid")
    if rec.get("source_category") not in E.SOURCE_CATEGORIES or rec.get("source_type") not in SOURCE_TYPES:
        why.append("source unknown")
    t = rec.get("technical") or {}
    if not t.get("decodable"):
        why.append("image not decodable")
    if t.get("exif_gps_present") is True:
        why.append("image carries GPS location in EXIF: remove it first (personal data)")
    if root is not None:
        p = _image_path(root, rec.get("validation_id", ""), rec)
        if p is None:
            why.append("image file missing")
        elif sha256(p) != rec.get("image_sha256"):
            why.append("image changed since intake (hash mismatch)")
    return why


def include(root: Path, rid: str) -> list[str]:
    rec = records(root).get(rid)
    if rec is None:
        raise CohortError("unknown id")
    why = eligibility(rec, root)
    if why:
        raise CohortError("not eligible: " + "; ".join(why))
    src = _image_path(root, rid, rec)
    dest = root / "approved" / rec["image_type"] / src.name
    if src.parent != dest.parent:
        shutil.move(str(src), str(dest))
    rec["inclusion_decision"] = "included"
    (root / "metadata" / f"{rid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return []


def exclude(root: Path, rid: str, reason: str, note: str = "") -> dict:
    """Record the exclusion (with a coded reason), then DELETE the image (data minimisation). Never exclude because of engine output."""
    rec = records(root).get(rid)
    if rec is None:
        raise CohortError("unknown id")
    if reason not in EXCLUSION_REASONS or (reason == "other_documented" and not note.strip()):
        raise CohortError(f"reason must be one of {sorted(EXCLUSION_REASONS)} (other_documented needs a note)")
    if any((root / "annotations" / d / f"{rid}.json").exists() for d in ("annotator_a", "annotator_b")):
        raise CohortError("an annotated image cannot be silently excluded; handle it through a documented decision")
    p = _image_path(root, rid, rec)
    if p is not None:
        p.unlink()
    out = {"validation_id": rid, "excluded_on": time.strftime("%Y-%m-%d"), "reason": reason, "note": note, "image_deleted": True,
           "source_category": rec.get("source_category"), "image_type": rec.get("image_type")}
    (root / "excluded" / f"{rid}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (root / "metadata" / f"{rid}.json").unlink()
    return out


# --------------------------------------------------------------------------- annotations (two independent humans)
def _ann_path(root: Path, who: str, rid: str) -> Path:
    return root / "annotations" / who / f"{rid}.json"


def annotation_problems(root: Path, who: str, rid: str, rec: dict) -> tuple[dict | None, list[str]]:
    p = _ann_path(root, who, rid)
    if not p.is_file():
        return None, []
    a = _read(p)
    if not isinstance(a, dict):
        return None, ["unreadable"]
    a = E._normalise(a)
    why = E.validate_annotation(a, root)
    ind = a.get("independence") or {}
    if any(ind.get(k) is not False for k in ATTESTATION):
        why.append("missing/false independence attestation (engine_output_seen, report_seen, other_annotator_seen must all be false)")
    if a.get("view") != rec.get("image_type"):
        why.append("view differs from the intake record")
    if not str(a.get("image", "")).replace("\\", "/").startswith("approved/"):
        why.append("annotation must reference an approved/ image")
    m = root / "machine_outputs" / f"{rid}.json"
    if m.is_file() and m.stat().st_mtime <= p.stat().st_mtime:
        why.append("CONTAMINATED: engine output for this image pre-dates the annotation")
    return a, why


def annotator_ids(root: Path) -> dict[str, set[str]]:
    out = {"annotator_a": set(), "annotator_b": set()}
    for who in out:
        for f in (root / "annotations" / who).glob("HLV-*.json"):
            a = _read(f)
            if isinstance(a, dict):
                out[who].add(str(a.get("annotation_source", "")))
    return out


def valid_annotations(root: Path) -> dict[str, dict[str, dict]]:
    """{rid: {'a': ann, 'b': ann}} counting only annotations that pass every rule, including A and B being different people."""
    recs = records(root)
    ids = annotator_ids(root)
    same_person = bool(ids["annotator_a"] & ids["annotator_b"])
    out: dict[str, dict] = {}
    for rid, rec in recs.items():
        for who, key in (("annotator_a", "a"), ("annotator_b", "b")):
            a, why = annotation_problems(root, who, rid, rec)
            if a is None or why:
                continue
            if who == "annotator_b" and same_person:
                continue  # one person labelling both columns is not two independent annotators
            out.setdefault(rid, {})[key] = a
    return out


def _poly(a: dict):
    return np.array((a.get("front") or {}).get("hairline_polyline_px") or [], dtype=float).reshape(-1, 2)


def suspected_copy(a: dict, b: dict) -> bool:
    """Exactly identical polylines (>= 5 points) from two humans are not plausible; flag for review. Identical categorical labels alone are normal."""
    pa, pb = _poly(a), _poly(b)
    return len(pa) >= 5 and pa.shape == pb.shape and bool(np.array_equal(pa, pb))


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    labels = sorted({x for p in pairs for x in p})
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(1 for a, _ in pairs if a == l) / n) * (sum(1 for _, b in pairs if b == l) / n) for l in labels)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


FIELDS_FRONT = [("front.hairline_visibility", lambda a: a["front"]["hairline_visibility"]),
                ("front.left_temple.visibility", lambda a: (a["front"].get("temples") or {}).get("left", {}).get("visibility")),
                ("front.right_temple.visibility", lambda a: (a["front"].get("temples") or {}).get("right", {}).get("visibility")),
                ("front.left_temple.recession", lambda a: (a["front"].get("temples") or {}).get("left", {}).get("recession")),
                ("front.right_temple.recession", lambda a: (a["front"].get("temples") or {}).get("right", {}).get("recession")),
                ("front.shape", lambda a: a["front"].get("shape")), ("front.quality", lambda a: a["front"].get("quality")),
                ("front.frontal_density", lambda a: a["front"].get("frontal_density"))]
FIELDS_TOP = [("top.assessable", lambda a: a["top"]["assessable"]), ("top.crown_density", lambda a: a["top"].get("crown_density")),
              ("top.parting_visible", lambda a: a["top"].get("parting_visible"))]


def agreement(root: Path, write: bool = False) -> dict:
    """Human A vs human B. Never involves the engine. Both original annotations are preserved untouched; disagreements are only listed."""
    va = {rid: v for rid, v in valid_annotations(root).items() if "a" in v and "b" in v}
    copies = [rid for rid, v in va.items() if suspected_copy(v["a"], v["b"])]
    use = {rid: v for rid, v in va.items() if rid not in copies}
    fields = {}
    disagree: dict[str, list[str]] = {}
    for name, getter in FIELDS_FRONT + FIELDS_TOP:
        pairs, unc = [], 0
        for rid, v in use.items():
            if not name.startswith(v["a"]["view"]):
                continue
            try:
                x, y = getter(v["a"]), getter(v["b"])
            except (KeyError, TypeError):
                continue
            if x in (None, "uncertain") or y in (None, "uncertain"):
                unc += 1
                continue
            pairs.append((x, y))
            if x != y:
                disagree.setdefault(rid, []).append(name)
        n = len(pairs)
        fields[name] = ({"n": n, "uncertain_excluded": unc, "result": E.INSUFFICIENT} if n < E.MIN_N else
                        {"n": n, "uncertain_excluded": unc, "percent_agreement": round(100 * sum(a == b for a, b in pairs) / n, 1),
                         "cohen_kappa": cohen_kappa(pairs), "result": "MEASURED"})
        fields[name]["raw_pairs"] = n
    dists = []
    for rid, v in use.items():
        pa, pb = _poly(v["a"]), _poly(v["b"])
        if len(pa) >= 5 and len(pb) >= 5:
            wpx = (records(root)[rid].get("technical") or {}).get("width")
            if wpx:
                d1 = E.point_errors(pa, pb, float(wpx)).mean()
                d2 = E.point_errors(pb, pa, float(wpx)).mean()
                dists.append(float((d1 + d2) / 2))
    out = {"compared_images": len(use), "suspected_copies_excluded": copies, "fields": fields,
           "polyline_distance_image_widths": ({"n": len(dists), "mean": round(float(np.mean(dists)), 4), "result": "MEASURED" if len(dists) >= E.MIN_N else E.INSUFFICIENT}
                                              if dists else {"n": 0, "result": "NOT MEASURED"}),
           "unit_note": "polyline distance is in IMAGE widths (independent of any detector); not face widths",
           "disagreements": disagree,
           "human_human_agreement": "NOT MEASURED" if len(use) == 0 else ("INSUFFICIENT SAMPLE SIZE" if len(use) < E.MIN_N else "MEASURED"),
           "adjudication": "NOT DEFINED - a human must define the adjudication procedure and consensus rule before final ground truth exists"}
    if write:
        (root / "reports").mkdir(exist_ok=True)
        (root / "reports" / "agreement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def annotation_queue(root: Path, annotator: str) -> list[str]:
    """IDs this annotator may label: approved images with NO engine output and not yet labelled by them, in a reproducible random order.
    Only pseudonymous ids are returned - never reports, engine output or the other annotator's work."""
    who = "annotator_a" if annotator.upper().startswith("A") else "annotator_b"
    ids = []
    for rid, rec in records(root).items():
        if rec.get("inclusion_decision") != "included" or eligibility(rec, root):
            continue
        if (root / "machine_outputs" / f"{rid}.json").exists() or _ann_path(root, who, rid).exists():
            continue
        ids.append(rid)
    random.Random(f"{annotator}:{len(ids)}").shuffle(ids)
    return ids


# --------------------------------------------------------------------------- lock, decisions, status, gates
def threshold_snapshot() -> dict:
    from app import hair, hairline
    return {"T_MILD": hairline.T_MILD, "T_POSSIBLE": hairline.T_POSSIBLE, "T_PRONOUNCED": hairline.T_PRONOUNCED, "MIN_CONTRAST_DE": hairline.MIN_CONTRAST_DE,
            "NOISE_FLOOR_V": hairline.NOISE_FLOOR_V, "CHANGE_V": hairline.CHANGE_V, "NOISE_FLOOR_DENSITY": hairline.NOISE_FLOOR_DENSITY,
            "COLUMNS": [len(hairline.COLUMNS), float(hairline.COLUMNS[0]), float(hairline.COLUMNS[-1])], "HEAD_BREADTH_MM": hair.HEAD_BREADTH_MM,
            "ENGINE_VERSION": hairline.ENGINE_VERSION}


def current_hashes() -> dict:
    return {"backend/app/hairline.py": sha256(REPO / "backend" / "app" / "hairline.py"), "backend/app/hair.py": sha256(REPO / "backend" / "app" / "hair.py"),
            "docs/HAIRLINE_THRESHOLD_REGISTER.md": sha256(REPO / "docs" / "HAIRLINE_THRESHOLD_REGISTER.md")}


def write_lock(reason: str, overwrite: bool = False) -> dict:
    if LOCK_FILE.exists() and not overwrite:
        raise CohortError("a lock already exists; relocking needs overwrite=True and a documented reason (this is deliberate friction)")
    if not reason.strip():
        raise CohortError("a reason is required")
    lock = {"locked_on": time.strftime("%Y-%m-%d"), "reason": reason, "files": current_hashes(), "thresholds": threshold_snapshot()}
    LOCK_FILE.write_text(json.dumps(lock, indent=1), encoding="utf-8")
    return lock


def decisions() -> dict:
    d = _read(DECISIONS_FILE) or {}
    return d


def decision_agreed(key: str) -> bool:
    """A human decision counts only with value true AND decided_by AND decided_on: a bare flag is not enough."""
    v = (decisions().get(key) or {})
    return v.get("value") is True and bool(str(v.get("decided_by", "")).strip()) and bool(str(v.get("decided_on", "")).strip())


def repo_has_real_images() -> list[str]:
    """Any .jpg/.jpeg inside the repository (dependencies and build output excluded). Real-person photographs must never be in the repo."""
    import os
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".next", ".git", "graphify-out", "__pycache__"} and not d.startswith(".venv")]
        for f in filenames:
            if f.lower().endswith((".jpg", ".jpeg")):
                found.append(str((Path(dirpath) / f).relative_to(REPO)))
    return found


def counts(root: Path) -> dict:
    recs = records(root)
    va = valid_annotations(root)
    consented = [r for r, rec in recs.items() if rec.get("consent_status") in E.CONSENT_OK and rec.get("validation_use_authorized") is True
                 and "validation" in (rec.get("consent_scope") or [])]
    eligible = [r for r, rec in recs.items() if rec.get("inclusion_decision") == "included" and not eligibility(rec, root)]
    cons = [p.stem for p in (root / "annotations" / "consensus").glob("HLV-*.json")] if (root / "annotations" / "consensus").is_dir() else []
    machine = [p.stem for p in (root / "machine_outputs").glob("HLV-*.json")] if (root / "machine_outputs").is_dir() else []
    excl = [p.stem for p in (root / "excluded").glob("HLV-*.json")] if (root / "excluded").is_dir() else []
    res = _read(root / "reports" / "results.json") or {}
    return {"candidates": len(recs), "consented": len(consented), "eligible": len(eligible), "excluded": len(excl),
            "annotator_a": sum(1 for v in va.values() if "a" in v), "annotator_b": sum(1 for v in va.values() if "b" in v),
            "both_annotators": sum(1 for v in va.values() if "a" in v and "b" in v), "consensus": len(cons), "engine_run": len(machine),
            "evaluated": res.get("annotations", 0) if res.get("status") == "MEASURED" else 0}


def gates(root: Path | None) -> list[dict]:
    g = []
    # 1 algorithm lock
    lock = _read(LOCK_FILE)
    if not lock:
        g.append({"id": 1, "name": "Algorithm lock", "status": BLOCKED, "detail": "no lock record (run: lock --reason ...)"})
    else:
        diffs = [k for k, v in current_hashes().items() if lock.get("files", {}).get(k) != v]
        thr = threshold_snapshot() == lock.get("thresholds")
        g.append({"id": 1, "name": "Algorithm lock", "status": PASS if not diffs and thr else BLOCKED,
                  "detail": f"hashes match lock of {lock.get('locked_on')}; thresholds identical" if not diffs and thr else f"changed since lock: {diffs or 'thresholds'}"})
    # 2 population
    pop = (REPO / "docs" / "HAIRLINE_VALIDATION_POPULATION.md").is_file()
    g.append({"id": 2, "name": "Intended-use population", "status": PASS if pop and decision_agreed("population_confirmed_by_owner") else BLOCKED,
              "detail": ("documented and owner-confirmed" if pop and decision_agreed("population_confirmed_by_owner") else
                         "documented" if pop else "not documented") + ("" if decision_agreed("population_confirmed_by_owner") else "; OWNER CONFIRMATION MISSING (decision file)")})
    # 3 acceptance criteria
    ok = decision_agreed("acceptance_thresholds_agreed")
    g.append({"id": 3, "name": "Real-photo acceptance criteria", "status": PASS if ok else BLOCKED,
              "detail": "agreed and signed" if ok else "NOT AGREED - ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION (no numbers are invented)"})
    c = counts(root) if root and (root / "metadata").is_dir() else {"eligible": 0, "consented": 0, "candidates": 0, "both_annotators": 0, "annotator_a": 0}
    # 4 consent
    bad = []
    if root and (root / "metadata").is_dir():
        for rid, rec in records(root).items():
            if rec.get("inclusion_decision") == "included" and eligibility(rec, root):
                bad.append(rid)
    g.append({"id": 4, "name": "Consent / validation authorization", "status": PASS if c["eligible"] > 0 and not bad else NOT_SAT,
              "detail": f"{c['eligible']} eligible image(s) with validation authorization" + (f"; INELIGIBLE but included: {bad}" if bad else "")})
    # 5 annotation independence
    contaminated, unattested = [], []
    if root and (root / "metadata").is_dir():
        for rid, rec in records(root).items():
            for who in ("annotator_a", "annotator_b"):
                a, why = annotation_problems(root, who, rid, rec)
                if a is not None and why:
                    (contaminated if any("CONTAMINATED" in w for w in why) else unattested).append(f"{who}/{rid}")
    n_ann = c["annotator_a"] + c.get("annotator_b", 0)
    g.append({"id": 5, "name": "Annotation independence", "status": PASS if n_ann > 0 and not contaminated and not unattested else NOT_SAT,
              "detail": f"{n_ann} valid attested annotation(s); contaminated={contaminated}; invalid={unattested}"})
    # 6 two-annotator readiness
    ids = annotator_ids(root) if root and (root / "metadata").is_dir() else {"annotator_a": set(), "annotator_b": set()}
    two = decision_agreed("second_annotator_available") and bool(ids["annotator_a"]) and bool(ids["annotator_b"]) and not (ids["annotator_a"] & ids["annotator_b"])
    g.append({"id": 6, "name": "Two-annotator readiness", "status": PASS if two and decision_agreed("adjudication_procedure_defined") else BLOCKED,
              "detail": ("two distinct annotators present; adjudication defined" if two and decision_agreed("adjudication_procedure_defined") else
                         "workflow exists, but: second annotator available=%s, adjudication procedure defined=%s, annotator ids A=%d B=%d" %
                         (decision_agreed("second_annotator_available"), decision_agreed("adjudication_procedure_defined"), len(ids["annotator_a"]), len(ids["annotator_b"])))})
    # 7 dataset separation
    imgs = repo_has_real_images()
    sep_ok = (root is not None and not workspace_problems(root)) and not imgs
    g.append({"id": 7, "name": "Dataset separation", "status": PASS if sep_ok else BLOCKED,
              "detail": "workspace outside repo/git/app data; no image files in the repository" if sep_ok else
              f"workspace problems={workspace_problems(root) if root else 'no workspace given'}; images in repo={imgs[:5]}"})
    # 8 reproducibility: BEFORE a run, the capability must be deterministic; AFTER a run, the manifest must still verify (no drift in data or code)
    man = _read(root / "reports" / "run_manifest.json") if root and (root / "reports").is_dir() else None
    keys = ("engine_files", "thresholds", "evaluator_sha256", "annotation_sha256", "image_sha256", "metadata_sha256")
    if man:
        ok8 = verify_manifest(root, man)
        d8 = "run manifest present and still verifies" if ok8 else "DATA OR CODE CHANGED SINCE THE LAST RUN: the manifest no longer verifies"
    elif root and (root / "metadata").is_dir():
        a1, a2 = build_manifest(root), build_manifest(root)
        ok8 = all(a1[k] == a2[k] for k in keys)
        d8 = "capability verified: the manifest (engine, evaluator, annotation and image hashes) is deterministic; no real run has been made yet"
    else:
        ok8, d8 = False, "no workspace"
    g.append({"id": 8, "name": "Evaluation reproducibility", "status": PASS if ok8 else (BLOCKED if man else NOT_SAT), "detail": d8})
    return g


def overall(gs: list[dict]) -> str:
    return "READY TO BEGIN THE VALIDATION RUN (this is not a validation result)" if all(x["status"] == PASS for x in gs) else "NOT READY"


def readiness_text(root: Path) -> str:
    c = counts(root)
    ag = agreement(root) if (root / "metadata").is_dir() else {"human_human_agreement": "NOT MEASURED"}
    gs = gates(root)
    res = _read(root / "reports" / "results.json") or {}
    eng = "MEASURED (see reports/results.json)" if res.get("status") == "MEASURED" else "NOT MEASURED"
    lines = ["Validation readiness", "--------------------", "",
             f"Candidate images:       {c['candidates']}", f"Consented images:       {c['consented']}", f"Eligible images:        {c['eligible']}", "",
             f"Annotator A:            {c['annotator_a']}", f"Annotator B:            {c['annotator_b']}", f"Both annotators:        {c['both_annotators']}", "",
             f"Human-human agreement:  {ag['human_human_agreement']}", f"Human-engine accuracy:  {eng}", "",
             f"Acceptance criteria:    {'AGREED' if decision_agreed('acceptance_thresholds_agreed') else 'NOT AGREED'}",
             f"Population defined:     {'YES' if decision_agreed('population_confirmed_by_owner') else 'NO (documented; owner confirmation missing)' if (REPO / 'docs' / 'HAIRLINE_VALIDATION_POPULATION.md').is_file() else 'NO'}",
             f"Algorithm locked:       {'YES' if gs[0]['status'] == PASS else 'NO'}", "", "Gates:"]
    lines += [f"  {x['id']}. {x['name']:<36} {x['status']:<14} {x['detail']}" for x in gs]
    lines += ["", "Overall:", overall(gs)]
    return "\n".join(lines)


# --------------------------------------------------------------------------- run (gated) and manifest
def build_manifest(root: Path) -> dict:
    return {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "engine_files": current_hashes(), "thresholds": threshold_snapshot(),
            "evaluator_sha256": sha256(HERE / "hairline_eval.py"), "cohort_tool_sha256": sha256(Path(__file__)),
            "annotation_sha256": {str(p.relative_to(root)): sha256(p) for p in sorted((root / "annotations").rglob("*.json"))},
            "image_sha256": {str(p.relative_to(root)): sha256(p) for p in sorted((root / "approved").rglob("*")) if p.is_file()},
            "metadata_sha256": {str(p.relative_to(root)): sha256(p) for p in sorted((root / "metadata").glob("*.json"))}}


def verify_manifest(root: Path, man: dict) -> bool:
    try:
        now = build_manifest(root)
    except OSError:
        return False
    return all(now[k] == man.get(k) for k in ("engine_files", "thresholds", "evaluator_sha256", "annotation_sha256", "image_sha256", "metadata_sha256"))


def run(root: Path) -> dict:
    gs = gates(root)
    if overall(gs) == "NOT READY":
        raise CohortError("validation run REFUSED: gates not satisfied -> " + "; ".join(f"{g['id']} {g['name']}: {g['status']}" for g in gs if g["status"] != PASS))
    layout = {"annotations": "annotations/consensus", "machine": "machine_outputs", "overlays": "overlays", "results": "reports/results.json", "index": "reports/overlay_index.json"}
    man = build_manifest(root)
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "run_manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    res = E.evaluate(root, write_outputs=True, layout=layout)
    return res


# --------------------------------------------------------------------------- CLI
def _yes(s: str) -> bool:
    return s.lower() in ("yes", "true", "1")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hairline_cohort")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("init", "status", "gates", "agreement", "run"):
        sub.add_parser(name).add_argument("root", type=Path)
    a = sub.add_parser("add")
    a.add_argument("root", type=Path)
    for f in ("image", "view", "source-type", "source-category", "consent-status", "validation-use", "consent-scope", "adult", "consent-ref"):
        a.add_argument("--" + f, required=True)
    a.add_argument("--captured-on")
    i = sub.add_parser("include")
    i.add_argument("root", type=Path)
    i.add_argument("id")
    x = sub.add_parser("exclude")
    x.add_argument("root", type=Path)
    x.add_argument("id")
    x.add_argument("--reason", required=True)
    x.add_argument("--note", default="")
    q = sub.add_parser("queue")
    q.add_argument("root", type=Path)
    q.add_argument("--annotator", required=True)
    lk = sub.add_parser("lock")
    lk.add_argument("--reason", required=True)
    lk.add_argument("--overwrite", action="store_true")
    ns = ap.parse_args(argv)
    try:
        if ns.cmd == "init":
            print(json.dumps({"created": init_workspace(ns.root)}, indent=2))
        elif ns.cmd == "add":
            r = add_candidate(ns.root, Path(ns.image), ns.view, ns.source_type.replace("-", "_"), ns.source_category, ns.consent_status, _yes(ns.validation_use),
                              ns.consent_scope.split(","), _yes(ns.adult), ns.consent_ref, ns.captured_on)
            print(json.dumps({"validation_id": r["validation_id"], "inclusion_decision": r["inclusion_decision"]}))
        elif ns.cmd == "include":
            include(ns.root, ns.id)
            print("included", ns.id)
        elif ns.cmd == "exclude":
            print(json.dumps(exclude(ns.root, ns.id, ns.reason, ns.note), indent=1))
        elif ns.cmd == "queue":
            print(json.dumps(annotation_queue(ns.root, ns.annotator)))
        elif ns.cmd == "agreement":
            print(json.dumps(agreement(ns.root, write=True), indent=1, default=str))
        elif ns.cmd == "status":
            print(readiness_text(ns.root))
        elif ns.cmd == "gates":
            gs = gates(ns.root)
            print(json.dumps({"gates": gs, "overall": overall(gs)}, indent=1))
        elif ns.cmd == "lock":
            print(json.dumps(write_lock(ns.reason, ns.overwrite), indent=1))
        elif ns.cmd == "run":
            print(json.dumps({k: v for k, v in run(ns.root).items() if k != "per_image"}, indent=1, default=str))
    except CohortError as e:
        print("REFUSED:", e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
