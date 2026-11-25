# Deployment assumptions and what each topology actually supports

## Evidence of the current deployment shape (from the repository, 2026-11-05)
- No Dockerfile, compose file, reverse-proxy config, process-manager file or hosting config exists.
- `start.bat` starts ONE `uvicorn app.main:app --reload --port 8000` process and `npm run dev`: a single-machine development setup.
- Storage is local: encrypted JSON files under `backend/data/`, account JSON files, and a local SQLite file (`.ratelimit.sqlite3`) for rate limits and
  try-on spend counters. In-process locks protect per-report updates.
- The README says "Dev mode ... Never deploy like this" for the no-payment-keys mode.
**The production plan is not recorded anywhere. It is an open question for the product owner** (below).

## What each topology supports today
| Topology | Supported? | Why |
|---|---|---|
| 1 machine, 1 server process | **Yes - the tested configuration** | all protections verified in this mode |
| 1 machine, several worker processes | **Partly** | rate limits, failed-lookup limits, admin-failure limits and the try-on daily cap/circuit breaker are shared (SQLite; two-process test). **Not safe:** concurrent updates of the SAME report from different processes can lose an update (the per-report lock is per process); the payment-unlock lock is per process |
| Several machines / instances | **No** | report and account files and the SQLite file are local to one machine; each instance would see different data and its own counters. Would need shared storage for reports (database or object store), a shared account store, a central rate-limit/spend store (e.g. Redis or the database), and cross-instance locking |
| Behind a reverse proxy / load balancer | **Only with configuration** | by default the client IP is the TCP peer, i.e. the proxy: **every user would share one set of limits**. Set `TRUST_PROXY=1` ONLY when a trusted proxy overwrites `X-Forwarded-For`; otherwise a client can spoof it and evade per-IP limits |

## Decision
No distributed limiter or shared-state architecture was built: the only evidence of deployment is single-machine, and building a distributed system for a
topology that may never exist would add risk without value. If a multi-instance deployment is planned, the minimum design is: Postgres (or equivalent) for
reports/accounts with row-level locking or optimistic versioning; encrypted object storage for photos; Redis (or Postgres) for rate limits and the spend
counter; the same key management; `TRUST_PROXY` configured at the edge. That is a project, not a setting.

## Recommended safe configuration for a first production deployment (single instance)
`uvicorn` without `--reload`, **one worker**; HTTPS terminated at a reverse proxy with `TRUST_PROXY=1` and the proxy setting `X-Forwarded-For`; `DATA_ENCRYPTION_KEY`
from a secret manager (not a file on the same disk); `ADMIN_TOKEN`, payment keys and `ANTHROPIC_API_KEY` in the environment; `RETENTION_DAYS`, `TRYON_DAILY_CAP`
and `ACCESS_TOKEN_DAYS` set deliberately; regular encrypted off-machine backups of `data/` and of the key (separately).
