# Report validation (verified implementation)

`backend/app/report_validator.py` runs after the photo analysis and BEFORE recommendations, previews and the report are
built, so unreliable results cannot flow into advice. It only removes, flags or relabels what a module already produced;
it never creates a value. Every decision is stored in `analysis["validation"]` and shown to the user in a "Some results
were withheld" box on the report page. 22 validator tests in `tests/test_validator_and_consistency.py`.

| Rule | Condition | Action |
|---|---|---|
| A | `too_bright` / `too_dark` quality flag | drop skin concerns that depend on brightness (tone, pigmentation, shine, under-eyes) |
| B | iris scale missing, non-finite, outside 0.005-2.0 mm/px, or camera-distance estimate outside 150-3000 mm | withhold every millimetre value; keep dimensionless ratios. Otherwise mm are labelled **estimated**, `validated: false` |
| C | `colour_cast` | drop colour-derived skin concerns (tone, redness, pigmentation, under-eyes, blemishes, dark spots, acne marks) and the skin-tone group |
| D | `beauty_filter` | keep texture/line/blemish readings but flag them as likely understated |
| E | yaw correction at the search limit (>= 29.5 deg) | drop symmetry, flag width-based ratios. `smiling` flags lip and lower-face metrics |
| F | no top-of-head photo | no overall hair score (the observed hairline reading is kept) |
| G | NaN/inf landmarks, < 468 landmarks, or > 10 landmarks outside the frame | reject the photo with an explicit message; no defaults |
| H | module failed or has no data | explicit `unavailable` in `validation.modules` |
| I | heuristic face-shape "confidence" | not published (it is not a calibrated probability) |

Skin score is recomputed from the concerns that remain; if none remain, skin is `unavailable` with a reason, not a
default score. `validation` also records `measurement_version`, `validator` version, and the landmarker model file name
with its real SHA-256 (or `missing`).

## What the end-to-end run showed (two real photos, real pipeline)
Both photos had a colour cast / over-exposure, so 8-9 skin readings and the skin-tone group were withheld, and the overall
hair score was withheld (no top photo). Both reports came back `status: partial`, mm labelled `estimated`.
**Consequence:** the gate is conservative; photos with warm light lose most skin readings, and therefore the skin preview.
Thresholds are unvalidated and need tuning on a labelled set.

## Bug found by this work
The first version treated "no camera estimate" (`cam is None`, which is normal for uploads without EXIF) as "no scale" and
withheld all mm values. Found by the end-to-end run, fixed, with a regression test
(`test_upload_without_exif_still_has_an_iris_scale`).

## Not done
- Per-landmark reliability scores and a validated landmark error are not implemented.
- Quality thresholds (e.g. beard 18%) are unvalidated.
- The validator does not check the rendered PDF/figures against table values automatically.

## Update (Phase 4)
- **Skin rules are now per metric, not lumped.** `SKIN_NEEDS` (what each metric depends on) and `FLAG_EFFECTS` (what each
  quality flag damages) decide, per metric, "withhold" or "flag"; withhold beats flag. Behaviour for colour cast,
  over/under-exposure and beauty filter is reproduced exactly; new: blur withholds fine-detail metrics, glasses withhold the
  under-eye reading and flag wrinkles, uneven light and beard flag the metrics that compare regions or use the lower face,
  low resolution flags fine detail. Details and the full table: SKIN_SEGMENTATION_VALIDATION.md. 24 tests.
- **Rule E uses an explicit pose status.** `compute()` now records `yaw_correction_status` (`ok | saturated | undetermined`).
  `saturated` suppresses symmetry and flags width ratios; `undetermined` (no usable depth) is flagged. See LANDMARK_VALIDATION.md.
- **Rule G extended:** two similar-sized faces (second face >= 0.6x the width of the first) are an error, not a silent choice
  (engineering threshold, unvalidated).
- Quality warnings were checked on two real photos: both had colour cast / over-exposure, so most colour-based skin metrics
  were withheld and only texture and wrinkles (flagged) remained. The gate is conservative by design; no threshold was loosened.

## Update: findings from reading a real report PDF (2026-11-05)
Defects found by reading the report as a user would, all fixed with tests (`test_report_explanations.py`, `test_medical.py`):
1. **"Skin score 100" after 9 of 10 skin readings were withheld** - the score was the average of the single survivor, and the page turned a missing score into 0.
   Now: no overall score when fewer than half of the readings survive, with the reason shown ("only 1 of 10 skin readings were reliable").
2. **Goal statuses said "no measurement points to a specific change" when the readings were withheld, not clean.** New statuses `measurement_unavailable` and
   `partly_unavailable` say so.
3. **The before/after section disappeared with no explanation.** `preview_status` now records, for each preview kind (skin, brows, jaw, lips, other), whether it was
   offered and why not (withheld skin readings, glasses, measurements in range, measurements unavailable, not simulable by image editing).
4. **Retake guidance** (`validation.retake_tips`): a specific tip per quality flag.
Added at the owner's request: an always-visible **Health & professional care** section (`app/medical.py`): limits of the report; three-level red-flag guide;
every professional consult with a status (indicated / not indicated by your measurements / could not assess / not offered for you (safety)); and a list of the health
answers given and what each changed. Two new health answers (`skin_condition`, `prescribed_skin_treatment`) really remove strong actives and procedures; a test fails
if a form option has no effect or an effect has no form option. A **routine preview** block shows the skin simulation beside the skincare routine, or explains why there
is none, and says no product-specific before/after exists.
**Content status: GENERAL INFORMATION - NOT CLINICALLY REVIEWED.** The red-flag text was written by the software's author; a clinician must review it before public use.
Not rerun after these UI changes: the browser suite (the previous 4 x 26/26 results predate them).
