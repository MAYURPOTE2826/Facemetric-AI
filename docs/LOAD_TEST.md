# Load and abuse-behaviour test (measured 2026-11-05)

**This is NOT a penetration test. PENETRATION TEST NOT PERFORMED.** It is also not a capacity benchmark: one small machine (4 CPU threads, Intel i3-4005U class,
8 GB RAM), a localhost client that competes with the server for the same CPU, an isolated test server (temporary encrypted data, stubbed paid provider, real
credentials blanked), and a few scenarios.
Reproduce: `cd backend && python -m evals.load_test --image <authorised photo> --out result.json` (the photo is read from where you keep it; it is not stored in the repo).

| Scenario | Requests / concurrent clients | Status codes | Latency s p50 / p95 / max | Throughput req/s | Expected behaviour -> observed |
|---|---|---|---|---|---|
| Concurrent report access (valid token) | 120 / 12 | 200 x 120 | 0.158 / 0.291 / 0.422 | 22.7 | all 200, no limiter hit (120 < 240/min) -> as expected |
| Repeated token failures | 80 / 8 | 404 x 20, 429 x 60 | 0.102 / 0.313 / 0.839 | 20.9 | exactly 20 x 404 then 429 (limit 20 per 10 min) -> exact |
| Repeated failed logins | 40 / 8 | 401 x 10, 429 x 30 | 0.012 / 5.427 / 5.517 | 4.3 | exactly 10 x 401 then 429 (limit 10 per 5 min) -> exact |
| Repeated consent requests | 50 / 8 | 200 x 30, 429 x 20 | 0.157 / 0.359 / 0.450 | 13.9 | exactly 30 x 200 then 429 (limit 30 per 10 min) -> exact |
| Repeated try-on (stubbed provider) | 40 / 8 | 200 x 20, 429 x 20 | 0.103 / 0.278 / 0.325 | 12.2 | 20 x 200 then 429 (per-IP 20/h); **provider calls made: 1** (identical requests share one call; per-report quota and global cap bound the rest) |
| Concurrent analysis, 4 clients (real pipeline) | 4 / 4 | 200 x 4 | 12.385 / 16.004 / 16.004 | 0.2 | all 200 |
| Sequential analysis, 1 client (baseline) | 2 / 1 | 200 x 2 | 3.595 / 3.748 / 3.748 | 0.2 | all 200 |

- **Server memory:** 146.9 MB idle -> 463.6 MB after four concurrent analyses, 464.1 MB at the end (not released). Each concurrent analysis adds roughly 80 MB.
- **Server alive after all scenarios:** yes. No 500 responses and no dropped connections in the final run.
- **Analysis is CPU-bound:** 4 simultaneous analyses took about 12-16 s each against about 3.6 s each when run one at a time - no speed-up from concurrency on this
  machine. Plan roughly one concurrent analysis per CPU thread and about 150 MB + 80 MB per concurrent analysis.
- **Login is CPU-bound by design:** 600,000-iteration password hashing gives about 4 logins/s on this machine; a burst of logins queues (p95 about 5.4 s). The limiter,
  not the hash, bounds an attacker.
- **Limiter behaviour:** every limit was exact under 8-12 concurrent clients, measured after the fixes below.

## Defects this test found (all fixed; each has a regression test that fails on the old code)
1. **Failed-lookup (and admin-failure) limiter overshoot:** 23 failures were allowed against a limit of 20, because the check and the recording were separate steps.
   Now one atomic operation. Tests: `test_concurrency.AtomicLimits`. Verified by re-introducing the old code: the test fails (30 allowed against 20).
2. **HTTP 500 / dropped connections** when several requests updated the same report at once (Windows file-replace collisions, no serialisation of read-modify-write).
   Now retried on transient errors and serialised per report within a process. Tests: `ConcurrentWrites`, `TransientFileErrors`. With the old code 3 of 24 consent
   requests failed.
3. **Try-on spend race:** 8 simultaneous identical requests made 3 provider calls, and the per-report quota could be raced. Now one generation per report at a time;
   consent is re-checked inside the lock. Tests: `ConcurrentTryOn`.

## Limits of these results
- Per-report locks are **per process**. With several worker processes, two updates of the same report can still race (lost update); the rate limiter and spend guard are
  cross-process (SQLite) but report updates are not. Run one worker per data directory, or add a file lock before scaling out.
- Single client machine, localhost, small scenarios; no sustained-load (soak) test, no memory-growth test over time, no network latency.
- Not tested: many distinct users signing up and logging in at once, large uploads, malformed-upload fuzzing, denial of service by slow clients.
