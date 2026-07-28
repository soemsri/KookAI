import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import main
from model_catalog import (
    ModelCatalogError,
    load_model_catalog,
    resolve_catalog_model,
    save_model_catalog,
    validate_model_catalog,
)


PROJECT_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "model_catalog.json",
)


class ModelCatalogTests(unittest.TestCase):
    def test_shipped_catalog_is_valid_and_has_enabled_default(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        default_model = resolve_catalog_model(catalog, catalog["default_model"])
        self.assertIsNotNone(default_model)
        self.assertTrue(default_model["enabled"])
        self.assertGreater(len(catalog["models"]), 20)

    def test_duplicate_model_ids_are_rejected(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        catalog["models"].append(dict(catalog["models"][0]))
        with self.assertRaises(ModelCatalogError):
            validate_model_catalog(catalog)

    def test_catalog_save_is_atomic_and_supports_cli_alias_lookup(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        catalog["catalog_version"] = "test.2"
        catalog["models"][0]["cli_model"] = "gemini-dynamic-test"
        with tempfile.TemporaryDirectory() as temp_directory:
            path = os.path.join(temp_directory, "models.json")
            saved = save_model_catalog(path, catalog)
            loaded = load_model_catalog(path)
        self.assertEqual(saved["catalog_version"], "test.2")
        resolved = resolve_catalog_model(loaded, "gemini-dynamic-test")
        self.assertEqual(resolved["id"], catalog["models"][0]["id"])

    def test_disabled_model_is_not_resolved_for_chat(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        catalog["models"][0]["enabled"] = False
        self.assertIsNone(
            resolve_catalog_model(catalog, catalog["models"][0]["id"])
        )


class ModelCatalogApiTests(unittest.TestCase):
    @staticmethod
    def request(host="127.0.0.1"):
        return SimpleNamespace(
            client=SimpleNamespace(host=host),
            headers={},
            query_params={},
        )

    def test_model_catalog_endpoint_returns_enabled_models(self):
        response = asyncio.run(main.get_models(self.request()))
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["models"])
        self.assertTrue(all(model["enabled"] for model in payload["models"]))

    def test_unknown_chat_model_is_rejected_before_task_start(self):
        request = main.ChatRequest(
            message="hello",
            model="model-that-does-not-exist",
            workspace="agy",
            target="Sandbox",
            conversation_id="temp-test",
        )
        with self.assertRaises(HTTPException) as context:
            main.verify_chat_model_request(request)
        self.assertEqual(context.exception.status_code, 422)

    def test_runtime_catalog_registers_dynamic_codex_model(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        dynamic_model = {
            "id": "future-codex",
            "label": "Future Codex",
            "description": "Future catalog model",
            "provider": "codex",
            "cli_model": "gpt-future-codex",
            "badge": "Codex",
            "usage_bucket": "gpt",
            "enabled": True,
            "capabilities": {
                "effort": ["Light", "Medium"],
                "speed": ["Standard"],
                "thinking": False,
                "thinking_required": False,
            },
        }
        catalog["models"].append(dynamic_model)
        with tempfile.TemporaryDirectory() as temp_directory:
            path = os.path.join(temp_directory, "models.json")
            save_model_catalog(path, catalog)
            with mock.patch.object(main, "MODEL_CATALOG_PATH", path):
                loaded = main.load_runtime_model_catalog()
        self.assertEqual(
            resolve_catalog_model(loaded, "future-codex")["cli_model"],
            "gpt-future-codex",
        )

    def test_local_catalog_update_is_validated_and_persisted(self):
        catalog = load_model_catalog(PROJECT_CATALOG_PATH)
        catalog["catalog_version"] = "api-test.1"

        class CatalogRequest(SimpleNamespace):
            async def json(self):
                return catalog

        request = CatalogRequest(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
            query_params={},
        )
        with tempfile.TemporaryDirectory() as temp_directory:
            path = os.path.join(temp_directory, "models.json")
            with mock.patch.object(main, "MODEL_CATALOG_PATH", path):
                response = asyncio.run(main.update_models(request))
                persisted = load_model_catalog(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(persisted["catalog_version"], "api-test.1")

    def test_remote_catalog_update_is_forbidden(self):
        request = self.request("198.51.100.4")
        with self.assertRaises(HTTPException) as context:
            asyncio.run(main.update_models(request))
        self.assertEqual(context.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
