# Validation datasets - status and how to build them (Phase 6B / 6F / 6I)

## Real dataset counts (2026-11-05; `python -m evals.dataset_status --status C:\Users\Admin\alexendra-validation-data`)
| Dataset | Subjects | Images | Annotations / masks / measurements | Evidence status |
|---|---|---|---|---|
| Landmarks | 0 | 0 | 0 landmark annotations | **NOT MEASURED** |
| Skin masks | 0 | 0 | 0 masks | **NOT MEASURED** |
| Physical measurements | 0 | 0 | 0 reference readings, 0 automated values, 0 paired subject-measurements | **NOT MEASURED** |
| Head pose | 0 | 0 | 0 reference poses | **NOT MEASURED** |

**No ground truth exists.** Nothing was fabricated, derived from the software's own output, or taken from synthetic data. The two photographs used for
testing earlier are not labelled and are not counted.

## What exists
- Empty skeletons with the labelling protocols were created OUTSIDE the repository at `C:\Users\Admin\alexendra-validation-data\` (`landmarks/`, `skin_masks/`,
  `measurements/`, `pose/`), each with its protocol README:
  - `landmarks/REFERENCE_STANDARD.md`: coordinate system = original un-mirrored image pixels, origin top-left, y increases downward; R_/L_ = the subject's
    right/left = image left/right; indices exactly as `landmark_map.py`; visibility rules; annotators must not see model output.
  - `skin_masks/PROTOCOL.md`: classes background, skin, beard, moustache, glasses, hair, eyes/brows, lips, other occlusion; stubble labelled as beard with a tag.
  - `measurements/PROTOCOL.md`: caliper reference, two repetitions, two operators. `pose/PROTOCOL.md`: independently measured head pose.
- `python -m evals.dataset_status --init <root>` (never overwrites; refuses a root inside the repository) and `--status <root>` (counts only files that exist
  AND pass each dataset's own validator).
- Evaluators, all arithmetic-tested on synthetic data only: `evals/landmark_accuracy.py`, `evals/skin_labelled_eval.py`, `evals/measurement_validation.py`,
  `evals/pose_validation.py`. Each prints NOT MEASURED on an empty dataset, applies no threshold, and treats model-derived references as AGREEMENT (or rejects
  them, for pose).

## What a person must do (this cannot be automated honestly)
1. **Consent and ethics:** written consent for each participant; decide retention; keep photographs outside Git and off third-party services unless the consent
   says otherwise.
2. **Landmarks:** annotate with a tool you run locally (for example CVAT or Label Studio on your own machine) to the reference standard, WITHOUT showing the
   model's output; two annotators on a subset to measure inter-annotator error. Record pose, lighting, resolution, device and occlusions per image.
3. **Skin masks:** paint the class map by hand per the protocol; include beard / stubble / clean-shaven, glasses, colour cast, over/under-exposure, several phones.
4. **Measurements:** calipers (or a 3D scanner) by trained examiners, two repetitions and a second operator, using the same anatomical definitions as the software.
5. **Pose:** a measured head pose (calibrated turntable, motion capture or head-mounted IMU), not read off the image.
6. Run the evaluators. Decide the acceptance criteria BEFORE looking at the results (an expert/product decision); until then the result is
   `ACCEPTANCE CRITERIA NOT DEFINED`.

Sample-size guidance: see MEASUREMENT_VALIDATION_PLAN.md (about 30 for a pilot, 100 or more for a published statement). A landmark or mask study needs enough
images per condition group for each reported group to have a meaningful n; the evaluators print n for every group and flag P95 when n < 20.
