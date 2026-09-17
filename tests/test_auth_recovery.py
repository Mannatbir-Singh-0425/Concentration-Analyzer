"""
Unit & Integration Tests for User Authentication and Password Recovery Flow.
Tests user registration, login, security question lookup, recovery key reset,
security answer reset, and session management.
"""

import unittest
import json
import tempfile
import os
from app import app, init_db, get_db

class TestAuthAndRecovery(unittest.TestCase):

    def setUp(self):
        # Configure app for testing
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_demo_login(self):
        """Test that demo user can log in with demo/demo123."""
        res = self.client.post("/api/login", json={
            "username": "demo",
            "password": "demo123"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("user", data)
        self.assertEqual(data["user"]["username"], "demo")

    def test_register_and_login_flow(self):
        """Test registering a new user with security question and logging in."""
        import time
        uname = f"test_scientist_{int(time.time()*1000) % 100000}"
        
        reg_res = self.client.post("/api/register", json={
            "username": uname,
            "password": "mypassword123",
            "security_question": "What was your childhood nickname?",
            "security_answer": "Einstein"
        })
        self.assertEqual(reg_res.status_code, 200)
        reg_data = reg_res.get_json()
        self.assertIn("recovery_key", reg_data)
        self.assertTrue(reg_data["recovery_key"].startswith("QUANT-"))
        recovery_key = reg_data["recovery_key"]

        # Check me endpoint is authenticated
        me_res = self.client.get("/api/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.get_json()["user"]["username"], uname)

        # Logout
        self.client.post("/api/logout")
        unauth_res = self.client.get("/api/me")
        self.assertEqual(unauth_res.status_code, 401)

        # Login with correct password
        login_res = self.client.post("/api/login", json={
            "username": uname,
            "password": "mypassword123"
        })
        self.assertEqual(login_res.status_code, 200)

        # Password Recovery Lookup
        lookup_res = self.client.post("/api/recover/lookup", json={"username": uname})
        self.assertEqual(lookup_res.status_code, 200)
        lookup_data = lookup_res.get_json()
        self.assertEqual(lookup_data["security_question"], "What was your childhood nickname?")
        self.assertTrue(lookup_data["has_security_question"])

        # Reset via Security Answer
        reset_res = self.client.post("/api/recover/reset", json={
            "username": uname,
            "method": "question",
            "answer": "einstein",  # case-insensitive
            "new_password": "newpassword456"
        })
        self.assertEqual(reset_res.status_code, 200)

        # Old password should fail
        self.client.post("/api/logout")
        bad_login = self.client.post("/api/login", json={
            "username": uname,
            "password": "mypassword123"
        })
        self.assertEqual(bad_login.status_code, 401)

        # New password should succeed
        good_login = self.client.post("/api/login", json={
            "username": uname,
            "password": "newpassword456"
        })
        self.assertEqual(good_login.status_code, 200)

    def test_recovery_via_key(self):
        """Test password reset via emergency recovery key."""
        import time
        uname = f"test_key_user_{int(time.time()*1000) % 100000}"
        
        reg_res = self.client.post("/api/register", json={
            "username": uname,
            "password": "firstpassword",
            "security_question": "Favorite element?",
            "security_answer": "Helium"
        })
        recovery_key = reg_res.get_json()["recovery_key"]
        self.client.post("/api/logout")

        # Wrong key should fail
        fail_res = self.client.post("/api/recover/reset", json={
            "username": uname,
            "method": "key",
            "answer": "QUANT-WRONG-KEY-0000",
            "new_password": "secondpassword"
        })
        self.assertEqual(fail_res.status_code, 401)

        # Correct key should succeed
        ok_res = self.client.post("/api/recover/reset", json={
            "username": uname,
            "method": "key",
            "answer": recovery_key,
            "new_password": "secondpassword"
        })
        self.assertEqual(ok_res.status_code, 200)

        # Verify login with new password
        self.client.post("/api/logout")
        login_res = self.client.post("/api/login", json={
            "username": uname,
            "password": "secondpassword"
        })
        self.assertEqual(login_res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
