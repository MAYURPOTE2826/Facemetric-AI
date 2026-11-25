# Recommendation consistency (verified implementation)

`backend/app/consistency.py`, wired into `recommendations.candidates()` and `styling.advice()`. Deterministic: no LLM is
used to detect or resolve conflicts. 11 consistency tests (plus 2 preview-label tests) in `tests/test_validator_and_consistency.py`.

## Root cause of the contradiction in the sample report
Two separate problems:
1. **A backwards recommendation.** `lower_third_split` is (nose-to-mouth) / (mouth-to-chin). The sample value 0.37 is
   below the 0.5 ideal, meaning the chin section is already long. The library said "chin-length beard styling ... adds
   height below the mouth" for this case, which makes it worse. The text is corrected: keep chin length short and add
   balance above the mouth.
2. **No conflict check.** The face-shape beard list (e.g. "Goatee or anchor beard to lengthen the face") was merged with
   "Keep the chin short" in the same section.

## Rules
- Conflict group `chin_length`. Each recommendation title maps to a stance (`long` / `short`) in `CHIN_STANCE`; a test
  fails if a title in that table no longer exists in the library.
- Evidence: `thirds_lower_mid` high -> short; low -> long; `lower_third_split` low -> short. Only non-ideal metrics count.
- Decision: one-sided evidence wins. If both sides have evidence, the metric with the lower score (larger deviation)
  wins. If the gap is under 10 score points the result is `unresolved`: **both** sides are suppressed and a note tells
  the user the measurements disagree.
- Suppressed items are recorded with the reason in `analysis["recommendation_audit"]`.
- Face-shape beard styles are reconciled with the same decision (`reconcile_beard_styles`).

## Traceability fields added to every recommendation
`id` (stable hash of feature + title), `category`, `supporting_metrics`, `preconditions`, `limitations`, `priority`,
`conflict_group`. Grooming/makeup items carry "cosmetic effect only - does not change bone structure".

## Not done
- Conflict resolution itself uses measurements only; goals are applied afterwards, as ordering (below).
- Only the `chin_length` conflict group exists; other pairs of opposite advice would need new groups.
- `preconditions` and `limitations` are generic per category, not individually clinically reviewed. Skincare and
  professional-procedure content has not had a clinical content review.

## Update (Phase 5): user-goal personalization (`app/personalization.py`, 15 tests)
The product already collects 8 preset goals (the frontend chips; a test keeps the backend map identical to them). What a goal can and cannot do:
- It only **reorders** recommendations that measurements already support. It never creates one, and never resurrects a recommendation the
  validator withheld or the conflict engine suppressed (conflicts are resolved first; tested).
- It never moves a recommendation above one in a **worse evidence tier**: tier 0 = measurement outside its reference range, 1 = near it,
  2 = skin concerns, 3 = general habits. Within a tier, goal matches come first, then the original measurement-severity order.
- With no goals, unknown goals, or only "Overall glow-up" the order is exactly as before (tested).
- Report sections and the 90-day plan follow the same rule (`order_metrics`).
- Each goal gets an honest **alignment** status shown in the report: `recommendations_available`, `general_recommendations_only`,
  `measurements_in_range` ("your measurements are within range, so no change is recommended"), `measurement_unavailable` ("we could not
  measure this reliably"), `no_specific_target`. A goal is never answered with an invented problem.
- Safety filters (e.g. nothing "professional" for a minor) are unchanged by goals (tested).
- Every recommendation keeps `id`, `supporting_metrics`, **`direction`** (low/high vs the reference), **`rationale`** (the measurement or
  skin score behind it), `limitations`, `priority`, `goal_match`, `ranking_reason`. **No `confidence` field**: none has been validated.
Not done: goals beyond the 8 chips (occasion, desired level of change, beard/hairstyle preference) are not collected; the LLM-written paid
report receives the goals through its prompt but its ordering is not constrained by this code.
