# Hairline engine - real-photo validation results

> **UPDATE (readiness gate phase):** the Edge launch failure described below was caused by Playwright 1.49.1 being unable to launch Edge 151 and is resolved
> (Playwright 1.56.1). Current browser results (Edge 38/38, Chromium 38/38, Firefox 35 + 3 skipped), the PDF QA, the consent/intake enforcement, the
> acceptance criteria, SOP, dataset specification and threshold register are in `HAIRLINE_VALIDATION_READINESS.md`. Real-photo accuracy is still NOT MEASURED.

## Headline
**REAL-PHOTO ACCURACY = NOT MEASURED.** No real photograph with a human annotation exists for this module, so no boundary error, precision, recall,
F1, shape agreement, density agreement or quality-gate figure is reported. Nothing in this document is an accuracy claim.

What this phase did instead (all of it is verification of the *validation pipeline* and of the surrounding product, not of the engine's accuracy):
1. Re-read the protocol and the code (section 2).
2. Extended the evaluator so it implements the protocol in full, including the human's right to say "uncertain" (section 3).
3. Proved the evaluator's arithmetic and rules with 13 self-tests on synthetic scenes (section 4) - labelled as such, not as validation.
4. Created the (empty) real-photo dataset skeleton outside the repository and confirmed it reports `NOT MEASURED`.
5. Ran the full regression suite and the browser tests after the hairline changes (section 7).

## 1. Dataset
| Item | Count |
|---|---|
| Real photographs available for this module | **0** (none anywhere on this machine except the app's own encrypted reports, which are not used - see below) |
| Human-annotated images | **0** |
| Front / top photos | 0 / 0 |
| Annotators, second annotator | none |
| Overlays of real photographs | none exist |
Dataset root: `~/.alexendra/validation/hairline` (outside the repository): `real/front`, `real/top`, `annotations`, `metadata`, `outputs`, `README.md`.
`python -m evals.hairline_eval --status <root>` -> `NOT MEASURED`.

**Why the app's stored reports were not used.** `backend/data` holds 59 encrypted reports with photographs of people who tested the app. They were
submitted to be analysed, not to build a validation set; no consent for that use is recorded, and a validation set built from the engine's own
reports would still need independent human labels. They were therefore left unread. Using them would need the owner's explicit decision and consent
confirmation per subject.

## 2. Protocol confirmed (no change made to make the engine pass)
- **Annotations required** (front): hairline visibility state, left-to-right hairline polyline (original pixels), per-temple visibility and recession
  label, shape, image quality, frontal-density rating. (top): crown assessable yes/no/uncertain, crown density, parting visible.
- **Format:** `hairline-annotation-v2` JSON (documented in `backend/evals/hairline_eval.py`); legacy v1 files are still read.
- **Valid:** source starts with `human:`; image exists and sits in the folder matching `view`; every enumeration value is known; visible/partial has
  >= 5 points with non-decreasing x. **Invalid:** model-assisted/unlabelled source, missing image, unknown value, visible/partial without a polyline.
- **Uncertain / partial / not_visible / occluded / outside_frame** are honoured: they are never turned into ground truth for the item they cover.
- **Front vs top:** separate folders and `view`; a front photo is always run with no top photo, so `crown.status` must be `not_assessable`
  (a violation is listed in `crown_front_only_violations`); a top photo is run through `hair.analyze_top` and compared with the human `assessable` label.
- **Metrics:** boundary error (distance to the human polyline / bizygomatic width) overall and for centre, left temple, right temple; P/R/F1 for
  hairline visibility, temple pattern, crown assessability and the quality-gate refusal; shape agreement; density agreement; false-reassurance cases;
  error vs confidence bins; error-taxonomy candidates. **No millimetres.** Anything with < 30 labelled items or < 8 positives prints
  `INSUFFICIENT SAMPLE SIZE` with the raw counts.
- **Confidence evaluation:** boundary error is binned by the engine's hairline confidence (>= 0.7 / 0.4-0.7 / < 0.4); calibration cannot be assessed without data.
- **Placeholder thresholds still in force (none tuned):** `T_MILD 0.06`, `T_POSSIBLE 0.11`, `T_PRONOUNCED 0.185` (face-width units), `MIN_CONTRAST_DE 18`,
  blur/exposure limits, density bands (scalp 8 % / 20 %), quality-gate "reliable" = visible and confidence >= 0.4, longitudinal `NOISE_FLOOR_V 0.03`,
  `CHANGE_V 0.06`, `NOISE_FLOOR_DENSITY 0.05`, and the evaluator's own `REVIEW_TRIGGER_BZ 0.06` (a review trigger, not an acceptance criterion).
  `ACCEPTANCE CRITERIA NOT YET DEFINED`.

## 3. Evaluator changes (made because the protocol required them, not because of any engine result)
The previous evaluator knew only "hairline visible: true/false" and had no way to say uncertain/partial/occluded, no top-photo labels, no
classification metrics, no overlays and no machine-output separation. It now has: schema v2 with the full state vocabulary; `--init`, `--status`,
`--run`; validation with stated reasons; boundary error by region; P/R/F1 with sample-size guards; false-reassurance detection; crown front-only
invariant check; confidence bins; error-taxonomy candidates; machine output written to `outputs/machine/` (never to `annotations/`); overlays
(human solid cyan, engine dashed orange) indexed by bucket: `no_issue, missed, false_detection, partial, inconclusive, boundary_error,
temple_error, density_error, crown_error, false_reassurance`.
Limitation: top-photo overlays show only the photograph and legend (the engine returns a scalp percentage, not a crown polygon).

## 4. Self-test evidence (software only)
`tests/test_hairline_eval_pipeline.py` (13 tests) uses drawn scenes with labels derived from the generator and the source string
`human:SELFTEST-synthetic`. It proves: every valid/invalid annotation case is classified as stated; P/R/F1 arithmetic; the sample-size guard; empty
dataset -> `NOT MEASURED`; uncertain/partial excluded; false reassurance and crown violations are detected; machine output and overlays are written
separately. **These are not accuracy numbers and are not reported as such.**

## 5. Engine results on real photographs
Not produced. Nothing was run on a real face in this phase because there is none to run. Therefore, for every output below the status is NOT MEASURED:
hairline boundary error, left/right/centre error, visibility P/R/F1, temple-pattern P/R/F1, crown assessability P/R/F1, quality-gate P/R/F1, shape
agreement, frontal-density agreement, confidence calibration, longitudinal accuracy, false-reassurance rate on real images.
False positives / false negatives / quality-gate examples / crown examples / density examples / error taxonomy / example overlays: **none exist**.
Density note: `FRONTAL DENSITY ACCURACY: NOT MEASURED` - a photograph cannot give follicle counts, and no human regional rating exists to compare against.
Shape note: whether humans can reliably tell the eight shape categories apart is unknown; that must be measured (inter-rater agreement) before a shape metric means anything.

## 6. What the software tests do show (and do not)
They show logic on drawn heads: no hairline is invented under a fringe or off-frame, the crown is never inferred from a front photo, styling/lighting/
resolution lower confidence, no diagnosis or medicine wording, no cm/mm, comparisons are refused when conditions differ. They do not show how
the segmenter and colour cue behave on real hair, skin tones, textures, lighting or devices. The "FALSE REASSURANCE" requirement is therefore
**implemented in the evaluator and unit-tested, but untested on real images**.

## 7. Regression and browser results (executed in this phase, after the changes)
| Check | Result |
|---|---|
| Backend `python -m unittest discover -s tests` | **439 ran, 0 failed, 16 skipped** (the skipped tests need `PFI_TEST_IMAGE` photographs, none supplied) |
| Hairline engine tests / evaluator self-tests | 40 / 13 pass |
| `python -m evals.report_evals` | 15/15 validator self-tests, 0 failures |
| `npx tsc --noEmit` / `npx eslint src` | no errors / no problems |
| Browser, Playwright bundled Chromium desktop | **29 passed, 0 failed** (26 security + 3 new hair-UI tests) |
| Browser, Firefox 132 desktop | **29 passed, 0 failed** |
| Browser, Microsoft Edge desktop | **FAILED TO LAUNCH** (`browserType.launch: Target page, context or browser has been closed` within ~130 ms; 24 failed / 5 passed where the 5 are API-only tests that open no browser). Environment problem, not an application result. **Edge is NOT TESTED in this phase.** The earlier 26/26 Edge run predates the hairline changes. |
| Not run | Edge mobile viewport, WebKit/Safari, real phones, print/PDF view |
The new browser spec (`browser-tests/tests/hair-ui.spec.ts`) checks what the pages **render** from a seeded synthetic hair result: the report section
(confidence, `NOT ASSESSABLE` crown, legend, limitations, no old hair score, no cm/mm/diagnosis words), the capture explainer on the photos step, and the
clear-progress flow (cancel / wrong word delete nothing; confirm + `DELETE` removes the account's reports). They say nothing about engine accuracy.
Regression areas covered by the suite: landmarks and proportions, skin analysis, report generation, authentication, authorization, consent,
retention, API contracts (backend suite); progress page and capture flow (browser, partly). **PDF output was not exercised.**

## 8. Changes made this phase
Only evaluator/validation infrastructure, tests and docs: `evals/hairline_eval.py` (rewritten to the full protocol), `tests/test_hairline_eval_pipeline.py`,
`browser-tests/tests/hair-ui.spec.ts`, a `hair` option on the test-only seed route in `browser-tests/server/run_test_backend.py`, this document and
`HAIRLINE_VALIDATION.md`. **No engine threshold or algorithm was changed**: there was no real-photo evidence to justify one.

## 9. Remaining gaps
1. Real, consented, human-annotated photographs (>= 200 for boundary work; >= 30 labelled items and >= 8 positives per classification metric; stratified by
   skin tone, hair colour/texture, length, age, sex, device, lighting) - none exist.
2. Written acceptance criteria before the first run.
3. Inter-annotator agreement on a second-annotator subset.
4. Test-retest repeat photographs to replace the longitudinal placeholder thresholds.
5. Head pitch handling; angled temple photographs (not analysed).
6. Edge desktop browser run to be repeated once the launch problem is fixed.
7. Clinician review of the legacy hair-fall "likely causes" text.

## 10. Production-readiness conclusion for this module
**NOT READY.** Accuracy is NOT MEASURED, no acceptance criteria exist, thresholds are placeholders, and the overall project verdict is unchanged
(NOT READY). Processing real images would not by itself change this; adequate validation would be required first.
