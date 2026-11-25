# Production readiness

## Verdict: **NOT READY**

Status words (only these): **VERIFIED** (demonstrated by an executed test or measurement), **MEASURED** (a real measurement exists; it may still not be an accuracy
claim), **PARTIALLY VERIFIED**, **NOT MEASURED** (no ground truth exists), **UNVERIFIED**, **NOT IMPLEMENTED**, **NOT TESTED**.

## Evidence matrix
| Area | Status | Evidence |
|---|---|---|
| Encryption at rest | **VERIFIED** | 59/59 reports decrypt, 0 differ from the backup, 463/463 images decode; the app refuses to start on a missing/corrupt/wrong key |
| Key recovery - decryption | **VERIFIED** | recovery gate on real data, 2026-11-05: 59/59 decrypt from a standalone key file, 59/59 equal to the backup, 0 differences |
| Key recovery - off-machine copy | **NOT IMPLEMENTED** | no copy exists off this machine (only local fixed drives C: to F:); the gate reports `off_machine: false` |
| Plaintext photo backup | **STILL EXISTS - NOT DELETED** | deletion precondition (verified off-machine key copy) unmet; the delete command was never run against the real backup; KEY_RECOVERY.md |
| Owner / wrong-account / anonymous authorization (API) | **VERIFIED** | backend security, owner-flow and concurrency tests; identical 404s on every report route |
| Same, in a browser | **PARTIALLY VERIFIED** | 26/26 in Edge desktop, 26/26 in Edge with a 390x844 touch viewport, 26/26 in Firefox 132, 26/26 in bundled Chromium. WebKit/Safari and real phones **NOT TESTED**; the mobile run is emulation |
| Anonymous token lifecycle (expiry, rotate, owner revoke) | **VERIFIED** | API and browser tests; no UI for rotate/revoke |
| Try-on consent (backend + UI) | **VERIFIED** | 16 backend + 6 browser scenarios x 4 browser runs; provider stub called 0 times without consent |
| Try-on spend control | **VERIFIED (count-based)** | global daily cap + circuit breaker, IP-rotation-proof, shared across processes; provider price **UNVERIFIED** (cap is a count) |
| Provider privacy (fal.ai, Gemini) | **UNVERIFIED** | documentation read 2026-11-05 (PROVIDER_PRIVACY.md) but the plan/settings used are unknown; `PROVIDER POLICY UNVERIFIED` remains visible |
| Rate limiting | **PARTIALLY VERIFIED** | SQLite: persistent, shared across processes on one machine; every limit exact under 8-12 concurrent clients (load test). Distributed limiter **NOT IMPLEMENTED** (not needed for the only evidenced topology) |
| Concurrency / load | **MEASURED** | LOAD_TEST.md: one small machine; found and fixed 3 defects; analysis is CPU-bound and uses ~80 MB per concurrent analysis; per-report locks are per process (multi-worker lost updates possible) |
| Penetration testing | **NOT TESTED** | PENETRATION TEST NOT PERFORMED |
| Landmark stability | **MEASURED** | 2 photographs; stability and robustness only (LANDMARK_VALIDATION.md) |
| Landmark accuracy | **NOT MEASURED** | 0 labelled subjects/images/annotations; evaluator ready (VALIDATION_DATASETS.md) |
| `frontalize` | **PARTIALLY VERIFIED** | roll-to-yaw defect fixed and proven on exact geometry; absolute yaw accuracy vs a reference **NOT MEASURED** (pose evaluator ready, 0 reference poses) |
| Skin segmentation accuracy (IoU, Dice, FPR, FNR) | **NOT MEASURED** | 0 labelled masks; contamination known only through indicators on 2 photos (SKIN_SEGMENTATION_VALIDATION.md); stubble and glasses-frame contamination remain |
| Skin metric gating | **PARTIALLY VERIFIED** | per-metric dependency table generated from code, 24 tests; thresholds unvalidated |
| Physical measurements | **NOT MEASURED** | 0 paired caliper readings; every value stays `ESTIMATED`; `ACCEPTANCE CRITERIA NOT YET DEFINED` |
| Reference ranges and thresholds | **UNVERIFIED** | labelled `PLACEHOLDER - NOT PRODUCTION VALIDATED` in data, UI and each report's validation block |
| Four reconstructed modules | **UNVERIFIED** | audited (RECONSTRUCTED_MODULES.md): no source, no independent validation |
| Account files | **NOT IMPLEMENTED (encryption)** | decision documented (ACCOUNT_DATA_DECISION.md); folder owner-only |
| User-goal personalization | **PARTIALLY VERIFIED** | 8 preset goals only; 15 tests; order never overrides evidence |
| Hairline & hair-density engine | **PARTIALLY IMPLEMENTED - accuracy NOT MEASURED** | classical CV pipeline (boundary, temples, shape, symmetry, density, crown-only-from-top-photo, quality gate, longitudinal compare); 40 synthetic-scene tests + 13 evaluator self-tests pass; 0 real photos, 0 human annotations, never run on a real face: REAL-PHOTO ACCURACY NOT MEASURED; thresholds are placeholders (HAIRLINE_VALIDATION_READINESS.md, HAIRLINE_THRESHOLD_REGISTER.md) |
| Deployment topology | **PARTIALLY VERIFIED** | code is single-machine by design; production plan not recorded (DEPLOYMENT_ASSUMPTIONS.md) |

## Executed tests (exact)
- Backend `python -m unittest discover -s tests`: **478 ran in the latest full run: 462 pass, 0 fail, 16 SKIPPED (they need the local photographs; not supplied in that run).** Earlier runs with the two authorised photos supplied passed all of that era's tests; the current suite has not been re-run with photos. (Photographs are not in the repository.)
- `python -m evals.report_evals`: 50/50 cases, 0 failures; 15/15 validator self-tests.
- Browser (`browser-tests/`, Playwright 1.56.1), latest run against the final code (38 tests = 26 security + 9 hair UI/progress + 3 PDF): Microsoft Edge 151 **38/38**, bundled Chromium **38/38**, Firefox **35 passed, 3 skipped** (PDF tests are Chromium-family only). Edge mobile viewport, WebKit/Safari, real phones: not run. Earlier 26/26 records (BROWSER_VERIFICATION.md) predate the hairline work and are historical. See HAIRLINE_VALIDATION_READINESS.md.
- Frontend `npx tsc --noEmit`: no errors. `npx eslint src`: no problems.
- Load test: executed once (LOAD_TEST.md). Penetration test, WebKit, real-phone tests: not run.

## Real validation dataset (Phase 6 required counts)
Subjects 0 - images 0 - landmark annotations 0 - skin masks 0 - physical measurements 0 - reference head poses 0. No accuracy number for landmarks, skin segmentation
or physical measurements exists, and none is claimed.

## Remaining blockers
Scientific: (1) landmark accuracy; (2) skin segmentation accuracy and the stubble/glasses contamination it would quantify; (3) physical-measurement accuracy and its
acceptance criteria; (4) head-pose reference for `frontalize`; (5) replacing the placeholder reference ranges/thresholds with cited, validated values; (6) expert review of
the four reconstructed modules.
Engineering/privacy: (7) off-machine key copy, then deletion of the plaintext photo backup; (8) provider retention/training confirmation for the plan in use (or disable
try-on); (9) account-file encryption (after key custody); (10) production topology decision - one worker is the only safe setting today; multi-process report updates can
lose an update; (11) penetration test; (12) WebKit/Safari and real-device testing; (13) `/api/analyze` has no global cap and analysis is CPU/memory-heavy.
