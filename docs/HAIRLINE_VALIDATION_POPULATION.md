# Hairline module - intended-use population, validation sample, and out-of-scope cases

Status: **documented from the project's own product material; NOT yet confirmed by the project owner** (decision file
`backend/evals/hairline_validation_decisions.json`, key `population_confirmed_by_owner`). Nothing here claims any demographic fact that the product
documentation does not support. Where the documentation is silent, this document says so and lists the question as an open decision.

Sources used (and only these): `README.md` ("India features", "Hair fall check"), the analysis form (`frontend/src/app/analyze/page.tsx`: age field,
sex options, ethnic-background options, photo guidance, optional hair questions and top-of-head photo), `backend/app/imaging.py` (photo-quality checks),
and the hairline project documents (`HAIRLINE_*.md`).

## A. Intended use
- **What the module does:** a screening aid that describes what a photograph shows about the hairline and temples (and, with a top-of-head photo, the crown).
  It is explicitly not a diagnosis (see `HAIRLINE_ACCEPTANCE_CRITERIA.md`, A9).
- **Who uses it (supported by the product):** adults who use the Facemetric-AI app and upload a front photo. The analysis form accepts ages 18-99 and the sexes
  "male" and "female" (used for reference ranges). The hair check is optional ("Worried about hair fall?"); a top-of-head photo is optional.
- **Market (README):** the product is built for the Indian market (INR pricing, Indian cities and climate, Indian skin concerns, products sold in India).
  The ethnic-background selector, however, offers nine options (East Asian, South Asian, Southeast Asian, Black/African, White/European, Hispanic/Latino,
  Middle Eastern/North African, Mixed/Other, prefer not to say), so the app does not prevent other users.
  **The documentation does not say whether the hair module is intended only for Indian-market users or for every user the app accepts. See D1.**
- **Photo types:** one front photo (hairline, temples, frontal density); one optional top-of-head photo (crown, parting). Angled temple photos are not an
  intended input today.

## B. Required image characteristics (only those already established by the project)
From the app's own capture guidance for the front photo: face the camera straight on at eye level; neutral expression, mouth closed; soft even light
(face a window); hair off the face, no glasses. From the top-photo guidance: photographed from above, bright even light, dry hair combed into the usual
parting, about 30 cm away. From the app's quality checks (`imaging.py`): a face must be found, and low resolution, blur, exposure and colour-cast problems are
flagged. From the hairline project documents (`HAIRLINE_VALIDATION_DATASET_SPEC.md`, the project's own specification rather than an enforced product rule):
forehead and hairline in frame and uncovered, no cap, no filter or beauty mode, natural hair position.
Images that do not meet these are **not thrown away**: they are the cases that test whether the engine correctly refuses (see C and the next section).

## C. Exclusions and known limitations (what the current engine is NOT intended to be validated for)
| Case | Treatment | Why |
|---|---|---|
| Head pitch (looking up/down) | **Not handled by the engine.** No performance claim is made for such photos; see D3 for how they are recorded | pitch changes apparent forehead height and is not estimated |
| Angled / three-quarter temple photos | Not analysed (NOT IMPLEMENTED); excluded from the validation sample as out of scope | the engine reads front photos only |
| Crown from a front photo | Must always be `NOT ASSESSABLE`; this is a safety invariant, not a performance claim | a front photo does not show the crown |
| Hairline hidden by fringe, cap, hand, or outside the frame | **Kept** in the sample and labelled by humans as not visible / occluded / outside frame | these are the cases that test refusal and false reassurance |
| Severe occlusion or unsuitable image quality | **Kept** when a human can label them "unusable"; excluded only for technical reasons (not decodable) or missing consent | needed to test the quality gate |
| Minors (under 18) | Excluded; adults only | the product form accepts 18+ and consent is adult-only |
| Photos with no valid validation consent | Not eligible, ever | consent rule |
| Shaved / very short hair, wet or glossy hair | Kept and labelled; the engine lowers confidence rather than reporting findings | tests the confidence rules |
Exclusion for image quality must be decided by a human **before** annotation and **never** from engine output or from how the engine performed.

## D. Three different things - not to be confused
| | Definition | Today |
|---|---|---|
| **Intended-use population** | the people and photographs the module is meant to serve (sections A-B) | documented above; scope question D1 open; not owner-confirmed |
| **Validation sample** | the specific consented, human-annotated photographs actually collected | **0 images** |
| **Excluded / out-of-scope cases** | photographs and conditions the module is not claimed to handle (section C) | listed above |
**The validation sample will not be described as representative of the intended-use population** until sampling evidence exists: counts per stratum
(skin tone, hair colour/texture, length, age band, sex, device, lighting) against what the population actually contains. Strata with fewer than 30 labelled
items are reported as `INSUFFICIENT SAMPLE SIZE`, and strata with zero images as NOT COVERED.

## Open decisions for the project owner (the engineering side must not decide these)
- **D1. Scope of the claim.** Is the hair module validated for (a) Indian-market users only, or (b) every adult the app accepts? The product documentation
  supports an India focus but does not restrict users. The answer determines which skin tones, hair types and sexes the sample must contain.
- **D2. Strata and quotas.** Which strata are mandatory, and the minimum per stratum (the dataset spec gives planning minimums only).
- **D3. Pitch / out-of-scope stress set.** Whether photographs with head pitch are kept in a clearly separate "stress set" that is never part of any
  headline metric, or are excluded outright.
- **D4. Devices.** Which capture devices the claim covers.
