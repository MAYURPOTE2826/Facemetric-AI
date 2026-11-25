# Encryption key: where it is, how it fails, how to recover

No key value appears in this document, in the logs, or in any API response (checked by tests).

## Where the key lives
> The paths below are the existing key and backup locations. Their historical `alexendra` directory names are
> intentionally preserved so a brand rename does not move or replace encryption keys or backups.

| Item | Location |
|---|---|
| Live key file (used by the app and by `python -m app.store --migrate`) | `C:\Users\Admin\.alexendra\data.key` (outside the project; NTFS ACL: your account only) |
| Recovery copy | `C:\Users\Admin\alexendra-backups\keys\data.key.copy` (same machine) |
| Override | `DATA_ENCRYPTION_KEY` environment variable (takes precedence), or `DATA_KEY_FILE` to point at another file |
| Off-machine copy | **none yet - you must make one** |

The app and the migration command resolve the key through the same function (`store._key()`), and the command loads
`backend/.env` first, so both always use the same key (tests: `test_migration_command_loads_the_same_settings_as_the_application`).

## What the application does when the key is wrong (all tested)
| Situation | Behaviour |
|---|---|
| Key file missing, encrypted reports exist | **Refuses to start** and refuses to generate a replacement ("would make every report unreadable") |
| Key file corrupted / truncated / not a valid Fernet key | **Refuses to start**; the message never contains the key; the file is left untouched |
| A different (wrong) key | **Refuses to start** ("does not decrypt the stored reports") |
| Correct key | Starts; logs only the number of encrypted reports and whether the key came from env or file |
| No reports yet and no key | Generates one new key file once (never overwrites an existing one) |

Verified against your real data (read-only, 2026-11-05): startup check reports 59 encrypted reports; the live key equals the
recovery copy; a recovery drill that read the key only from the copy decrypted 59 of 59 reports; the plaintext backup
matches the decrypted live data exactly (0 differences, 59 readable).

## Recovery procedures
1. **Live key file lost or damaged, copy intact:** copy `alexendra-backups\keys\data.key.copy` to
   `C:\Users\Admin\.alexendra\data.key` (or set `DATA_KEY_FILE` to the copy). Start the app. Do not delete the copy.
2. **Both local copies lost, you have an off-machine copy:** restore it to `C:\Users\Admin\.alexendra\data.key`, or put its
   value in `DATA_ENCRYPTION_KEY`.
3. **Every copy of the key lost:** encrypted reports cannot be decrypted by anyone. The only recovery is the plaintext
   backup `alexendra-backups\data-20261105-023200` (still present). Copy its `*.json` files into `backend\data\`, then re-run
   `python -m app.store --migrate --backup-dir <that backup>` with a **new** key.
4. **Never** run the app or the migration "to fix it" without the original key while encrypted reports exist; the code stops
   you, but do not work around that guard.

Key rotation is **not implemented**.

## Do this now (not done by me)
- Save a copy of `data.key` in a password manager or other offline storage. A copy on the same disk does not protect against
  losing the disk.

## Plaintext backup: when and how to delete it (NOT done - needs your explicit decision)
The backup `C:\Users\Admin\alexendra-backups\data-20261105-023200` holds **every photo unencrypted** and the account
files (emails, password hashes).

Delete it only after ALL of these are true:
- [x] key recovery verified (drill above)
- [x] encrypted reads verified through the application's code path
- [x] backup integrity verified (byte-identical at backup time; matches decrypted live data)
- [x] recovery procedure documented (this file)
- [ ] an off-machine copy of the key exists
- [ ] you have opened the app, signed in, and viewed a few of your own reports in the browser

Then, in PowerShell:
```powershell
Remove-Item -LiteralPath "C:\Users\Admin\alexendra-backups\data-20261105-023200" -Recurse -Force
# optional, mechanical disks only: overwrite the freed space of that folder's volume (slow)
cipher /w:C:\Users\Admin\alexendra-backups
```
Caveats: on an SSD/NVMe, overwrite tools cannot guarantee removal (wear levelling). Full-disk encryption (BitLocker) is the
reliable protection for deleted data. Also check for other copies: Recycle Bin (`Remove-Item` bypasses it), OneDrive/File
History sync of the folder, and shadow copies (`vssadmin list shadows`). Afterwards move or delete
`alexendra-backups\keys\data.key.copy` once the off-machine copy is confirmed.

## Phase 5M status (checked 2026-11-05) - backup deletion preconditions
| Precondition | Status |
|---|---|
| Recovery key exists in two locations | MET (live key file + `alexendra-backups\keys\data.key.copy`), **both on this machine** |
| At least one copy is OFF this machine | **NOT MET / UNVERIFIED** - only local fixed drives C:, D:, E:, F: exist; no removable or network drive; the copy needs to go to a password manager or offline storage you control |
| Procedure understandable without the author | MET (this document) |
| Encrypted data restorable from the recovery key | MET (drill: 59/59 decrypt reading the key only from the copy; re-run today) |
| Backup integrity verified | MET (59/59 readable, 0 differences from the decrypted live data; re-run today) |
**Therefore the plaintext backup was NOT deleted.** Delete it only after you have stored a copy of the key off this machine.

## Phase 6A - the recovery gate tool (`backend/tools/recovery_gate.py`)
Run this when you have put a copy of the key on removable or network media (a USB drive kept elsewhere, a hardware token, a NAS share that is not your own cloud
sync). It never prints the key.
```
python tools/recovery_gate.py verify --key-file <path-to-the-copy> --backup <plaintext-backup-folder>
```
`verify` (read-only) decrypts every report in `backend/data` using ONLY the key in that file, compares each document with the plaintext backup, and reports the
drive type of the key copy. Verified on the real data on 2026-11-05 with the live key file standing in as the "copy": **59/59 decrypt, 59/59 equal to the backup,
0 differences, and the key location reported as `off_machine: false` (fixed local disk).** The decryption half of the gate passes; the off-machine half does not,
because no off-machine copy exists yet.
```
python tools/recovery_gate.py delete-backup --key-file <copy> --backup <folder> --confirm-delete
```
refuses unless ALL hold: the key copy is on a removable/network drive; it is not inside the project, the backup folder, or a cloud-sync folder (OneDrive, Dropbox,
Google Drive, iCloud ...); it decrypts every report and every document equals the backup; `--confirm-delete` was passed. Deletion overwrites each file with random
bytes, flushes, removes it, and verifies the folder is gone (on SSD/NVMe this cannot guarantee the old blocks are gone; use full-disk encryption).
16 tests cover verification, wrong/garbage keys, tampered or missing backup files, the classification rules, every refusal path and the deletion path, all on
temporary folders. **The delete command was never run against the real backup.**

**Deletion status: the plaintext backup still exists. Recovery location type: none off-machine yet. Decryption-half verification date: 2026-11-05.**
