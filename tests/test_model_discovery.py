import json
import os
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import asyncio

import main
import model_discovery
from model_catalog import (
    load_model_catalog,
    save_model_catalog,
    validate_model_catalog,
    resolve_catalog_model,
)


class ModelDiscoveryTests(unittest.TestCase):
    def test_normalize_codex_label(self):
        self.assertEqual(model_discovery.normalize_codex_label("gpt-6-sol", "GPT-6-Sol"), "6 Sol")
        self.assertEqual(model_discovery.normalize_codex_label("gpt-6-luna", "GPT-6-Luna"), "6 Luna")
        self.assertEqual(model_discovery.normalize_codex_label("gpt-5.6-terra", "GPT-5.6-Terra"), "5.6 Terra")
        self.assertEqual(model_discovery.normalize_codex_label("gpt-5.5", "GPT-5.5"), "5.5")
        self.assertEqual(model_discovery.normalize_codex_label("gpt-custom-model"), "Custom Model")

    def test_parse_codex_cache_entry(self):
        hidden_entry = {
            "slug": "codex-auto-review",
            "display_name": "Codex Auto Review",
            "visibility": "hide",
        }
        self.assertIsNone(model_discovery.parse_codex_cache_entry(hidden_entry))

        valid_entry = {
            "slug": "gpt-6-sol",
            "display_name": "GPT-6-Sol",
            "description": "Our powerful reasoning model",
            "visibility": "list",
            "supported_reasoning_levels": [
                {"effort": "low"},
                {"effort": "medium"},
                {"effort": "high"},
                {"effort": "xhigh"},
                {"effort": "ultra"},
            ],
            "additional_speed_tiers": ["fast"],
        }
        parsed = model_discovery.parse_codex_cache_entry(valid_entry)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["id"], "6 Sol")
        self.assertEqual(parsed["label"], "6 Sol")
        self.assertEqual(parsed["cli_model"], "gpt-6-sol")
        self.assertEqual(parsed["provider"], "codex")
        self.assertEqual(parsed["usage_bucket"], "gpt")
        self.assertIn("Ultra", parsed["capabilities"]["effort"])
        self.assertIn("Fast", parsed["capabilities"]["speed"])

    def test_sync_model_catalog_adds_missing_codex_models(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            catalog_path = os.path.join(temp_directory, "models.json")
            # Minimal catalog without 6 Sol or 6 Luna
            base_catalog = {
                "schema_version": 1,
                "catalog_version": "2026.01.01",
                "default_model": "Gemini 3.8 Flash (High)",
                "models": [
                    {
                        "id": "Gemini 3.8 Flash (High)",
                        "label": "Gemini 3.8 Flash (High)",
                        "description": "Default gemini model",
                        "provider": "agy",
                        "cli_model": "gemini-3.8-flash-high",
                        "badge": "Gemini",
                        "usage_bucket": "gemini",
                        "enabled": True,
                        "capabilities": {
                            "effort": [],
                            "speed": [],
                            "thinking": False,
                            "thinking_required": False,
                        },
                    }
                ],
            }
            save_model_catalog(catalog_path, base_catalog)

            updated_catalog, was_updated = model_discovery.sync_model_catalog(
                catalog_path, force=True
            )
            self.assertTrue(was_updated)
            self.assertIn(".auto.", updated_catalog["catalog_version"])

            sol = resolve_catalog_model(updated_catalog, "6 Sol")
            self.assertIsNotNone(sol)
            self.assertEqual(sol["cli_model"], "gpt-6-sol")
            self.assertEqual(sol["provider"], "codex")

            luna = resolve_catalog_model(updated_catalog, "6 Luna")
            self.assertIsNotNone(luna)
            self.assertEqual(luna["cli_model"], "gpt-6-luna")

            # Subsequent sync with no new models should report was_updated=False
            same_catalog, second_update = model_discovery.sync_model_catalog(
                catalog_path, force=True
            )
            self.assertFalse(second_update)
            self.assertEqual(len(same_catalog["models"]), len(updated_catalog["models"]))

    def test_sync_models_endpoint(self):
        class MockRequest(SimpleNamespace):
            headers = {}
            query_params = {}
            client = SimpleNamespace(host="127.0.0.1")

        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = os.path.join(temp_dir, "models.json")
            base_catalog = {
                "schema_version": 1,
                "catalog_version": "test.1",
                "default_model": "Gemini 3.8 Flash (High)",
                "models": [
                    {
                        "id": "Gemini 3.8 Flash (High)",
                        "label": "Gemini 3.8 Flash (High)",
                        "description": "Default gemini model",
                        "provider": "agy",
                        "cli_model": "gemini-3.8-flash-high",
                        "badge": "Gemini",
                        "usage_bucket": "gemini",
                        "enabled": True,
                        "capabilities": {
                            "effort": [],
                            "speed": [],
                            "thinking": False,
                            "thinking_required": False,
                        },
                    }
                ],
            }
            save_model_catalog(test_path, base_catalog)
            with mock.patch.object(main, "MODEL_CATALOG_PATH", test_path):
                response = asyncio.run(main.sync_models_endpoint(MockRequest()))
                self.assertEqual(response.status_code, 200)
                body = json.loads(response.body)
                self.assertEqual(body["status"], "success")
                self.assertTrue(body["updated"])
                self.assertGreater(body["model_count"], 1)


if __name__ == "__main__":
    unittest.main()
