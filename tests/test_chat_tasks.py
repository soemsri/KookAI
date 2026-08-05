import unittest
import asyncio
from unittest.mock import MagicMock, patch
from main import chat_tasks, chat_tasks_lock, list_chat_tasks_endpoint, get_chat_task_endpoint

class TestChatTasks(unittest.TestCase):
    def setUp(self):
        with chat_tasks_lock:
            chat_tasks.clear()

    @patch("main.verify_authorization")
    def test_list_active_chat_tasks(self, mock_auth):
        mock_auth.return_value = True
        with chat_tasks_lock:
            chat_tasks["task1"] = {
                "task_id": "task1",
                "status": "running",
                "conversation_id": "convo_123",
                "message": "Test prompt",
                "workspace": "agy-mobile",
                "events": [{"seq": 0, "type": "progress", "message": "Thinking..."}],
                "result": None
            }
            chat_tasks["task2"] = {
                "task_id": "task2",
                "status": "success",
                "conversation_id": "convo_456",
                "message": "Old prompt",
                "workspace": "agy-mobile",
                "events": [],
                "result": {"reply": "Done"}
            }

        mock_req = MagicMock()
        res = asyncio.run(list_chat_tasks_endpoint(mock_req, active_only=True))
        data = res.body.decode("utf-8")
        import json
        json_data = json.loads(data)
        self.assertIn("tasks", json_data)
        self.assertEqual(len(json_data["tasks"]), 1)
        self.assertEqual(json_data["tasks"][0]["task_id"], "task1")
        self.assertEqual(json_data["tasks"][0]["message"], "Test prompt")

    @patch("main.verify_authorization")
    def test_get_chat_task_by_id(self, mock_auth):
        mock_auth.return_value = True
        with chat_tasks_lock:
            chat_tasks["task1"] = {
                "task_id": "task1",
                "status": "running",
                "conversation_id": "convo_123",
                "message": "Test prompt",
                "workspace": "agy-mobile",
                "events": [{"seq": 0, "type": "progress", "message": "Working..."}],
                "result": None
            }

        mock_req = MagicMock()
        res = asyncio.run(get_chat_task_endpoint("task1", mock_req))
        data = res.body.decode("utf-8")
        import json
        json_data = json.loads(data)
        self.assertEqual(json_data["task_id"], "task1")
        self.assertEqual(json_data["message"], "Test prompt")
        self.assertEqual(len(json_data["events"]), 1)

    @patch("main.process_video_source")
    def test_video_processing_progress_callback_signature(self, mock_process_video):
        from main import build_chat_response, ChatRequest
        mock_process_video.return_value = {
            "frame_paths": [],
            "prompt_summary": "Video analysis data..."
        }
        events = []
        def mock_callback(event_type, message):
            events.append((event_type, message))

        req = ChatRequest(
            message="/watch https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            model="Gemini 3.6 Flash (High)",
            conversation_id="test_convo",
            provider="agy",
            workspace="agy",
            target="Sandbox"
        )
        with patch("main.run_selected_cli", return_value={"reply": "ok", "conversation_id": "test_convo"}):
            res = build_chat_response(req, progress_callback=mock_callback)

        self.assertTrue(any("🎥 Processing video" in msg for et, msg in events))

    @patch("main.process_video_source")
    def test_agy_video_frames_stay_in_history_but_not_cli_prompt(self, mock_process_video):
        from main import build_chat_response, ChatRequest, in_memory_chats

        frame_path = "D:/workspace/.kookai_cache/video/v_test/frames/frame_0001.jpg"
        mock_process_video.return_value = {
            "frame_paths": [frame_path],
            "prompt_summary": "### Video Transcript\n[00:00] Test transcript",
        }
        request = ChatRequest(
            message="/watch https://example.com/test.mp4",
            model="Gemini 3.6 Flash (High)",
            conversation_id="video-prompt-test",
            provider="agy",
            workspace="KookAI",
            target="Sandbox",
        )

        try:
            with patch("main.run_selected_cli", return_value=("ok", "video-prompt-test")) as run_cli:
                build_chat_response(request)

            execution_prompt = run_cli.call_args.args[0]
            self.assertNotIn("file://", execution_prompt)
            self.assertIn("Test transcript", execution_prompt)
            self.assertIn("file://", in_memory_chats["video-prompt-test"][0]["content"])
        finally:
            in_memory_chats.pop("video-prompt-test", None)


if __name__ == "__main__":
    unittest.main()
