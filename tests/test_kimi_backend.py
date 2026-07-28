import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import kimi_backend
import main


class KimiBackendTests(unittest.TestCase):
    def test_model_provider_and_alias_mapping(self):
        self.assertEqual(
            kimi_backend.kimi_model_alias("Kimi K3"),
            "kimi-for-coding/k3",
        )
        self.assertEqual(codex_backend.resolve_provider(None, "Kimi K3"), "kimi")
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("agy", "Kimi K3")

    def test_build_new_and_resumed_kimi_commands(self):
        new_command = kimi_backend.build_kimi_command(
            "kimi",
            "Explain this project",
            "Kimi K3",
            target="Sandbox",
        )
        self.assertEqual(new_command[0], "kimi")
        self.assertIn("kimi-for-coding/k3", new_command)
        self.assertIn("Explain this project", new_command)
        self.assertNotIn("--session", new_command)

        resumed_command = kimi_backend.build_kimi_command(
            "kimi",
            "Continue",
            "Kimi K3",
            conversation_id="kimi_session-123",
        )
        self.assertEqual(
            resumed_command[-2:],
            ["--session", "session-123"],
        )

    def test_parse_kimi_stream_json(self):
        output = "\n".join(
            [
                json.dumps({"role": "assistant", "content": "Checking"}),
                json.dumps(
                    {
                        "role": "assistant",
                        "content": "Done",
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {"name": "Shell", "arguments": "{}"},
                            }
                        ],
                    }
                ),
                json.dumps(
                    {
                        "role": "meta",
                        "type": "session.resume_hint",
                        "session_id": "session-123",
                    }
                ),
            ]
        )

        parsed = kimi_backend.parse_kimi_stream_json(output)

        self.assertEqual(parsed["session_id"], "session-123")
        self.assertEqual(parsed["final_message"], "Checking\nDone")
        self.assertEqual(parsed["errors"], [])

    def test_parse_kimi_stream_json_captures_error_and_ignores_invalid_lines(self):
        output = "\n".join(
            [
                "not-json",
                json.dumps({"role": "error", "content": "Authentication required"}),
            ]
        )

        parsed = kimi_backend.parse_kimi_stream_json(output)

        self.assertIsNone(parsed["session_id"])
        self.assertEqual(parsed["final_message"], "")
        self.assertEqual(parsed["errors"], ["Authentication required"])

    def test_selected_cli_routes_to_kimi(self):
        with mock.patch.object(
            main,
            "run_kimi_cli",
            return_value=("done", "kimi_session-1"),
        ) as run_kimi:
            result = main.run_selected_cli(
                "hello",
                "Kimi K3",
                "temp-1",
                "Sandbox",
                "agy",
                provider="kimi",
            )

        self.assertEqual(result, ("done", "kimi_session-1"))
        run_kimi.assert_called_once()

    def test_kimi_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "kimi_conversations.json")
            with mock.patch.object(main, "KIMI_CONVERSATIONS_FILE", history_path):
                main.persist_kimi_exchange(
                    "kimi_session-1",
                    "agy",
                    "Kimi K3",
                    "hello",
                    "hi",
                )
                record = main.get_kimi_conversation("kimi_session-1")

        self.assertEqual(record["provider"], "kimi")
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(len(record["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
