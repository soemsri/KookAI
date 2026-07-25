import json
import os
import tempfile
import unittest
from unittest import mock

import claude_backend
import codex_backend
import main


class ClaudeBackendTests(unittest.TestCase):
    def test_model_provider_and_effort_mapping(self):
        self.assertEqual(claude_backend.claude_model_slug("Fable 5"), "fable")
        self.assertEqual(claude_backend.claude_model_slug("Opus 4.8"), "claude-opus-4-8")
        self.assertEqual(codex_backend.resolve_provider(None, "Sonnet 5"), "claude")
        self.assertEqual(
            claude_backend.normalize_claude_effort("Extra", "Opus 5"),
            ("Extra", "xhigh"),
        )
        with self.assertRaises(ValueError):
            claude_backend.normalize_claude_effort("Extra", "Sonnet 4.6")

    def test_build_command_uses_stdin_and_safe_permissions(self):
        command = claude_backend.build_claude_command(
            "claude",
            "prompt stays off argv",
            "Sonnet 5",
            effort="Max",
            target="Sandbox",
            conversation_id="claude_session-123",
        )
        self.assertNotIn("prompt stays off argv", command)
        self.assertIn("stream-json", command)
        self.assertIn("sonnet", command)
        self.assertIn("max", command)
        self.assertIn("session-123", command)
        self.assertIn("dontAsk", command)
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_build_legacy_model_omits_unsupported_effort(self):
        command = claude_backend.build_claude_command(
            "claude",
            "hello",
            "Haiku 4.5",
            effort="Medium",
            target="Real",
        )
        self.assertNotIn("--effort", command)
        self.assertIn("--dangerously-skip-permissions", command)

    def test_parse_stream_uses_result_and_session(self):
        output = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "session_id": "abc"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "intermediate"}]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "result": "final",
                        "session_id": "abc",
                    }
                ),
            ]
        )
        parsed = claude_backend.parse_claude_stream_json(output)
        self.assertEqual(parsed["session_id"], "abc")
        self.assertEqual(parsed["final_message"], "final")
        self.assertEqual(parsed["errors"], [])

    def test_thinking_environment_can_disable_and_reenable(self):
        disabled = claude_backend.build_claude_environment(False)
        self.assertEqual(disabled["MAX_THINKING_TOKENS"], "0")
        self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", disabled)
        enabled = claude_backend.build_claude_environment(True)
        self.assertNotIn("MAX_THINKING_TOKENS", enabled)
        self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", enabled)

    def test_claude_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "claude_conversations.json")
            with mock.patch.object(main, "CLAUDE_CONVERSATIONS_FILE", history_path):
                main.persist_claude_exchange(
                    "claude_session-1",
                    "project",
                    "Sonnet 5",
                    "High",
                    True,
                    "hello",
                    "world",
                )
                record = main.get_claude_conversation("claude_session-1")

        self.assertIsNotNone(record)
        self.assertEqual(record["provider"], "claude")
        self.assertEqual(record["thinking"], True)
        self.assertEqual(record["messages"][-1]["content"], "world")


if __name__ == "__main__":
    unittest.main()
