# Hairline annotation - standard operating procedure

Purpose: produce human ground truth that is independent of the software being tested. Status: **ready for use; no annotation has been made.**
Machine-readable format and validity rules: docstring of `backend/evals/hairline_eval.py` (schema `hairline-annotation-v2`).

## 0. Independence rules (mandatory)
The annotator must NOT:
1. see the engine's prediction, score, overlay, confidence or status for any image before annotating it (annotate first; the evaluator is run later);
2. use an engine overlay, or any engine output, as a starting point or to "check" a label;
3. use another automated detector (landmarks, segmentation, edge detector, AI model, an assistant such as Claude) to generate or pre-fill a label;
4. use the app's report for that person (or any generated report) as ground truth;
5. be shown how a previous annotator labelled the same image (second annotation is made independently).
Annotation files whose `annotation_source` does not start with `human:<annotator id>` are rejected by the evaluator. A model-assisted label would
measure agreement with the model, not accuracy.
Human-human agreement (two annotators) and human-engine agreement are different quantities and are always reported separately.

## 1. Before you start
- Confirm the image has an intake record (`metadata/<id>.json`) with `consent_status` of `consented` or `authorized`. No record, no annotation.
- Use an image viewer that shows the original, un-mirrored, un-filtered image at full resolution with pixel coordinates (x to the right, y DOWN, origin at the
  top-left corner). Do not zoom-crop away the context you need to judge visibility.
- Annotate in random order. Record your annotator id in `annotation_source` ("human:<id>").
- If you cannot tell, say **uncertain**. Never guess. An image you cannot reliably label is not converted into ground truth.

## 2. Left and right
`left` always means the SUBJECT's left, which is the IMAGE's right. The polyline is traced from the image's left edge to the image's right edge
(non-decreasing x).

## 3. FRONT photos (`view: "front"`)
### 3.1 `hairline_visibility`
| Value | Use when |
|---|---|
| `visible` | the whole hair/forehead boundary from temple to temple can be followed by eye |
| `partial` | part of the boundary can be followed and part cannot (fringe over one side, shadow, glare); trace only the part you can follow |
| `not_visible` | the boundary cannot be identified anywhere (fringe over the forehead, hair covering, bald/shaved with no edge) |
| `occluded` | something other than hair covers it (cap, turban, dupatta, hand, headband) |
| `outside_frame` | the hairline is cut off by the image edge |
| `uncertain` | you cannot decide between the above |

### 3.2 `hairline_polyline_px` (required for `visible` and `partial`)
Trace the visible boundary where continuous hair meets forehead skin, at least 5 points, left to right, original pixel coordinates.
Place points on the boundary itself, not on a guessed smooth curve; follow the temple corners down the sides. Ignore single stray hairs and the
fuzzy edge of baby hairs: follow the edge of the main hair mass. For `partial`, stop where you can no longer follow the boundary. Do not extrapolate.

### 3.3 Temples (`temples.left` / `temples.right`)
- `visibility`: same vocabulary as 3.1, judged for that temple only.
- `recession`: your visual impression of how far that temple corner sits above the centre hairline: `none`, `mild` (a mature-looking corner),
  `possible`, `pronounced`, or `uncertain`. This is a screening impression, **not a diagnosis**. Use `uncertain` whenever the temple is not clearly visible,
  and never label recession for a temple whose visibility is not `visible`.
### 3.4 Centre hairline
Covered by the polyline (its middle section). If the centre is hidden (fringe) but the sides are visible, use `partial`.
### 3.5 `shape`
One of: `relatively_straight`, `rounded`, `mildly_mature`, `m_shaped`, `v_shaped`, `asymmetric`, `irregular`, `insufficient_visibility`, `uncertain`.
Describe the outline only; a mature hairline is not hair loss. If two annotators cannot agree on shapes, that disagreement is a finding about the
categories, not an error to be argued away.
### 3.6 `frontal_density` (visible scalp in the band just above the hairline)
`no_reduction`, `slight`, `reduced`, or `uncertain`. This is your impression of how much scalp shows through the hair; it is not a hair count.
Use `uncertain` for very short hair, wet or glossy hair, strong light, or low resolution, where scalp showing is expected or unreadable.
### 3.7 `quality`
`usable` (you could confidently read the hairline); `marginal`; `unusable` (blur, dark, overexposed, tiny, heavily filtered, head turned or tilted
so you could not read it); `uncertain`. Judge the PHOTO, not the person.
### 3.8 Tags
Add any that apply: `fringe`, `side_part`, `pulled_back`, `cap`, `curly`, `wet`, `glossy`, `short`, `long`, `dark_hair`, `light_hair`, `low_contrast`,
`dark`, `overexposed`, `blurry`, `low_res`, `head_turned`, `glasses`, `filter`.

## 4. TOP photos (`view: "top"`)
- `assessable`: `yes` (crown/vertex region visible and judgeable), `no` (not visible or obscured: the crown is covered, the photo is not from above, hair
  length/style hides it), `uncertain`. "Partially visible" crown: choose `yes` only if you could judge density there; otherwise `no` or `uncertain`.
- `crown_density`: `no_reduction`, `slight`, `reduced`, `uncertain` (impression of visible scalp at the crown/vertex; not a hair count).
- `parting_visible`: `yes`, `no`, `uncertain`.
- Vertex region, parting region and visible-scalp region polygons are NOT required by the current evaluator; if the project later adds them they will be
  specified here before use. Do not invent a format.
- Quality issues: use `tags` (`blurry`, `dark`, `overexposed`, `cap`, `low_res`, `not_from_above`).

## 5. Quality assurance
- A second annotator independently labels at least 20 % of images (and any image the first annotator marked uncertain may be sent to the second).
- Report inter-annotator agreement separately: categorical labels by percent agreement and Cohen's kappa; polylines by mean distance between annotators in
  face widths. Disagreements are NOT resolved by looking at the engine. If a consensus label is wanted, a third human adjudicates after both finish, and the
  original labels are kept.
- Do not edit an annotation after the engine has been run on that image.
- Time per image and any problems are logged in `annotation_status` (`annotated`, `second_annotated`, `rejected`).

## 6. Example (front)
    {"schema": "hairline-annotation-v2", "annotation_source": "human:A01", "image": "real/front/V0001.jpg", "view": "front",
     "tags": ["side_part"],
     "front": {"hairline_visibility": "partial", "hairline_polyline_px": [[410,380],[460,350],[520,330],[600,322],[680,330]],
               "temples": {"left": {"visibility": "visible", "recession": "mild"}, "right": {"visibility": "occluded", "recession": "uncertain"}},
               "shape": "uncertain", "quality": "usable", "frontal_density": "uncertain"}}
Matching intake record `metadata/V0001.json`:
    {"validation_id": "V0001", "consent_status": "consented", "image_type": "front", "source_category": "volunteer", "annotation_status": "annotated"}

## 7. Workspace, per-annotator folders and the independence attestation (added for the first cohort)
- Annotators work only from the pseudonymous queue (`python -m evals.hairline_cohort queue <root> --annotator A01`) and see `approved/` images by id only.
  The queue never contains an image the engine has already processed. Reports, engine output, overlays and the other annotator's labels are not in the annotator's
  workspace and must not be opened.
- Annotator A writes `annotations/annotator_a/HLV-NNNN.json`; annotator B writes `annotations/annotator_b/HLV-NNNN.json`. They must be two different people
  (`annotation_source` = `human:<id>`, different ids). One person cannot fill both columns.
- Every annotation file must include this attestation, and every value must be `false`; otherwise the file is not counted:
      "independence": {"engine_output_seen": false, "report_seen": false, "other_annotator_seen": false}
- The `image` field points at the approved copy, for example `approved/front/HLV-0001.jpg`.
- Both original annotations are always kept. Disagreements are listed by `agreement`, never overwritten. Resolution needs the adjudication procedure, which is
  **not yet defined** (decision `adjudication_procedure_defined`). Exactly identical polylines from two annotators are flagged as a suspected copy and are not counted.
- Crown: for a front image the crown is never labelled; for a top image use `top.assessable` (`yes` = ASSESSED, `no` = NOT ASSESSABLE, `uncertain`).
