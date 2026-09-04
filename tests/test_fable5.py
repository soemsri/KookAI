import unittest
from unittest.mock import patch
import main

class TestFable5Command(unittest.TestCase):
    def test_fable5_help_when_no_arguments(self):
        req = main.ChatRequest(
            message="/fable5",
            conversation_id="convo-fable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("Fable-5 Framework", reply)
        self.assertIn("One-Command Reproduce", reply)
        self.assertIn("The 8-Step Loop", reply)

    @patch("main.run_selected_cli")
    def test_fable5_wrapped_execution(self, mock_cli):
        mock_cli.return_value = ("### 🎯 Fable-5 Framing (4-Box)\n- Goal: Fixed bug\nDone!", "convo-fable-test")
        
        req = main.ChatRequest(
            message="/fable5 fix race condition in session sync",
            conversation_id="convo-fable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("Fable-5 Framing", reply)
        
        # Verify wrapped prompt was sent to CLI
        mock_cli.assert_called_once()
        passed_prompt = mock_cli.call_args[0][0]
        self.assertIn("[SYSTEM: FABLE-5 8-STEP FRAMEWORK ACTIVATED]", passed_prompt)
        self.assertIn("fix race condition in session sync", passed_prompt)
        self.assertIn("MANDATORY INVARIANTS & INSTRUCTIONS", passed_prompt)

    def test_help_contains_fable5(self):
        req = main.ChatRequest(
            message="/help",
            conversation_id="convo-fable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("/fable5", reply)

if __name__ == "__main__":
    unittest.main()
