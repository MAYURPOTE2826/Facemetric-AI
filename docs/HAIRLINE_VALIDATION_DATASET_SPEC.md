# Hairline validation dataset - specification and intake requirements

Status: **specification only. 0 photographs exist.** A large dataset is not automatically representative; this document states what representation is
required, and anything the dataset does not cover must be reported as NOT COVERED rather than assumed.

> **Layout update:** the first-cohort workspace (candidates / approved / excluded / per-annotator annotations / consensus / machine_outputs / overlays / reports / consent / metadata, plus pseudonymous `HLV-NNNN` ids and the lifecycle) is defined in `HAIRLINE_VALIDATION_COHORT_INTAKE.md` and created by `python -m evals.hairline_cohort init`. The older `real/front`, `real/top`, `outputs/` layout is still read by `python -m evals.hairline_eval` for single-annotator use.

## 1. Location and layout (OUTSIDE the repository)
Root: `~/.alexendra/validation/hairline` (created by `python -m evals.hairline_eval --init <root>`).
    real/front/<id>.jpg     real/top/<id>.jpg     annotations/<id>.json     metadata/<id>.json (intake record)     outputs/ (machine output, overlays, results)
Real-person photographs are never committed, pushed, or sent to a third party. Synthetic scenes live only in `backend/tests/` and are never mixed in.
Front and top photographs are separate folders and separate annotation `view`s. Do not duplicate images.

## 2. Intake requirement (enforced by the evaluator: an image without a valid record cannot become ground truth)
One record per image at `metadata/<id>.json`:

| Field | Allowed values | Meaning |
|---|---|---|
| `validation_id` | non-empty string, unique | the id used everywhere (never a name, email or phone number) |
| `consent_status` | `consented` or `authorized` | `consented` = the person gave documented consent for this use; `authorized` = a licence/authority for this use is documented |
| `consent_scope` | list, must include `validation` for `app_customer_report` | what the person agreed to |
| `image_type` | `front` or `top` | must equal the annotation view |
| `source_category` | `volunteer`, `staff`, `licensed_dataset`, `public_domain_licensed`, `app_customer_report`, `other_documented` | where the image came from |
| `annotation_status` | `pending`, `annotated`, `second_annotated`, `rejected` | workflow state |
| optional | `sex`, `device`, `capture_date`, `consent_ref` | stratification and traceability |

Consent must be recorded outside the image folder and say: purpose (validating a hair-screening algorithm), who may see the photo (named annotators),
where it is stored, how long, that it is not published, and how to withdraw. Withdrawal deletes the photograph, its annotation, metadata and any
machine output/overlay for that id. Adults only (18+). No scraped images.

### Existing application data
The 59 encrypted application reports, and any other production/customer image, are **not** part of the validation set merely because they exist locally.
They may be used only if the individual's explicit consent for validation use is established and recorded (category `app_customer_report`, scope
including `validation`). Using them does not weaken any existing privacy, retention or governance control; reading them requires the app's key and
must follow `SECURITY_AND_PRIVACY.md`. Until then they are out of scope.

## 3. Size (planning minimums - NOT a statistical power result)
| Item | Planning minimum | Why |
|---|---|---|
| Front photos with a traceable hairline polyline | 200 | boundary-error statistics need enough images per region; confirm with a power analysis once variance is known |
| Front photos where the human says "not visible / occluded / outside frame / unusable" | >= 30 (and part of the 200 total or additional) | otherwise visibility, quality-gate and false-reassurance results are INSUFFICIENT |
| Top-of-head photos | 60, including >= 8 "assessable" and >= 8 "not assessable" | crown assessability needs both classes |
| Repeat photographs for longitudinal work | >= 30 people, same-day pair + different-day pair | needed to replace the placeholder change thresholds |
| Second annotator | >= 20 % of images | inter-annotator agreement |
| Per-stratum reporting | >= 30 labelled items in a stratum, else INSUFFICIENT SAMPLE SIZE | evaluator guard |
Planning minimums are the evaluator's guards plus engineering judgement. They do not guarantee statistical adequacy.

## 4. Required variation (each is a stratum to be counted and reported; "NOT COVERED" if absent)
- **Hairline visibility:** clearly visible; partly visible; hidden by fringe; hidden by cap/turban/dupatta; off-frame.
- **Hairline shape:** straight, rounded, mature, M-shaped, V-shaped, irregular, asymmetric (as labelled by humans, not by the engine).
- **Temples:** no recession through pronounced (human-labelled); left/right asymmetry.
- **Hair:** colour (black, brown, blond, grey/white, dyed); texture (straight, wavy, curly, coily); length (shaved/very short, short, medium, long);
  condition (dry, wet, oily/product, glossy); styling (side part, pulled back, fringe, undercut).
- **Hair/skin contrast:** high (dark hair, light skin), medium, low (light/grey hair on light skin; dark hair on dark skin in shadow).
- **Skin tone:** the full range (record a skin-tone scale such as Fitzpatrick I-VI or Monk; at least the groups the intended users belong to).
- **Capture quality:** sharp/blurred; resolution (small face in frame to large); exposure (dark, normal, overexposed/strong overhead light); colour cast;
  filters/beauty mode; head turn (yaw) and tilt (pitch); glasses.
- **Occlusion:** none; fringe; hand; cap; hair tie/headband; shadows.
- **Crown (top photos):** visible; partly visible; obscured by hair length/style or head covering; parting visible/not visible.
- **Demographics:** age bands (18-24, 25-34, 35-44, 45-54, 55+), sex, and the geographic/ethnic mix of the product's intended users.
  **The intended-use population for the hair module has not been defined by the project owner; it must be stated before collection.**
- **Devices:** several phone models and at least one webcam; front and rear cameras.

## 5. Splits
Development set (may be used to understand failures) and validation set (frozen, never used for tuning) are separated by **person**, not by image.
Repeat photographs of the same person stay in one split. The validation set is frozen with a file-hash manifest before the first `--run`.

## 6. Quality controls
Reject images that cannot be decoded; keep "unusable" images (they are needed to test refusal) but label them so; do not crop, filter or enhance;
store originals only. Annotation follows `HAIRLINE_ANNOTATION_SOP.md`. Report the composition table (counts per stratum) in the results document.

## 7. What this dataset would and would not show
It can show how the locked engine behaves on photos like those collected, with stated uncertainty. It cannot show clinical validity, performance on
groups not collected, or follicle-level density. Gaps are reported, not assumed away.
