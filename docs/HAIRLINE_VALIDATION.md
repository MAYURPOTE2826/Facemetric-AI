# Hairline & hair-density engine - validation status and protocol

**Hairline detection accuracy: NOT MEASURED.** No labelled hairline data exists. Nothing in this document, the tests, or the report claims a
precision, recall, F1, accuracy or millimetre error for this module.

## 1. What exists (software testing - this is NOT accuracy)
`backend/tests/test_hairline_engine.py` (40 tests) runs the engine on **synthetic drawn heads** (`tests/hair_fixtures.py`). They prove the
*logic*: no invented hairline when the forehead is covered, crown never inferred from a front photo, styling/lighting/resolution lower confidence,
no diagnosis/prescription wording, no centimetres/millimetres, comparison refused when conditions differ, legacy keys preserved.
Synthetic scenes have perfect segmentation masks and clean edges, so passing them says nothing about real photographs, real segmenter errors,
real hair texture or real skin tones.

Scenario coverage (test class / name): straight, rounded, mild mature, possible-pattern, asymmetric, side-part asymmetry, fringe, pulled-back, wet/glossy,
strong light, low light, low resolution, curly/textured, dark hair, light hair, top photo, no top photo, obscured crown, very short haircut,
hairline outside frame, no/tiny face, head roll. "Multiple faces" is rejected upstream by the existing face-count check, not in this module.

## 2. What is NOT measured (and what would measure it)
| Claim | Status | Needed |
|---|---|---|
| Hairline boundary position error | NOT MEASURED | >= 200 consented photographs with a human-drawn visible hairline polyline (`evals/hairline_eval.py` computes the error) |
| Temple recession classification | NOT MEASURED | Human labels of temple recession severity by a qualified rater, with inter-rater agreement |
| Frontal / temple density | NOT MEASURED | Human-labelled scalp-visibility regions, or a reference method such as phototrichogram on the same subjects |
| Crown / parting | NOT MEASURED (legacy top-photo code, unchanged) | Labelled top-of-head photographs |
| Image-quality gate thresholds | NOT MEASURED | Photographs labelled usable / not usable for hairline reading |
| Longitudinal noise floor (`NOISE_FLOOR_V`, `CHANGE_V`) | NOT MEASURED - placeholders | Test-retest photographs of the same people on the same day, different days, different lighting |
| Bias across skin tone, hair colour/texture, age, sex | NOT MEASURED | A dataset stratified on those attributes |

All thresholds in `app/hairline.py` (`T_MILD`, `T_POSSIBLE`, `T_PRONOUNCED`, `MIN_CONTRAST_DE`, blur/exposure limits, density bands) are **placeholders**.
They were chosen from general published norms (a mature hairline recedes ~1-1.5 cm at the temples; bizygomatic width ~13.5 cm) converted to ratios
of face width, and have not been tuned or checked against data.

## 3. Annotation requirements (for a real dataset)
- Photographs outside the repository; consent record per subject; no upload to third parties.
- Per image, drawn by a human who has NOT seen the engine's output (a pre-filled annotation measures agreement with the model, not accuracy; the
  evaluator rejects any `annotation_source` not starting with `human:`):
  visible hairline polyline (original pixels, left to right); temple visible yes/no per side; crown visible; density regions (polygons);
  image-quality label (usable / marginal / unusable); tags: fringe, wet, product, cap, pulled-back, very short, curly, dark/light hair, lighting.
- Second annotator on >= 20 % of images to measure inter-annotator error; report it next to the model error, because the model cannot be
  more accurate than the labels.
- Stratify across skin tone, hair colour and texture, hair length, age, sex, devices, lighting.
- Pre-register acceptance criteria BEFORE running the evaluator. None are defined yet: `ACCEPTANCE CRITERIA NOT YET DEFINED`.

## 4. How to run once data exists
    python -m evals.hairline_eval --init   <root>   # empty skeleton outside the repo (real/front, real/top, annotations, metadata, outputs)
    python -m evals.hairline_eval --status <root>   # counts only what exists; NOT MEASURED when there are no valid human annotations
    python -m evals.hairline_eval --run    <root>   # runs the PRODUCTION engine; writes outputs/machine, outputs/overlays, results.json
Annotation schema `hairline-annotation-v2` (visibility states incl. uncertain/partial/occluded/outside_frame, top-photo labels) is documented in the
docstring of `backend/evals/hairline_eval.py`. Results of the latest phase: `HAIRLINE_VALIDATION_RESULTS.md` (REAL-PHOTO ACCURACY = NOT MEASURED).

## 5. Known limitations of the method
- Classical CV on top of the selfie multiclass segmenter. Where the segmenter mislabels hair, brows, hats or shadows, cue A is wrong; cue B (colour)
  only disagrees when hair and skin differ enough, so light/blond/grey hair or a strong tan shadow lowers confidence rather than being corrected.
- Head pitch (looking up/down) changes the apparent forehead height; only yaw and roll are estimated. Pitch is NOT handled.
- Angled temple photographs are recommended in the capture guidance but are **not analysed** (NOT IMPLEMENTED).
- A front photo cannot show shedding (hair fall) or crown thinning. The engine says so; it never infers either.
- Normalised distances are ratios to face width. No centimetres or millimetres are reported anywhere in the new section. The legacy
  `hairline.height_cm` field is still stored (it feeds a diagram) but is no longer shown in text.
- The legacy questionnaire "likely causes" list (unchanged) names common causes of hair fall in plain language; it is not produced by this
  engine and still needs clinician review.
