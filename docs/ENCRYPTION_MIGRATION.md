# Encryption migration of existing reports (performed 2026-11-05)

59 plaintext reports in `backend/data/` were encrypted with Fernet. This file records what was done and how to recover.

## What was done
1. **Backup first.** All 68 files of `backend/data/` (59 reports + 9 account files) were copied to
   `C:\Users\Admin\alexendra-backups\data-20261105-023200` (outside the repo). Verified: same file set, SHA-256 identical for
   every file, all 59 reports parse as JSON. Access restricted to the owning Windows account (NTFS ACL).
2. **Key.** Generated once at `C:\Users\Admin\.alexendra\data.key` (outside the project, owner-only ACL, valid Fernet key,
   same value on re-read). A separate copy is in `C:\Users\Admin\alexendra-backups\keys\`. No previous key existed, so none
   was replaced. The key value was never printed or logged.
3. **Dry run** of the real command: 59 would encrypt, 0 failed, nothing written.
4. **Migration:** `python -m app.store --migrate --backup-dir <backup>`. Result: 59 encrypted, 0 failed, 0 plaintext
   remaining, exit code 0. Each report is verified three times (encrypt/decrypt round trip; the written temp file before
   replacing; the file after replacing). The command refuses to run without a byte-identical backup while any plaintext
   report remains.

## Independent verification (fresh process, read-only)
| Check | Result |
|---|---|
| Report files / encrypted / plaintext / stray temp files | 59 / 59 / 0 / 0 |
| Decryption failures | 0 |
| Documents that differ from the plaintext backup (all fields, ids, owners, photos, previews) | 0 |
| Embedded images decoded (photos, previews, annotated images, figures) | 463 / 463 |
| Owned reports keeping owner and listed in the owner's account | 38 / 38 |
| Read through the application (admin endpoint) | 59 / 59 |
| Fresh process with no env key, using the key file | 59 / 59 decrypt |
| Re-run of the migration | 59 already-encrypted-verified, data hash identical before and after |
| Plaintext report copies elsewhere under the project | none (matches are source code and tests only) |
| Anonymous reports older than 90 days (would be purged at next app start) | 0 |

Not tested: signing in as a real account owner (no passwords available) to open a report in the browser UI; the browser
UI after migration.

## Key recovery
- Encrypted reports can only be read with this key. **Copy `data.key` into a password manager or offline storage now.**
- If the key file is lost: restore it from `alexendra-backups\keys\data.key.copy` (or your own copy) to
  `C:\Users\Admin\.alexendra\data.key`, or set `DATA_ENCRYPTION_KEY` to its value.
- The app will not create a replacement key while encrypted reports exist; it stops with an explicit error.
- If the key is lost everywhere, reports are recoverable only from the plaintext backup folder.

## Cleanup (not done)
The plaintext backup and the in-folder key copy were deliberately kept. After you confirm the application works with the
encrypted reports: store the key off this machine, then securely delete the plaintext backup. Do not keep the only key
copy next to the data.

## Remaining
Account files (`data/users/*.json`: emails, password hashes, session hashes) are not encrypted and were not migrated.

## Follow-up checks (read-only, after the migration)
- Application startup check against the real data: 59 encrypted reports, key from the key file.
- Live key equals the recovery copy; reading the reports with only the recovery copy decrypted 59 of 59.
- Plaintext backup matches the decrypted live data: 0 differences, 59 readable, still owner-only ACL.
- Recovery procedure, failure behaviour and secure-deletion instructions for the backup: KEY_RECOVERY.md.
- The plaintext backup has **not** been deleted.
