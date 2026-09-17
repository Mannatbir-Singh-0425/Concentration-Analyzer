"""
Test suite for enhanced signup, smart login, auto-login, and session persistence.
"""

import unittest
import time
from app import app, get_db


class TestSignupFlow(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_signup_and_auto_login(self):
        ts = int(time.time() * 1000) % 100000
        username = f"smart_user_{ts}"
        password = "secret_password_123"

        # 1. Register new account
        res = self.client.post("/api/register", json={
            "username": username,
            "password": password
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("token", data)
        token = data["token"]

        # 2. Check /api/me works with session
        me_res = self.client.get("/api/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()["user"]["username"], username)

        # 3. Simulate re-registering with same credentials (smooth auto-sign in)
        re_client = app.test_client()
        re_res = re_client.post("/api/register", json={
            "username": username,
            "password": password
        })
        self.assertEqual(re_res.status_code, 200)
        re_data = re_res.get_json()
        self.assertTrue(re_data.get("auto_signed_in"))
        self.assertEqual(re_data["user"]["username"], username)
        token = re_data["token"]

        # 4. Re-registering with wrong password gives account_exists error
        bad_client = app.test_client()
        bad_res = bad_client.post("/api/register", json={
            "username": username,
            "password": "wrong_password_999"
        })
        self.assertEqual(bad_res.status_code, 400)
        self.assertTrue(bad_res.get_json().get("account_exists"))

        # 5. Test auto_login endpoint restores session from token
        auto_client = app.test_client()
        # initially unauthenticated
        self.assertEqual(auto_client.get("/api/me").status_code, 401)
        # auto-login with remember token
        auto_res = auto_client.post("/api/auto_login", json={
            "username": username,
            "token": token
        })
        self.assertEqual(auto_res.status_code, 200)
        self.assertTrue(auto_res.get_json()["authenticated"])
        # Now /api/me should be authenticated!
        self.assertEqual(auto_client.get("/api/me").status_code, 200)

        # 6. Test login with wrong username gives not_found
        login_bad_user = self.client.post("/api/login", json={
            "username": f"nonexistent_{ts}",
            "password": "any"
        })
        self.assertEqual(login_bad_user.status_code, 401)
        self.assertTrue(login_bad_user.get_json().get("not_found"))

        # 7. Test login with wrong password gives invalid_password
        login_bad_pw = self.client.post("/api/login", json={
            "username": username,
            "password": "incorrect_password"
        })
        self.assertEqual(login_bad_pw.status_code, 401)
        self.assertTrue(login_bad_pw.get_json().get("invalid_password"))


if __name__ == "__main__":
    unittest.main()
