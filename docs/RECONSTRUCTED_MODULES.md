# Reconstructed modules - audit (Phase 6K)

Four report modules were lost and rebuilt by me in an earlier session. **None is authoritative.** Everything they show that looks like a
reference value is labelled **`PLACEHOLDER - NOT PRODUCTION VALIDATED`** in the data, the UI and the validation block of every report.
No value below has a verified source; none has been validated against ground truth. Arithmetic unit tests exist (they check the code does
what it says, not that what it says is correct).

## 1. `backend/app/anthropometry.py` - measurement table
| Aspect | Finding |
|---|---|
| Source / specification | **none.** The original is lost. An earlier docstring claimed "Farkas-style adult norms, leaning on South Asian data"; that was an unverifiable claim and has been removed |
| Formula | 14 distances between named landmarks (`landmark_map.py`), axis `x`, `y` or straight line, times `mm_per_px`; 4 ratios of those distances |
| Scale | `11.7 mm / iris diameter px` - population-average constant, unvalidated (MEASUREMENT_VALIDATION_PLAN.md) |
| Reference ranges | per-sex mean and SD written from general knowledge for each of 14 rows; displayed range = mean +/- 1.5 SD; status typical/above/below. **PLACEHOLDER.** A previous range (nasion-chin 75-93 mm) was wrong and was corrected, which shows the risk |
| Assumptions | frontal, neutral, level head; soft-tissue landmarks stand in for anatomical points; smiling shortens lip distances; beard hides jaw/chin rows (those rows are withheld when a beard is detected - detection itself misses smoothed beards) |
| Independently validated | **No** |
| Dependent outputs | the "Your estimated measurements" table (free preview and paid report), `measurements_mm` evidence, the mm labels on the measurements figure, the PDF |

## 2. `backend/app/eyes.py` - eye and brow findings and advice
| Aspect | Finding |
|---|---|
| Source / specification | none |
| Formulas | eye width/height from the eye-corner and lid landmarks; **openness** = (sum of eye heights)/(sum of eye widths); **spacing** = inner-eye gap / mean eye width; **brow height** = mean (brow-top y - upper-lid y) x mm/px; **brow slope** = angle of inner-to-outer brow landmark line |
| Thresholds (all **PLACEHOLDER**) | openness < 0.24 "narrower", > 0.36 "rounder"; spacing < 0.9 "close", > 1.15 "wide"; brow height 5-18 mm "low", > 28 mm "high"; slope < -8 deg "tails slope downward", > 22 deg "steep" |
| Known limitation | the slope finding is evaluated for the **right brow only** (the code branch checks `name == "right"`); with glasses the brow-tail landmark can land on the frame, making the slope unreliable (seen on a real photo) |
| Advice text | generic grooming guidance written by me; not reviewed by a clinician or brow professional |
| Independently validated | **No** |
| Dependent outputs | "Eyes & brows" section and its annotated image, `eyes_and_brows` evidence in the report text |

## 3. `backend/app/diagrams.py` - report figures
| Aspect | Finding |
|---|---|
| Source / specification | none (the thirds and fifths are classical proportion canons, not a validated standard) |
| Formulas | pupil-line levelling (`align.py`); verticals through six eye/cheek landmarks (fifths); horizontals at hairline, glabella, subnasale and menton (thirds); left/right mirror composites about a landmark-fitted midline; mm labels from `mm_per_px` |
| Reference ranges | **none shown** (the figures only draw lines and print measured sizes) |
| Assumptions | the "hairline" line uses the hair module's estimate when available, otherwise the forehead mesh point (not the true hairline); the mirror composites show the photo's geometry, not a diagnosis |
| Independently validated | **No** |
| Dependent outputs | measurements / fifths / thirds figures, the two symmetry figures, the PDF |

## 4. `frontend/src/components/ReportFigures.tsx` - presentation
| Aspect | Finding |
|---|---|
| Source / specification | none |
| Formula | **none** - it renders what the backend sends; the only logic is wording for typical/above/below and the placeholder labels |
| Reference ranges | displays the backend's placeholder ranges; the column header now reads "Typical - placeholder - not validated" and a status line repeats it |
| Independently validated | **No** (the browser suite renders it; that tests display, not correctness) |
| Dependent outputs | every table and figure block in the report page and the print view |

## Other reference values that remain unverified (not reconstructed, but user-visible)
`backend/app/metrics.py` ideals and tolerances (e.g. `nose_intercanthal` 1.15, `mouth_nose` 1.40): the code comments cite "Kerala/North-Indian
studies; Farkas 2005"; **none of those sources was re-checked.** The descriptions shown to users were reworded to say "unverified approximation"
instead of "typical for Indian / South Asian faces". The Pallett 2010 citation for the eye-separation ratio is marked "not re-verified here".

## What would make them production-validated
1. A named, cited reference dataset (or consented local data) per measurement, appropriate to the intended population, chosen and signed off
   by a qualified anthropometrist.
2. Ranges recomputed from it with the sample size stated, replacing every PLACEHOLDER value.
3. The measurement validation study (MEASUREMENT_VALIDATION_PLAN.md) for the mm values.
4. Review of the brow/eye advice text by a suitable professional.
