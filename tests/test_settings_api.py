import unittest
import os
import tempfile
from fastapi.testclient import TestClient
from main import app

class TestSettingsAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_get_and_post_settings(self):
        # Test GET /api/settings
        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("has_groq_key", data)
        self.assertIn("groq_api_key_masked", data)
        self.assertIsInstance(data["has_groq_key"], bool)

        # Test POST /api/settings
        post_res = self.client.post("/api/settings", json={"groq_api_key": "gsk_dummykey1234567890abcdef"})
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(post_res.json()["status"], "ok")
        self.assertIn("gsk_dummykey1234567890abcdef", os.environ.get("GROQ_API_KEY", ""))

        # Verify GET reflects new key
        res2 = self.client.get("/api/settings")
        self.assertEqual(res2.status_code, 200)
        self.assertTrue(res2.json()["has_groq_key"])

if __name__ == "__main__":
    unittest.main()
