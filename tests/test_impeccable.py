import unittest
from unittest.mock import patch
import main

class TestImpeccableCommand(unittest.TestCase):
    def test_impeccable_help_when_no_arguments(self):
        req = main.ChatRequest(
            message="/impeccable",
            conversation_id="convo-impeccable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("Impeccable Design Specialist", reply)
        self.assertIn("audit", reply)
        self.assertIn("polish", reply)
        self.assertIn("Common Commands", reply)

    @patch("main.run_selected_cli")
    def test_impeccable_wrapped_execution(self, mock_cli):
        mock_cli.return_value = ("### UI Polished\nRefined spacing and buttons.", "convo-impeccable-test")
        
        req = main.ChatRequest(
            message="/impeccable polish ChatScreen send button",
            conversation_id="convo-impeccable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("UI Polished", reply)
        
        # Verify wrapped prompt was sent to CLI
        mock_cli.assert_called_once()
        passed_prompt = mock_cli.call_args[0][0]
        self.assertIn("[SYSTEM: IMPECCABLE DESIGN SPECIALIST ACTIVATED]", passed_prompt)
        self.assertIn("polish ChatScreen send button", passed_prompt)
        self.assertIn("CORE PRINCIPLES & OPERATIONAL INVARIANTS", passed_prompt)

    def test_help_contains_impeccable(self):
        req = main.ChatRequest(
            message="/help",
            conversation_id="convo-impeccable-test",
            workspace="agy",
            model="Gemini 3.8 Flash (High)",
            target="Real"
        )
        res = main.build_chat_response(req)
        reply = res.get("reply", "")
        self.assertIn("/impeccable", reply)

if __name__ == "__main__":
    unittest.main()
