# Hairline validation cohort - intake specification

**PILOT VALIDATION COHORT.** The first cohort is a pilot. It is not production evidence and does not change any readiness verdict by itself.
Tooling: `backend/evals/hairline_cohort.py` (`python -m evals.hairline_cohort ...`). Current state: 0 candidates (see `HAIRLINE_VALIDATION_COHORT_READINESS.md`).

## 1. Principle
```
NO VALIDATION CONSENT  ->  NOT ELIGIBLE FOR VALIDATION
CUSTOMER REPORT        ->  explicit validation authorization?  NO: DO NOT USE   YES: MAY ENTER INTAKE
```
The tool refuses an image that lacks consent, refuses anything read from the application's data folder, and never opens the application's encrypted reports.
It does not copy identity information: records carry a pseudonymous id and an opaque consent reference only.

## 2. Workspace
Outside the repository, outside any git work tree and outside the application's data folder (the tool refuses otherwise). Default: `~/.alexendra/validation/hairline`.
```
candidates/{front,top}/   received images awaiting an eligibility decision
approved/{front,top}/     eligible images (the only images annotators see)
excluded/                 one small record per excluded id: coded reason; the image itself is deleted (data minimisation)
annotations/annotator_a/  annotator A's labels         annotations/annotator_b/  annotator B's labels (independent)
annotations/consensus/    human-adjudicated ground truth (only after A and B; procedure NOT YET DEFINED)
machine_outputs/          engine output (written only by a gated run)      overlays/  human-vs-engine overlays (gated run)
reports/                  agreement, results, run manifest                 consent/   opaque consent-reference index only (forms are held by the owner elsewhere)
metadata/                 one intake record per image
```
`.gitignore` blocks `validation/`, `.alexendra/`, `backend/data/`. Real-person photographs are never committed, pushed, used as test fixtures, or served over a URL.

## 3. Intake record (`metadata/HLV-NNNN.json`) - required fields
| Field | Rule |
|---|---|
| `validation_id` | `HLV-0001`, `HLV-0002`, ...; assigned by the tool; never reused (even after an exclusion); never a name, email or phone number |
| `source_type`, `source_category` | where the image came from: volunteer / staff / licensed dataset / public-domain licensed / app customer report / other documented |
| `consent_status` | `consented` or `authorized` (a documented licence). Anything else is refused |
| `validation_use_authorized` | must be `true`, and `consent_scope` must include `validation` |
| `adult_confirmed` | must be `true` (18+) |
| `consent_ref` | an opaque reference (letters, digits, `. _ -`, no `@`) pointing to a consent record the owner holds elsewhere |
| `image_type` / `capture_type` | `front` or `top`; must match the folder and the annotations |
| `captured_on` | optional date only; no time, no location |
| `technical` | objective, engine-independent facts: decodable, width, height, whether EXIF carries GPS |
| `image_sha256` | hash taken at intake; a later change makes the image ineligible |
| `inclusion_decision`, `exclusion_reason` | `pending` / `included` / `excluded` and a coded reason |
| `annotation_status` | `pending` ... (workflow state) |
Forbidden in any record: names, emails, phone numbers, addresses, dates of birth, IP addresses, account/user/report/analysis ids. The tool flags and rejects them.
GPS location in EXIF makes an image ineligible until it is removed. The original file name is not stored.

## 4. Eligibility and exclusion
Eligible = valid consent and validation authorization + adult + valid capture type + decodable + no GPS in EXIF + unchanged since intake. **Engine output is never consulted.**
Exclusion codes: `out_of_scope_head_pitch`, `out_of_scope_angled_photo`, `out_of_scope_other_view`, `not_decodable`, `consent_withdrawn`, `consent_missing`,
`duplicate_of_other_id`, `other_documented` (needs a written note). An annotated image cannot be silently excluded.
Do not exclude an image because it is hard, blurry, dark or covered: those are the cases that test refusal. They are labelled `unusable` / `not_visible` by humans and kept.

## 5. Lifecycle (derived from the files that exist, never from a stored flag)
```
CANDIDATE -> CONSENT VERIFIED -> ELIGIBLE -> ANNOTATOR A COMPLETE -> ANNOTATOR B COMPLETE -> AGREEMENT CHECK -> CONSENSUS READY -> ENGINE RUN -> EVALUATION
```
Humans annotate first; the engine runs last. An annotation whose image already has older engine output is **contaminated** and does not count.

## 6. Commands
    python -m evals.hairline_cohort init     <root>
    python -m evals.hairline_cohort add      <root> --image F --view front --source-type volunteer_capture --source-category volunteer \
                                             --consent-status consented --validation-use yes --consent-scope validation --adult yes --consent-ref CONSENT-0001
    python -m evals.hairline_cohort include  <root> HLV-0001          # runs the eligibility check, then moves it to approved/
    python -m evals.hairline_cohort exclude  <root> HLV-0001 --reason out_of_scope_head_pitch
    python -m evals.hairline_cohort queue    <root> --annotator A01   # ids only, randomised, skips anything the engine has seen
    python -m evals.hairline_cohort agreement <root>                  # human A vs human B
    python -m evals.hairline_cohort status | gates <root>
    python -m evals.hairline_cohort run <root>                        # refuses until every gate passes

## 7. Withdrawal and retention
If a person withdraws consent: exclude with `consent_withdrawn`, delete the image and every annotation, machine output, overlay and report line for that id, and
record the deletion date in the consent index. Retention period for the validation set must be stated by the owner before collection (not yet defined).
Access is limited to the named annotators and the engineering owner; images are never uploaded to a third party.
