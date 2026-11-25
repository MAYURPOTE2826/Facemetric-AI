# Physical measurement validation plan (not yet executed)

## Current state - no accuracy claim is made
Millimetre values come from an **unvalidated iris-size constant**: `mm_per_px = 11.7 mm / measured iris diameter in px`. They
are labelled "estimated" in every report (`validation.calibration = {status: "estimated", validated: false}`). No `+/- mm`
figure may be stated until the procedure below has produced one.

## Sources of uncertainty (known, not yet quantified)
1. Individual iris (horizontal visible iris diameter) differs from the 11.7 mm population value; this is a *scale* error that
   affects every length by the same percentage.
2. Landmark localisation error (measured only as stability so far - see LANDMARK_VALIDATION.md - not as error against truth).
3. Perspective: closer cameras exaggerate central features; correction applies only when focal length is known (EXIF or the
   live camera) and uses an assumed depth model.
4. Pose, expression, facial hair, and what each landmark means anatomically (soft-tissue landmarks, not bone).
5. Photo conditions: blur, compression, resolution.

## Ground truth required
For each participant, with written informed consent and approval appropriate to your jurisdiction:
- Direct measurements by a trained examiner with a digital sliding caliper (or a 3D scanner), each landmark distance
  taken **twice by the same examiner and once by a second examiner**, to estimate repeatability and inter-observer error. The
  measurements must correspond to the same definitions the software uses (soft-tissue bizygomatic width, nasion-gnathion,
  alar width, intercanthal and biocular width, mouth width, etc.).
- A neutral-expression, level-head, front photograph in the same session with the real capture flow, and (separately) with
  typical phone cameras and lighting.
- The camera model, whether EXIF focal length was present, and capture distance are recorded as covariates. Do not infer or
  record demographic labels from the photographs.

## Sample size (a recommendation with its reasoning)
Agreement limits (mean difference +/- 1.96 SD of the differences, Bland-Altman) have a standard error of roughly
`1.71 * s / sqrt(n)` for large n, where s is the SD of the differences. With n = 30 each limit is only known to about
+/-0.31 s; with n = 100 about +/-0.17 s. Therefore: **a pilot of about 30 participants** to find gross problems and estimate s,
then **at least 100** for any published accuracy statement, with the count recomputed from the pilot's s and the precision
you need. Compute it before collecting, not after.

## Procedure
1. Freeze the software version (record `measurement_version`, model SHA-256).
2. Collect ground truth and photographs; the analysis operator must not see the caliper values.
3. For every measurement and participant compute the difference `d = software - caliper` (mm) and relative difference.
4. Report per measurement: n, mean difference (bias), SD of differences, 95% limits of agreement, mean absolute error,
   Bland-Altman plot, and the proportion of results within a pre-registered tolerance.
5. Separately report the *scale* component (regress software length on caliper length across measurements per participant: a
   slope different from 1 indicates a per-person scale error) and the *landmark* component (residual after scale correction).
6. Stratify by capture condition (EXIF present or not, distance, phone), not by inferred demographics.
7. Compare with and without the perspective correction.

## Acceptance criteria (to be set BEFORE the study, by the product owner and an anthropometry expert)
Not invented here. The criteria must state, per measurement, the maximum acceptable bias and the maximum acceptable
half-width of the 95% limits of agreement, chosen from how the number is used in the report. Until a criterion is met, that
measurement stays "estimated"; if the limits are too wide to be useful it stays withheld or ratio-only. A measurement may
only be shown with a `+/-` figure if that figure came from this study and applies to the same capture conditions.

## Failure outcomes
If agreement is poor, options in order: show dimensionless ratios only; calibrate against a user-supplied reference object
(e.g. a credit card held at the forehead) and validate that; or keep millimetres withheld.

## Implemented framework (Phase 5) - ready for the study, no study run
`python -m evals.measurement_validation --reference reference.csv --automated automated.csv [--out report.json]` (16 tests, hand-computed
arithmetic on synthetic numbers). **No caliper data exists; nothing has been validated; every measurement stays `ESTIMATED - NOT VALIDATED`.**
- `reference.csv`: `subject_id, measurement, operator, repetition, value_mm, instrument`
- `automated.csv`: `subject_id, image_id, measurement, value_mm, device, conditions, measurement_version`
Per measurement it reports: n pairs; mean error (bias = automated - reference); SD of errors; 95% limits of agreement and the standard error of
each limit; a proportional-bias slope; absolute error (mean, median, P95, max) and relative absolute error; the Bland-Altman points
(pair mean, difference) for plotting; reference repeatability (within-subject SD, repeatability coefficient, mean difference between
operators); automated repeatability across a subject's photographs; and lists of unmatched records. The reference value for a subject is the
mean over all operators and repetitions. Output always carries `ACCEPTANCE CRITERIA NOT YET DEFINED`; a source scan test fails if any
`+/- N mm`, `+/- N%`, "clinically accurate" or "high precision" claim appears in the application or frontend source (it found and led to the
removal of three such claims in `hair.py` and one in `anthropometry.py`).
