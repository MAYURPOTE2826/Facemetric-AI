# Hairline validation - go / no-go checklist

Purpose: stop validation from starting accidentally. `python -m evals.hairline_cohort gates <root>` computes these gates from the real files and from the
human-owned decision file `backend/evals/hairline_validation_decisions.json` (a decision counts only with `value: true` **and** `decided_by` **and** `decided_on`).
`python -m evals.hairline_cohort run <root>` refuses to run the engine unless every gate is PASS. States: **PASS**, **BLOCKED** (needs a human decision), **NOT SATISFIED** (needs data).

| # | Gate | PASS only if | State on 2026-11-06 |
|---|---|---|---|
| 1 | Algorithm lock | the SHA-256 of `app/hairline.py`, `app/hair.py` and the threshold register, and every locked threshold value, equal the recorded lock (`backend/evals/hairline_lock.json`); the threshold-lock tests pass | **PASS** (hairline.py `2ccffc04...8585f60`, hair.py `a82d1d0e...3ade`) |
| 2 | Intended-use population | `HAIRLINE_VALIDATION_POPULATION.md` exists **and** the owner has confirmed it (D1 answered) | **BLOCKED** (documented; owner confirmation missing) |
| 3 | Real-photo acceptance criteria | thresholds for `HAIRLINE_ACCEPTANCE_CRITERIA.md` section B are explicitly agreed and signed | **BLOCKED** (`ACCEPTANCE THRESHOLD: TO BE AGREED BEFORE VALIDATION`; no numbers invented) |
| 4 | Consent | at least one image has valid validation authorization and **no** included image lacks it | **NOT SATISFIED** (0 eligible images) |
| 5 | Annotation independence | every counted annotation carries the attestation (no engine output, report or other annotator seen), none is contaminated, at least one exists | **NOT SATISFIED** (0 annotations) |
| 6 | Two-annotator readiness | two distinct annotators have labelled, the second annotator is confirmed available, and an adjudication procedure is defined | **BLOCKED** (workflow and tooling exist; no second annotator; adjudication NOT DEFINED) |
| 7 | Dataset separation | the workspace is outside the repository, git, and app data, and no `.jpg/.jpeg` exists in the repository | **PASS** |
| 8 | Evaluation reproducibility | the run manifest (engine, evaluator, annotation, image and metadata hashes) is deterministic before a run and still verifies after one | **PASS (capability)**; no real run has been made |

**Overall: NOT READY.** It becomes "ready to begin the validation run" only when all eight gates are PASS, and even then it is not a validation result.
No real-photo accuracy number may be quoted before a run has produced one.

## What must be decided by a human before the gates can pass
1. Owner confirms the population and answers D1-D4 (`HAIRLINE_VALIDATION_POPULATION.md`).
2. Owner and reviewers agree and sign the real-photo acceptance thresholds - before the first run.
3. A second independent annotator is identified and briefed.
4. The adjudication procedure and consensus rule are defined (who adjudicates; how a consensus polyline is formed; what happens to unresolved cases).
5. Consent forms and the retention period for the validation set are in place.

## Changing the lock
Any edit to the locked files makes gate 1 BLOCKED. A deliberate re-lock needs `python -m evals.hairline_cohort lock --reason "..." --overwrite`, a matching
entry in `HAIRLINE_THRESHOLD_REGISTER.md`, and the threshold-lock test baseline updated. Never to improve a validation score.
