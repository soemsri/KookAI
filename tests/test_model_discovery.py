import json
import os
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import asyncio

import main
import model_discovery
import codex_backend
import claude_backend
import grok_backend
import kimi_backend
import muse_backend
import deepseek_backend
import zai_backend
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

    def test_parse_agy_models_output(self):
        raw_output = (
            "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
            "gemini-3.1-pro-high\tGemini 3.1 Pro (High)\n"
            "claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\n"
            "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
        )
        parsed = model_discovery.parse_agy_models_output(raw_output)
        self.assertEqual(len(parsed), 4)

        flash = next(m for m in parsed if m["cli_model"] == "gemini-3.8-flash-high")
        self.assertEqual(flash["provider"], "agy")
        self.assertEqual(flash["usage_bucket"], "gemini")
        self.assertEqual(flash["badge"], "Flash")
        self.assertEqual(flash["capabilities"]["effort"], [])
        self.assertFalse(flash["capabilities"]["thinking"])

        pro = next(m for m in parsed if m["cli_model"] == "gemini-3.1-pro-high")
        self.assertEqual(pro["badge"], "Pro")

        claude = next(m for m in parsed if m["cli_model"] == "claude-sonnet-4-6")
        self.assertEqual(claude["usage_bucket"], "claude")

        oss = next(m for m in parsed if m["cli_model"] == "gpt-oss-120b-medium")
        self.assertEqual(oss["usage_bucket"], "gpt")

    def test_parse_grok_models_output(self):
        raw_output = (
            "Default model: grok-4.5\n\n"
            "Available models:\n"
            "  * grok-4.5 (default)\n"
            "  * grok-4.6\n"
            "  * grok-4.20\n"
        )
        parsed = model_discovery.parse_grok_models_output(raw_output)
        self.assertEqual(len(parsed), 3)

        slugs = {m["cli_model"] for m in parsed}
        self.assertIn("grok-4.5", slugs)
        self.assertIn("grok-4.6", slugs)
        self.assertIn("grok-4.20", slugs)

        for m in parsed:
            self.assertEqual(m["provider"], "xai")
            self.assertEqual(m["usage_bucket"], "xai")
            self.assertEqual(m["badge"], "Grok")
            self.assertTrue(m["capabilities"]["thinking"])
            self.assertEqual(m["capabilities"]["speed"], [])

    def test_provider_discovery_capabilities_conformance(self):
        """Verify each provider's discovered models comply with validate_model_catalog rules."""
        providers_handlers = [
            ("codex", model_discovery.discover_codex_models(cache_path="/nonexistent")),
            ("agy", model_discovery.KNOWN_AGY_MODELS),
            ("claude", model_discovery.discover_claude_models()),
            ("xai", model_discovery.KNOWN_GROK_MODELS),
            ("kimi", model_discovery.discover_kimi_models()),
            ("muse", model_discovery.discover_muse_models()),
            ("deepseek", model_discovery.discover_deepseek_models()),
            ("zai", model_discovery.discover_zai_models()),
        ]

        for provider_name, models in providers_handlers:
            self.assertGreater(len(models), 0, f"Provider {provider_name} has no models")
            dummy_catalog = {
                "schema_version": 1,
                "catalog_version": f"test-{provider_name}",
                "default_model": models[0]["id"],
                "models": models,
            }
            # Must pass catalog validation without raising ModelCatalogError
            validated = validate_model_catalog(dummy_catalog)
            self.assertEqual(len(validated["models"]), len(models))

    def test_sync_model_catalog_adds_missing_multi_provider_models(self):
        with tempfile.TemporaryDirectory() as temp_directory:
            catalog_path = os.path.join(temp_directory, "models.json")
            # Minimal catalog with only one model
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

            # Verify models from multiple providers were discovered and added
            providers_in_catalog = {m["provider"] for m in updated_catalog["models"]}
            self.assertIn("codex", providers_in_catalog)
            self.assertIn("claude", providers_in_catalog)
            self.assertIn("xai", providers_in_catalog)
            self.assertIn("kimi", providers_in_catalog)
            self.assertIn("muse", providers_in_catalog)
            self.assertIn("deepseek", providers_in_catalog)
            self.assertIn("zai", providers_in_catalog)

            # Check individual models
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "6 Sol"))
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "Fable 5"))
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "Grok 4.6"))
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "Kimi K3"))
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "DeepSeek Pro 0813"))
            self.assertIsNotNone(resolve_catalog_model(updated_catalog, "GLM 5.2"))

            # Verify all provider backends were configured dynamically
            self.assertTrue(codex_backend.is_codex_model("6 Sol"))
            self.assertTrue(claude_backend.is_claude_model("Fable 5"))
            self.assertTrue(grok_backend.is_grok_model("Grok 4.6"))
            self.assertTrue(kimi_backend.is_kimi_model("Kimi K3"))
            self.assertTrue(muse_backend.is_muse_model("Muse Spark 1.2"))
            self.assertTrue(deepseek_backend.is_deepseek_model("DeepSeek Pro 0813"))
            self.assertTrue(zai_backend.is_zai_model("GLM 5.2"))

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
