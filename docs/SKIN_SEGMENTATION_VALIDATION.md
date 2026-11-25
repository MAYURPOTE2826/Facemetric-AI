# Skin segmentation validation

## Status: segmentation ACCURACY IS NOT MEASURED
No labelled ground-truth masks exist in this repository, so **IoU, Dice, false-positive rate and false-negative rate have
not been measured on any data.** The harness exists and its arithmetic is tested (`evals/skin_segmentation_eval.py`,
`tests/test_skin_gating_and_segmentation.py`); it needs a labelled set.

## Labelling protocol for the future ground-truth set
Only authorised photographs. For each `name.jpg` provide `name_skinmask.png`: **white = bare facial skin that should be
analysed**, black = eyes, brows, lips, nostrils, hair, beard, glasses and frames, background, clothing, ears. Include
variety: beard/clean-shaven, glasses, strong colour cast, over/under-exposure, side lighting, shadows, makeup, different
phones. Run `python -m evals.skin_segmentation_eval --labelled <dir>`; report the number of images with every pooled figure.
Do not group images by demographic labels inferred from photographs.

## What the mask is
`skin.build_skin_mask()` (extracted from `analyze()` with **byte-identical output** on both test photos): face oval minus
eyes, brows, lips and nostrils (landmark polygons), minus facial hair found by a dark-textured-region heuristic, minus the
segmenter's hair and accessory classes, plus (new) minus large dark regions below the nose base.

## What was measured without ground truth (contamination indicators, NOT accuracy)
Two photographs, both bearded men; one also wears glasses.
| Indicator | Photo A | Photo B (glasses) |
|---|---|---|
| Mask pixels inside eye/brow/lip polygons | 0.0% | 0.0% |
| Mask pixels outside the face oval | 0.0% | 0.0% |
| Mask pixels darker than 0.62x median cheek - before the new rule | 0.18% | **21.35%** |
| same, after the new rule (**true by construction: it uses the same 0.62 threshold**) | 0.17% | 3.25% |
| Face-oval coverage by mask, before -> after | 54.3% -> 54.3% | 69.6% -> 55.9% |
The segmenter-label indicator is **circular for hair and accessories** (those classes are already removed from the mask), so
"0% hair inside the mask" proves nothing and is not used as evidence.

### Visual inspection (the real evidence, 2 photos)
- Photo A: beard, brows, eyes, nose underside and mouth are excluded; the boundary is blocky.
- Photo B before the change: **the entire beard and moustache were inside the mask**, and parts of the glasses frames. The
  texture heuristic needs texture; this beard is smooth and dark. The segmenter did not label it as hair either.
- Photo B after: moustache and the bulk of the beard are excluded. **Residual stubble along the lower cheeks and the glasses
  frames are still partly inside the mask.** This is an improvement, not a fix.
- The new rule only removes pixels (tested: the new mask is always a subset of the old one). Its threshold (0.62) and minimum
  area are unvalidated engineering choices.

## Related defect found: beard detection
The quality gate's "beard" flag depends on the segmenter labelling beard as hair. On photo B (clear beard) it did not fire,
so jaw/chin measurements were trusted. A second detector (e.g. dark fraction of the jaw region) was NOT added: every
photograph available has a beard, so there is no negative example to set a false-positive rate, and inventing a threshold
would be unjustified. **Open.**

## Metric-specific gating (implemented)
Each skin metric declares what it depends on (`report_validator.SKIN_NEEDS`); a quality flag withholds or flags only the
metrics whose dependency it damages (`FLAG_EFFECTS`).
| Metric | Depends on |
|---|---|
| redness | colour |
| dark_spots | colour |
| acne_marks | colour, lower face |
| blemishes | colour, fine detail, lower face |
| dark_circles | colour, eye region (clear) |
| uneven_tone | colour, exposure, even light, lower face |
| pigmentation | colour, exposure, even light |
| shine | exposure |
| texture | fine detail, lower face |
| wrinkles | fine detail, eye region (partial) |
| Flag | Effect |
|---|---|
| colour_cast | withhold colour metrics |
| too_bright / too_dark | withhold exposure metrics (too_dark also flags colour) |
| blurry | withhold fine-detail metrics |
| beauty_filter, low_resolution | flag fine-detail metrics |
| glasses | withhold under-eye reading, flag wrinkles |
| uneven_light | flag region-comparison metrics |
| beard | flag lower-face metrics |
Texture under a colour cast stays available; colour metrics under blur stay available. 24 tests pin these decisions. The
requirements and effects are **engineering judgements, not validated rules**. As requested, thresholds were not loosened:
the previous lump-sum behaviour (colour cast, over/under-exposure, beauty filter) is reproduced exactly; new rules only add
withholding or flags (blur, glasses, uneven light, beard, low resolution).

## Update (Phase 5): labelled-mask evaluation pipeline and per-metric gating table

### Status stays: **ACCURACY NOT MEASURED**
No labelled masks exist; none were fabricated. `python -m evals.skin_labelled_eval --dataset <dir>` is ready (14 tests, synthetic label maps
only, hand-computed expectations). With an empty dataset it prints `ACCURACY NOT MEASURED`.

**Label map** (`labels/<image_id>.png`, one class id per pixel): 0 background, 1 skin, 2 beard, 3 moustache, 4 glasses (lens + frame),
5 hair, 6 eyes/brows, 7 lips/mouth, 8 other occlusion. Manifest per image: `subject_id`, `image_file`, `labels_file`, `conditions{lighting,
tags[]}`, `consent_ref`; dataset-level `label_source` (`human:<id>` or `model:<name>`; model labels are reported as AGREEMENT, not accuracy).
**Reported:** overall skin-vs-rest IoU, Dice, precision, recall, false-positive rate, false-negative rate (pixel-pooled, image counts
shown); **per region**: for skin the recall (share of true skin kept), for every other class the **contamination** (share of that region's
pixels wrongly inside the mask) - BEARD, MOUSTACHE, GLASSES, HAIR, EYES/BROWS, LIPS, OTHER, BACKGROUND; and the overall metrics per lighting
value and per tag. Undefined rates are `None`, never invented; prediction failures are counted; no thresholds are applied.

### Per-metric requirements and flag effects (generated from `report_validator.SKIN_NEEDS` / `FLAG_EFFECTS`)
Reading the table: **WITHHELD** = the metric is removed from the report; **flagged** = kept with a reliability note; **no effect** = unaffected.
The architecture is unchanged: only the affected metric is suppressed (e.g. a colour cast withholds colour metrics but leaves texture and
shine alone).

| Metric | Required input | Required image quality | Segmentation / region needed | Lighting needed | Beard | Glasses | Colour cast | Beauty filter | Blur | Over/under-exposed |
|---|---|---|---|---|---|---|---|---|---|---|
| `acne_marks` | chroma/hue of skin pixels (a*, b*) | neutral colour balance | skin mask (always); clean lower-face mask | any | flagged | no effect | WITHHELD | no effect | no effect | no effect / flagged |
| `blemishes` | chroma/hue of skin pixels (a*, b*); fine spatial detail | neutral colour balance; sharp, adequate resolution, not smoothed | skin mask (always); clean lower-face mask | any | flagged | no effect | WITHHELD | flagged | WITHHELD | no effect / flagged |
| `dark_circles` | chroma/hue of skin pixels (a*, b*) | neutral colour balance | skin mask (always); unobstructed eye area | any | no effect | WITHHELD | WITHHELD | no effect | no effect | no effect / flagged |
| `dark_spots` | chroma/hue of skin pixels (a*, b*) | neutral colour balance | skin mask (always) | any | no effect | no effect | WITHHELD | no effect | no effect | no effect / flagged |
| `pigmentation` | chroma/hue of skin pixels (a*, b*); absolute lightness (L*) | neutral colour balance; not over/under-exposed | skin mask (always) | even lighting | no effect | no effect | WITHHELD | no effect | no effect | WITHHELD / WITHHELD |
| `redness` | chroma/hue of skin pixels (a*, b*) | neutral colour balance | skin mask (always) | any | no effect | no effect | WITHHELD | no effect | no effect | no effect / flagged |
| `shine` | absolute lightness (L*) | not over/under-exposed | skin mask (always) | non-clipped exposure | no effect | no effect | no effect | no effect | no effect | WITHHELD / WITHHELD |
| `texture` | fine spatial detail | sharp, adequate resolution, not smoothed | skin mask (always); clean lower-face mask | any | flagged | no effect | no effect | flagged | WITHHELD | no effect / no effect |
| `uneven_tone` | chroma/hue of skin pixels (a*, b*); absolute lightness (L*) | neutral colour balance; not over/under-exposed | skin mask (always); clean lower-face mask | even lighting | flagged | no effect | WITHHELD | no effect | no effect | WITHHELD / WITHHELD |
| `wrinkles` | fine spatial detail | sharp, adequate resolution, not smoothed | skin mask (always); eye area + forehead/smile-line zones | any | no effect | flagged | no effect | flagged | WITHHELD | no effect / no effect |

These requirements are engineering judgements encoded in code and pinned by 24 tests; they have not been validated against labelled data.
