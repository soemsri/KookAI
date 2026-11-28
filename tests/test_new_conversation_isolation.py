import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import cli_manager
import main


class NewConversationIsolationTests(unittest.TestCase):
    def setUp(self):
        with main.chat_tasks_lock:
            main.chat_tasks.clear()
        main.chat_task_cancel_events.clear()
        with main._claimed_agy_cids_lock:
            main._claimed_agy_cids.clear()
        with main.convo_id_mapping_lock:
            main.convo_id_mapping.clear()
        with main.in_memory_chats_lock:
            main.in_memory_chats.clear()
        cli_manager.reset_session_locks()

    def tearDown(self):
        with main.chat_tasks_lock:
            running_ids = [
                tid
                for tid, t in main.chat_tasks.items()
                if t.get("status") in ("running", "queued")
            ]
        for tid in running_ids:
            main.cancel_chat_task(tid)
        time.sleep(0.05)
        with main.chat_tasks_lock:
            main.chat_tasks.clear()
        with main._claimed_agy_cids_lock:
            main._claimed_agy_cids.clear()
        with main.convo_id_mapping_lock:
            main.convo_id_mapping.clear()
        with main.in_memory_chats_lock:
            main.in_memory_chats.clear()
        cli_manager.reset_session_locks()

    def _wait_for_tasks(self, task_ids, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with main.chat_tasks_lock:
                if all(
                    main.chat_tasks.get(tid, {}).get("status")
                    in ("success", "error", "cancelled")
                    for tid in task_ids
                ):
                    return {tid: dict(main.chat_tasks[tid]) for tid in task_ids}
            time.sleep(0.02)
        self.fail(f"Timed out waiting for tasks {task_ids}")

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_new_conversation_in_same_project_while_agy_working_never_mixes_messages(
        self, _mock_verify_model, _mock_auth
    ):
        """Reproduces user bug: starting a New Conversation in KookAI while task 1 is still working
        must never steal task 2's agy DB or merge task 1's messages into task 2's conversation."""
        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as cli_dir, tempfile.TemporaryDirectory() as data_dir:
            kookai_dir = os.path.join(projects_root, "KookAI")
            os.makedirs(kookai_dir, exist_ok=True)
            convos_dir = os.path.join(cli_dir, "conversations")
            os.makedirs(convos_dir, exist_ok=True)

            cid_1 = "11111111-1111-4111-8111-111111111111"
            cid_2 = "22222222-2222-4222-8222-222222222222"
            task1_db_created = threading.Event()
            task2_db_created = threading.Event()
            allow_task2_finish = threading.Event()

            def write_agy_artifacts(cid: str, prompt_text: str, mtime_val: float):
                db_file = os.path.join(convos_dir, f"{cid}.db")
                with open(db_file, "wb") as f:
                    f.write(b"sqlite")
                os.utime(db_file, (mtime_val, mtime_val))
                log_dir = os.path.join(cli_dir, "brain", cid, ".system_generated", "logs")
                os.makedirs(log_dir, exist_ok=True)
                # Use default ensure_ascii=True to verify Unicode escape decoding (\u0exx) works too
                with open(os.path.join(log_dir, "transcript.jsonl"), "w", encoding="utf-8") as lf:
                    lf.write(
                        json.dumps(
                            {
                                "type": "USER_INPUT",
                                "content": prompt_text,
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )

            def fake_run_agy_command(cmd, cwd_path, **kwargs):
                prompt_arg = cmd[-1]
                base_ts = time.time()
                if "งานหน้าต่างที่ 1" in prompt_arg:
                    write_agy_artifacts(cid_1, prompt_arg, base_ts + 10.0)
                    task1_db_created.set()
                    # Wait until user clicks New Conversation and Task 2 creates cid_2.db (with newer mtime!)
                    assert task2_db_created.wait(timeout=3.0)
                    return MagicMock(returncode=0, stdout="คำตอบของหน้าต่างที่ 1", stderr="")
                else:
                    write_agy_artifacts(cid_2, prompt_arg, base_ts + 50.0)
                    task2_db_created.set()
                    assert allow_task2_finish.wait(timeout=3.0)
                    return MagicMock(returncode=0, stdout="คำตอบของหน้าต่างใหม่ที่ 2", stderr="")

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                patch.object(main, "ALL_ANTIGRAVITY_CLI_DIRS", [cli_dir]),
                patch.object(
                    main,
                    "CANONICAL_CONVERSATIONS_FILE",
                    os.path.join(data_dir, "conversations.json"),
                ),
                patch.object(
                    main,
                    "CONVERSATION_METADATA_FILE",
                    os.path.join(data_dir, "conversation_metadata.json"),
                ),
                patch("main.resolve_chat_model", return_value={
                    "id": "Gemini 4 Carbon (High)",
                    "label": "Gemini 4 Carbon (High)",
                    "provider": "agy",
                    "cli_model": "gemini-4-carbon-high",
                    "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
                }),
                patch("main.run_agy_command", side_effect=fake_run_agy_command),
            ):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.query_params = {}
                mock_req.client.host = "127.0.0.1"

                # 1. Start Task 1 in Window 1
                req1 = main.ChatRequest(
                    message="งานหน้าต่างที่ 1 กำลังทำค้างไว้",
                    model="Gemini 4 Carbon (High)",
                    workspace="KookAI",
                    target="Sandbox",
                    conversation_id="temp_KookAI_win1",
                    provider="agy",
                )
                r1 = asyncio.run(main.start_chat_task_endpoint(req1, mock_req))
                tid1 = json.loads(r1.body.decode("utf-8"))["task_id"]
                self.assertTrue(task1_db_created.wait(timeout=2.0))

                # 2. User clicks New Conversation -> Window 2 in SAME project KookAI while Task 1 is still working!
                req2 = main.ChatRequest(
                    message="งานหน้าต่างใหม่ที่ 2",
                    model="Gemini 4 Carbon (High)",
                    workspace="KookAI",
                    target="Sandbox",
                    conversation_id="temp_KookAI_win2",
                    provider="agy",
                )
                r2 = asyncio.run(main.start_chat_task_endpoint(req2, mock_req))
                tid2 = json.loads(r2.body.decode("utf-8"))["task_id"]

                # Wait for Task 1 to finish while Task 2 is still running
                self._wait_for_tasks([tid1])
                allow_task2_finish.set()
                done_all = self._wait_for_tasks([tid1, tid2])

                res1 = done_all[tid1]["result"]
                res2 = done_all[tid2]["result"]

                self.assertEqual(res1["conversation_id"], cid_1)
                self.assertEqual(res2["conversation_id"], cid_2)
                self.assertNotEqual(res1["conversation_id"], res2["conversation_id"])

                # Verify Window 2's messages NEVER contain Window 1's prompt or reply!
                detail2_resp = asyncio.run(main.get_conversation_details(cid_2, mock_req))
                detail2 = json.loads(detail2_resp.body.decode("utf-8"))
                self.assertEqual(
                    detail2["messages"],
                    [
                        {"role": "user", "content": "งานหน้าต่างใหม่ที่ 2"},
                        {"role": "assistant", "content": "คำตอบของหน้าต่างใหม่ที่ 2"},
                    ],
                )

                detail1_resp = asyncio.run(main.get_conversation_details(cid_1, mock_req))
                detail1 = json.loads(detail1_resp.body.decode("utf-8"))
                self.assertEqual(
                    detail1["messages"],
                    [
                        {"role": "user", "content": "งานหน้าต่างที่ 1 กำลังทำค้างไว้"},
                        {"role": "assistant", "content": "คำตอบของหน้าต่างที่ 1"},
                    ],
                )

    def test_already_claimed_agy_db_is_never_reused_by_second_conversation(self):
        """If the only new DB on disk was already claimed by another concurrent session,
        run_agy_cli must keep the second session isolated under its own conversation_id."""
        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as cli_dir:
            os.makedirs(os.path.join(projects_root, "KookAI"), exist_ok=True)
            convos_dir = os.path.join(cli_dir, "conversations")
            os.makedirs(convos_dir, exist_ok=True)
            claimed_cid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
            with open(os.path.join(convos_dir, f"{claimed_cid}.db"), "wb") as f:
                f.write(b"sqlite")
            with main._claimed_agy_cids_lock:
                main._claimed_agy_cids.add(claimed_cid)

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                patch.object(main, "ALL_ANTIGRAVITY_CLI_DIRS", [cli_dir]),
                patch("main.get_existing_db_ids", side_effect=[set(), {claimed_cid}]),
                patch(
                    "main.run_agy_command",
                    return_value=MagicMock(returncode=0, stdout="Isolated reply", stderr=""),
                ),
            ):
                reply, resolved_cid = main.run_agy_cli(
                    message="same prompt",
                    model_ui_name="Gemini 4 Carbon (High)",
                    conversation_id="temp_KookAI_isolated",
                    target="Sandbox",
                    workspace="KookAI",
                )
                self.assertEqual(reply, "Isolated reply")
                self.assertEqual(resolved_cid, "temp_KookAI_isolated")

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_in_flight_conversation_visible_in_history_and_details_and_resolves_temp_mapping(
        self, _mock_verify_model, _mock_auth
    ):
        hold_task = threading.Event()
        task_entered = threading.Event()

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            os.makedirs(os.path.join(projects_root, "KookAI"), exist_ok=True)

            def fake_run_selected_cli(message, model_ui_name, conversation_id, *args, **kwargs):
                task_entered.set()
                hold_task.wait(timeout=3.0)
                with main.convo_id_mapping_lock:
                    main.convo_id_mapping[f"codex:KookAI:{conversation_id}"] = "codex_resolved_xyz"
                return "เสร็จเรียบร้อย", "codex_resolved_xyz"

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                patch.object(main, "SEED_CONVERSATIONS", []),
                patch.object(
                    main,
                    "CANONICAL_CONVERSATIONS_FILE",
                    os.path.join(data_dir, "conversations.json"),
                ),
                patch.object(
                    main,
                    "CODEX_CONVERSATIONS_FILE",
                    os.path.join(data_dir, "codex_conversations.json"),
                ),
                patch.object(
                    main,
                    "CONVERSATION_METADATA_FILE",
                    os.path.join(data_dir, "conversation_metadata.json"),
                ),
                patch("main.get_real_conversations", return_value=[]),
                patch("main.resolve_chat_model", return_value={
                    "id": "6.1 Sol",
                    "label": "6.1 Sol",
                    "provider": "codex",
                    "cli_model": "gpt-6.1-sol",
                    "capabilities": {"effort": ["Medium"], "speed": ["Standard"], "thinking": False, "thinking_required": False},
                }),
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.query_params = {}
                mock_req.client.host = "127.0.0.1"

                req = main.ChatRequest(
                    message="สั่งงานค้างไว้ในหน้าต่างแรก",
                    model="6.1 Sol",
                    workspace="KookAI",
                    target="Sandbox",
                    conversation_id="temp_KookAI_inflight",
                    provider="codex",
                    effort="Medium",
                    speed="Standard",
                )
                start_resp = asyncio.run(main.start_chat_task_endpoint(req, mock_req))
                tid = json.loads(start_resp.body.decode("utf-8"))["task_id"]
                self.assertTrue(task_entered.wait(timeout=2.0))

                # While still running, /api/chat-history and /api/conversations include the active session
                hist_resp = asyncio.run(main.get_chat_history(mock_req))
                hist_convos = json.loads(hist_resp.body.decode("utf-8"))["conversations"]
                self.assertTrue(any(c["id"] == "temp_KookAI_inflight" for c in hist_convos))

                convo_resp = asyncio.run(main.get_conversations(mock_req, project="KookAI"))
                proj_convos = json.loads(convo_resp.body.decode("utf-8"))["conversations"]
                self.assertTrue(any(c["id"] == "temp_KookAI_inflight" for c in proj_convos))

                # And /api/conversation/temp_KookAI_inflight includes the in-flight user message
                inflight_detail_resp = asyncio.run(
                    main.get_conversation_details("temp_KookAI_inflight", mock_req)
                )
                inflight_detail = json.loads(inflight_detail_resp.body.decode("utf-8"))
                self.assertEqual(
                    inflight_detail["messages"],
                    [{"role": "user", "content": "สั่งงานค้างไว้ในหน้าต่างแรก"}],
                )

                # Once finished and mapped via codex:KookAI:temp_KookAI_inflight -> codex_resolved_xyz,
                # querying temp_KookAI_inflight still resolves cleanly!
                hold_task.set()
                self._wait_for_tasks([tid])

                mapped_detail_resp = asyncio.run(
                    main.get_conversation_details("temp_KookAI_inflight", mock_req)
                )
                mapped_detail = json.loads(mapped_detail_resp.body.decode("utf-8"))
                self.assertEqual(
                    mapped_detail["messages"],
                    [
                        {"role": "user", "content": "สั่งงานค้างไว้ในหน้าต่างแรก"},
                        {"role": "assistant", "content": "เสร็จเรียบร้อย"},
                    ],
                )


if __name__ == "__main__":
    unittest.main()
