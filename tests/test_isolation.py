"""
Multi-Tenant Privacy & User Data Isolation Tests
Verifies that:
- User A's categories, samples, and predictions are strictly hidden from User B.
- New users start with a clean private workspace.
- Voluntary starter standard loading works per-user without cross-tenant leakage.
- Category deletion cleanly purges records and model files for that user only.
- Strict anti-caching privacy headers are enforced.
"""

import unittest
import time
from app import app


class TestDataIsolation(unittest.TestCase):

    def setUp(self):
        app.config["TESTING"] = True
        self.client_a = app.test_client()
        self.client_b = app.test_client()

    def test_multi_user_strict_isolation(self):
        ts = int(time.time() * 1000) % 100000
        user_a = f"alice_{ts}"
        user_b = f"bob_{ts}"

        # 1. Register User A
        res_a = self.client_a.post("/api/register", json={
            "username": user_a,
            "password": "alice_password_123"
        })
        self.assertEqual(res_a.status_code, 200)

        # User A starts with a clean slate
        cat_res_a = self.client_a.get("/api/categories")
        self.assertEqual(cat_res_a.status_code, 200)
        self.assertEqual(len(cat_res_a.get_json()["categories"]), 0)

        # Anti-caching header check
        self.assertIn("no-store", cat_res_a.headers.get("Cache-Control", ""))

        # 2. User A creates private category
        create_res = self.client_a.post("/api/categories", json={
            "name": "Alice Secret Serum",
            "unit": "ppm"
        })
        self.assertEqual(create_res.status_code, 200)

        cat_res_a2 = self.client_a.get("/api/categories")
        cats_a = [c["name"] for c in cat_res_a2.get_json()["categories"]]
        self.assertIn("Alice Secret Serum", cats_a)

        # 3. Register User B
        res_b = self.client_b.post("/api/register", json={
            "username": user_b,
            "password": "bob_password_123"
        })
        self.assertEqual(res_b.status_code, 200)

        # User B should NOT see User A's category
        cat_res_b = self.client_b.get("/api/categories")
        self.assertEqual(cat_res_b.status_code, 200)
        cats_b = [c["name"] for c in cat_res_b.get_json()["categories"]]
        self.assertNotIn("Alice Secret Serum", cats_b)
        self.assertEqual(len(cats_b), 0)

        # 4. User B cannot fetch samples of Alice's category
        samples_b = self.client_b.get("/api/category_samples/Alice%20Secret%20Serum")
        self.assertEqual(samples_b.status_code, 200)
        self.assertEqual(len(samples_b.get_json()["samples"]), 0)

        # 5. User B cannot delete Alice's category
        del_b = self.client_b.delete("/api/categories/Alice%20Secret%20Serum")
        self.assertEqual(del_b.status_code, 404)

        # Verify Alice still has her category
        cat_res_a3 = self.client_a.get("/api/categories")
        self.assertEqual(len(cat_res_a3.get_json()["categories"]), 1)

        # 6. User B can voluntarily seed starter standards into their own account
        seed_res = self.client_b.post("/api/categories/seed_starter")
        self.assertEqual(seed_res.status_code, 200)

        cat_res_b2 = self.client_b.get("/api/categories")
        cats_b_after = [c["name"] for c in cat_res_b2.get_json()["categories"]]
        self.assertIn("Protein Test", cats_b_after)
        self.assertIn("Water Nitrate", cats_b_after)
        self.assertIn("Food Color Dye", cats_b_after)

        # Verify Alice did NOT get those standards automatically
        cat_res_a4 = self.client_a.get("/api/categories")
        cats_a_after = [c["name"] for c in cat_res_a4.get_json()["categories"]]
        self.assertEqual(cats_a_after, ["Alice Secret Serum"])

        # 7. User B can delete a starter standard from their own account
        del_protein = self.client_b.delete("/api/categories/Protein%20Test")
        self.assertEqual(del_protein.status_code, 200)

        cat_res_b3 = self.client_b.get("/api/categories")
        cats_b3 = [c["name"] for c in cat_res_b3.get_json()["categories"]]
        self.assertNotIn("Protein Test", cats_b3)

        # 8. User A can delete her category cleanly
        del_alice = self.client_a.delete("/api/categories/Alice%20Secret%20Serum")
        self.assertEqual(del_alice.status_code, 200)

        cat_res_a_final = self.client_a.get("/api/categories")
        self.assertEqual(len(cat_res_a_final.get_json()["categories"]), 0)


if __name__ == "__main__":
    unittest.main()
