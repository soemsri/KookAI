"""Exercise the same authenticated GET used by already-installed mobile apps."""

import asyncio
import copy
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

import httpx

import main
from model_catalog import load_model_catalog, save_model_catalog


class ModelStartupRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "models.json")
        self.catalog = load_model_catalog(main.BUILTIN_MODEL_CATALOG_PATH)
        save_model_catalog(self.path, self.catalog)
        self.patches = [
            mock.patch.object(main, "MODEL_CATALOG_PATH", self.path),
            mock.patch.object(main, "_model_catalog_sync_task", None),
            mock.patch.object(main, "_model_catalog_sync_path", None),
            mock.patch.object(main, "_last_models_sync_check_time", 0),
            mock.patch.object(main, "MODEL_CATALOG_WAIT_SECONDS", 0.1),
            mock.patch.object(main, "sync_model_catalog", side_effect=self.discover),
        ]
        for patch in self.patches:
            patch.start()
        self.sync = main.sync_model_catalog
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("127.0.0.1", 1234)),
            base_url="http://kookai.test",
        )

    async def asyncTearDown(self):
        task = main._model_catalog_sync_task
        if task is not None:
            try:
                await task
            except Exception:
                pass
        await self.client.aclose()
        for patch in reversed(self.patches):
            patch.stop()
        main.load_runtime_model_catalog()
        self.directory.cleanup()

    def discover(self, path, *, force=False):
        self.assertTrue(force)
        time.sleep(0.01)
        catalog = load_model_catalog(path)
        catalog["catalog_version"] = "startup-new-model"
        if not any(model["id"] == "Startup new model" for model in catalog["models"]):
            model = copy.deepcopy(catalog["models"][0])
            model.update(id="Startup new model", label="Startup new model", cli_model="startup-new-model")
            catalog["models"].append(model)
        return save_model_catalog(path, catalog), True

    async def test_first_mobile_get_contains_new_model_and_legacy_schema(self):
        response = await self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-KookAI-Model-Sync"], "complete")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        payload = response.json()
        self.assertEqual(set(payload), set(self.catalog))
        self.assertEqual(payload["catalog_version"], "startup-new-model")
        self.assertIn("Startup new model", [model["id"] for model in payload["models"]])
        self.assertEqual(payload["default_model"], self.catalog["default_model"])

    async def test_concurrent_get_and_post_share_one_real_discovery(self):
        responses = await asyncio.gather(
            self.client.get("/api/models"),
            self.client.get("/api/models"),
            self.client.post("/api/models/sync"),
        )
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertTrue(all(response.json()["catalog_version"] == "startup-new-model" for response in responses))
        self.sync.assert_called_once_with(self.path, force=True)

    async def test_recent_get_uses_cache_but_manual_post_still_forces_discovery(self):
        await self.client.get("/api/models")
        responses = await asyncio.gather(
            self.client.get("/api/models"), self.client.post("/api/models/sync"),
        )
        self.assertEqual(responses[0].headers["X-KookAI-Model-Sync"], "cached")
        self.assertEqual(self.sync.call_count, 2)
        self.assertTrue(all(call.kwargs["force"] for call in self.sync.call_args_list))

    async def test_expired_cooldown_discovers_again(self):
        await self.client.get("/api/models")
        main._last_models_sync_check_time = time.monotonic() - 61
        await self.client.get("/api/models")
        self.assertEqual(self.sync.call_count, 2)

    async def test_discovery_failure_returns_last_good_catalog(self):
        self.sync.side_effect = RuntimeError("provider unavailable")
        response = await self.client.get("/api/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-KookAI-Model-Sync"], "failed")
        self.assertEqual(response.json()["catalog_version"], self.catalog["catalog_version"])
        self.assertEqual(load_model_catalog(self.path), self.catalog)

    async def test_timeout_keeps_worker_alive_and_next_get_sees_completed_catalog(self):
        release = threading.Event()

        def slow_discovery(path, *, force=False):
            release.wait(timeout=2)
            return self.discover(path, force=force)

        self.sync.side_effect = slow_discovery
        try:
            response = await asyncio.wait_for(self.client.get("/api/models"), timeout=1)
            self.assertEqual(response.headers["X-KookAI-Model-Sync"], "pending")
            self.assertEqual(response.json()["catalog_version"], self.catalog["catalog_version"])
            self.assertFalse(main._model_catalog_sync_task.done())
        finally:
            release.set()
        await main._model_catalog_sync_task
        response = await self.client.get("/api/models")
        self.assertEqual(response.json()["catalog_version"], "startup-new-model")
        self.assertEqual(self.sync.call_count, 1)

    async def test_cancelled_request_does_not_cancel_shared_refresh(self):
        release = threading.Event()

        def slow_discovery(path, *, force=False):
            release.wait(timeout=2)
            return self.discover(path, force=force)

        self.sync.side_effect = slow_discovery
        request = asyncio.create_task(self.client.get("/api/models"))
        try:
            for _ in range(100):
                if main._model_catalog_sync_task is not None:
                    break
                await asyncio.sleep(0.001)
            self.assertIsNotNone(main._model_catalog_sync_task)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertFalse(main._model_catalog_sync_task.cancelled())
        finally:
            release.set()
        await main._model_catalog_sync_task
        self.assertEqual(load_model_catalog(self.path)["catalog_version"], "startup-new-model")

    async def test_remote_auth_and_disabled_models_guard_run_before_discovery(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("192.0.2.10", 1234)),
            base_url="http://kookai.test",
        ) as client:
            response = await client.get("/api/models")
            self.assertEqual(response.status_code, 401)
            with mock.patch.object(main, "verify_authorization", return_value=True):
                response = await client.get("/api/models?include_disabled=true")
            self.assertEqual(response.status_code, 403)
        self.sync.assert_not_called()

    async def test_disabled_models_and_default_are_preserved(self):
        disabled = next(model for model in self.catalog["models"] if model["id"] != self.catalog["default_model"])
        disabled["enabled"] = False
        save_model_catalog(self.path, self.catalog)
        response = await self.client.get("/api/models")
        self.assertNotIn(disabled["id"], [model["id"] for model in response.json()["models"]])
        response = await self.client.get("/api/models?include_disabled=true")
        found = next(model for model in response.json()["models"] if model["id"] == disabled["id"])
        self.assertFalse(found["enabled"])
        self.assertEqual(response.json()["default_model"], self.catalog["default_model"])
