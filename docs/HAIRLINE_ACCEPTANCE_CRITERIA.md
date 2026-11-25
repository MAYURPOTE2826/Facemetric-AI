# Hairline engine - acceptance criteria

Written BEFORE any real-photo result exists. Nothing here may be edited after the first `--run` on real data to make a result pass; a change needs a
dated entry in section D naming who decided and why.

Engine under test: `hairline-engine-v1` (locked baseline, no tuning). Verdict for the module today: **NOT READY**.

## A. Software correctness (testable now; independent of real photographs)
These are pass/fail and are verified by the automated suites named in the last column. Passing them says the software behaves as designed.
It says nothing about accuracy.

| # | Criterion | Verified by | Status |
|---|---|---|---|
| A1 | No crash on a valid image | `test_hairline_engine.py` (all scenes) | PASS (synthetic) |
| A2 | No crash on an incomplete, hidden, off-frame, tiny or missing face | `test_hairline_engine.py` (Framing), `test_hairline_false_reassurance.py` | PASS (synthetic) |
| A3 | A front photo NEVER yields a crown reading (`crown.status = not_assessable`, `density = null`) | `test_hairline_false_reassurance.py` case 5; evaluator invariant `crown_front_only_violations` | PASS (synthetic) |
| A4 | No false certainty when the hairline is hidden/off-frame/covered: status inconclusive, temples and density `not_assessable`, no reassuring wording | `test_hairline_false_reassurance.py` cases 1, 2, 4; browser H4 | PASS (synthetic) |
| A5 | Every claim carries a confidence; low contrast/quality lowers it | `test_hairline_engine.py`, false-reassurance case 3 | PASS (synthetic) |
| A6 | `not_assessable` / `inconclusive` states exist and are used | as A4 | PASS (synthetic) |
| A7 | `hair.analysis` is additive: legacy keys unchanged; every outcome has the same required structure; old reports without it still load | `test_hair_api_contract.py`; browser H7 | PASS |
| A8 | Engine failure never breaks the legacy report and never produces a healthy-looking result | `test_hair_api_contract.py`, false-reassurance case 6; browser H5 | PASS |
| A9 | No diagnosis, cure, reassurance ("healthy hair", "no hair loss") or medicine wording in any output | `test_hairline_engine.py` Safety; browser H1/H4/H5 | PASS |
| A10 | No cm/mm values in the new section; distances are ratios to face width | `test_hairline_engine.py` Safety; browser H1 | PASS |
| A11 | Longitudinal comparison refuses when pose, lighting, hair length, wetness, visibility or quality differ, and compares when they match | `test_hairline_longitudinal_safety.py`; browser H8a/H8b | PASS |
| A12 | No image can become ground truth without a valid consent/intake record; model-assisted labels are rejected | `test_hairline_eval_pipeline.py` | PASS |
| A13 | Thresholds are locked and registered; every one is marked PLACEHOLDER | `test_hairline_threshold_lock.py`, `HAIRLINE_THRESHOLD_REGISTER.md` | PASS |
| A14 | Security/privacy controls unchanged (auth, ownership, consent, retention, encryption) | backend security suites; browser security specs | PASS (see readiness doc for browser engines run) |

## B. Real-photo performance (NOT YET EVALUABLE - 0 annotated real photographs)
Each metric below will be computed by `python -m evals.hairline_eval --run <root>`. **No target value exists, because no evidence supports one.**
Writing a number now would be inventing it. Each target must be agreed, with the reasoning recorded, before the first real run.

| Metric | Definition (as computed by the evaluator) | Minimum labelled sample | Acceptance threshold |
|---|---|---|---|
| Hairline boundary error | mean / p95 distance from engine points to the human polyline, in face widths | planning minimum: 200 front images with a traced polyline | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Centre-hairline error | same, points with \|u\| <= 0.12 | as above | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Left / right temple boundary error | same, points with u >= 0.28 / u <= -0.28 | as above | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Hairline visibility precision / recall / F1 | positive = human "visible"; negatives = not visible / occluded / outside frame | >= 30 labelled and >= 8 positives (evaluator guard) | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Temple pattern precision / recall / F1 | positive = human "possible"/"pronounced" recession; engine abstentions reported separately | >= 30 and >= 8 positives | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Crown assessability precision / recall / F1 | human "assessable yes" vs engine `assessed` | >= 30 top photos, >= 8 positives | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Quality-gate refusal precision / recall / F1 | positive = human "unusable"; engine refuses if hairline not visible or confidence < 0.4 | >= 30 and >= 8 positives | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Shape agreement | share of images where engine label equals the human label (only if humans can agree with each other) | >= 30 | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Frontal-density agreement | human ordinal rating of VISIBLE density vs engine band (not follicle density) | >= 30 | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| **False reassurance rate** (safety-critical) | images the human marks not visible/occluded/outside frame/unusable where the engine nevertheless claims a detected hairline, "no obvious recession" or "no reduced density" | all such images | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION (principle: every case is reviewed individually, whatever the rate) |
| Crown front-only violations | front photos where crown status is not `not_assessable` | all front photos | must be **zero** by design (rule A3; not a statistical target) |
| Longitudinal accuracy | agreement of change calls with repeat-photo ground truth | repeat photos on the same people, same-day and different-day | NOT MEASURED; change thresholds are placeholders; ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Confidence calibration | boundary error by confidence bin | enough images per bin | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |
| Subgroup performance | every metric above by skin tone, hair colour/texture, length, age band, sex, device, lighting | >= 30 per subgroup, otherwise reported as INSUFFICIENT SAMPLE SIZE | ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION |

## C. Rules for the validation itself
1. Thresholds in section B are agreed and signed (names, date) **before** the first run on real data.
2. The annotated validation set is frozen before the first run (manifest of file hashes). No annotation is edited after seeing engine output.
3. The engine is not tuned on the validation set. If tuning is wanted, a separate development set is used and the validation set stays untouched. Any
   threshold change is recorded in `HAIRLINE_THRESHOLD_REGISTER.md` with its evidence.
4. Report point estimates with confidence intervals and the raw counts. Statistics below the sample guard print `INSUFFICIENT SAMPLE SIZE`.
5. The engine cannot be judged more tightly than humans agree with each other: human-human agreement (second annotator subset) is reported separately
   from human-engine agreement and sets the floor on what any target can mean.
6. Synthetic scenes are never counted as evidence for section B.
7. A pass on section B would still not make the module "validated for medical use": the module is a screening aid and the overall PFI governance
   verdict is separate.
8. If any hard-safety item (A3, A4, A8, A9) fails on real photographs, the module stays NOT READY regardless of other results.

## D. Decision log (to be filled before validation)
| Date | Decision | Decided by | Evidence / reasoning |
|---|---|---|---|
| - | Acceptance thresholds for section B | NOT YET DECIDED | - |
| - | Dataset frozen (manifest hash) | NOT YET DONE | - |
