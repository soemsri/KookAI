import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import muse_backend
import main


class MuseBackendTests(unittest.TestCase):
    def test_model_provider_alias_and_effort_mapping(self):
        self.assertEqual(muse_backend.muse_model_slug("Muse Spark 1.2"), "muse-spark-1.2")
        self.assertEqual(codex_backend.resolve_provider(None, "Muse Spark 1.2"), "muse")
        self.assertEqual(
            muse_backend.normalize_muse_effort("High", "Muse Spark 1.2"),
            ("High", "high"),
        )
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("agy", "Muse Spark 1.2")

    def test_build_new_sandbox_and_resumed_real_commands(self):
        sandbox_command = muse_backend.build_muse_command(
            "muse",
            "Explain this project",
            "Muse Spark 1.2",
            effort="Low",
            target="Sandbox",
            cwd_path="/workspace/project",
        )
        self.assertEqual(sandbox_command[0], "muse")
        self.assertIn("muse-spark-1.2", sandbox_command)
        self.assertIn("streaming-json", sandbox_command)
        self.assertIn("--no-auto-update", sandbox_command)
        self.assertIn("--always-approve", sandbox_command)
        self.assertIn("--sandbox", sandbox_command)
        self.assertIn("workspace", sandbox_command)
        self.assertIn("--cwd", sandbox_command)
        self.assertIn("low", sandbox_command)
        self.assertNotIn("--resume", sandbox_command)

        resumed_command = muse_backend.build_muse_command(
            "muse",
            "Continue",
            "Muse Spark 1.2",
            target="Real",
            conversation_id="muse_session-123",
        )
        self.assertIn("--resume", resumed_command)
        self.assertIn("session-123", resumed_command)
        self.assertNotIn("--sandbox", resumed_command)

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

        parsed = muse_backend.parse_muse_streaming_json(output)

        self.assertEqual(parsed["session_id"], "session-123")
        self.assertEqual(parsed["final_message"], "Hello world")
        self.assertEqual(parsed["stop_reason"], "EndTurn")
        self.assertEqual(parsed["errors"], [])

        error = muse_backend.parse_muse_streaming_json(
            json.dumps({"type": "error", "message": "Not signed in"})
        )
        self.assertEqual(error["errors"], ["Not signed in"])

    def test_selected_cli_routes_to_muse(self):
        with mock.patch.object(
            main,
            "run_muse_cli",
            return_value=("done", "muse_session-1"),
        ) as run_muse:
            result = main.run_selected_cli(
                "hello",
                "Muse Spark 1.2",
                "temp-1",
                "Sandbox",
                "agy",
                provider="muse",
            )

        self.assertEqual(result, ("done", "muse_session-1"))
        run_muse.assert_called_once()

    def test_muse_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "muse_conversations.json")
            with mock.patch.object(main, "MUSE_CONVERSATIONS_FILE", history_path):
                main.persist_muse_exchange(
                    "muse_session-1",
                    "agy",
                    "Muse Spark 1.2",
                    "Medium",
                    "hello",
                    "hi",
                )
                record = main.get_muse_conversation("muse_session-1")

        self.assertEqual(record["provider"], "muse")
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(record["effort"], "Medium")
        self.assertEqual(len(record["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
