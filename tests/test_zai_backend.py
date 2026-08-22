import json
import os
import tempfile
import unittest
from unittest import mock

import codex_backend
import main
import zai_backend


class ZaiBackendTests(unittest.TestCase):
    def test_provider_and_catalog_alias_mapping(self):
        self.assertEqual(codex_backend.resolve_provider(None, "GLM 5.2"), "zai")
        self.assertEqual(
            zai_backend.zai_model_alias("GLM 4.7"),
            "zai-coding-plan/glm-4.7",
        )

    def test_command_uses_opencode_headless_model_and_resume(self):
        command = zai_backend.build_zai_command(
            "opencode", "hello", "GLM 5.2",
            conversation_id="zai_ses_123", target="Real",
        )
        self.assertEqual(command[:4], ["opencode", "run", "--format", "json"])
        self.assertIn("zai-coding-plan/glm-5.2", command)
        self.assertIn("--auto", command)
        self.assertEqual(command[-3:], ["--session", "ses_123", "hello"])

    def test_regular_zai_api_provider_can_be_selected(self):
        with mock.patch.dict(os.environ, {"ZAI_OPENCODE_PROVIDER": "zai"}):
            command = zai_backend.build_zai_command(
                "opencode", "hello", "GLM 4.7"
            )
        self.assertIn("zai/glm-4.7", command)

    def test_parse_opencode_json_events(self):
        output = "\n".join([
            json.dumps({"type": "step_start", "sessionID": "ses_123", "part": {"type": "step-start"}}),
            json.dumps({"type": "text", "sessionID": "ses_123", "part": {"type": "text", "text": "hello "}}),
            json.dumps({"type": "text", "sessionID": "ses_123", "part": {"type": "text", "text": "world"}}),
        ])
        parsed = zai_backend.parse_zai_stream_json(output)
        self.assertEqual(parsed["session_id"], "ses_123")
        self.assertEqual(parsed["final_message"], "hello world")
        self.assertEqual(parsed["errors"], [])

    def test_selected_cli_routes_to_zai(self):
        with mock.patch.object(
            main, "run_zai_cli", return_value=("done", "zai_ses_1")
        ) as run_zai:
            result = main.run_selected_cli(
                "hello", "GLM 5.2", "temp-1", "Sandbox", "agy",
                provider="zai",
            )
        self.assertEqual(result, ("done", "zai_ses_1"))
        run_zai.assert_called_once()

    def test_zai_history_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "zai_conversations.json")
            with mock.patch.object(main, "ZAI_CONVERSATIONS_FILE", path):
                main.persist_zai_exchange(
                    "zai_ses_1", "agy", "GLM 5.2", "hello", "hi"
                )
                record = main.get_zai_conversation("zai_ses_1")
        self.assertEqual(record["provider"], "zai")
        self.assertEqual(record["session_id"], "ses_1")
        self.assertEqual(len(record["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
