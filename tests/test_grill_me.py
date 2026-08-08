import os
import json
import tempfile
import unittest
from unittest.mock import patch
import main

class TestGrillMeSkill(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace_dir = self.tmp_dir.name
        # Clear interview states
        main.interview_states.clear()

    def tearDown(self):
        self.tmp_dir.cleanup()
        main.interview_states.clear()

    @patch("main.run_selected_cli")
    def test_grill_me_flow_and_persistence(self, mock_cli):
        # 1. First call: /grill-me init
        q1_json = json.dumps({
            "type": "question",
            "question": "Should we use TypeScript or JavaScript for new components?",
            "options": ["(Recommended) TypeScript", "JavaScript"],
            "allow_other": True
        })
        mock_cli.return_value = (q1_json, "convo-123")

        req1 = main.ChatRequest(
            message="/grill-me",
            conversation_id="convo-123",
            workspace=self.workspace_dir,
            model="Gemini 3.6 Flash (High)",
            target="Antigravity CLI"
        )
        res1 = main.build_chat_response(req1)
        reply1 = res1.get("reply", "")
        self.assertIn("TypeScript", reply1)
        self.assertIn("convo-123", main.interview_states)

        # 2. Second call: User answers question 1
        summary_md = "# Design Alignment Summary\n\n1. TypeScript selected."
        mock_cli.return_value = (summary_md, "convo-123")

        req2 = main.ChatRequest(
            message="(Recommended) TypeScript",
            conversation_id="convo-123",
            workspace=self.workspace_dir,
            model="Gemini 3.6 Flash (High)",
            target="Antigravity CLI"
        )
        res2 = main.build_chat_response(req2)
        reply2 = res2.get("reply", "")
        self.assertIn("Design Alignment Summary", reply2)
        # State should be cleared upon conclusion
        self.assertNotIn("convo-123", main.interview_states)

        # Verify files created in workspace
        pref_json = os.path.join(self.workspace_dir, "alignment_preferences.json")
        pref_md = os.path.join(self.workspace_dir, "alignment_preferences.md")
        agents_md = os.path.join(self.workspace_dir, ".agents", "AGENTS.md")

        self.assertTrue(os.path.exists(pref_json))
        self.assertTrue(os.path.exists(pref_md))
        self.assertTrue(os.path.exists(agents_md))

        # Check valid JSON structure
        with open(pref_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertIn("summary", data)
            self.assertEqual(len(data.get("answers", [])), 1)
            self.assertEqual(data["answers"][0]["answer"], "(Recommended) TypeScript")

    def test_get_workspace_alignment_context(self):
        pref_file = os.path.join(self.workspace_dir, "alignment_preferences.json")
        with open(pref_file, "w", encoding="utf-8") as f:
            json.dump({
                "project": "test_project",
                "summary": "User prefers dark mode and REST APIs."
            }, f)

        ctx = main.get_workspace_alignment_context(self.workspace_dir)
        self.assertIn("[WORKSPACE DESIGN ALIGNMENT & PREFERENCES IN EFFECT]", ctx)
        self.assertIn("User prefers dark mode and REST APIs.", ctx)

if __name__ == "__main__":
    unittest.main()
