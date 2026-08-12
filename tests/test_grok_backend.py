import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import grok_backend
import main


class GrokBackendTests(unittest.TestCase):
    def test_model_provider_alias_and_effort_mapping(self):
        self.assertEqual(grok_backend.grok_model_slug("Grok 4.6"), "grok-4.6")
        self.assertEqual(grok_backend.grok_model_slug("Grok 4.5"), "grok-4.5")
        self.assertEqual(codex_backend.resolve_provider(None, "Grok 4.6"), "xai")
        self.assertEqual(codex_backend.resolve_provider(None, "Grok 4.5"), "xai")
        self.assertEqual(
            grok_backend.normalize_grok_effort("High", "Grok 4.6"),
            ("High", "high"),
        )
        self.assertEqual(
            grok_backend.normalize_grok_effort("High", "Grok 4.5"),
            ("High", "high"),
        )
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("agy", "Grok 4.6")

    def test_build_new_sandbox_and_resumed_real_commands(self):
        sandbox_command = grok_backend.build_grok_command(
            "grok",
            "Explain this project",
            "Grok 4.5",
            effort="Low",
            target="Sandbox",
            cwd_path="/workspace/project",
        )
        self.assertEqual(sandbox_command[0], "grok")
        self.assertIn("grok-4.5", sandbox_command)
        self.assertIn("streaming-json", sandbox_command)
        self.assertIn("--no-auto-update", sandbox_command)
        self.assertIn("--always-approve", sandbox_command)
        self.assertIn("--sandbox", sandbox_command)
        self.assertIn("workspace", sandbox_command)
        self.assertIn("--cwd", sandbox_command)
        self.assertIn("low", sandbox_command)
        self.assertNotIn("--resume", sandbox_command)

        resumed_command = grok_backend.build_grok_command(
            "grok",
            "Continue",
            "Grok Build 0.1",
            target="Real",
            conversation_id="grok_session-123",
        )
        self.assertIn("--resume", resumed_command)
        self.assertIn("session-123", resumed_command)
        self.assertNotIn("--sandbox", resumed_command)
        self.assertNotIn("--effort", resumed_command)

    def test_parse_streaming_json_collects_chunks_session_and_errors(self):
        output = "\n".join(
            [
                json.dumps({"type": "thought", "data": "Checking files"}),
                json.dumps({"type": "text", "data": "Hello"}),
                json.dumps({"type": "text", "data": " world"}),
                json.dumps(
                    {
                        "type": "end",
                        "stopReason": "EndTurn",
                        "sessionId": "session-123",
                    }
                ),
            ]
        )

        parsed = grok_backend.parse_grok_streaming_json(output)

        self.assertEqual(parsed["session_id"], "session-123")
        self.assertEqual(parsed["final_message"], "Hello world")
        self.assertEqual(parsed["stop_reason"], "EndTurn")
        self.assertEqual(parsed["errors"], [])

        error = grok_backend.parse_grok_streaming_json(
            json.dumps({"type": "error", "message": "Not signed in"})
        )
        self.assertEqual(error["errors"], ["Not signed in"])

    def test_selected_cli_routes_to_xai(self):
        with mock.patch.object(
            main,
            "run_grok_cli",
            return_value=("done", "grok_session-1"),
        ) as run_grok:
            result = main.run_selected_cli(
                "hello",
                "Grok 4.5",
                "temp-1",
                "Sandbox",
                "agy",
                provider="xai",
            )

        self.assertEqual(result, ("done", "grok_session-1"))
        run_grok.assert_called_once()

    def test_grok_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "grok_conversations.json")
            with mock.patch.object(main, "GROK_CONVERSATIONS_FILE", history_path):
                main.persist_grok_exchange(
                    "grok_session-1",
                    "agy",
                    "Grok 4.5",
                    "Medium",
                    "hello",
                    "hi",
                )
                record = main.get_grok_conversation("grok_session-1")

        self.assertEqual(record["provider"], "xai")
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(record["effort"], "Medium")
        self.assertEqual(len(record["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
