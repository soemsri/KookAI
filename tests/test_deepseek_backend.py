import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import deepseek_backend
import main


class DeepSeekBackendTests(unittest.TestCase):
    def test_model_provider_alias(self):
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek Pro 0813"), "deepseek-pro-0813")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek V4"), "deepseek-v4")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek R1"), "deepseek-reasoner")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek V3"), "deepseek-chat")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek Coder V2.5"), "deepseek-coder")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek Coder 33B"), "deepseek-coder-33b")
        self.assertEqual(deepseek_backend.deepseek_model_alias("DeepSeek Math 7B"), "deepseek-math")
        self.assertEqual(codex_backend.resolve_provider(None, "DeepSeek Pro 0813"), "deepseek")
        self.assertEqual(codex_backend.resolve_provider(None, "DeepSeek R1"), "deepseek")
        with self.assertRaises(ValueError):
            codex_backend.resolve_provider("agy", "DeepSeek Pro 0813")

    def test_build_deepseek_command(self):
        cmd = deepseek_backend.build_deepseek_command(
            "deepcode",
            "Explain this project",
            "DeepSeek Pro 0813",
            target="Sandbox",
            conversation_id="deepseek_session-123",
            cwd_path="/workspace/project",
        )
        self.assertEqual(cmd[0], "deepcode")
        self.assertIn("deepseek-pro-0813", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--cwd", cmd)
        self.assertIn("--session", cmd)
        self.assertIn("session-123", cmd)

    def test_parse_stream_json(self):
        output = "\n".join(
            [
                json.dumps({"type": "session.resume_hint", "session_id": "session-123"}),
                json.dumps({"role": "assistant", "content": "Hello"}),
                json.dumps({"role": "assistant", "content": " world"}),
            ]
        )

        parsed = deepseek_backend.parse_deepseek_stream_json(output)

        self.assertEqual(parsed["session_id"], "session-123")
        self.assertEqual(parsed["final_message"], "Hello world")
        self.assertEqual(parsed["errors"], [])

        error = deepseek_backend.parse_deepseek_stream_json(
            json.dumps({"type": "error", "message": "API key invalid"})
        )
        self.assertEqual(error["errors"], ["API key invalid"])

    def test_selected_cli_routes_to_deepseek(self):
        with mock.patch.object(
            main,
            "run_deepseek_cli",
            return_value=("done", "deepseek_session-1"),
        ) as run_deepseek:
            result = main.run_selected_cli(
                "hello",
                "DeepSeek Pro 0813",
                "temp-1",
                "Sandbox",
                "agy",
                provider="deepseek",
            )

        self.assertEqual(result, ("done", "deepseek_session-1"))
        run_deepseek.assert_called_once()

    def test_deepseek_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "deepseek_conversations.json")
            with mock.patch.object(main, "DEEPSEEK_CONVERSATIONS_FILE", history_path):
                main.persist_deepseek_exchange(
                    "deepseek_session-1",
                    "agy",
                    "DeepSeek Pro 0813",
                    "hello",
                    "hi",
                )
                record = main.get_deepseek_conversation("deepseek_session-1")

        self.assertEqual(record["provider"], "deepseek")
        self.assertEqual(record["session_id"], "session-1")
        self.assertEqual(len(record["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
