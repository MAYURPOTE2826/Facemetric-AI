"""Persistent / shared rate limiting and the global try-on spend guard.

Honest scope: counters are shared by processes on ONE machine and survive restarts. Nothing here (or anywhere in the
project) is distributed across machines.
"""
import json
import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import consent, main, security, spend_guard, store, tryon
from test_security import Base, make_report

BACKEND = Path(__file__).resolve().parent.parent


class PersistentLimiter(Base):
    def test_counts_survive_a_restart(self):
        for _ in range(4):
            security.limiter.hit("restart:k", 5, 600)
        fresh = security.RateLimiter()  # a new object = a restarted process reading the same file
        self.assertEqual(fresh.count("restart:k", 600), 4)
        fresh.hit("restart:k", 5, 600)
        with self.assertRaises(Exception) as cm:
            fresh.hit("restart:k", 5, 600)
        self.assertEqual(cm.exception.status_code, 429)

    def test_window_expires(self):
        lim = security.limiter
        lim.hit("win:k", 1, 1)
        with self.assertRaises(Exception):
            lim.hit("win:k", 1, 1)
        time.sleep(1.2)
        lim.hit("win:k", 1, 1)  # allowed again

    def test_two_worker_processes_share_one_limit(self):
        """Two real OS processes hammer the same key; together they get exactly `limit` successes (a per-process
        limiter would let each process have its own `limit`)."""
        code = textwrap.dedent("""
            import os, sys
            sys.path.insert(0, r"%s")
            from fastapi import HTTPException
            from app import security
            ok = 0
            for _ in range(12):
                try:
                    security.limiter.hit("shared:k", 10, 600); ok += 1
                except HTTPException as e:
                    assert e.status_code == 429
            print(ok)
        """ % BACKEND)
        env = {**os.environ, "DATA_DIR": str(store.DATA_DIR)}
        procs = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        outs = [p.communicate(timeout=120) for p in procs]
        for p, (o, e) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, e[-400:])
        successes = sum(int(o.strip().splitlines()[-1]) for o, _ in outs)
        self.assertEqual(successes, 10)

    def test_concurrent_hits_in_one_process_never_exceed_the_limit(self):
        import threading
        results = []

        def work():
            try:
                security.limiter.hit("threads:k", 7, 600)
                results.append(1)
            except Exception:
                results.append(0)

        ts = [threading.Thread(target=work) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sum(results), 7)

    def test_a_hit_that_is_refused_is_not_recorded(self):
        for _ in range(3):
            security.limiter.hit("norecord:k", 3, 600)
        for _ in range(5):
            with self.assertRaises(Exception):
                security.limiter.hit("norecord:k", 3, 600)
        self.assertEqual(security.limiter.count("norecord:k", 600), 3)

    def test_rate_limit_dependencies_expose_their_parameters_for_the_endpoint_matrix(self):
        dep = security.rate_limit("x", 3, 60)
        self.assertEqual(dep.rate_limit, ("x", 3, 60))


class SpendGuard(Base):
    def setUp(self):
        super().setUp()
        self.saved = (spend_guard.DAILY_CAP, spend_guard.BREAKER_FAILS, spend_guard.BREAKER_PAUSE)
        self.env = {k: os.environ.get(k) for k in ("FAL_KEY", "TRYON_PROVIDER", "GEMINI_API_KEY")}
        os.environ.update(FAL_KEY="fake", TRYON_PROVIDER="fal")
        os.environ.pop("GEMINI_API_KEY", None)
        self.calls = []

        def stub(photo, kind, style, *, consented=False):
            if not consented:
                raise tryon.ConsentRequired("no")
            self.calls.append(1)
            return {"image": "AAAA", "identity": 0.9, "provider": "fal", "kind": kind, "style": style}
        self.stub = mock.patch.object(tryon, "generate", side_effect=stub)
        self.gen = self.stub.start()

    def tearDown(self):
        self.stub.stop()
        spend_guard.DAILY_CAP, spend_guard.BREAKER_FAILS, spend_guard.BREAKER_PAUSE = self.saved
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def report(self):
        res, tok = make_report(paid=True)
        res["style"] = {"hairstyles": ["Textured quiff", "Side part", "Crop"], "beard": [], "glasses": []}
        consent.grant(res, "fal")
        store.save(res)
        return res["id"], {"X-Report-Token": tok}

    def call(self, client, rid, hdr, style="Textured quiff"):
        return client.post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": style}, headers=hdr)

    def test_daily_cap_is_global_and_cannot_be_bypassed_by_rotating_ips_or_reports(self):
        spend_guard.DAILY_CAP = 3
        codes = []
        for i in range(6):  # a different client IP AND a different report each time
            rid, hdr = self.report()
            c = TestClient(main.app, client=(f"203.0.113.{i + 1}", 50000 + i))
            codes.append(self.call(c, rid, hdr).status_code)
        self.assertEqual(codes, [200, 200, 200, 429, 429, 429])
        self.assertEqual(len(self.calls), 3)  # the provider was reached exactly 3 times
        body = self.call(TestClient(main.app, client=("203.0.113.99", 1)), *self.report()).json()
        self.assertEqual(body["detail"]["code"], "tryon_capacity")

    def test_cap_counts_attempts_even_when_they_fail_or_are_rejected(self):
        spend_guard.DAILY_CAP = 3
        self.gen.side_effect = tryon.TryOnError("The generated image didn't look enough like you")
        for i in range(3):
            rid, hdr = self.report()
            self.assertEqual(self.call(TestClient(main.app, client=(f"198.51.100.{i + 1}", 1)), rid, hdr).status_code, 422)
        self.gen.side_effect = None
        rid, hdr = self.report()
        self.assertEqual(self.call(TestClient(main.app), rid, hdr).status_code, 429)  # a rejected attempt was still paid for

    def test_breaker_opens_after_consecutive_provider_failures_and_stops_calling_the_provider(self):
        spend_guard.DAILY_CAP, spend_guard.BREAKER_FAILS = 100, 5
        self.gen.side_effect = tryon.ProviderError("fal.ai error 500")
        codes = []
        for i in range(8):
            rid, hdr = self.report()
            codes.append(self.call(TestClient(main.app, client=(f"192.0.2.{i + 1}", 1)), rid, hdr).status_code)
        self.assertEqual(codes[:5], [502] * 5)
        self.assertEqual(codes[5:], [503] * 3)
        self.assertEqual(self.gen.call_count, 5)  # nothing was sent once the breaker opened
        rid, hdr = self.report()
        self.assertEqual(self.call(TestClient(main.app), rid, hdr).json()["detail"]["code"], "tryon_paused")

    def test_breaker_closes_after_the_pause_and_after_a_success(self):
        spend_guard.BREAKER_FAILS, spend_guard.BREAKER_PAUSE = 3, 600
        t0 = time.time()
        for i in range(3):
            spend_guard.finish(spend_guard.reserve(now=t0 + i), "provider_failure")
        with self.assertRaises(Exception) as cm:
            spend_guard.reserve(now=t0 + 10)
        self.assertEqual(cm.exception.status_code, 503)
        ticket = spend_guard.reserve(now=t0 + 700)  # pause elapsed: one probe call is allowed
        spend_guard.finish(ticket, "ok")
        spend_guard.reserve(now=t0 + 701)  # a success closed the breaker

    def test_quality_rejections_do_not_trip_the_breaker(self):
        spend_guard.DAILY_CAP, spend_guard.BREAKER_FAILS = 100, 3
        for _ in range(10):
            spend_guard.finish(spend_guard.reserve(), "rejected")
        spend_guard.reserve()  # still allowed

    def test_old_calls_fall_out_of_the_24h_window(self):
        spend_guard.DAILY_CAP = 2
        now = time.time()
        spend_guard.reserve(now=now - 90000)
        spend_guard.reserve(now=now - 90000)
        spend_guard.reserve(now=now)  # the two old ones no longer count
        self.assertEqual(spend_guard.usage(now)["used_24h"], 1)

    def test_usage_survives_a_restart_and_is_shared_with_other_processes(self):
        spend_guard.reserve()
        spend_guard.reserve()
        code = ("import sys; sys.path.insert(0, r'%s'); from app import spend_guard; print(spend_guard.usage()['used_24h'])" % BACKEND)
        out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "DATA_DIR": str(store.DATA_DIR)},
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "2")

    def test_requests_refused_before_the_provider_cost_nothing(self):
        rid, hdr = self.report()
        os.environ["FAL_KEY"] = "fake"
        r = make_report(paid=True)  # no consent
        no_consent = TestClient(main.app).post(f"/api/analyses/{r[0]['id']}/tryon", json={"kind": "hair", "style": "x"}, headers={"X-Report-Token": r[1]})
        self.assertEqual(no_consent.status_code, 403)
        self.assertEqual(TestClient(main.app).post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": "NOT-RECOMMENDED"}, headers=hdr).status_code, 400)
        self.assertEqual(spend_guard.usage()["used_24h"], 0)

    def test_a_crash_mid_call_still_counts(self):
        spend_guard.DAILY_CAP = 100
        rid, hdr = self.report()
        self.gen.side_effect = RuntimeError("unexpected crash inside the provider call")
        with self.assertRaises(RuntimeError):
            self.call(TestClient(main.app, raise_server_exceptions=True), rid, hdr)
        self.assertEqual(spend_guard.usage()["used_24h"], 1)  # reserved before the call, so the spend is not hidden


if __name__ == "__main__":
    unittest.main()
