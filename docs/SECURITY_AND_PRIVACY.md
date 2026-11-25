# Security and privacy (verified implementation)

Everything marked "tested" is covered by automated tests in `backend/tests/` (`test_security.py`, `test_phase_security.py`,
`test_migration.py`). Items under "Not done / open" are NOT implemented. Browser-level behaviour is **not** verified (see
"Browser verification").

## Access control (tested)
A report is reachable only with a credential, never with its id alone: (1) the signed-in **owner** (Bearer session; sessions
expire after 60 days, are stored as SHA-256 hashes and revoked on logout), or (2) the per-report **access token** (256-bit,
returned once by `/api/analyze`, sent as `X-Report-Token`, only its hash stored). Report ids are 128-bit random.
**Token lifecycle (added in Phase 5):** access tokens now **expire** (default 90 days, `ACCESS_TOKEN_DAYS`; 0 = never; legacy reports without an
expiry field keep working), can be **rotated** by any credential holder (`POST /api/analyses/{id}/token/rotate` - the old token dies immediately), and
can be **revoked entirely by the signed-in owner only** (`DELETE /api/analyses/{id}/token`; a token holder cannot revoke). Anonymous reports are also
deleted after `RETENTION_DAYS`. There is no UI for rotate/revoke yet (API only).
Every report route uses the same dependency (`security.report_access`): read, delete, checkout, confirm, try-on, consent,
claim. Every failure - malformed id, unknown id, wrong token, someone else's report, expired or revoked session - returns the
**same 404 body and length**, so the API does not reveal which reports exist (tested route by route, including with a signed-in
wrong account). Claiming an unowned report needs its token. There is no server-side PDF or image route; the print view loads
the same protected JSON.

Owner flow traced and tested at API level: sign up / log in -> `/api/me/progress` lists only that account's reports -> open
(owner) -> delete (owner only; another account and anonymous callers are refused and the file stays) -> checkout/confirm ->
try-on -> claim. Another user's report id with a valid session of a different account is refused on **all** of these routes.

## Encryption at rest (tested; migration done)
Fernet (AES-128-CBC + HMAC-SHA256). All 59 existing reports were migrated and independently verified - see
ENCRYPTION_MIGRATION.md. Key handling, failure behaviour and recovery - see KEY_RECOVERY.md. The app refuses to start on a
missing, corrupted or wrong key (tested), never generates a replacement while encrypted reports exist, and never writes or
returns the key (log capture, API-response scan and a source scan are tested).

## Try-on consent (implemented, tested; UI not exercised in a browser)
What leaves the server: the front-face photo (a cropped copy up to 768 px) plus a text prompt, sent to fal.ai or Google Gemini
(whichever the server is configured with).
- **Server-enforced**: the try-on route requires a current consent record for exactly the active provider *before* any quota
  is spent; `tryon.generate()` itself raises `ConsentRequired` unless called with `consented=True`. Direct API calls cannot
  bypass it (tested with extra body fields, headers and cookies; the external-call functions are mocked to fail if reached).
- Consent is per report, per provider, per consent-text version, valid 30 days (an engineering choice), revocable
  (`POST ... accept:false` or `DELETE`), and a consent request that names a different provider or text version is rejected.
- Stored minimum: `{version, provider, granted_at, expires_at}` on the encrypted report - no image copy, no IP or user agent.
- The UI shows: where the photo goes, which provider, why, what is requested, retention, that it is optional, and for how
  long; two buttons (agree / no thanks) and a withdraw link.
- **Provider retention/training policies are UNKNOWN to Alexandra**: they were not verified from the providers' current
  documentation, and the disclosure says so ("has NOT been verified by Alexandra"). A test forbids unverified claims
  ("not stored", "zero retention", etc.) in the text.
- Not done: no consent for the **analysis** itself beyond the existing product flow; no data-processing agreement review.

## Account files (audited; not encrypted)
`backend/data/users/` holds per user: id, **email (plaintext)**, name, created_at, a 16-byte random salt, the PBKDF2-HMAC-SHA256
hash (32 bytes), report ids, session hashes + expiry, and check-in feedback text. Verified:
- Passwords are never stored in plaintext; sessions are stored only as hashes (tested).
- **Password hashing cost:** the 8 existing accounts use 200,000 iterations; new accounts use 600,000 (OWASP guidance for
  PBKDF2-SHA256). Existing hashes are upgraded to 600,000 on the owner's next successful login (tested); until then
  they are on the weaker setting.
- **Login timing:** an unknown email now costs the same hashing work as a real check, and an index entry with a missing user
  file behaves exactly like an unknown email (found in real data: one orphan entry used to crash login with a 500 and block
  that email from signing up; fixed, tested).
- Account files cannot be reached through report endpoints (`store.path` accepts only hex report ids inside the report
  folder; tested with `users`, `_index`, account ids and traversal forms); `load_all` ignores them; `/api/me` returns no
  secrets; a report response never contains the owner's email, hash, salt or id (tested).
- Signup still tells a caller that an email is already registered (needed for the sign-up flow without email
  verification). Login does not.
- The plaintext backup folder also contains these account files (emails + password hashes).
- Account folder permissions are restricted to the owning Windows account at every application start (tested that it is requested). Decision record: ACCOUNT_DATA_DECISION.md.
- **Encryption of account files was NOT done.** Assessment: the threat is theft of the data folder (emails are personal data;
  hashes and session hashes are offline-crackable only at PBKDF2 cost). Encrypting them with the existing key is feasible
  (`accounts._load/_save`) and would protect the emails, but it also makes the key a single point of failure for **logging in**,
  not just for reading reports, and needs a migration with the same backup discipline. Recommended, deferred pending your
  decision.

## Rate limiting and spend control (Phase 5) - full per-endpoint table: ENDPOINT_MATRIX.md
**Storage:** a SQLite file in the data directory (`.ratelimit.sqlite3`). Counters **survive a restart** and are **shared by every worker process on
this machine** (verified by a test that runs two real OS processes against one limit: they got exactly the limit in total). They are **NOT
distributed across machines**: several servers behind a load balancer would each keep their own, and no central store (Redis etc.) exists. Counted per
client IP (`X-Forwarded-For` ignored unless `TRUST_PROXY=1`).
The matrix (generated from the real routes, with a test that fails if a route is unclassified) lists, for every endpoint: authentication, sensitivity,
limiter, scope, window, restart-survival, abuse consequence, and the reason when unlimited. Highlights: failed report lookups 20/10 min then 429; report
ceiling 240/min; analyze 20/h; login 10/5 min; signup 10/h; checkout/confirm/delete 30/10 min each; claim, consent, token 30/10 min; admin: 10 failed
attempts/10 min then 429 even for the right token; unlimited by design with stated reasons: health, webhook (signature-verified), logout and `/api/me*`
(session-protected, own data only).
**Try-on spend protection (global, not per-IP):** per-IP 20/h, per-report quota 6, **plus** `spend_guard`: a rolling-24h **daily cap** (default 100,
`TRYON_DAILY_CAP`) and a **circuit breaker** (5 consecutive provider failures pause external calls for 10 minutes; quality rejections do not trip it).
It is a **count**, not money: Alexandra has no verified provider pricing, so convert the cap yourself. Attempts are counted when reserved, so a crash cannot
hide spend. Tested: 6 different IPs and 6 different reports hit the same global cap (exactly 3 provider calls allowed); rejected and failed attempts still
count; the breaker opens, stops calling the provider, and closes after the pause; usage is shared with other processes and survives restart; requests
refused before the provider (no consent, bad style) cost nothing.
**Still true:** an attacker with many IPs bypasses per-IP limits (the global cap is what bounds try-on spend; 128-bit ids make guessing infeasible
regardless); `/api/analyze` has only a per-IP limit (CPU/disk, no global cap); there is no distributed limiter.

## Deletion and retention (tested)
`DELETE /api/analyses/{id}` (same credential as reading) removes the report and everything inside it. At startup,
reports with **no owner account** older than `RETENTION_DAYS` (default **90**; 0 disables) are deleted. The migrated data was
checked: 0 reports would be purged today.

## Browser verification (Phase 5) - run record: BROWSER_VERIFICATION.md
A real run in Microsoft Edge against the real Next.js frontend and an isolated backend (temporary encrypted data directory, stubbed paid provider that
counts calls, every credential from `backend/.env` blanked so nothing real can be spent or called). 26 tests across the 7 scenarios you listed:
owner, wrong account, anonymous token (valid / invalid / none / expired / rotated / owner-revoked), delete (UI, cancel, token holder), try-on consent
(disclosure and the visible `PROVIDER POLICY UNVERIFIED` marker, decline, agree, withdraw, report/provider binding, API-only bypass attempts,
wrong-account and unauthenticated), claim (UI and the full API matrix incl. replay), credentials/logout (headers attached, client state cleared, old
session dead on the server, stale credentials re-injected into the browser, direct API with garbage credentials, server-side revocation while the
browser still holds the token). The generated record lists each test with expected and actual result.
Not covered by the browser suite: the print/PDF view, the `/account` list rendering beyond redirects, mobile viewports, other browsers, real payment
flows, and the real provider (always stubbed). Frontend checks are not a security boundary; every assertion that matters is also made directly
against the API.
Observed (not a vulnerability): after "Sign out" the app lands on `/login?next=/account` instead of `/` (the account page's redirect wins a race with
the button's `router.push("/")`).

## Not done / open
- Browser coverage is limited to the scenarios above (see BROWSER_VERIFICATION.md).
- Account files not encrypted (decision needed); 8 accounts still on the 200,000-iteration hash until they log in.
- Rate limiting is persistent and shared per machine but not distributed; `/api/analyze` has no global cap.
- Provider retention/training policy for fal.ai and Gemini unverified.
- The anonymous access token lives in `localStorage` (readable by any script on the page; lost when site data is cleared).
- The plaintext backup (all photos, unencrypted) still exists; deleting it needs your explicit decision (KEY_RECOVERY.md).
- No off-machine copy of the encryption key; no key rotation.
- No HTTPS/HSTS/security-header audit; logs not audited beyond key leakage; no penetration test.
