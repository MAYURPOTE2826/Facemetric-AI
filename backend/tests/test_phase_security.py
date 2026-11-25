"""Key safety, owner flows, try-on consent, account data and rate limiting.

Run from backend/:  python -m unittest discover -s tests -v
Isolated temp directories, throw-away keys, no network (the external image providers are mocked and asserted
NOT to be called when they must not be). No real photographs or passwords.
"""
import json
import logging
import os
import re
import time
import unittest
from pathlib import Path
from unittest import mock

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import accounts, admin, consent, main, security, store, tryon
from test_security import Base, make_report

BACKEND = Path(__file__).resolve().parent.parent
PWD = "correct horse battery staple"


# --------------------------------------------------------------------------- Part 1: key safety
class KeySafety(Base):
    def test_corrupted_key_is_a_safe_failure_and_never_echoed(self):
        os.environ["DATA_ENCRYPTION_KEY"] = "this-is-not-a-valid-fernet-key-SECRETMARKER"
        store.reset_cipher()
        with self.assertRaises(RuntimeError) as cm:
            store._cipher()
        self.assertNotIn("SECRETMARKER", str(cm.exception))
        with self.assertRaises(RuntimeError):
            store.startup_check()

    def test_truncated_key_file_is_a_safe_failure(self):
        os.environ.pop("DATA_ENCRYPTION_KEY", None)
        kf = self.tmp / "k" / "data.key"
        kf.parent.mkdir()
        kf.write_bytes(Fernet.generate_key()[:20])
        os.environ["DATA_KEY_FILE"] = str(kf)
        store.reset_cipher()
        with self.assertRaises(RuntimeError):
            store.startup_check()
        self.assertEqual(len(kf.read_bytes()), 20)  # untouched, not "repaired" or replaced

    def test_missing_key_with_encrypted_reports_stops_startup(self):
        os.environ.pop("DATA_ENCRYPTION_KEY", None)
        os.environ["DATA_KEY_FILE"] = str(self.tmp / "keys" / "data.key")
        store.reset_cipher()
        make_report.__globals__["store"].DATA_DIR  # (same module object)
        store.save({"id": "0123456789ab", "created_at": 1})  # generates a key + encrypts
        (self.tmp / "keys" / "data.key").unlink()
        store.reset_cipher()
        with self.assertRaises(RuntimeError) as cm:
            store.startup_check()
        self.assertIn("Refusing to generate a new key", str(cm.exception))
        self.assertFalse((self.tmp / "keys" / "data.key").exists())

    def test_wrong_key_stops_startup(self):
        make_report()
        os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        store.reset_cipher()
        with self.assertRaises(RuntimeError) as cm:
            store.startup_check()
        self.assertIn("does not decrypt", str(cm.exception))

    def test_the_application_itself_refuses_to_start_with_a_bad_key(self):
        make_report()
        os.environ["DATA_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        store.reset_cipher()
        with self.assertRaises(RuntimeError):
            with TestClient(main.app):  # entering the context runs the startup hooks
                pass

    def test_application_starts_with_the_right_key_and_reports_only_non_secret_facts(self):
        make_report()
        info = store.startup_check()
        self.assertEqual(info["encrypted_reports"], 1)
        self.assertNotIn(os.environ["DATA_ENCRYPTION_KEY"], json.dumps(info))
        with TestClient(main.app) as c:
            self.assertEqual(c.get("/api/health").status_code, 200)

    def test_key_never_appears_in_logs(self):
        os.environ.pop("DATA_ENCRYPTION_KEY", None)
        os.environ["DATA_KEY_FILE"] = str(self.tmp / "gen" / "data.key")
        store.reset_cipher()
        records = []

        class H(logging.Handler):
            def emit(self, r):
                records.append(r.getMessage())

        root = logging.getLogger()
        h, old = H(level=logging.DEBUG), root.level
        root.addHandler(h)
        root.setLevel(logging.DEBUG)
        try:
            make_report()                       # generates the key file and saves
            store.migrate()
            store.startup_check()
            store.load(next(p.stem for p in store.DATA_DIR.glob("*.json")))
        finally:
            root.removeHandler(h)
            root.setLevel(old)
        key = (self.tmp / "gen" / "data.key").read_bytes().decode().strip()
        self.assertTrue(records, "expected at least the key-generation warning to be logged")
        self.assertFalse([r for r in records if key in r or key[:12] in r])

    def test_no_source_line_passes_a_key_to_logging_or_print(self):
        bad = []
        for f in (BACKEND / "app").glob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"(log|logger|logging)\.\w+\(|print\(", line) and re.search(r"\b(key|_key\(\)|token_hash)\b\s*[,)]", line):
                    bad.append(f"{f.name}:{n}")
        self.assertEqual(bad, [])

    def test_key_is_never_in_any_api_response(self):
        secret = os.environ["DATA_ENCRYPTION_KEY"]
        res, token = make_report(paid=True)
        h = {"X-Report-Token": token}
        seen = [self.client.get("/api/health"), self.client.get(f"/api/analyses/{res['id']}", headers=h),
                self.client.get(f"/api/analyses/{res['id']}"), self.client.post(f"/api/analyses/{res['id']}/confirm", json={}),
                self.client.get("/api/analyses/not-an-id"), self.client.get("/openapi.json"),
                self.client.post("/api/auth/login", json={"email": "x@example.com", "password": "nope-nope-nope"})]
        for r in seen:
            self.assertNotIn(secret, r.text)
            self.assertNotIn(secret, json.dumps(dict(r.headers)))

    def test_key_file_default_is_outside_the_project_and_not_in_a_repo_file(self):
        os.environ.pop("DATA_KEY_FILE", None)
        self.assertNotIn(BACKEND.resolve(), store.key_file_path().resolve().parents)
        ours = (list((BACKEND / "app").glob("*.py")) + list((BACKEND / "tests").glob("*.py")) + list((BACKEND / "evals").glob("*.py"))
                + list(BACKEND.glob("*.example")) + list(BACKEND.glob(".env*")) + list(BACKEND.parent.glob("docs/*.md")))
        self.assertTrue(ours)
        for f in ours:  # a Fernet key is exactly 44 chars: 43 url-safe base64 chars + "="
            self.assertIsNone(re.search(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}=(?![A-Za-z0-9_=-])", f.read_text(encoding="utf-8", errors="ignore")),
                              f"possible Fernet key in {f.name}")
        self.assertFalse((BACKEND / ".secrets").exists())

    def test_migration_command_loads_the_same_settings_as_the_application(self):
        with mock.patch("dotenv.load_dotenv") as ld:
            store._cli(["--migrate", "--dry-run"])
        ld.assert_called_once_with(BACKEND / ".env")
        # and the application loads backend/.env too (python-dotenv searches upward from app/main.py)
        self.assertIn("load_dotenv()", (BACKEND / "app" / "main.py").read_text(encoding="utf-8"))

    def test_decryption_survives_a_restart(self):
        res, _ = make_report()
        store.reset_cipher()
        self.assertEqual(store.load(res["id"])["id"], res["id"])


# --------------------------------------------------------------------------- Part 2: owner flows (API level)
class OwnerFlows(Base):
    def login(self, email):
        self.client.post("/api/auth/signup", json={"email": email, "password": PWD})
        r = self.client.post("/api/auth/login", json={"email": email, "password": PWD})
        self.assertEqual(r.status_code, 200)
        t = r.json()["token"]
        return accounts.user_from_auth(f"Bearer {t}"), {"Authorization": f"Bearer {t}"}

    def test_login_listing_selection_retrieval_flow(self):
        a, ha = self.login("a@example.com")
        b, hb = self.login("b@example.com")
        ra, _ = make_report(owner=a)
        rb, _ = make_report(owner=b)
        prog = self.client.get("/api/me/progress", headers=ha)
        self.assertEqual(prog.status_code, 200)
        self.assertIn(ra["id"], prog.text)
        self.assertNotIn(rb["id"], prog.text)
        self.assertEqual(self.client.get(f"/api/analyses/{ra['id']}", headers=ha).status_code, 200)

    def test_wrong_account_gets_exactly_the_same_response_as_a_nonexistent_report(self):
        a, ha = self.login("a@example.com")
        _, hb = self.login("b@example.com")
        ra, _ = make_report(owner=a)
        wrong = self.client.get(f"/api/analyses/{ra['id']}", headers=hb)
        ghost = self.client.get(f"/api/analyses/{security.new_report_id()}", headers=hb)
        self.assertEqual((wrong.status_code, wrong.json()), (ghost.status_code, ghost.json()))
        self.assertEqual(wrong.headers.get("content-length"), ghost.headers.get("content-length"))

    def test_every_report_route_denies_the_wrong_account_identically(self):
        a, ha = self.login("a@example.com")
        _, hb = self.login("b@example.com")
        ra, _ = make_report(owner=a, paid=True)
        gid = security.new_report_id()
        calls = [("get", "", None), ("delete", "", None), ("post", "/checkout", {"plan": "full"}), ("post", "/confirm", {}),
                 ("post", "/tryon", {"kind": "hair", "style": "x"}), ("post", "/consent/tryon", {"accept": True, "provider": "fal", "version": "v"}),
                 ("delete", "/consent/tryon", None)]
        for method, suffix, body in calls:
            security.limiter.reset()
            real = getattr(self.client, method)(f"/api/analyses/{ra['id']}{suffix}", headers=hb, **({"json": body} if body is not None else {}))
            ghost = getattr(self.client, method)(f"/api/analyses/{gid}{suffix}", headers=hb, **({"json": body} if body is not None else {}))
            self.assertEqual((real.status_code, real.json()), (ghost.status_code, ghost.json()), f"{method} {suffix}")
            self.assertEqual(real.status_code, 404)
        self.assertEqual(self.client.post(f"/api/me/analyses/{ra['id']}/claim", headers=hb).status_code, 404)
        self.assertTrue(store.path(ra["id"]).exists())

    def test_other_account_cannot_delete_but_the_owner_can(self):
        a, ha = self.login("a@example.com")
        _, hb = self.login("b@example.com")
        ra, _ = make_report(owner=a)
        self.assertEqual(self.client.delete(f"/api/analyses/{ra['id']}", headers=hb).status_code, 404)
        self.assertTrue(store.path(ra["id"]).exists())
        self.assertEqual(self.client.delete(f"/api/analyses/{ra['id']}", headers=ha).status_code, 200)
        self.assertFalse(store.path(ra["id"]).exists())

    def test_session_revoked_by_logout_and_expired_are_denied_on_every_route(self):
        a, ha = self.login("a@example.com")
        ra, _ = make_report(owner=a)
        self.client.post("/api/auth/logout", headers=ha)
        for method, suffix in (("get", ""), ("delete", ""), ("post", "/confirm")):
            r = getattr(self.client, method)(f"/api/analyses/{ra['id']}{suffix}", headers=ha, **({"json": {}} if method == "post" else {}))
            self.assertEqual(r.status_code, 404, f"{method} {suffix}")

    def test_no_report_route_works_without_a_credential(self):
        ra, _ = make_report(paid=True)
        for method, suffix, body in (("get", "", None), ("delete", "", None), ("post", "/checkout", {"plan": "full"}),
                                     ("post", "/confirm", {}), ("post", "/tryon", {"kind": "hair", "style": "x"}),
                                     ("post", "/consent/tryon", {"accept": True, "provider": "fal", "version": "v"})):
            security.limiter.reset()
            r = getattr(self.client, method)(f"/api/analyses/{ra['id']}{suffix}", **({"json": body} if body is not None else {}))
            self.assertEqual(r.status_code, 404, f"{method} {suffix}")

    def test_frontend_sends_credentials_on_every_report_request(self):
        """STATIC check of the frontend source, not a browser test: every fetch to a report route builds its headers
        with reportHeaders(); the analyze page stores the access token."""
        src = BACKEND.parent / "frontend" / "src"
        missing = []
        for f in src.rglob("*.tsx"):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"fetch\(\s*`(/api/(?:analyses|me/analyses)/[^`]*)`(.{0,260})", text, re.S):
                if "reportHeaders(" not in m.group(2):
                    missing.append(f"{f.name}: {m.group(1)}")
        self.assertEqual(missing, [])
        self.assertIn("saveReportToken(data.id, data.access_token)", (src / "app" / "analyze" / "page.tsx").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- Part 4: try-on consent
def paid_report_with_styles(owner=None):
    res, token = make_report(owner=owner, paid=True)
    res["style"] = {"hairstyles": ["Textured quiff"], "beard": [], "glasses": []}
    store.save(res)
    return res, token


class TryOnConsent(Base):
    def setUp(self):
        super().setUp()
        self.env = {k: os.environ.get(k) for k in ("FAL_KEY", "GEMINI_API_KEY", "TRYON_PROVIDER")}
        os.environ.update(FAL_KEY="fake-not-used", TRYON_PROVIDER="fal")
        os.environ.pop("GEMINI_API_KEY", None)
        self.net = [mock.patch.object(tryon, "_fal", side_effect=AssertionError("PHOTO SENT TO fal WITHOUT CONSENT")),
                    mock.patch.object(tryon, "_gemini", side_effect=AssertionError("PHOTO SENT TO gemini WITHOUT CONSENT"))]
        self.fal, self.gem = (p.start() for p in self.net)

    def tearDown(self):
        for p in self.net:
            p.stop()
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        super().tearDown()

    def post_tryon(self, rid, token, **kw):
        return self.client.post(f"/api/analyses/{rid}/tryon", json={"kind": "hair", "style": "Textured quiff", **kw},
                                headers={"X-Report-Token": token})

    def accept(self, rid, token, provider="fal", version=consent.VERSION):
        return self.client.post(f"/api/analyses/{rid}/consent/tryon", headers={"X-Report-Token": token},
                                json={"accept": True, "provider": provider, "version": version})

    def test_try_on_without_consent_is_refused_and_nothing_is_sent(self):
        res, tok = paid_report_with_styles()
        r = self.post_tryon(res["id"], tok)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "consent_required")
        self.fal.assert_not_called(); self.gem.assert_not_called()
        self.assertEqual(store.load(res["id"]).get("tryons") or {}, {})  # no quota spent

    def test_direct_api_bypass_attempts_do_not_work(self):
        res, tok = paid_report_with_styles()
        for kw in ({"consent": True}, {"consented": True}, {"accept": True}, {"provider": "fal"}):
            self.assertEqual(self.post_tryon(res["id"], tok, **kw).status_code, 403, kw)
        for hdr in ({"X-Consent": "yes"}, {"X-Tryon-Consent": "true"}, {"Cookie": "consent=1"}):
            r = self.client.post(f"/api/analyses/{res['id']}/tryon", json={"kind": "hair", "style": "Textured quiff"},
                                 headers={"X-Report-Token": tok, **hdr})
            self.assertEqual(r.status_code, 403, hdr)
        self.assertEqual(self.client.get(f"/api/analyses/{res['id']}/consent/tryon", headers={"X-Report-Token": tok}).status_code, 405)
        self.fal.assert_not_called(); self.gem.assert_not_called()

    def test_consent_for_one_report_does_not_cover_another(self):
        r1, t1 = paid_report_with_styles()
        r2, t2 = paid_report_with_styles()
        self.assertEqual(self.accept(r1["id"], t1).status_code, 200)
        self.assertEqual(self.post_tryon(r2["id"], t2).status_code, 403)

    def test_try_on_with_consent_goes_through_with_the_consent_flag(self):
        res, tok = paid_report_with_styles()
        self.assertTrue(self.accept(res["id"], tok).json()["granted"])
        stub = {"image": "AAAA", "identity": 0.9, "provider": "fal", "kind": "hair", "style": "Textured quiff"}
        with mock.patch.object(tryon, "generate", return_value=stub) as gen:
            r = self.post_tryon(res["id"], tok)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(gen.call_args.kwargs["consented"])

    def test_generate_itself_refuses_without_the_flag_and_never_reaches_the_network(self):
        with mock.patch("httpx.post", side_effect=AssertionError("network")):
            with self.assertRaises(tryon.ConsentRequired):
                tryon.generate("AAAA", "hair", "x")
            with self.assertRaises(tryon.ConsentRequired):
                tryon.generate("AAAA", "hair", "x", consented=False)

    def test_expired_consent_is_refused(self):
        res, tok = paid_report_with_styles()
        self.accept(res["id"], tok)
        r = store.load(res["id"])
        r["_consent"]["tryon_external"]["expires_at"] = int(time.time()) - 5
        store.save(r)
        self.assertEqual(self.post_tryon(res["id"], tok).status_code, 403)
        self.fal.assert_not_called()

    def test_withdrawn_consent_is_refused_again_via_post_and_delete(self):
        res, tok = paid_report_with_styles()
        for revoke in (lambda: self.client.post(f"/api/analyses/{res['id']}/consent/tryon", headers={"X-Report-Token": tok},
                                                json={"accept": False, "provider": "fal", "version": consent.VERSION}),
                       lambda: self.client.delete(f"/api/analyses/{res['id']}/consent/tryon", headers={"X-Report-Token": tok})):
            self.accept(res["id"], tok)
            self.assertEqual(revoke().json()["granted"], False)
            self.assertEqual(self.post_tryon(res["id"], tok).status_code, 403)
        self.fal.assert_not_called()

    def test_consent_does_not_carry_over_to_a_different_provider(self):
        res, tok = paid_report_with_styles()
        self.accept(res["id"], tok)  # consented to fal
        os.environ.update(GEMINI_API_KEY="fake", TRYON_PROVIDER="gemini")
        self.assertEqual(self.post_tryon(res["id"], tok).status_code, 403)
        self.gem.assert_not_called()

    def test_consent_request_must_name_the_current_provider_and_text_version(self):
        res, tok = paid_report_with_styles()
        self.assertEqual(self.accept(res["id"], tok, provider="gemini").status_code, 409)
        self.assertEqual(self.accept(res["id"], tok, version="tryon-consent-v0").status_code, 409)
        self.assertEqual(self.post_tryon(res["id"], tok).status_code, 403)

    def test_unauthorised_caller_cannot_consent_on_the_owners_behalf(self):
        res, _ = paid_report_with_styles()
        r = self.client.post(f"/api/analyses/{res['id']}/consent/tryon", json={"accept": True, "provider": "fal", "version": consent.VERSION})
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("_consent", store.load(res["id"]))

    def test_unpaid_report_is_refused_before_consent_matters(self):
        res, tok = make_report(paid=False)
        self.assertEqual(self.post_tryon(res["id"], tok).status_code, 402)

    def test_stored_consent_record_is_minimal_and_holds_no_image(self):
        res, tok = paid_report_with_styles()
        self.accept(res["id"], tok)
        rec = store.load(res["id"])["_consent"]["tryon_external"]
        self.assertEqual(set(rec), {"version", "provider", "granted_at", "expires_at"})
        self.assertNotIn("photo", json.dumps(rec).lower())
        self.assertEqual(rec["expires_at"] - rec["granted_at"], consent.VALID_DAYS * 86400)

    def test_disclosure_names_the_provider_and_states_what_is_unverified(self):
        res, tok = paid_report_with_styles()
        body = self.client.get(f"/api/analyses/{res['id']}", headers={"X-Report-Token": tok}).json()
        d = body["tryon"]["disclosure"]
        self.assertEqual(d["provider"], "fal")
        self.assertIn("fal.ai", d["provider_name"])
        self.assertIn("leaves Alexandra's servers", d["leaves_infrastructure"])
        self.assertIn("NOT been verified", d["retention"])
        self.assertIn("do not need this", d["optional"])
        self.assertFalse(body["tryon"]["consent"]["granted"])
        self.assertFalse([k for k in body if k.startswith("_")])  # raw consent record is never exposed

    def test_disclosure_makes_no_unverified_claims_about_provider_retention(self):
        txt = json.dumps(consent.disclosure("fal")).lower() + json.dumps(consent.disclosure("gemini")).lower()
        for claim in ("deleted immediately", "not stored", "never stored", "does not retain", "not used for training", "gdpr compliant", "zero retention"):
            self.assertNotIn(claim, txt)

    def test_try_on_not_configured_is_a_503_not_a_consent_error(self):
        os.environ.pop("FAL_KEY", None)
        os.environ.pop("TRYON_PROVIDER", None)
        res, tok = paid_report_with_styles()
        self.assertEqual(self.post_tryon(res["id"], tok).status_code, 503)

    def test_try_on_calls_are_rate_limited_per_client(self):
        res, tok = paid_report_with_styles()
        codes = [self.post_tryon(res["id"], tok).status_code for _ in range(24)]
        self.assertIn(429, codes)
        self.fal.assert_not_called()


# --------------------------------------------------------------------------- Part 5: account data
class AccountData(Base):
    def user_file(self, email):
        uid = accounts._index()[email]
        return accounts.USERS_DIR / f"{uid}.json"

    def test_password_is_never_stored_in_plaintext_and_uses_the_current_cost(self):
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        raw = self.user_file("a@example.com").read_text(encoding="utf-8")
        self.assertNotIn(PWD, raw)
        u = json.loads(raw)
        self.assertEqual((len(u["pw"]), u["iters"]), (64, accounts.PBKDF2_ITERS))
        self.assertEqual(len(bytes.fromhex(u["salt"])), 16)

    def test_session_tokens_are_stored_only_as_hashes(self):
        r = self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD}).json()
        secret = r["token"].split(".", 1)[1]
        self.assertNotIn(secret, self.user_file("a@example.com").read_text(encoding="utf-8"))

    def test_legacy_hash_is_upgraded_on_login_and_still_works(self):
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        uid = "legacyuser0001"
        user = {"id": uid, "email": "old@example.com", "name": "", "created_at": 1, "salt": salt.hex(),
                "pw": accounts._hash_pw(PWD, salt, accounts.LEGACY_ITERS), "analyses": [], "sessions": []}
        accounts._save(user)
        accounts.INDEX.write_text(json.dumps({"old@example.com": uid}), encoding="utf-8")
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "old@example.com", "password": "wrong-password"}).status_code, 401)
        self.assertNotIn("iters", json.loads(self.user_file("old@example.com").read_text()))  # a failed login upgrades nothing
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "old@example.com", "password": PWD}).status_code, 200)
        u = json.loads(self.user_file("old@example.com").read_text())
        self.assertEqual(u["iters"], accounts.PBKDF2_ITERS)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "old@example.com", "password": PWD}).status_code, 200)

    def test_login_failure_is_identical_for_unknown_email_and_wrong_password_and_does_the_same_work(self):
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        security.limiter.reset()
        wrong = self.client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-password-1"})
        security.limiter.reset()
        with mock.patch.object(accounts, "_hash_pw", wraps=accounts._hash_pw) as h:
            unknown = self.client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
        self.assertEqual((wrong.status_code, wrong.json()), (unknown.status_code, unknown.json()))
        self.assertEqual(h.call_count, 1, "unknown email must still pay the hashing cost")

    def test_me_endpoint_never_returns_secrets(self):
        r = self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD}).json()
        me = self.client.get("/api/me", headers={"Authorization": f"Bearer {r['token']}"})
        for field in ("pw", "salt", "sessions", "iters", "hash"):
            self.assertNotIn(f'"{field}"', me.text)

    def test_report_responses_do_not_contain_the_owners_account_data(self):
        r = self.client.post("/api/auth/signup", json={"email": "owner@example.com", "password": PWD}).json()
        user = accounts.user_from_auth(f"Bearer {r['token']}")
        res, _ = make_report(owner=user)
        body = self.client.get(f"/api/analyses/{res['id']}", headers={"Authorization": f"Bearer {r['token']}"}).text
        for leak in ("owner@example.com", user["pw"], user["salt"], user["id"] + '"'):
            self.assertNotIn(leak, body)

    def test_account_files_cannot_be_reached_through_report_endpoints(self):
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        uid = accounts._index()["a@example.com"]
        for bad in ("users", "_index", uid, f"users/{uid}", f"..%2Fusers%2F{uid}", "users%2F_index"):
            security.limiter.reset()
            self.assertEqual(self.client.get(f"/api/analyses/{bad}").status_code, 404, bad)
        self.assertFalse(store.valid_id(uid))  # account ids are not valid report ids

    def test_load_all_ignores_account_files(self):
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        make_report()
        self.assertEqual(len(store.load_all()), 1)

    def test_orphan_index_entry_does_not_crash_login_and_can_sign_up_again(self):
        """Found in real data: an index email pointing at a user file that does not exist. Login used to raise a 500
        (revealing the email exists) and signup was blocked forever."""
        accounts.INDEX.write_text(json.dumps({"ghost@example.com": "deadbeefdeadbeef"}), encoding="utf-8")
        r = self.client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "whatever-123"})
        self.assertEqual(r.status_code, 401)
        security.limiter.reset()
        unknown = self.client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"})
        self.assertEqual((r.status_code, r.json()), (unknown.status_code, unknown.json()))
        self.assertEqual(self.client.post("/api/auth/signup", json={"email": "ghost@example.com", "password": PWD}).status_code, 200)

    def test_startup_restricts_the_account_folder_to_the_current_user(self):
        with mock.patch.object(store, "restrict_to_current_user") as r:
            with TestClient(main.app):
                pass
        self.assertIn(mock.call(accounts.USERS_DIR), r.call_args_list)

    def test_duplicate_signup_is_reported_but_login_does_not_reveal_existence(self):
        """Documented trade-off: signup says the email exists (needed for UX without email verification)."""
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        self.assertEqual(self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD}).status_code, 409)


# --------------------------------------------------------------------------- Part 6: rate limiting
class RateLimits(Base):
    def test_admin_brute_force_is_throttled_even_for_the_right_token_afterwards(self):
        with mock.patch.object(admin, "ADMIN_TOKEN", "the-real-admin-token-value"):
            codes = [self.client.get("/api/admin/analyses", headers={"X-Admin-Token": f"guess{i}"}).status_code for i in range(13)]
            self.assertEqual(codes[:10], [401] * 10)
            self.assertEqual(codes[10:], [429] * 3)
            ok = self.client.get("/api/admin/analyses", headers={"X-Admin-Token": "the-real-admin-token-value"})
            self.assertEqual(ok.status_code, 429)  # blocked until the window passes: guessing cannot be interleaved
            security.limiter.reset()
            self.assertEqual(self.client.get("/api/admin/analyses", headers={"X-Admin-Token": "the-real-admin-token-value"}).status_code, 200)

    def test_admin_is_disabled_without_a_token(self):
        with mock.patch.object(admin, "ADMIN_TOKEN", ""):
            self.assertEqual(self.client.get("/api/admin/analyses", headers={"X-Admin-Token": ""}).status_code, 503)

    def test_report_mutation_routes_are_limited(self):
        rid = security.new_report_id()
        for method, suffix in (("delete", ""), ("post", "/checkout"), ("post", "/confirm")):
            security.limiter.reset()
            kw = {"json": {}} if method == "post" else {}
            codes = [getattr(self.client, method)(f"/api/analyses/{rid}{suffix}", **kw).status_code for _ in range(34)]
            self.assertIn(429, codes, f"{method} {suffix}")

    def test_claim_and_consent_routes_are_limited(self):
        rid = security.new_report_id()
        self.client.post("/api/auth/signup", json={"email": "a@example.com", "password": PWD})
        h = {"Authorization": "Bearer " + self.client.post("/api/auth/login", json={"email": "a@example.com", "password": PWD}).json()["token"]}
        security.limiter.reset()
        self.assertIn(429, [self.client.post(f"/api/me/analyses/{rid}/claim", headers=h).status_code for _ in range(34)])
        security.limiter.reset()
        self.assertIn(429, [self.client.post(f"/api/analyses/{rid}/consent/tryon", json={"accept": True, "provider": "fal", "version": "x"}).status_code for _ in range(34)])

    def test_report_probing_is_cut_off_after_a_burst(self):
        codes = [self.client.get(f"/api/analyses/{security.new_report_id()}").status_code for _ in range(60)]
        self.assertEqual(codes.count(404), security.DENIED_LIMIT)
        self.assertEqual(set(codes[security.DENIED_LIMIT:]), {429})

    def test_limiter_state_lives_in_a_file_in_the_data_dir_not_in_process_memory(self):
        """Pins the truth so documentation cannot drift: counters are in SQLite (survive restarts, shared by local
        worker processes). There is still no central store, so several MACHINES would each have their own limits."""
        security.limiter.hit("pin:test", 5, 60)
        self.assertTrue((store.DATA_DIR / ".ratelimit.sqlite3").exists())
        self.assertFalse(hasattr(security.limiter, "_hits"))
        src = Path(security.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"import\s+redis|from\s+redis|redis\.Redis|Redis\(", src))  # no central store is used


if __name__ == "__main__":
    unittest.main()
