import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import main


class CodexBackendTests(unittest.TestCase):
    def test_model_and_provider_mapping(self):
        self.assertEqual(codex_backend.codex_model_slug("5.6 Sol"), "gpt-5.6-sol")
        self.assertEqual(codex_backend.resolve_provider(None, "5.4"), "codex")
        self.assertEqual(
            codex_backend.resolve_provider(None, "Gemini 3.5 Flash (High)"),
            "agy",
        )
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("agy", "5.6 Terra")
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("codex", "Claude Sonnet 4.6 (Thinking)")

    def test_capability_validation(self):
        self.assertEqual(
            codex_backend.normalize_codex_effort("Ultra", "5.6 Sol"),
            ("Ultra", "ultra"),
        )
        self.assertEqual(
            codex_backend.normalize_codex_speed("Fast", "5.6 Luna"),
            ("Fast", "priority"),
        )
        with self.assertRaises(ValueError):
            codex_backend.normalize_codex_effort("Ultra", "5.6 Luna")
        with self.assertRaises(ValueError):
            codex_backend.normalize_codex_speed("Fast", "5.4 Mini")

    def test_build_new_codex_command_uses_stdin_and_workspace_sandbox(self):
        command = codex_backend.build_codex_command(
            "codex",
            "prompt stays off argv",
            "5.6 Sol",
            effort="Medium",
            speed="Standard",
            target="Sandbox",
        )
        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertEqual(command[-1], "-")
        self.assertNotIn("prompt stays off argv", command)
        self.assertIn("gpt-5.6-sol", command)
        self.assertIn("model_reasoning_effort=medium", command)
        self.assertIn("service_tier=default", command)
        self.assertIn("workspace-write", command)

    def test_build_resume_fast_ultra_command(self):
        command = codex_backend.build_codex_command(
            "codex",
            "continue",
            "5.6 Terra",
            effort="Ultra",
            speed="Fast",
            target="Real",
            conversation_id="codex_thread-123",
            image_paths=["C:/tmp/image.png"],
        )
        self.assertIn("model_reasoning_effort=ultra", command)
        self.assertIn("service_tier=priority", command)
        self.assertIn("features.fast_mode=true", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        resume_index = command.index("resume")
        self.assertEqual(command[resume_index + 1], "thread-123")
        self.assertEqual(command[-1], "-")

    def test_parse_jsonl_uses_last_completed_agent_message(self):
        output = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "abc"}),
                "not-json",
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "first"},
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "final"},
                    }
                ),
                json.dumps({"type": "turn.completed", "usage": {}}),
            ]
        )
        parsed = codex_backend.parse_codex_jsonl(output)
        self.assertEqual(parsed["session_id"], "abc")
        self.assertEqual(parsed["final_message"], "final")
        self.assertEqual(parsed["errors"], [])

    def test_codex_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "codex_conversations.json")
            with mock.patch.object(main, "CODEX_CONVERSATIONS_FILE", history_path):
                main.persist_codex_exchange(
                    "codex_session-1",
                    "project",
                    "5.6 Sol",
                    "Medium",
                    "Standard",
                    "hello",
                    "world",
                )
                record = main.get_codex_conversation("codex_session-1")

        self.assertIsNotNone(record)
        self.assertEqual(record["provider"], "codex")
        self.assertEqual(record["messages"][-1]["content"], "world")


if __name__ == "__main__":
    unittest.main()
