# Landmark accuracy - dataset contract and evaluator

## Status: **ACCURACY NOT MEASURED**
No labelled landmark dataset exists in this repository and none was fabricated. The infrastructure to measure accuracy is built and tested
on synthetic data (arithmetic only). The two-photo experiment in LANDMARK_VALIDATION.md measures **stability and robustness, not accuracy**.

## The three things, kept apart
| Term | Question | Needs a reference? | Tool |
|---|---|---|---|
| **ACCURACY** | how far are the model's landmarks from an independent human annotation? | yes (human labels) | `python -m evals.landmark_accuracy --dataset <dir>` |
| **ROBUSTNESS** | how does that accuracy change by pose, lighting, occlusion, image quality? | yes (same labels, grouped) | same tool, `ROBUSTNESS_by_condition` |
| **STABILITY** | how much do landmarks move when the INPUT is perturbed? | no | `python -m evals.landmark_validation --image <path>` |
If the reference annotations were produced by a model (annotation_source starting `model:`), the evaluator labels the result **AGREEMENT**,
not accuracy: one model compared with another says nothing about truth.

## Where data lives
Real-person photographs and annotations stay **outside the repository**, in a folder you control, with consent recorded per image
(`consent_ref`). Tests use blank images and a stub detector only. Do not label images with demographic attributes inferred from photographs.

## Layout (`python -m evals.landmark_accuracy --validate <dir>` checks it)
```
<dir>/manifest.json
<dir>/images/<image_file>
<dir>/annotations/<image_id>.json
```
`manifest.json`: `dataset_version`, `annotation_protocol`, and `items[]` each with
`image_id`, `subject_id`, `image_file`, `capture{device, format, width_px, height_px}`,
`conditions{pose{yaw_deg,pitch_deg,roll_deg,source}, pose_group (frontal|yaw_15_30|yaw_over_30|pitch|roll|other), lighting
(even|side|dim|bright|warm|cool|mixed), occlusion[] (glasses|beard|hand|mask|hair|none), expression, quality_group (good|blurred|low_res|compressed|filtered)}`,
`consent_ref`.
`annotations/<image_id>.json`: `image_id`, `annotation_source` (`human:<annotator id>` or `model:<name>`), `annotation_version`,
`landmarks{"<index 0-477>": {"xy":[x_px,y_px], "visible":bool}}` (a subset of indices is allowed; indices follow `landmark_map.py`).

## What is computed (all in % of the normaliser)
Normaliser = inter-pupil distance from the reference iris centres (468/473); falls back to the outer-eye-corner distance (33/263); an
image with neither is reported as skipped, not guessed. Reported: pooled landmark error **mean, median, P95, max**; per-image mean
error distribution; **per-landmark** mean; **per-region** (eyes, iris, brows, nose, mouth, face contour); and the same statistics
**per condition group** (pose group, lighting, occlusion label, quality group). Detection failures and skipped images are listed, never
dropped. Groups with fewer than 20 landmark errors carry a note that P95 is not meaningful; always read `n`.
**No pass/fail and no acceptance threshold is defined or applied** (`acceptance_criteria: NOT DEFINED`).

## Verified so far (synthetic only)
18 tests check the arithmetic against hand-computed values (known shifts give exact means/medians/P95/max; per-region and per-landmark
numbers; grouping by pose/lighting/occlusion/quality including images counted in each of their occlusion labels; invisible landmarks
excluded; failures counted; normaliser fallback; model-reference labelling; dataset validation catching missing files, duplicate ids,
bad pose groups, out-of-range indices, malformed coordinates). Region index lists are defined in `landmark_accuracy.REGIONS` and are
range- and duplicate-checked by tests; their anatomical membership has not been cross-checked against MediaPipe's own connection constants.
