# Account-file security decision

## Decision: account files are NOT encrypted yet (deliberate, with prerequisites)
This is a decision backed by the evidence below, not an oversight. Cheap mitigations were applied now; encryption is deferred until
a prerequisite that is currently unmet (off-machine key custody) is satisfied.

## Evidence: what is stored (audited 2026-11-05, read-only; no value was printed)
| Item | Finding |
|---|---|
| Location | `backend/data/users/` - one JSON file per user plus `_index.json` (email -> user id) |
| Users | 8 user files; the index has 9 entries (1 orphan entry pointing at a missing file - login/signup now handle it) |
| Per-user fields | id, **email (plaintext)**, name, created_at, 16-byte random salt, PBKDF2-HMAC-SHA256 hash, hash cost, report ids, session hashes + expiry, check-in feedback text |
| Passwords | never stored in plaintext or reversibly (tested) |
| Hash cost | all 8 existing accounts are on 200,000 iterations; new accounts 600,000; each existing account upgrades on its next successful login |
| Sessions | stored only as SHA-256 hashes (tested); 60-day expiry; revoked on logout (browser-tested) |
| Reachability | no report endpoint can reach these files (`store.path` accepts only hex report ids inside the report folder; tested with traversal forms); `GET /api/me` and progress return only the caller's own data; a report response never contains the owner's email/hash/salt (tested) |
| Backups | the plaintext migration backup contains these files (emails + hashes) |
| Folder permissions | now restricted to the owning account at every application start (NTFS ACL via `icacls`; tested that it is requested) |

## Threat model
- **In scope:** theft or accidental exposure of the data folder or a backup of it (lost laptop, copied folder, cloud-sync leak).
  What leaks: email addresses (personal data) and password hashes that are only attackable offline at PBKDF2 cost (200k-600k
  iterations; strength depends on each user's password).
- **Already mitigated:** no network path to the files; owner-only folder permissions; hashed-only secrets; timing-safe login;
  enumeration-safe login; throttled login/signup.
- **Not mitigated by encryption either:** an attacker on the running host (the app must be able to decrypt), SQL-style abuse
  (none: file storage), weak user passwords.

## Options considered
| Option | Protects | Cost / risk | Verdict |
|---|---|---|---|
| A. Leave as is + owner-only permissions | nothing against a copied folder beyond hash cost | none | **current** |
| B. Encrypt user files with the SAME key as reports | emails at rest | couples sign-in availability to the report key: losing that key would lock every user out of their accounts (they could not even sign in to attempt anything), and a single key compromise exposes both | rejected (your instruction, and the analysis agrees) |
| C. Independent account key + keyed-HMAC email index (blind index) + encrypted user files | emails at rest; efficient, safe lookup (HMAC(email) -> id; no scan, no decryption to look up) | a second secret with its own custody, recovery, startup check and backup/restore tests; index must be rebuildable from user files; migration of 8 accounts with the same backup discipline | **recommended, deferred** |
| D. Store only an email hash (no plaintext email) | email at rest | the product sends nothing by email today, but the account page and support flows may need the address; irreversible | not chosen without a product decision |

## Why deferred (the evidence)
1. **Key custody is not yet established.** The report key still has no off-machine copy (checked: only local fixed drives C:-F:
   exist). Adding a second key before the first is safely custodied doubles the loss risk and the lock-out risk.
2. **Risk is bounded today:** 8 accounts; no network path; hashes upgraded on login; folder now owner-only.
3. **The design is understood and testable** (below), so it can be done as one reviewed change when custody exists.

## Prerequisites and design for option C (NOT implemented)
- Off-machine copies of BOTH keys, verified by a restore drill.
- `DATA_ACCOUNT_KEY` independent of `DATA_ENCRYPTION_KEY`; its own key file (`~/.alexendra/accounts.key`), never generated while
  encrypted account files exist (same guard as reports); startup failure behaviour tested for missing / corrupt / wrong key.
- Blind index: `HMAC-SHA256(index_key, lowercase email)` -> user id, with `index_key` derived from the account key; lookups never decrypt
  other users; `_index.json` holds no plaintext email.
- User files encrypted with Fernet (`ACC1:` marker, as reports use `ENC1:`); passwords stay hashed (never reversible); no secret is logged.
- Migration with the same gates as the report migration: verified byte-identical backup first, per-file triple verification, idempotent,
  rollback by restoring the backup; recovery procedure documented and drilled.
- Tests: startup failure modes, backup/restore, lookup correctness and timing parity, no-plaintext-email-on-disk scan, login/signup/logout
  regression, orphan-entry behaviour.
