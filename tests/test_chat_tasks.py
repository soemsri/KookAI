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

if __name__ == "__main__":
    unittest.main()
