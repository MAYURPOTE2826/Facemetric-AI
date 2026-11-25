# Hairline validation readiness gate

## Current validation status
**REAL-PHOTO ACCURACY: NOT MEASURED.**
Hairline, temple, density, crown, quality-gate and longitudinal accuracy are all NOT MEASURED. Nothing in this project reports, implies or
estimates a real-world accuracy figure for the hairline engine.

## Why
**0 consented real photographs. 0 human annotations.** No consented photograph set exists on this machine. The 59 encrypted application reports contain
photographs of people who tested the app; they were not submitted for validation, no validation consent is recorded, and they are NOT used (see
`HAIRLINE_VALIDATION_DATASET_SPEC.md`, section 2).

## Engine lock (baseline before real-photo validation)
No detection algorithm and no threshold was changed in this phase. The 51 thresholds are registered in `HAIRLINE_THRESHOLD_REGISTER.md`, every one
marked `VALIDATION STATUS: PLACEHOLDER`, and the named ones are pinned by `tests/test_hairline_threshold_lock.py`.

| File | SHA-256 at start of this phase | SHA-256 now | Change |
|---|---|---|---|
| `backend/app/hairline.py` | `adaf605e1c0bb46b8eb0959b7e5274c56b6c843be9c5ad5acbfb6970b9d068b3` | `2ccffc04c9563fedbfeac61af9d61c5a2e78bb16495cd5085200521838585f60` | **one drawing-only defect fix** (below) |
| `backend/app/hair.py` | `a82d1d0ef2141ae5ee608da254960d713b4f91f6570408d2970f2356ec023ade` | `a82d1d0ef2141ae5ee608da254960d713b4f91f6570408d2970f2356ec023ade` | none |
| `backend/evals/hairline_eval.py` | `52dd5f4ef35e2a333e7134ea6f1788164fcd9caae02e09be74648a52a6b8ba6c` | (changed) | consent/intake enforcement added (validation infrastructure) |

**The one change to `hairline.py` was found by the PDF QA, not by tuning.** For a hidden hairline the report said "Not reliably visible, low confidence
(29 %)" but the overlay drew a green "high-confidence boundary" line and a blue analysis region. The overlay now follows the quality gate: grey curve and no
analysis region when the hairline is not reliably visible or density is not assessable. This changes only the picture. Detection output, confidence values,
statuses and thresholds are unchanged. Covered by `OverlayNeverMoreCertainThanTheVerdict` (3 tests).

## Infrastructure: is the pipeline ready for real-photo validation?
**Yes, as software. It has never been run on a real photograph.**
- Intake/consent enforced in code: an annotation without a valid `metadata/<id>.json` (validation_id, consent_status, image_type, source_category,
  annotation_status) is rejected; `app_customer_report` images additionally need `consent_scope` to include `validation`.
- Evaluator (`python -m evals.hairline_eval --init | --status | --run`): v2 annotation schema with uncertain/partial/occluded/outside_frame, top-photo labels,
  boundary error by region, P/R/F1 with sample-size guards, false-reassurance listing, crown front-only invariant, confidence bins, error-taxonomy candidates,
  machine output and overlays written separately. 17 evaluator self-tests (synthetic scenes, generator-derived labels, **not accuracy evidence**).
- Empty dataset skeleton created outside the repository at `~/.alexendra/validation/hairline`; `--status` reports `NOT MEASURED`.

## Documents
| Document | Status |
|---|---|
| Acceptance criteria (`HAIRLINE_ACCEPTANCE_CRITERIA.md`) | **Defined for software correctness (A1-A14, all pass). Real-photo targets are NOT defined**: each reads `ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION`; the decision log is empty |
| Annotation SOP (`HAIRLINE_ANNOTATION_SOP.md`) | **Ready** (front and top procedures, left/right convention, independence rules, second-annotator rules) |
| Dataset specification (`HAIRLINE_VALIDATION_DATASET_SPEC.md`) | **Ready** as a specification; planning minimums are not a power calculation; the intended-use population is not yet stated by the project owner |
| Consent / intake workflow | **Documented and enforced in the evaluator**; no consent records exist yet |
| Threshold register (`HAIRLINE_THRESHOLD_REGISTER.md`) | 51 thresholds, 51 PLACEHOLDER, 0 validated |

## Browser status (run in this phase, against the final code)
| Browser | Result |
|---|---|
| Microsoft Edge 151 desktop | **38 passed, 0 failed** (26 security + 9 hair UI/progress + 3 PDF) |
| Playwright bundled Chromium desktop | **38 passed, 0 failed** |
| Firefox (Playwright 1.56.1 bundled build) desktop | **35 passed, 0 failed, 3 skipped** (the 3 PDF tests use `page.pdf`, which exists only in Chromium-family browsers, so they are skipped by design) |
Not run: Edge mobile viewport, WebKit/Safari, real phones. (The earlier 26-test mobile/Edge/Firefox/Chromium records in `BROWSER_VERIFICATION.md` predate
the hairline work and were not regenerated; that file is historical.)

**Edge blocker resolved.** The earlier "browser has been closed" failure was reproducible without the app: Edge 151 itself starts fine
(`--remote-debugging-port` works), but Playwright 1.49.1 could not launch it (process exited 0 immediately). Playwright 1.56.1, tried first in a scratch directory,
launched Edge 151. `browser-tests` was therefore moved to `@playwright/test` **1.56.1** (pinned; backups of the previous manifest are
`browser-tests/package.json.bak-1.49.1` and `package-lock.json.bak-1.49.1`), and Chromium and Firefox builds for 1.56.1 were installed. Application code was not
involved. This means the Chromium/Firefox versions differ from the earlier Chromium 131-era / Firefox 132 runs.
**One intermittent test race was fixed**: S6.1 asserted "Save" button gone, but the button only renames itself to "Saving..." while the claim request is in flight,
so the assertion could pass early. It now waits for the claim response and requires HTTP 200 (stricter, not weaker). It had failed once under load on Edge and passed
4/4 in isolation before the fix.

### Browser coverage of the hairline functionality (UI behaviour only - not model accuracy)
| Requirement | Test |
|---|---|
| Hair section appears; hairline confidence rows | H1 |
| Overlay image appears and actually loads | H1 (naturalWidth > 50) |
| Crown NOT ASSESSABLE for front-only | H1, H5, P1 |
| Top-photo explainer on the capture page | H2 |
| Hidden hairline / engine error: inconclusive, no reassuring wording | H4, H5, P3 |
| Front + top: crown shown as assessed | H6, P2 |
| Legacy report without `hair.analysis` still renders | H7 |
| Progress comparison: comparable -> "no change beyond normal variation"; hidden hairline -> refused with a reason | H8a, H8b |
| Clear-all-progress button: cancel and wrong word delete nothing; confirm deletes | H3 |
| Existing facial-analysis report flow and security | S1-S7 (26 tests) |
**A UI defect was found and fixed while writing H8**: the hair comparison on the progress page was nested inside the "aligned photos" block and would not show without
aligned thumbnails; it now renders whenever a comparison exists.

## PDF / print status
**Tested** (Chromium-family only; the app's PDF is the browser print view of `/report/<id>/print`). Real PDFs were generated for: front-only, front + top,
hidden hairline, engine error (`browser-tests/results/pdf-qa/*.pdf`) and the pages were rendered and inspected.
- Present and correct: hair section, overlay, legend, per-row confidence, crown NOT ASSESSABLE (front-only) / assessed (front + top), guidance, limitations,
  NOT MEASURED statement; no cm/mm; images load; no horizontal overflow; `no-print` controls hidden.
- Defects found and fixed: the "accuracy NOT MEASURED" line was orphaned onto the next page (cards, guidance and limitations now keep together);
  the overlay filled most of a page (constrained in print); a redundant legacy "add a top-of-head photo" line duplicated the new crown row (hidden when the
  new section exists); the misleading green overlay for a hidden hairline (above).
- Not covered: Safari/Firefox print output, other paper sizes, very long localized text, the mobile layout of the PDF. The overlay in these PDFs is a drawn
  synthetic head, so colours/legibility on a real photograph are NOT checked.

## Regression (actual numbers, final code)
| Check | Result |
|---|---|
| Backend full suite | **478 ran, 0 failed, 16 skipped** (the 16 need `PFI_TEST_IMAGE` photographs; not supplied) |
| Hairline engine tests | 40 pass |
| Evaluator self-tests | 17 pass |
| False-reassurance / longitudinal safety / API contract / threshold lock | 13 / 12 / 7 / 3 pass |
| `evals.report_evals` | 0 validator failures |
| `tsc --noEmit` / `eslint src` | clean / clean |
Covered by this regression: landmarks and proportions, skin analysis, report generation, authentication, authorization, consent, retention, existing API
contracts, capture flow, progress page. Synthetic scenes are used for software, regression, evaluator and failure-mode testing only; **they are not reported as
real-photo accuracy, real-world validation, clinical validation or model accuracy.**

## Remaining blockers
1. Consented real photographs and human annotations (0 of each).
2. Real-photo acceptance thresholds agreed and recorded BEFORE validation (none defined).
3. Intended-use population for the hair module stated by the project owner.
4. Second annotator and inter-annotator agreement; repeat photographs for the longitudinal thresholds.
5. All 51 thresholds remain placeholders.
6. Head pitch not handled; angled temple photographs recommended but not analysed.
7. Real-photo overlay legibility/colour not checked in print; Safari/WebKit and real phones untested; PDF only verified through the Chromium print path.
8. Clinician review of the legacy hair-fall "likely causes" text (not produced by this engine).
9. Overall PFI blockers unchanged (see `PRODUCTION_READINESS.md`).

## Verdict
# NOT READY
The hairline module is ready to START real-photo validation (pipeline, SOP, specification, consent gate and criteria framework exist) but is **not validated, not
accurate-by-evidence, not clinically validated and not production-ready**. The overall PFI governance verdict is unchanged: NOT READY.

## Next phase
Real consented photograph collection and independent human annotation. Only after the annotations exist (and the real-photo acceptance thresholds are agreed)
should accuracy be measured. Do not tune the algorithm before then.
