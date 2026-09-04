import unittest
import asyncio
import json
import os
import tempfile
from unittest.mock import MagicMock, patch
import threading
from fastapi import HTTPException
import main
from main import (
    chat_tasks,
    chat_tasks_lock,
    list_chat_tasks_endpoint,
    get_chat_task_endpoint,
    cancel_chat_task_endpoint,
    cancel_chat_task_by_body_endpoint,
    cancel_chat_task,
    chat_task_cancel_events,
    chat_task_active_procs,
    chat_task_active_procs_lock,
    AgentCommandCancelled,
    CancelTaskRequest,
)

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
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    main,
                    "CANONICAL_CONVERSATIONS_FILE",
                    os.path.join(temp_dir, "conversations.json"),
                ),
                patch.object(
                    main,
                    "CONVERSATION_METADATA_FILE",
                    os.path.join(temp_dir, "conversation_metadata.json"),
                ),
                patch(
                    "main.run_selected_cli",
                    return_value={"reply": "ok", "conversation_id": "test_convo"},
                ),
            ):
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
            with tempfile.TemporaryDirectory() as temp_dir:
                with (
                    patch.object(
                        main,
                        "CANONICAL_CONVERSATIONS_FILE",
                        os.path.join(temp_dir, "conversations.json"),
                    ),
                    patch.object(
                        main,
                        "CONVERSATION_METADATA_FILE",
                        os.path.join(temp_dir, "conversation_metadata.json"),
                    ),
                    patch(
                        "main.run_selected_cli",
                        return_value=("ok", "video-prompt-test"),
                    ) as run_cli,
                ):
                    build_chat_response(request)

                execution_prompt = run_cli.call_args.args[0]
                self.assertNotIn("file://", execution_prompt)
                self.assertIn("Test transcript", execution_prompt)
                self.assertIn("file://", in_memory_chats["video-prompt-test"][0]["content"])
        finally:
            in_memory_chats.pop("video-prompt-test", None)

    def test_agy_conversation_survives_in_memory_cache_reset(self):
        conversation_id = "temp_KookAI_persisted"
        with tempfile.TemporaryDirectory() as temp_dir:
            canonical_path = os.path.join(temp_dir, "conversations.json")
            metadata_path = os.path.join(temp_dir, "conversation_metadata.json")
            with (
                patch.object(main, "CANONICAL_CONVERSATIONS_FILE", canonical_path),
                patch.object(main, "CONVERSATION_METADATA_FILE", metadata_path),
                patch(
                    "main.run_selected_cli",
                    return_value=("persisted reply", conversation_id),
                ),
            ):
                request = main.ChatRequest(
                    message="latest prompt",
                    model="Gemini 3.6 Flash (High)",
                    conversation_id=conversation_id,
                    provider="agy",
                    workspace="KookAI",
                    target="Sandbox",
                )
                try:
                    main.build_chat_response(request)
                    main.in_memory_chats.pop(conversation_id, None)
                    record = main.get_canonical_conversation(conversation_id)

                    mock_request = MagicMock()
                    mock_request.headers = {}
                    mock_request.query_params = {}
                    with patch("main.verify_authorization", return_value=True):
                        detail_response = asyncio.run(
                            main.get_conversation_details(conversation_id, mock_request)
                        )
                        history_response = asyncio.run(
                            main.get_chat_history(mock_request)
                        )
                    detail = json.loads(detail_response.body.decode("utf-8"))
                    history = json.loads(history_response.body.decode("utf-8"))
                finally:
                    main.in_memory_chats.pop(conversation_id, None)

            self.assertIsNotNone(record)
            self.assertEqual(record["project"], "KookAI")
            self.assertEqual(record["provider"], "agy")
            self.assertEqual(
                record["messages"],
                [
                    {"role": "user", "content": "latest prompt"},
                    {"role": "assistant", "content": "persisted reply"},
                ],
            )
            self.assertEqual(detail["project"], "KookAI")
            self.assertEqual(detail["provider"], "agy")
            self.assertEqual(detail["messages"], record["messages"])
            self.assertTrue(
                any(
                    conversation["id"] == conversation_id
                    for conversation in history["conversations"]
                )
            )

            with open(canonical_path, "r", encoding="utf-8") as persisted_file:
                persisted = json.load(persisted_file)
            self.assertIn(conversation_id, persisted)

    @patch("main.verify_authorization")
    def test_cancel_chat_task_by_id_success(self, mock_auth):
        mock_auth.return_value = True
        with chat_tasks_lock:
            chat_tasks["task_cancel_1"] = {
                "task_id": "task_cancel_1",
                "status": "running",
                "conversation_id": "convo_cancel_1",
                "message": "Long running query",
                "events": [{"seq": 0, "type": "progress", "message": "Thinking..."}],
                "result": None,
                "created_at": 1000.0,
                "completed_at": None,
            }

        mock_req = MagicMock()
        res = asyncio.run(cancel_chat_task_endpoint("task_cancel_1", mock_req))
        data = json.loads(res.body.decode("utf-8"))

        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "cancelled")
        self.assertEqual(data.get("task_id"), "task_cancel_1")

        with chat_tasks_lock:
            task = chat_tasks["task_cancel_1"]
            self.assertEqual(task["status"], "cancelled")
            self.assertIsNotNone(task["completed_at"])
            self.assertEqual(task["result"]["status"], "cancelled")
            self.assertIn("cancelled", task["result"]["reply"].lower())
            self.assertTrue(any("cancelled" in ev["message"].lower() for ev in task["events"]))

    @patch("main.verify_authorization")
    def test_cancel_chat_task_by_body(self, mock_auth):
        mock_auth.return_value = True
        with chat_tasks_lock:
            chat_tasks["task_body_1"] = {
                "task_id": "task_body_1",
                "status": "running",
                "conversation_id": "convo_body_1",
                "message": "Task to cancel by body task_id",
                "events": [],
                "result": None,
            }
            chat_tasks["task_body_2"] = {
                "task_id": "task_body_2",
                "status": "running",
                "conversation_id": "convo_body_2",
                "message": "Task to cancel by convo_id",
                "events": [],
                "result": None,
            }

        mock_req = MagicMock()
        # 1. Cancel by task_id in body
        res1 = asyncio.run(cancel_chat_task_by_body_endpoint(mock_req, CancelTaskRequest(task_id="task_body_1")))
        data1 = json.loads(res1.body.decode("utf-8"))
        self.assertTrue(data1.get("success"))
        self.assertEqual(data1.get("status"), "cancelled")
        self.assertEqual(chat_tasks["task_body_1"]["status"], "cancelled")

        # 2. Cancel by conversation_id in body
        res2 = asyncio.run(cancel_chat_task_by_body_endpoint(mock_req, CancelTaskRequest(conversation_id="convo_body_2")))
        data2 = json.loads(res2.body.decode("utf-8"))
        self.assertEqual(data2.get("status"), "cancelled")
        self.assertEqual(chat_tasks["task_body_2"]["status"], "cancelled")

    @patch("main.verify_authorization")
    def test_cancel_already_finished_task(self, mock_auth):
        mock_auth.return_value = True
        with chat_tasks_lock:
            chat_tasks["finished_task"] = {
                "task_id": "finished_task",
                "status": "success",
                "conversation_id": "convo_done",
                "message": "Done message",
                "events": [],
                "result": {"reply": "All done", "status": "success"},
            }

        mock_req = MagicMock()
        res = asyncio.run(cancel_chat_task_endpoint("finished_task", mock_req))
        data = json.loads(res.body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "success")
        self.assertIn("already", data.get("message", "").lower())
        # Ensure result was not overwritten
        self.assertEqual(chat_tasks["finished_task"]["result"]["reply"], "All done")

    @patch("main.verify_authorization")
    def test_cancel_nonexistent_task(self, mock_auth):
        mock_auth.return_value = True
        mock_req = MagicMock()
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(cancel_chat_task_endpoint("nonexistent_tid", mock_req))
        self.assertEqual(cm.exception.status_code, 404)

    @patch("main.kill_process_tree")
    def test_cancel_terminates_registered_process(self, mock_kill):
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with chat_tasks_lock:
            chat_tasks["proc_task"] = {
                "task_id": "proc_task",
                "status": "running",
                "conversation_id": "convo_proc",
                "events": [],
                "result": None,
            }
        with chat_task_active_procs_lock:
            chat_task_active_procs["proc_task"] = (mock_proc, 99999)

        try:
            cancel_chat_task("proc_task")
            mock_kill.assert_called_once_with(mock_proc, 99999)
        finally:
            with chat_task_active_procs_lock:
                chat_task_active_procs.pop("proc_task", None)

    def test_run_selected_cli_no_failover_on_cancellation(self):
        cancel_evt = threading.Event()
        cancel_evt.set()

        with self.assertRaises(AgentCommandCancelled):
            main.run_selected_cli(
                message="Will be cancelled",
                model_ui_name="Gemini 3.6 Flash (High)",
                conversation_id="cancel_conv",
                target="Sandbox",
                workspace="KookAI",
                provider="agy",
                cancel_event=cancel_evt,
            )

    @patch("subprocess.Popen")
    def test_run_agent_command_raises_on_cancel_event(self, mock_popen):
        cancel_evt = threading.Event()
        cancel_evt.set()

        with self.assertRaises(AgentCommandCancelled):
            main.run_agent_command(
                ["echo", "hello"],
                os.getcwd(),
                cancel_event=cancel_evt,
            )
        # Should raise before even launching Popen
        mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
