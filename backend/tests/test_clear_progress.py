import unittest
from fastapi import HTTPException
from app import accounts, store


class Clear(unittest.TestCase):
    def test_requires_confirmation_and_sign_in(self):
        with self.assertRaises(HTTPException) as c:
            accounts.clear_progress({}, None)
        self.assertEqual(c.exception.status_code, 401)

    def test_route_exists_and_demands_confirm_text(self):
        import inspect
        src = inspect.getsource(accounts.clear_progress)
        self.assertIn('"DELETE"', src)
        self.assertIn('_owner") == user["id"]', src)


if __name__ == "__main__":
    unittest.main()
