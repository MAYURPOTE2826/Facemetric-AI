"""Concurrency regressions found by the load test (evals/load_test.py):
  * the failed-lookup limiter allowed 23 failures against a limit of 20 (check-then-record race);
  * concurrent consent requests on one report returned HTTP 500 (Windows file-replace collisions, no update serialisation).
Real threads, real HTTP stack (one TestClient per thread). Timing-independent assertions only."""
import os
import threading
import unittest
from collections import Counter
from unittest import mock

from fastapi.testclient import TestClient

from app import admin, consent, main, security, store
from test_security import Base, make_report

IP = ("198.51.100.7", 40000)


def run_threads(n, fn):
    barrier, out = threading.Barrier(n), []

    def work(i):
        c = TestClient(main.app, client=IP)
        barrier.wait()
        out.append(fn(c, i))
    ts = [threading.Thread(target=work, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


class AtomicLimits(Base):
    def test_failed_lookups_are_limited_exactly_even_when_simultaneous(self):
        codes = run_threads(40, lambda c, i: c.get(f"/api/analyses/{security.new_report_id()}").status_code)
        h = Counter(codes)
        self.assertEqual(h[404], security.DENIED_LIMIT)  # was 23 against a limit of 20 before the fix
        self.assertEqual(h[404] + h[429], 40)

    def test_failed_admin_attempts_are_limited_exactly_even_when_simultaneous(self):
        with mock.patch.object(admin, "ADMIN_TOKEN", "the-real-admin-token-value"):
            codes = run_threads(30, lambda c, i: c.get("/api/admin/analyses", headers={"X-Admin-Token": f"guess{i}"}).status_code)
        h = Counter(codes)
        self.assertEqual(h[401], admin.ADMIN_FAIL_LIMIT)
        self.assertEqual(h[401] + h[429], 30)

    def test_failed_logins_are_limited_exactly_even_when_simultaneous(self):
        codes = run_threads(25, lambda c, i: c.post("/api/auth/login", json={"email": "x@example.com", "password": f"wrong-password-{i}"}).status_code)
        self.assertEqual(Counter(codes)[401], 10)


class ConcurrentWrites(Base):
    def setUp(self):
        super().setUp()
        os.environ.update(FAL_KEY="fake", TRYON_PROVIDER="fal")
        os.environ.pop("GEMINI_API_KEY", None)

    def test_concurrent_consent_requests_all_succeed_and_leave_a_valid_report(self):
        res, tok = make_report(paid=True)
        body = {"accept": True, "provider": "fal", "version": consent.VERSION}
        codes = run_threads(24, lambda c, i: c.post(f"/api/analyses/{res['id']}/consent/tryon", json=body, headers={"X-Report-Token": tok}).status_code)
        self.assertEqual(Counter(codes), {200: 24}, "no request may fail with a 500 under concurrency")
        final = store.load(res["id"])
        self.assertTrue(consent.state(final, "fal")["granted"])
        self.assertEqual(final["id"], res["id"])  # still a complete, decryptable document

    def test_concurrent_grant_and_withdraw_never_corrupt_the_report(self):
        res, tok = make_report(paid=True)

        def act(c, i):
            if i % 2:
                return c.delete(f"/api/analyses/{res['id']}/consent/tryon", headers={"X-Report-Token": tok}).status_code
            return c.post(f"/api/analyses/{res['id']}/consent/tryon", json={"accept": True, "provider": "fal", "version": consent.VERSION}, headers={"X-Report-Token": tok}).status_code
        codes = run_threads(20, act)
        self.assertEqual(set(codes), {200})
        self.assertEqual(store.load(res["id"])["id"], res["id"])

    def test_concurrent_token_rotations_leave_exactly_one_valid_token(self):
        res, tok = make_report()
        tokens = run_threads(12, lambda c, i: c.post(f"/api/analyses/{res['id']}/token/rotate", headers={"X-Report-Token": tok}))
        ok = [t for t in tokens if t.status_code == 200]
        self.assertTrue(ok)
        self.assertTrue(all(t.status_code in (200, 404) for t in tokens))  # later requests may find the old token already dead
        c = TestClient(main.app, client=("203.0.113.9", 1))
        valid = [t.json()["access_token"] for t in ok if c.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": t.json()["access_token"]}).status_code == 200]
        self.assertEqual(len(valid), 1)

    def test_store_update_lock_prevents_lost_updates_between_threads(self):
        res, _ = make_report()
        n = 40

        def bump():
            with store.lock(res["id"]):
                r = store.load(res["id"])
                r["counter"] = r.get("counter", 0) + 1
                store.save(r)
        ts = [threading.Thread(target=bump) for _ in range(n)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(store.load(res["id"])["counter"], n)


class TransientFileErrors(Base):
    def test_save_retries_a_transient_permission_error_then_succeeds(self):
        res, _ = make_report()
        real, calls = os.replace, {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise PermissionError("sharing violation")
            return real(a, b)
        with mock.patch.object(store.os, "replace", flaky):
            res["x"] = 1
            store.save(res)
        self.assertEqual(calls["n"], 4)
        self.assertEqual(store.load(res["id"])["x"], 1)
        self.assertEqual(list(store.DATA_DIR.glob(".tmp-*")), [])

    def test_a_permanent_permission_error_is_not_swallowed(self):
        res, _ = make_report()
        with mock.patch.object(store.os, "replace", side_effect=PermissionError("denied")), mock.patch.object(store.time, "sleep"):
            with self.assertRaises(PermissionError):
                store.save(res)
        self.assertEqual(list(store.DATA_DIR.glob(".tmp-*")), [])

    def test_load_retries_a_transient_permission_error(self):
        res, _ = make_report()
        real, calls = store.Path.read_bytes, {"n": 0}

        def flaky(self_):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("busy")
            return real(self_)
        with mock.patch.object(store.Path, "read_bytes", flaky):
            self.assertEqual(store.load(res["id"])["id"], res["id"])

    def test_a_report_deleted_mid_read_is_a_404_not_a_500(self):
        res, _ = make_report()
        with mock.patch.object(store.Path, "read_bytes", side_effect=FileNotFoundError):
            with self.assertRaises(store.HTTPException) as cm:
                store.load(res["id"])
        self.assertEqual(cm.exception.status_code, 404)


class ConcurrentTryOn(Base):
    """Found by the load test: 8 simultaneous identical try-on requests made 3 provider calls (cache miss race) and the per-report
    quota could be raced. Generation is now serialised per report."""

    def setUp(self):
        super().setUp()
        from app import spend_guard, tryon
        self.tryon, self.spend = tryon, spend_guard
        self.env = {k: os.environ.get(k) for k in ("FAL_KEY", "TRYON_PROVIDER", "GEMINI_API_KEY")}
        os.environ.update(FAL_KEY="fake", TRYON_PROVIDER="fal")
        os.environ.pop("GEMINI_API_KEY", None)
        self.calls = []

        def stub(photo, kind, style, *, consented=False):
            if not consented:
                raise tryon.ConsentRequired("no")
            import time
            time.sleep(0.15)  # long enough that concurrent requests overlap
            self.calls.append(style)
            return {"image": "AAAA", "identity": 0.9, "provider": "fal", "kind": kind, "style": style}
        self.patch = mock.patch.object(tryon, "generate", side_effect=stub)
        self.patch.start()
        self.saved_quota = tryon.QUOTA

    def tearDown(self):
        self.patch.stop()
        self.tryon.QUOTA = self.saved_quota
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def report(self, styles=("Textured quiff", "Side part", "Crop")):
        res, tok = make_report(paid=True)
        res["style"] = {"hairstyles": list(styles), "beard": [], "glasses": []}
        consent.grant(res, "fal")
        store.save(res)
        return res["id"], {"X-Report-Token": tok}

    def test_identical_simultaneous_requests_share_one_provider_call(self):
        rid, hdr = self.report()
        codes = run_threads(8, lambda c, i: c.post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": "Textured quiff"}, headers=hdr).status_code)
        self.assertEqual(Counter(codes), {200: 8})
        self.assertEqual(len(self.calls), 1)  # was 3
        self.assertEqual(self.spend.usage()["used_24h"], 1)

    def test_the_per_report_quota_cannot_be_raced(self):
        self.tryon.QUOTA = 2
        rid, hdr = self.report()
        styles = ["Textured quiff", "Side part", "Crop"]
        codes = run_threads(3, lambda c, i: c.post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": styles[i]}, headers=hdr).status_code)
        self.assertEqual(sorted(codes), [200, 200, 429])
        self.assertEqual(len(self.calls), 2)  # the quota held: never a third provider call
        self.assertEqual(len(store.load(rid)["tryons"]), 2)

    def test_consent_withdrawn_while_a_request_waits_is_honoured(self):
        rid, hdr = self.report()
        import threading as th
        started, release = th.Event(), th.Event()
        original = self.patch.target.generate

        def slow(photo, kind, style, *, consented=False):
            started.set()
            release.wait(5)
            self.calls.append(style)
            return {"image": "AAAA", "identity": 0.9, "provider": "fal", "kind": kind, "style": style}
        with mock.patch.object(self.tryon, "generate", side_effect=slow):
            results = {}

            def first():
                results["a"] = TestClient(main.app, client=IP).post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": "Textured quiff"}, headers=hdr).status_code

            def second():
                started.wait(5)
                results["b"] = TestClient(main.app, client=IP).post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": "Side part"}, headers=hdr).status_code

            t1, t2 = th.Thread(target=first), th.Thread(target=second)
            t1.start(); t2.start()
            started.wait(5)
            TestClient(main.app, client=IP).delete(f"/api/analyses/{rid}/consent/tryon", headers=hdr)  # withdraw while #2 waits on the lock
            release.set()
            t1.join(); t2.join()
        self.assertEqual(results["a"], 200)
        self.assertEqual(results["b"], 403)  # the waiting request re-checked consent inside the lock
        self.assertEqual(self.calls, ["Textured quiff"])


if __name__ == "__main__":
    unittest.main()
