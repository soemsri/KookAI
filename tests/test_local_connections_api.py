"""Connection checks must refresh inventory without logging in or changing defaults."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import local_backend
import main


class LocalConnectionAPITests(unittest.TestCase):
    def setUp(self):
        local_backend._cache.clear()
        self.client = TestClient(main.app)
        self.admin = patch.object(main, "can_manage_cli_connections", return_value=True)
        self.admin.start()
        self.addCleanup(self.admin.stop)
        self.env = patch.dict(os.environ, {"KOOKAI_LOCAL_LLM_URL": "http://127.0.0.1:1234"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(local_backend._cache.clear)

    def test_status_shows_normalized_config_without_contacting_server(self):
        with patch.object(local_backend, "_request") as request:
            response = self.client.get("/api/local/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "http://127.0.0.1:1234/v1"})
        request.assert_not_called()

    def test_connect_bypasses_empty_cache_and_updates_real_catalog(self):
        with patch.object(local_backend, "_request", return_value=iter([{"data": []}])):
            self.assertEqual(local_backend.discover_local_models(), [])
        with patch.object(local_backend, "_request", return_value=iter([{"data": [{"id": "local-test"}]}])) as request, \
             patch.object(main, "launch_cli_login") as login:
            response = self.client.post("/api/local/connect")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ready")
        self.assertEqual(data["models"][0]["label"], "local-test (Local)")
        self.assertEqual(data["harness"]["id"], "qwen")
        self.assertEqual(data["harness"]["name"], "Qwen Code")
        self.assertIn("enabled", data["harness"])
        self.assertIn("installed", data["harness"])
        self.assertIn("mode", data["harness"])
        local = [m for m in data["catalog"]["models"] if m["provider"] == "local"]
        self.assertEqual(local[0]["id"], data["models"][0]["id"])
        self.assertNotEqual(data["catalog"]["default_model"], local[0]["id"])
        request.assert_called_once_with("models")
        login.assert_not_called()

    def test_offline_removes_previously_discovered_models(self):
        with patch.object(local_backend, "_request", return_value=iter([{"data": [{"id": "old-model"}]}])):
            self.assertTrue(local_backend.discover_local_models())
        with patch.object(local_backend, "_request", side_effect=OSError("offline")):
            response = self.client.post("/api/local/connect")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "no_models")
        self.assertEqual(data["models"], [])
        self.assertFalse(any(m["provider"] == "local" for m in data["catalog"]["models"]))

    def test_exo_with_no_active_instance_is_not_reported_connected(self):
        with patch.object(local_backend, "_request", side_effect=[
            iter([{"data": [{"id": "not-loaded", "owned_by": "exo"}]}]),
            iter([{"instances": {}}]),
        ]):
            response = self.client.post("/api/local/connect")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_models")

    def test_remote_clients_cannot_check_or_connect(self):
        with patch.object(main, "can_manage_cli_connections", return_value=False), \
             patch.object(main, "discover_local_models") as discover:
            self.assertEqual(self.client.get("/api/local/status").status_code, 403)
            self.assertEqual(self.client.post("/api/local/connect").status_code, 403)
        discover.assert_not_called()

    def test_invalid_configuration_is_actionable(self):
        with patch.dict(os.environ, {"KOOKAI_LOCAL_LLM_URL": "file:///tmp/model"}):
            for method, path in [("get", "/api/local/status"), ("post", "/api/local/connect")]:
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 400)
                self.assertIn("KOOKAI_LOCAL_LLM_URL", response.json()["detail"])
