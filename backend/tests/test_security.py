"""Security tests: report access control, enumeration, path traversal, rate limiting, encryption at rest, retention.

Run from backend/:  python -m unittest discover -s tests -v
Uses an isolated temporary data directory and a throw-away encryption key. No real photographs.
"""
import copy
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import accounts, main, recommendations, report, security, store

BASE = json.loads((Path(__file__).resolve().parent.parent / "evals" / "base_analysis.json").read_text(encoding="utf-8"))
SECRET_PHOTO = "UNIQUE_PHOTO_MARKER_9f3a1c"  # must never appear in a file on disk in plaintext


def make_report(owner: dict | None = None, created_at: float | None = None, paid: bool = False):
    """A saved report using the anonymised, image-free base analysis. Returns (result, access_token)."""
    analysis = copy.deepcopy(BASE)
    cands = recommendations.candidates(analysis["metrics"], analysis["skin"], analysis.get("profile"))
    result = {**analysis, "id": security.new_report_id(), "created_at": created_at or int(time.time()),
              "report": report.rule_report(analysis, cands), "report_source": "rules", "paid": paid,
              "_candidates": cands, "_photo": SECRET_PHOTO}
    token = security.issue_access(result)
    if owner:
        accounts.attach(owner, result)
    store.save(result)
    return result, token


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="alex-sec-"))
        self._saved = (store.DATA_DIR, accounts.USERS_DIR, accounts.INDEX, os.environ.get("DATA_ENCRYPTION_KEY"))
        store.DATA_DIR = self.tmp / "data"
        accounts.USERS_DIR = store.DATA_DIR / "users"
        accounts.INDEX = accounts.USERS_DIR / "_index.json"
        store.DATA_DIR.mkdir(parents=True)
        accounts.USERS_DIR.mkdir(parents=True)
        os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        store.reset_cipher()
        security.limiter.reset()
        # Test speed only: a cheap password hash inside the fixtures. Production constants are untouched (restored below).
        self._iters = (accounts.PBKDF2_ITERS, accounts.LEGACY_ITERS)
        accounts.PBKDF2_ITERS, accounts.LEGACY_ITERS = 2_000, 1_000
        self.client = TestClient(main.app)

    def tearDown(self):
        accounts.PBKDF2_ITERS, accounts.LEGACY_ITERS = self._iters
        store.DATA_DIR, accounts.USERS_DIR, accounts.INDEX, key = self._saved
        if key is None:
            os.environ.pop("DATA_ENCRYPTION_KEY", None)
        else:
            os.environ["DATA_ENCRYPTION_KEY"] = key
        store.reset_cipher()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def signup(self, email: str) -> tuple[dict, dict]:
        r = self.client.post("/api/auth/signup", json={"email": email, "password": "correct horse battery"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        return accounts.user_from_auth(f"Bearer {body['token']}"), {"Authorization": f"Bearer {body['token']}"}


class ReportAccess(Base):
    def test_report_id_alone_is_not_enough(self):
        res, _ = make_report()
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}").status_code, 404)

    def test_valid_access_token_opens_the_report(self):
        res, token = make_report()
        r = self.client.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["id"], res["id"])

    def test_response_never_leaks_internal_fields(self):
        res, token = make_report()
        body = self.client.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": token}).json()
        self.assertFalse([k for k in body if k.startswith("_")])
        self.assertNotIn("access_token", body)
        self.assertNotIn(SECRET_PHOTO, json.dumps(body))

    def test_only_the_hash_of_the_token_is_stored(self):
        res, token = make_report()
        stored = store.load(res["id"])
        self.assertNotIn(token, json.dumps(stored))
        self.assertEqual(stored["_access_hash"], security.token_hash(token))

    def test_wrong_token_and_unknown_id_look_identical(self):
        res, _ = make_report()
        wrong = self.client.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": "nope"})
        missing = self.client.get(f"/api/analyses/{security.new_report_id()}", headers={"X-Report-Token": "nope"})
        self.assertEqual((wrong.status_code, wrong.json()), (missing.status_code, missing.json()))

    def test_malformed_ids_are_rejected_as_not_found(self):
        for bad in ("..", "abc", "g" * 32, "%2e%2e%2fsecret", "0" * 31, "0" * 33):
            self.assertEqual(self.client.get(f"/api/analyses/{bad}").status_code, 404, bad)

    def test_ids_are_128_bit_and_unique(self):
        ids = {security.new_report_id() for _ in range(500)}
        self.assertEqual(len(ids), 500)
        self.assertTrue(all(len(i) == 32 and store.valid_id(i) for i in ids))


class Ownership(Base):
    def test_owner_session_opens_their_report_without_a_token(self):
        user, headers = self.signup("a@example.com")
        res, _ = make_report(owner=user)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=headers).status_code, 200)

    def test_other_signed_in_user_cannot_open_it(self):
        owner, _ = self.signup("a@example.com")
        _, other = self.signup("b@example.com")
        res, _ = make_report(owner=owner)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=other).status_code, 404)

    def test_other_user_cannot_claim_someone_elses_report_by_id(self):
        owner, _ = self.signup("a@example.com")
        _, other = self.signup("b@example.com")
        res, _ = make_report(owner=owner)
        self.assertEqual(self.client.post(f"/api/me/analyses/{res['id']}/claim", headers=other).status_code, 404)
        self.assertEqual(store.load(res["id"])["_owner"], owner["id"])

    def test_claim_needs_the_report_credential_not_just_the_id(self):
        _, headers = self.signup("b@example.com")
        res, token = make_report()
        self.assertEqual(self.client.post(f"/api/me/analyses/{res['id']}/claim", headers=headers).status_code, 404)
        ok = self.client.post(f"/api/me/analyses/{res['id']}/claim", headers={**headers, "X-Report-Token": token})
        self.assertEqual(ok.status_code, 200)

    def test_expired_session_is_rejected(self):
        user, headers = self.signup("a@example.com")
        res, _ = make_report(owner=user)
        u = accounts._load(user["id"])
        for s in u["sessions"]:
            s["expires"] = int(time.time()) - 10
        accounts._save(u)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=headers).status_code, 404)

    def test_logged_out_session_is_revoked(self):
        user, headers = self.signup("a@example.com")
        res, _ = make_report(owner=user)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=headers).status_code, 200)
        self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=headers).status_code, 404)


class OtherEndpoints(Base):
    def test_checkout_confirm_tryon_need_a_credential(self):
        res, token = make_report()
        for method, url, body in (("post", f"/api/analyses/{res['id']}/checkout", {"plan": "full"}),
                                  ("post", f"/api/analyses/{res['id']}/confirm", {}),
                                  ("post", f"/api/analyses/{res['id']}/tryon", {"kind": "hair", "style": "x"})):
            self.assertEqual(getattr(self.client, method)(url, json=body).status_code, 404, url)
        # with the token the same confirm call is authorised (then fails on payment, not on access)
        r = self.client.post(f"/api/analyses/{res['id']}/confirm", json={}, headers={"X-Report-Token": token})
        self.assertNotEqual(r.status_code, 404)

    def test_unauthorised_delete_keeps_the_report(self):
        res, token = make_report()
        self.assertEqual(self.client.delete(f"/api/analyses/{res['id']}").status_code, 404)
        self.assertTrue(store.path(res["id"]).exists())

    def test_authorised_delete_removes_the_report_and_its_photos(self):
        user, headers = self.signup("a@example.com")
        res, _ = make_report(owner=user)
        self.assertEqual(self.client.delete(f"/api/analyses/{res['id']}", headers=headers).status_code, 200)
        self.assertFalse(store.path(res["id"]).exists())
        self.assertNotIn(res["id"], accounts._load(user["id"])["analyses"])
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}", headers=headers).status_code, 404)

    def test_there_is_no_unauthenticated_pdf_or_image_route(self):
        """PDF export is the browser print view of the same JSON; there are no raw image/PDF routes to bypass."""
        paths = set(main.app.openapi()["paths"])
        self.assertFalse([p for p in paths if "pdf" in p.lower() or "/image" in p.lower() or "/photo" in p.lower()])
        res, _ = make_report()
        for url in (f"/api/analyses/{res['id']}/pdf", f"/api/analyses/{res['id']}/photo", f"/report/{res['id']}/print"):
            self.assertIn(self.client.get(url).status_code, (404, 405))


class PathTraversal(Base):
    def test_store_path_only_accepts_hex_ids(self):
        for bad in ("../etc/passwd", "..\\..\\windows\\win.ini", "a/b", "", ".", "..", "x" * 12, "A" * 32,
                    "0123456789ab/../0123456789ab"):
            with self.assertRaises(Exception, msg=bad):
                store.path(bad)

    def test_resolved_path_stays_inside_the_data_dir(self):
        p = store.path(security.new_report_id())
        self.assertEqual(p.parent, store.DATA_DIR.resolve())


class RateLimit(Base):
    def test_repeated_failed_lookups_are_throttled(self):
        codes = [self.client.get(f"/api/analyses/{security.new_report_id()}").status_code for _ in range(security.DENIED_LIMIT + 3)]
        self.assertEqual(codes[0], 404)
        self.assertIn(429, codes)
        self.assertEqual(codes[-1], 429)

    def test_login_is_throttled(self):
        codes = [self.client.post("/api/auth/login", json={"email": "x@example.com", "password": "wrong-password"}).status_code
                 for _ in range(14)]
        self.assertIn(429, codes)

    def test_a_throttled_client_with_valid_credentials_is_still_blocked_not_leaked(self):
        res, token = make_report()
        for _ in range(security.DENIED_LIMIT):
            self.client.get(f"/api/analyses/{security.new_report_id()}")
        r = self.client.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": token})
        self.assertEqual(r.status_code, 429)


class EncryptionAtRest(Base):
    def test_file_on_disk_is_encrypted(self):
        res, _ = make_report()
        raw = store.path(res["id"]).read_bytes()
        self.assertTrue(raw.startswith(store.MAGIC))
        self.assertNotIn(SECRET_PHOTO.encode(), raw)
        self.assertNotIn(b'"profile"', raw)
        self.assertEqual(store.load(res["id"])["_photo"], SECRET_PHOTO)  # and it round-trips

    def test_wrong_key_cannot_read_it(self):
        res, _ = make_report()
        os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        store.reset_cipher()
        with self.assertRaises(Exception):
            store.load(res["id"])

    def test_legacy_plaintext_is_readable_and_migrates(self):
        legacy = {"id": "0123456789ab", "created_at": 1, "_photo": SECRET_PHOTO}
        p = store.DATA_DIR / "0123456789ab.json"
        p.write_text(json.dumps(legacy), encoding="utf-8")
        self.assertEqual(store.load("0123456789ab")["_photo"], SECRET_PHOTO)
        self.assertEqual(store.migrate_plaintext(), 1)
        self.assertTrue(p.read_bytes().startswith(store.MAGIC))
        self.assertNotIn(SECRET_PHOTO.encode(), p.read_bytes())

    def test_legacy_report_without_credentials_is_not_publicly_reachable(self):
        store.save({"id": "0123456789ab", "created_at": 1, "metrics": [], "profile": {}})
        self.assertEqual(self.client.get("/api/analyses/0123456789ab").status_code, 404)

    def test_no_partial_files_are_left_after_save(self):
        make_report()
        self.assertEqual(list(store.DATA_DIR.glob(".tmp-*")), [])


class Retention(Base):
    def test_old_anonymous_reports_are_purged_owned_and_recent_are_kept(self):
        owner, _ = self.signup("a@example.com")
        old_anon, _ = make_report(created_at=time.time() - 200 * 86400)
        old_owned, _ = make_report(owner=owner, created_at=time.time() - 200 * 86400)
        recent_anon, _ = make_report()
        removed = store.purge_expired(90)
        self.assertEqual(removed, [old_anon["id"]])
        self.assertTrue(store.path(old_owned["id"]).exists())
        self.assertTrue(store.path(recent_anon["id"]).exists())

    def test_retention_zero_disables_purging(self):
        make_report(created_at=time.time() - 999 * 86400)
        self.assertEqual(store.purge_expired(0), [])


if __name__ == "__main__":
    unittest.main()
