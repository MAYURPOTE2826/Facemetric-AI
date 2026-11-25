"""Every route must have an explicit security classification; sensitive routes without a limiter must say why."""
import unittest

from evals import endpoint_matrix as em


class EndpointMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = em.collect()

    def test_every_route_is_classified_and_no_classification_is_stale(self):
        routes = {r["key"] for r in self.rows if r["path"].startswith("/api")}
        self.assertFalse(routes - set(em.MANUAL), f"unclassified routes: {sorted(routes - set(em.MANUAL))}")
        self.assertFalse(set(em.MANUAL) - routes, f"classifications for routes that no longer exist: {sorted(set(em.MANUAL) - routes)}")

    def test_every_report_route_uses_the_report_access_dependency(self):
        for r in self.rows:
            if r["path"].startswith("/api/analyses/"):
                self.assertTrue(r["report_access"], r["key"])

    def test_every_admin_route_requires_the_admin_dependency(self):
        for r in self.rows:
            if r["path"].startswith("/api/admin/"):
                self.assertTrue(r["admin"], r["key"])

    def test_unlimited_routes_must_justify_it(self):
        for r in self.rows:
            if r["path"].startswith("/api") and not r["limits"] and not r["report_access"] and not r["admin"]:
                self.assertTrue(em.MANUAL[r["key"]][3], f"{r['key']} has no limiter and no stated reason")

    def test_the_expensive_and_credential_routes_are_limited(self):
        by = {r["key"]: r for r in self.rows}
        for key in ("POST /api/analyze", "POST /api/auth/login", "POST /api/auth/signup", "POST /api/analyses/{analysis_id}/tryon",
                    "POST /api/analyses/{analysis_id}/checkout", "POST /api/analyses/{analysis_id}/confirm",
                    "POST /api/me/analyses/{analysis_id}/claim", "POST /api/analyses/{analysis_id}/consent/tryon",
                    "DELETE /api/analyses/{analysis_id}"):
            self.assertTrue(by[key]["limits"], f"{key} has no rate limit")

    def test_rendered_matrix_contains_no_unclassified_row(self):
        self.assertNotIn("UNCLASSIFIED", em.render())


if __name__ == "__main__":
    unittest.main()
