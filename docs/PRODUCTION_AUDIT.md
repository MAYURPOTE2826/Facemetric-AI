# Production audit - Facemetric-AI (PFI)

Status: **Phase 1-2 partially complete.** This file records only what was verified by reading code or running
tests. Anything not listed under "Verified" must be treated as unverified.

## Verified fixes (with evidence)

| # | Finding | Root cause | Fix | Evidence |
|---|---|---|---|---|
| 1 | Report showed face width-to-height 2.65 vs reference 1.9 ("outside") for a normal face | `fwhr` divided by eyelid-to-upper-lip height; the published definition (reference 1.9) uses brow-to-upper-lip | `metrics.py` now uses brow level | `tests/test_measurements.py::test_fwhr_is_width_over_brow_to_upper_lip` |
| 2 | "Face height 111.7 mm = Above (+33%)" for a normal face | Placeholder range 75-93 mm was wrong for nasion-to-menton (adult ~110-125 mm) | Range corrected, row renamed "Nasion-to-chin height" | Code review; ranges remain approximate and **not validated** |
| 3 | Mirror section showed "Symmetry score: 3" next to category score 87 | UI passed the raw deviation % (3.37) as a score | Page now passes the metric's `score` | Code review (`report/[id]/page.tsx`) |
| 4 | "Skin tone group: very light" for a brown-skinned user | ITA colour read under too-bright / colour-cast / filtered light | Group is set to "unknown" when `too_bright`, `colour_cast` or `beauty_filter` quality flags exist | Code review (`main.py`); not yet tested on a fixture set |
| 5 | Full beard not flagged, so jaw/chin ratios were trusted | Beard threshold of 30% of the jaw region was too lax | Lowered to 18% | **Not validated on data** - needs a labelled beard set |
| 6 | Unsupported "+/-3 mm" accuracy claim in the report | My own reconstruction of `anthropometry.py` asserted it | Removed; the table now carries a `calibration` block (`validated: false`, min 5% uncertainty) and the UI says "estimated" | `test_calibration_is_declared_unvalidated` |
| 7 | Browser print/PDF: dark sections unreadable, cards split across pages, URL/date header | No print-colour-adjust, no page-break rules | `globals.css` print rules | Not yet re-exported to PDF to confirm |
| 8 | CORS allowed every origin | `allow_origins=["*"]` | Defaults to `http://localhost:3000`; override with `CORS_ORIGINS` | Code review |

## Verified findings NOT yet fixed

- **Report access is unauthenticated.** `GET /api/analyses/{id}` returns the report to anyone holding the id. Ids are
  `uuid4().hex[:12]` (48 bits). Photos and analyses are stored as plain JSON under `backend/data/`.
- **No landmark/model integrity checks** (asset checksums, 478-point assertion) and no per-landmark reliability score.
- **Iris calibration is a fixed 11.7 mm constant** and a default 26 mm (35mm-equivalent) focal length when EXIF is
  absent. It has never been compared with physical ground truth.
- **`frontalize()` can silently saturate.** Its search is bounded to +/-30 deg, and ties are broken toward -30 deg when
  the landmark set carries no depth (found while building the test fixture). A result at the bound should be flagged
  unreliable instead of being used.
- **Contradictory recommendations.** `recommendations.py` can emit "Soften lower-face length - keep beard short at the
  chin" (thirds, high) together with "Balance lip-to-chin height - chin-length beard styling" (lower-third split, low).
  No conflict check exists.
- **Hair score of 95** is produced from a front photo alone; crown and density cannot be assessed from it.
- **Before/after previews** are classical image warping and smoothing, not a generative model. They are labelled
  "AI simulation", which overstates the method.
- **Four modules were rebuilt by me, not recovered:** `anthropometry.py`, `eyes.py`, `diagrams.py` and
  `components/ReportFigures.tsx` had been lost. Their formulas and reference ranges are placeholders.

## Update: security / validation / consistency phase (verified)

| Earlier finding | Status now |
|---|---|
| Report access unauthenticated, 48-bit ids | **Fixed** - credential required (owner session or per-report token); 128-bit ids; uniform 404; rate limits. See SECURITY_AND_PRIVACY.md |
| Photos stored unencrypted | **Fixed for new reports**; 59 existing reports still plaintext until migrated |
| Contradictory chin recommendations | **Fixed** - one recommendation was backwards (lower-third split); deterministic conflict engine added. See RECOMMENDATION_CONSISTENCY.md |
| Hair score 95 from front photo alone | **Fixed** - overall score withheld without a crown photo |
| Previews called "AI simulation" | **Fixed** - labelled as image editing; the try-on feature (a real generative model) is unchanged |
| Unvalidated formulas / ranges, rebuilt modules | **Still open** |
| No landmark integrity checks | **Partly fixed** - NaN, too-few and out-of-frame landmarks are rejected; model file SHA-256 is recorded per report; no per-landmark reliability score |
| `frontalize()` saturation | **Partly fixed** - a saturated yaw correction now suppresses symmetry; the function itself is unchanged |

Bugs introduced and caught by the tests during this phase (all fixed, with regression tests): publishing without
`style.confidence` crashed the unpaid-report preview (HTTP 500); the new chin regex matched the app's own sentence; the
validator treated uploads without EXIF as having no mm scale.

New finding: try-on transmits the user's photo to a third-party model provider (see SECURITY_AND_PRIVACY.md).

## Test status
- `python -m unittest discover -s tests` (from backend/): 9 tests, all pass.
- `python -m evals.report_evals`: 50 report cases, 0 failures; 15 validator self-tests, 0 failures (pre-existing).
- Landmark accuracy, segmentation IoU and measurement error: **not measured** (no ground-truth dataset in the repo).

## Update: post-migration security and Phase 4 (verified)

| Item | Result |
|---|---|
| Key failure modes | app refuses to start on missing / corrupted / wrong key; never writes or returns the key (tested) |
| Owner authorization | API-level tests for every report route and wrong-account / anonymous / invalid token / expired / revoked cases; **browser level still pending** |
| Try-on consent | server-enforced; no photo is sent without a current per-report, per-provider consent; provider retention policy unknown |
| Account files | audited; not encrypted (decision pending); login timing leak and an orphan-index crash found in real data and fixed; hash cost raised for new/upgraded accounts |
| Rate limiting | extended to admin, try-on, mutations, consent, claim; still in-memory per process |
| Landmark map | central `landmark_map.py`; the L/R pair table verified against the real model with a mirror test |
| Landmark stability | measured on 2 photos (LANDMARK_VALIDATION.md); **accuracy not measured** |
| `frontalize` bug | root cause established; saturation and undetermined cases now explicit; range not widened (reasoned, not validated) |
| Multiple faces | ambiguous two-person photos rejected |
| Skin mask | builder extracted (byte-identical output); a real defect (whole beard inside the mask on a smoothed-beard photo) found by inspection and partly mitigated; **accuracy not measured** |
| Skin gating | metric-specific; thresholds unvalidated |

Defects found by this phase's own checks and fixed: `frontalize` tie-break to -30 deg on depthless input; sign wrap-around at
35 deg unflagged; silent choice between two equal faces; whole beard in the skin mask; login 500 on an orphan index entry
(and email enumeration through it); unknown-email timing difference; several mistakes in my own new tests (fixed in the tests; no existing test was weakened).

Defects found and **not** fixed: beard quality flag misses a smoothed beard (no negative example to set a threshold);
residual stubble and glasses frames inside the skin mask; no occlusion detector for hands/masks; frontalize's yaw estimate
differs from MediaPipe's by 4-5 deg on both photos (unexplained); gate accepts 15 deg of MediaPipe yaw, which can approach
the +/-30 deg frontalize limit.

## Update: Phase 5 (browser verification, spend control, validation infrastructure) - verified

| Item | Result |
|---|---|
| Browser authorization | 26/26 real-browser tests pass (Edge, real frontend, isolated backend) - BROWSER_VERIFICATION.md |
| Gap found by the browser scenarios | anonymous report tokens had no expiry and no revocation -> added 90-day expiry, rotate, owner-only revoke (tested in API and browser) |
| Try-on consent in the browser | disclosure, decline, agree, withdraw, report/provider binding, API-only bypass attempts: all pass; `PROVIDER POLICY UNVERIFIED` shown |
| Rate limiting | in-memory -> SQLite: survives restart, shared across processes on one machine (not distributed); endpoint matrix generated from routes with a test that fails on any unclassified route |
| Paid try-on abuse | global daily cap + circuit breaker, independent of IP and report (tested) |
| Account files | decision documented (encryption deferred with prerequisites); folder permissions restricted at startup; orphan-index login crash fixed earlier |
| `frontalize` | in-plane roll leaked into yaw (exact-geometry proof) - fixed; saturation explicit; yaw discrepancy vs MediaPipe analysed, not adjudicated |
| Landmark / skin / measurement validation | evaluators + dataset contracts built and arithmetic-tested on synthetic data; **no accuracy measured** |
| Personalization | goals reorder within evidence tiers; honest alignment statuses; directions and rationales on every recommendation |
| Unsupported precision claims | a source scan found "about +/-10%", "+/-20%" (hair) and "+/-5%" (measurement note, plus a `min_relative_uncertainty` field I had added); all removed; the scan is now a test |

Defects found by this phase and fixed: roll leaking into yaw; unlimited token lifetime; per-process rate limits; no global paid-call cap; four unsupported
precision claims; test-fixture mistakes in my own new tests (fixed in the tests; no existing test weakened).
Defects found and NOT fixed: after sign-out the app lands on `/login?next=/account` (cosmetic race); `/api/analyze` has no global cap; residual
stubble and glasses-frame pixels inside the skin mask; beard flag misses a smoothed beard.
Not run: load test, penetration test, other browsers, mobile viewports, print/PDF re-export.

## Update: Phase 6 (real-data validation attempt) - verified

**Headline: the three scientific gaps are still open, because no ground truth exists and none was fabricated.** Real dataset counts: 0 subjects, 0 images,
0 landmark annotations, 0 skin masks, 0 caliper measurements, 0 reference head poses (VALIDATION_DATASETS.md).

| Item | Result |
|---|---|
| Encryption recovery gate | decryption half VERIFIED on real data (59/59 decrypt from a standalone key file, 59/59 equal to the backup); off-machine half NOT MET - no removable/network media; plaintext backup NOT deleted. Gate tool + 16 tests; the delete command was never run against the real backup |
| Landmark / skin / measurement / pose accuracy | NOT MEASURED. Tooling: reference standard, dataset skeletons outside the repo, status counter, pose-validation evaluator (12 tests), all earlier evaluators |
| Reconstructed modules | audited (RECONSTRUCTED_MODULES.md); every reference range / threshold now carries `PLACEHOLDER - NOT PRODUCTION VALIDATED` in data, UI and each report's validation block; an unverifiable "Farkas" source claim was removed; population-typicality wording in metric descriptions replaced by "unverified approximation" |
| Provider privacy | provider documentation read (PROVIDER_PRIVACY.md): Gemini's terms treat paid and unpaid use differently (unpaid inputs may be used to improve products and read by reviewers); fal.ai documents 90-day default payload retention and publicly accessible media URLs, and states nothing about training. **Still UNVERIFIED for this deployment** (plan unknown); warning kept |
| Rate limiting / deployment | code is single-machine by design (local files + local SQLite); no deployment plan in the repo; no distributed system built (DEPLOYMENT_ASSUMPTIONS.md) |
| Load / abuse testing | executed (LOAD_TEST.md); it found three real concurrency defects, all fixed with regression tests proven to fail on the old code |
| Browser coverage | Edge desktop, Edge mobile viewport, Firefox 132 desktop: 26/26 each; bundled Chromium: see BROWSER_VERIFICATION.md; WebKit/Safari and real phones NOT TESTED |

Defects found by this phase and fixed:
1. failed-lookup and admin-failure limiter overshoot under concurrency (23 allowed against 20);
2. HTTP 500 / dropped connections when several requests updated one report simultaneously (Windows file replace; no serialisation);
3. try-on spend race (8 identical simultaneous requests made 3 provider calls; quota raceable);
4. `classify_key_copy` bound its drive-type function at definition time (found by its own tests; the failure direction was the safe one).
Defects found and NOT fixed: report updates are serialised per process only (several worker processes can still lose an update); `/api/analyze` has no global
cap; analysis is CPU-bound (4 concurrent analyses took 12-16 s each vs 3.6 s sequentially) and uses ~80 MB per concurrent analysis that is not released.
Mistake of mine caught and corrected: I first recorded "Chrome" as failing; Chrome was not found by Playwright (an environment issue, not an application failure), so
it is reported as NOT TESTED and replaced by a bundled-Chromium run.
