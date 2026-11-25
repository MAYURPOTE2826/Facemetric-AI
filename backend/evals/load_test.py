"""Controlled load / abuse-behaviour test against an ISOLATED test server (never your real data).

    python -m evals.load_test --image <authorised photo> [--out docs/LOAD_TEST.md]

It starts browser-tests/server/run_test_backend.py on port 8101 (temporary encrypted data directory, stubbed paid provider, all real credentials
blanked), drives it with concurrent HTTP clients from this machine, and records response times, status-code histograms, limiter exactness and the
server's memory. It is NOT a penetration test and NOT a capacity benchmark: one small machine, a localhost client that competes with the server
for the same CPU, and a handful of scenarios. Results describe THIS machine only.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PORT = 8101
BASE = f"http://127.0.0.1:{PORT}"
PWD = "correct horse battery staple"


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))] if v else None


def listener_pid(port: int) -> int | None:
    """PID of the process actually LISTENING on the port (the venv python.exe is a launcher stub that spawns the real server)."""
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def rss_mb(pid: int | None) -> float | None:
    if pid is None:
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20).stdout
        return round(int(out.strip().split('","')[-1].replace('"', "").replace(" K", "").replace(",", "").replace(".", "")) / 1024, 1)
    except Exception:  # noqa: BLE001
        return None


def run_parallel(n_requests: int, workers: int, fn):
    """fn(i) -> (status, seconds). Returns summary + raw."""
    results, lock, idx = [], threading.Lock(), iter(range(n_requests))

    def worker():
        with httpx.Client(timeout=300) as c:
            while True:
                with lock:
                    i = next(idx, None)
                if i is None:
                    return
                t = time.perf_counter()
                try:
                    status = fn(c, i)
                except Exception as e:  # noqa: BLE001
                    status = f"EXC:{type(e).__name__}"
                with lock:
                    results.append((status, time.perf_counter() - t))

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker) for _ in range(workers)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0
    lat = [s for _, s in results]
    return {"requests": n_requests, "concurrent_clients": workers, "wall_s": round(wall, 2), "throughput_rps": round(n_requests / wall, 1),
            "status_codes": dict(Counter(str(s) for s, _ in results)), "latency_s": {"p50": round(pct(lat, 50), 3), "p95": round(pct(lat, 95), 3), "max": round(max(lat), 3), "mean": round(statistics.mean(lat), 3)}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--out")
    a = ap.parse_args()
    env = {**os.environ, "PFI_BROWSER_API_PORT": str(PORT)}
    py = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
    srv = subprocess.Popen([str(py), str(ROOT / "browser-tests" / "server" / "run_test_backend.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    res: dict = {"machine": {"cpu_threads": os.cpu_count(), "processor": platform.processor()[:60], "python": platform.python_version()}, "scenarios": {}}
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                    break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        else:
            sys.exit("server did not start")
        spid = listener_pid(PORT)
        res["server_process_pid_measured"] = spid
        res["server_memory_mb_idle"] = rss_mb(spid)
        reset = lambda: httpx.post(f"{BASE}/__test/reset")  # noqa: E731
        sc = res["scenarios"]

        # 1. concurrent report access (valid token): 120 requests, 12 clients
        reset()
        r = httpx.post(f"{BASE}/__test/seed", json={}).json()
        sc["1_concurrent_report_access_valid_token"] = run_parallel(120, 12, lambda c, i: c.get(f"{BASE}/api/analyses/{r['id']}", headers={"X-Report-Token": r["token"]}).status_code)

        # 2. repeated token failures: 80 wrong-token lookups
        reset()
        sc["2_repeated_token_failures"] = run_parallel(80, 8, lambda c, i: c.get(f"{BASE}/api/analyses/{r['id']}", headers={"X-Report-Token": f"wrong{i}"}).status_code)
        sc["2_repeated_token_failures"]["expected"] = "exactly 20 x 404 then 429 (failed-lookup limit 20 per 10 min)"

        # 3. repeated failed authentication: 40 wrong-password logins
        reset()
        httpx.post(f"{BASE}/api/auth/signup", json={"email": "load@example.com", "password": PWD})
        reset()
        sc["3_repeated_failed_logins"] = run_parallel(40, 8, lambda c, i: c.post(f"{BASE}/api/auth/login", json={"email": "load@example.com", "password": f"wrong-password-{i}"}).status_code)
        sc["3_repeated_failed_logins"]["expected"] = "exactly 10 x 401 then 429 (login limit 10 per 5 min)"

        # 4. repeated consent requests: 50
        reset()
        rr = httpx.post(f"{BASE}/__test/seed", json={"paid": True}).json()
        sc["4_repeated_consent_requests"] = run_parallel(50, 8, lambda c, i: c.post(f"{BASE}/api/analyses/{rr['id']}/consent/tryon", headers={"X-Report-Token": rr["token"]}, json={"accept": True, "provider": "fal", "version": "tryon-consent-v1"}).status_code)
        sc["4_repeated_consent_requests"]["expected"] = "exactly 30 x 200 then 429 (consent limit 30 per 10 min)"

        # 5. repeated try-on: consent given, 40 requests; provider is a counting stub
        reset()
        httpx.post(f"{BASE}/api/analyses/{rr['id']}/consent/tryon", headers={"X-Report-Token": rr["token"]}, json={"accept": True, "provider": "fal", "version": "tryon-consent-v1"})
        sc["5_repeated_tryon"] = run_parallel(40, 8, lambda c, i: c.post(f"{BASE}/api/analyses/{rr['id']}/tryon", headers={"X-Report-Token": rr["token"]}, json={"kind": "hair", "style": "Textured quiff"}).status_code)
        calls = httpx.get(f"{BASE}/__test/provider_calls").json()["count"]
        sc["5_repeated_tryon"]["provider_calls_made"] = calls
        sc["5_repeated_tryon"]["expected"] = "per-report quota (6) bounds provider calls; per-IP limit 20/h bounds requests; provider calls must not exceed 6"

        # 6. concurrent analysis (real pipeline): needs an authorised photo
        if a.image and Path(a.image).exists():
            reset()
            data = Path(a.image).read_bytes()
            mem0 = rss_mb(spid)

            def analyse(c, i):
                return c.post(f"{BASE}/api/analyze", files={"front": ("p.jpg", data, "image/jpeg")}, data={"profile": json.dumps({"age": 28, "sex": "male"}), "source": "upload"}).status_code
            sc["6_concurrent_analysis_4_clients"] = run_parallel(4, 4, analyse)
            sc["6_concurrent_analysis_4_clients"]["server_memory_mb_before_after"] = [mem0, rss_mb(spid)]
            reset()
            sc["6b_sequential_analysis_baseline"] = run_parallel(2, 1, analyse)
        else:
            sc["6_concurrent_analysis"] = "NOT RUN - no --image supplied"

        res["server_memory_mb_end"] = rss_mb(spid)
        res["server_alive_after_all_scenarios"] = httpx.get(f"{BASE}/api/health", timeout=10).status_code == 200
    finally:
        srv.terminate()
    txt = json.dumps(res, indent=2)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
