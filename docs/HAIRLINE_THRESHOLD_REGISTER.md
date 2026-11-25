# Hairline threshold register

Every number below is a **placeholder** chosen by the software's author. None has been tuned, calibrated or validated against labelled real photographs, repeat photographs or clinical assessment. **No row implies that a value is clinically or statistically validated.**

Rule: a threshold may change only with a recorded reason (what evidence, which dataset, who decided) added here AND a matching update of the baseline in `backend/tests/test_hairline_threshold_lock.py`. A value must never be tuned to improve a validation score.

Baseline recorded before real-photo validation (engine locked, no tuning): file hashes are in `HAIRLINE_VALIDATION_READINESS.md`.

Units: 'face widths' = bizygomatic width (cheekbone to cheekbone), so values are resolution-independent; they are NOT calibrated millimetres.

ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION (see `HAIRLINE_ACCEPTANCE_CRITERIA.md`) - none of the values here is an acceptance target.


## Boundary detection

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `COLUMNS` | 25 columns, u from -0.5 to +0.5 (face widths) | where across the forehead the hairline is sampled | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `scan start` | v0 = max(0.10, brow height + 0.04) face widths above the glabella | start above the brow so brows are not mistaken for hairline | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `scan range` | up to 1.6 face widths above the glabella | how far to look for hair | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `run length` | max(3 px, 0.02 x face width) | consecutive hair pixels needed to accept a boundary | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `cue agreement tolerance` | 0.035 face widths | segmentation cue and colour cue 'agree' if within this | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `column confidence values` | 0.9 agree; 0.4 disagree or colour-only; 0.55 segmentation-only when colour cue unusable | per-column confidence | design choice; not calibrated against error | **VALIDATION STATUS: PLACEHOLDER** |
| `outlier rule` | replace a column differing > 0.08 from the median of its neighbours; confidence capped at 0.3 | remove one-column spikes | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `MIN_CONTRAST_DE` | 18.0 (Lab distance between skin and hair colour) | below this the colour cue is not used | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `reference pixel minimums` | 40 forehead-skin px, 200 hair px | need enough pixels to form colour references | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Quality gate

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `tiny-face rejection` | bizygomatic width < 40 px | face too small to analyse | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `low_resolution flag / resolution score` | flag if width < 150 px; score = min(1, width/300) | resolution gate | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `blur` | Laplacian variance of head crop rescaled to width 300: score = clip((v-15)/45); flag 'blurry' if score < 0.35 | sharpness gate | design choice; no source; exercised only on synthetic scenes | **VALIDATION STATUS: PLACEHOLDER** |
| `over-exposure` | flag if > 12 % of forehead samples have Lab L > 235 | exposure gate | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `under-exposure` | flag if > 12 % of samples have L < 25 or mean L < 60 | exposure gate | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `glossy / wet hair` | flag if > 4 % of hair pixels exceed median hair L + 80 | specular highlights | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `skin/hair contrast score` | min(1, contrast / 30) when colour cue usable, else 0.5 | contrast gate | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `head-turn proxy` | |left-right nose offset| / face width; flag > 0.15; confidence x 0.5 | yaw gate (pitch is NOT handled) | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `fringe / covered forehead` | forehead band v 0.14-0.34, |u|<0.35: skin fraction < 0.5 => fringe | hairline hidden by hair | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `headwear / outside frame` | flag if >= 6 of 25 columns are 'covered' / 'edge' | cap or off-frame hairline | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `textured / irregular boundary` | std of second difference of the curve > 0.045 => flag, confidence x 0.7 | curly/textured/clumped hair | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `hairline_visible` | valid columns >= 60 %, no fringe, no cap, not off-frame | gate for any hairline claim | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `temple visible` | at least 3 valid columns in 0.28 <= |u| <= 0.5 on that side | gate for a temple claim | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `confidence formula` | min(res, blur, expo) x (0.5 + 0.5 x contrast) x (1 or 0.3 if hairline not visible); overall_score weights 0.35/0.30/0.20/0.15 | combine gate parts | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Temples

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `T_MILD` | 0.06 face widths | temple corner depth at which 'mildly mature shape' starts | general norm: a mature hairline recedes ~1-1.5 cm at the temples, face width ~13.5 cm (citation not re-verified) | **VALIDATION STATUS: PLACEHOLDER** |
| `T_POSSIBLE` | 0.11 face widths | 'possible recession pattern' starts | same as above; legacy cm thresholds 0.8/1.5/2.5/3.5 converted | **VALIDATION STATUS: PLACEHOLDER** |
| `T_PRONOUNCED` | 0.185 face widths | 'more pronounced' possible pattern | same as above | **VALIDATION STATUS: PLACEHOLDER** |
| `zones` | depth: 0.28 <= |u| <= 0.46 vs centre |u| <= 0.12; density: 0.28-0.5 | where temple and centre are measured | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Shape

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `asymmetric` | |left depth - right depth| > 0.08 | shape label | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `mature / M-shaped` | both depths >= T_MILD / >= T_POSSIBLE | shape label | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `V-shaped` | centre - nearby >= 0.04 and centre - lateral >= 0.04 (points at +-0.12, +-0.40) | shape label | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `rounded / straight` | centre - lateral >= 0.06 => rounded; v range < 0.05 over |u|<=0.42 => straight | shape label | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Symmetry

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `score` | 100 x (1 - mean mirrored difference / 0.15); needs >= 4 mirrored pairs | symmetry | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Density

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `band` | 0.01-0.13 face widths above the hairline; frontal u +-0.3 | region sampled | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `scalp-visibility bands` | < 0.08 none; < 0.20 slight; else reduced | density label | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `score` | 100 x (1 - scalp / 0.4) | density score | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `confidence modifiers` | very short hair (thickness < 0.10) x 0.4; glossy x 0.6; hair close to skin x 0.6; < 0.25 => inconclusive | lower confidence when density is unreliable | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Crown (new view)

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `confidence / density` | confidence 0.7, or 0.3 if hair area < 10 % of image; score = 100 x (1 - scalp% / 40); labels < 10 % / < 20 % | crown summary from the top photo | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `regional split` | centre = within 0.45 of head radius | central vs outer scalp | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Crown (legacy analyze_top)

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `scalp-percentage bands` | < 8 / < 16 / < 28 % | crown label and score | unsourced guidance 'under ~10 % is typical in good light' | **VALIDATION STATUS: PLACEHOLDER** |
| `dark-hair scalp rule` | hair L < 45 => bright skin-coloured pixels (L > hair L + 28, a > 4) count as scalp | detect scalp through dark hair | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `parting` | strip length >= 0.25 of span and length/width >= 4; width bands 3 / 6 / 10 mm | parting width (now shown only relative to head width) | clinical scales referenced in code comments; not re-verified | **VALIDATION STATUS: PLACEHOLDER** |
| `HEAD_BREADTH_MM` | 145 | scale for the parting estimate | approximate adult head breadth; individual variation ignored | **VALIDATION STATUS: PLACEHOLDER** |

## Longitudinal

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `NOISE_FLOOR_V` | 0.03 face widths | change below this = 'stable' | no test-retest data exists | **VALIDATION STATUS: PLACEHOLDER** |
| `CHANGE_V` | 0.06 face widths | at/above this = 'measurable change' | no test-retest data exists | **VALIDATION STATUS: PLACEHOLDER** |
| `NOISE_FLOOR_DENSITY` | 0.05 scalp-visibility (x2 for 'measurable') | density change | no test-retest data exists | **VALIDATION STATUS: PLACEHOLDER** |
| `comparability limits` | confidence >= 0.4; head-turn proxy difference <= 0.08 and each <= 0.15; forehead lightness difference <= 18; hair length/wetness flags equal; >= 10 common columns | refuse comparison when conditions differ | design choice; no source; behaviour pinned by tests (not validated) | **VALIDATION STATUS: PLACEHOLDER** |

## Legacy hairline (hair.py _hairline)

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `stage thresholds` | recession 0.8 / 1.5 / 2.5 / 3.5 cm; height 7 / 7.5 / 8 cm | legacy score/label (no longer shown; height_cm still feeds a diagram) | cited in code comments (Korean/Thai studies, Norwood scale); not re-verified; cm values uncalibrated | **VALIDATION STATUS: PLACEHOLDER** |

## Evaluator (evals/hairline_eval.py)

| Threshold | Current value | Purpose | Source / rationale | Validation |
|---|---|---|---|---|
| `MIN_N / MIN_POS` | 30 labelled items / 8 positives | below this a statistic prints INSUFFICIENT SAMPLE SIZE | a conservative guard, not a power calculation | **VALIDATION STATUS: PLACEHOLDER** |
| `REVIEW_TRIGGER_BZ` | 0.06 face widths | boundary error above this is listed for human error review | review trigger ONLY; not an acceptance criterion | **VALIDATION STATUS: PLACEHOLDER** |
| `gate 'reliable'` | hairline_visible and confidence >= 0.4 | how the evaluator reads the engine's quality gate | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |
| `false-reassurance density rule` | density 'no reduced' with confidence >= 0.25 | what counts as a clean density claim | design choice; no source | **VALIDATION STATUS: PLACEHOLDER** |

## Count
51 thresholds registered, 51 PLACEHOLDER, 0 validated.
