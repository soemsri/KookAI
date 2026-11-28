import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import cli_manager
import main


class MultiProjectConcurrencyTests(unittest.TestCase):
    def setUp(self):
        with main.chat_tasks_lock:
            main.chat_tasks.clear()
        main.chat_task_cancel_events.clear()
        with main._claimed_agy_cids_lock:
            main._claimed_agy_cids.clear()
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
            time.sleep(0.03)
        self.fail(f"Timed out waiting for tasks {task_ids}")

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_three_projects_execute_truly_in_parallel_without_cross_talk(
        self, _mock_verify_model, _mock_auth
    ):
        barrier = threading.Barrier(3)
        observed_workspaces = {}
        observed_lock = threading.Lock()

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            for proj in ("AlphaApp", "BetaService", "GammaWeb"):
                os.mkdir(os.path.join(projects_root, proj))

            def fake_run_selected_cli(
                message,
                model_ui_name,
                conversation_id,
                target,
                workspace,
                *args,
                **kwargs,
            ):
                # All 3 project threads must arrive simultaneously or Barrier raises BrokenBarrierError
                barrier.wait(timeout=2.5)
                with observed_lock:
                    observed_workspaces[workspace] = message
                resolved_cid = f"resolved_{workspace}"
                return f"Completed work in {workspace}", resolved_cid

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
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
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.client.host = "127.0.0.1"

                started_ids = []
                for proj in ("AlphaApp", "BetaService", "GammaWeb"):
                    req = main.ChatRequest(
                        message=f"Build feature for {proj}",
                        model="Gemini 3.6 Flash (High)",
                        workspace=proj,
                        target="Sandbox",
                        conversation_id=f"temp_{proj}_1",
                        provider="agy",
                    )
                    resp = asyncio.run(main.start_chat_task_endpoint(req, mock_req))
                    payload = json.loads(resp.body.decode("utf-8"))
                    self.assertEqual(payload["workspace"], proj)
                    started_ids.append(payload["task_id"])

                finished = self._wait_for_tasks(started_ids)
                for tid in started_ids:
                    self.assertEqual(finished[tid]["status"], "success")
                    ws = finished[tid]["workspace"]
                    self.assertEqual(
                        finished[tid]["result"]["reply"], f"Completed work in {ws}"
                    )
                    self.assertEqual(
                        finished[tid]["result"]["conversation_id"], f"resolved_{ws}"
                    )
                    canonical = main.get_canonical_conversation(f"resolved_{ws}")
                    self.assertIsNotNone(canonical)
                    self.assertEqual(canonical["project"], ws)
                    self.assertEqual(len(canonical["messages"]), 2)
                    self.assertIn(ws, canonical["messages"][1]["content"])

                self.assertEqual(
                    set(observed_workspaces.keys()),
                    {"AlphaApp", "BetaService", "GammaWeb"},
                )

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_batch_endpoint_dispatches_multiple_projects_simultaneously(
        self, _mock_verify_model, _mock_auth
    ):
        barrier = threading.Barrier(3)

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            for proj in ("ProjOne", "ProjTwo", "ProjThree"):
                os.mkdir(os.path.join(projects_root, proj))

            def fake_run_selected_cli(
                message, model_ui_name, conversation_id, target, workspace, *args, **kwargs
            ):
                barrier.wait(timeout=2.5)
                return f"Batch result for {workspace}: {message}", conversation_id

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
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
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {"X-Device-Alias": "WebConsole"}
                mock_req.client.host = "127.0.0.1"

                batch_req = main.BatchChatTaskRequest(
                    message="Run test suite and report summary",
                    model="Gemini 3.6 Flash (High)",
                    workspaces=["ProjOne", "ProjTwo", "ProjThree", "projone"],
                    target="Sandbox",
                    provider="agy",
                )
                resp = asyncio.run(main.start_batch_chat_tasks_endpoint(batch_req, mock_req))
                body = json.loads(resp.body.decode("utf-8"))

                self.assertEqual(body["status"], "running")
                self.assertEqual(body["count"], 3)  # Case-insensitive deduplication
                self.assertTrue(body["batch_id"].startswith("batch_"))
                task_ids = [t["task_id"] for t in body["tasks"]]
                self.assertEqual(
                    [t["workspace"] for t in body["tasks"]],
                    ["ProjOne", "ProjTwo", "ProjThree"],
                )
                # Every project gets its own distinct conversation ID
                self.assertEqual(len({t["conversation_id"] for t in body["tasks"]}), 3)

                finished = self._wait_for_tasks(task_ids)
                for t in body["tasks"]:
                    done_task = finished[t["task_id"]]
                    self.assertEqual(done_task["status"], "success")
                    self.assertIn(
                        f"Batch result for {t['workspace']}",
                        done_task["result"]["reply"],
                    )

                # Filter tasks by batch_id
                list_resp = asyncio.run(
                    main.list_chat_tasks_endpoint(
                        mock_req, batch_id=body["batch_id"], active_only=False
                    )
                )
                listed = json.loads(list_resp.body.decode("utf-8"))["tasks"]
                self.assertEqual(len(listed), 3)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_batch_rejects_unknown_project_before_spawning_any_task(
        self, _mock_verify_model, _mock_auth
    ):
        with tempfile.TemporaryDirectory() as projects_root:
            os.mkdir(os.path.join(projects_root, "ValidProj"))
            with patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.client.host = "127.0.0.1"
                batch_req = main.BatchChatTaskRequest(
                    message="Audit dependencies",
                    model="Gemini 3.6 Flash (High)",
                    workspaces=["ValidProj", "MissingProj"],
                    target="Sandbox",
                    provider="agy",
                )
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(main.start_batch_chat_tasks_endpoint(batch_req, mock_req))
                self.assertEqual(ctx.exception.status_code, 422)
                with main.chat_tasks_lock:
                    self.assertEqual(len(main.chat_tasks), 0)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_per_session_mutex_rejects_same_conversation_with_409_but_allows_other_projects(
        self, _mock_verify_model, _mock_auth
    ):
        hold_event = threading.Event()
        entered_proj_a = threading.Event()

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            os.mkdir(os.path.join(projects_root, "ProjectA"))
            os.mkdir(os.path.join(projects_root, "ProjectB"))

            def fake_run_selected_cli(
                message, model_ui_name, conversation_id, target, workspace, *args, **kwargs
            ):
                if workspace == "ProjectA" and conversation_id == "shared_cid":
                    entered_proj_a.set()
                    hold_event.wait(timeout=3.0)
                return f"Done {workspace}:{conversation_id}", conversation_id

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
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
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {"X-Device-Alias": "MobilePhone"}
                mock_req.client.host = "127.0.0.1"

                req_a1 = main.ChatRequest(
                    message="First command",
                    model="Gemini 3.6 Flash (High)",
                    workspace="ProjectA",
                    target="Sandbox",
                    conversation_id="shared_cid",
                    provider="agy",
                )
                resp_a1 = asyncio.run(main.start_chat_task_endpoint(req_a1, mock_req))
                tid_a1 = json.loads(resp_a1.body.decode("utf-8"))["task_id"]
                self.assertTrue(entered_proj_a.wait(timeout=2.0))

                # Duplicate concurrent write to exact same ProjectA:shared_cid -> 409 Conflict
                with self.assertRaises(HTTPException) as conflict_ctx:
                    asyncio.run(main.start_chat_task_endpoint(req_a1, mock_req))
                self.assertEqual(conflict_ctx.exception.status_code, 409)

                # Different project (ProjectB) with same cid string -> succeeds immediately!
                req_b = main.ChatRequest(
                    message="Parallel command in ProjectB",
                    model="Gemini 3.6 Flash (High)",
                    workspace="ProjectB",
                    target="Sandbox",
                    conversation_id="shared_cid",
                    provider="agy",
                )
                resp_b = asyncio.run(main.start_chat_task_endpoint(req_b, mock_req))
                tid_b = json.loads(resp_b.body.decode("utf-8"))["task_id"]

                # Different conversation in ProjectA -> also succeeds immediately!
                req_a2 = main.ChatRequest(
                    message="Second parallel chat in ProjectA",
                    model="Gemini 3.6 Flash (High)",
                    workspace="ProjectA",
                    target="Sandbox",
                    conversation_id="other_cid",
                    provider="agy",
                )
                resp_a2 = asyncio.run(main.start_chat_task_endpoint(req_a2, mock_req))
                tid_a2 = json.loads(resp_a2.body.decode("utf-8"))["task_id"]

                # Both tid_b and tid_a2 finish even while tid_a1 is still held!
                done_others = self._wait_for_tasks([tid_b, tid_a2])
                self.assertEqual(done_others[tid_b]["status"], "success")
                self.assertEqual(done_others[tid_a2]["status"], "success")

                # Release tid_a1 and confirm lock is freed afterward
                hold_event.set()
                done_a1 = self._wait_for_tasks([tid_a1])
                self.assertEqual(done_a1[tid_a1]["status"], "success")
                self.assertEqual(cli_manager.get_active_session_locks(), {})

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_cancel_by_workspace_leaves_other_projects_running(
        self, _mock_verify_model, _mock_auth
    ):
        started_a = threading.Event()
        release_b = threading.Event()

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            os.mkdir(os.path.join(projects_root, "CancelMeProj"))
            os.mkdir(os.path.join(projects_root, "KeepRunningProj"))

            def fake_run_selected_cli(
                message, model_ui_name, conversation_id, target, workspace, *args, **kwargs
            ):
                cancel_ev = kwargs.get("cancel_event")
                if workspace == "CancelMeProj":
                    started_a.set()
                    while not (cancel_ev and cancel_ev.is_set()):
                        time.sleep(0.02)
                    raise main.AgentCommandCancelled("Cancelled")
                release_b.wait(timeout=3.0)
                return "KeepRunningProj finished cleanly", conversation_id

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
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
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.client.host = "127.0.0.1"

                r1 = asyncio.run(
                    main.start_chat_task_endpoint(
                        main.ChatRequest(
                            message="Long task",
                            model="Gemini 3.6 Flash (High)",
                            workspace="CancelMeProj",
                            target="Sandbox",
                            conversation_id="c1",
                            provider="agy",
                        ),
                        mock_req,
                    )
                )
                r2 = asyncio.run(
                    main.start_chat_task_endpoint(
                        main.ChatRequest(
                            message="Important task",
                            model="Gemini 3.6 Flash (High)",
                            workspace="KeepRunningProj",
                            target="Sandbox",
                            conversation_id="c2",
                            provider="agy",
                        ),
                        mock_req,
                    )
                )
                tid1 = json.loads(r1.body.decode("utf-8"))["task_id"]
                tid2 = json.loads(r2.body.decode("utf-8"))["task_id"]
                self.assertTrue(started_a.wait(timeout=2.0))

                # Cancel ONLY CancelMeProj
                cancel_res = asyncio.run(
                    main.cancel_chat_task_by_body_endpoint(
                        mock_req, main.CancelTaskRequest(workspace="CancelMeProj")
                    )
                )
                cancel_body = json.loads(cancel_res.body.decode("utf-8"))
                self.assertEqual(cancel_body["status"], "cancelled")

                # KeepRunningProj is STILL running!
                with main.chat_tasks_lock:
                    self.assertEqual(main.chat_tasks[tid2]["status"], "running")

                release_b.set()
                finished = self._wait_for_tasks([tid1, tid2])
                self.assertEqual(finished[tid1]["status"], "cancelled")
                self.assertEqual(finished[tid2]["status"], "success")
                self.assertEqual(
                    finished[tid2]["result"]["reply"], "KeepRunningProj finished cleanly"
                )

    @patch("main.verify_authorization", return_value=True)
    @patch("main.verify_chat_model_request", return_value=None)
    def test_worker_semaphore_queues_overflow_tasks_and_drains_automatically(
        self, _mock_verify_model, _mock_auth
    ):
        gate = threading.Event()
        first_entered = threading.Event()

        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as data_dir:
            os.mkdir(os.path.join(projects_root, "SlotOneProj"))
            os.mkdir(os.path.join(projects_root, "QueuedProj"))

            def fake_run_selected_cli(
                message, model_ui_name, conversation_id, target, workspace, *args, **kwargs
            ):
                if workspace == "SlotOneProj":
                    first_entered.set()
                    gate.wait(timeout=3.0)
                return f"Completed {workspace}", conversation_id

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                patch.object(main, "chat_task_semaphore", threading.Semaphore(1)),
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
                patch("main.run_selected_cli", side_effect=fake_run_selected_cli),
            ):
                mock_req = MagicMock()
                mock_req.headers = {}
                mock_req.client.host = "127.0.0.1"

                r1 = asyncio.run(
                    main.start_chat_task_endpoint(
                        main.ChatRequest(
                            message="Task 1",
                            model="Gemini 3.6 Flash (High)",
                            workspace="SlotOneProj",
                            target="Sandbox",
                            conversation_id="s1",
                            provider="agy",
                        ),
                        mock_req,
                    )
                )
                tid1 = json.loads(r1.body.decode("utf-8"))["task_id"]
                self.assertTrue(first_entered.wait(timeout=2.0))

                r2 = asyncio.run(
                    main.start_chat_task_endpoint(
                        main.ChatRequest(
                            message="Task 2",
                            model="Gemini 3.6 Flash (High)",
                            workspace="QueuedProj",
                            target="Sandbox",
                            conversation_id="s2",
                            provider="agy",
                        ),
                        mock_req,
                    )
                )
                tid2 = json.loads(r2.body.decode("utf-8"))["task_id"]

                # Wait briefly for tid2 to hit semaphore and enter queued state
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    with main.chat_tasks_lock:
                        if main.chat_tasks[tid2]["status"] == "queued":
                            break
                    time.sleep(0.02)

                with main.chat_tasks_lock:
                    self.assertEqual(main.chat_tasks[tid2]["status"], "queued")

                # Active tasks list must include queued tasks too
                active_res = asyncio.run(main.list_chat_tasks_endpoint(mock_req, active_only=True))
                active_ids = {t["task_id"] for t in json.loads(active_res.body.decode("utf-8"))["tasks"]}
                self.assertEqual(active_ids, {tid1, tid2})

                gate.set()
                finished = self._wait_for_tasks([tid1, tid2])
                self.assertEqual(finished[tid1]["status"], "success")
                self.assertEqual(finished[tid2]["status"], "success")

    def test_concurrent_agy_runs_do_not_steal_other_projects_conversation_db(self):
        with tempfile.TemporaryDirectory() as projects_root, tempfile.TemporaryDirectory() as cli_dir:
            os.mkdir(os.path.join(projects_root, "ProjAlpha"))
            os.mkdir(os.path.join(projects_root, "ProjBeta"))
            convos_dir = os.path.join(cli_dir, "conversations")
            os.makedirs(convos_dir, exist_ok=True)

            # Simulate both projects creating new DBs while running concurrently,
            # with ProjBeta's DB having a NEWER mtime than ProjAlpha's DB!
            cid_alpha = "11111111-aaaa-4444-8888-aaaaaaaaaaaa"
            cid_beta = "22222222-bbbb-4444-8888-bbbbbbbbbbbb"

            def fake_run_agy_command(cmd, cwd_path, **kwargs):
                for cid, proj_name, offset in (
                    (cid_alpha, "ProjAlpha", 10),
                    (cid_beta, "ProjBeta", 50),
                ):
                    db_file = os.path.join(convos_dir, f"{cid}.db")
                    with open(db_file, "wb") as f:
                        f.write(b"sqlite")
                    now = time.time() + offset
                    os.utime(db_file, (now, now))
                    log_dir = os.path.join(cli_dir, "brain", cid, ".system_generated", "logs")
                    os.makedirs(log_dir, exist_ok=True)
                    with open(
                        os.path.join(log_dir, "transcript.jsonl"), "w", encoding="utf-8"
                    ) as lf:
                        lf.write(
                            json.dumps(
                                {
                                    "type": "USER_INPUT",
                                    "content": (
                                        f"Selected KookAI project/workspace: {proj_name}\n"
                                        f"Workspace directory: {os.path.join(projects_root, proj_name)}\n\n"
                                        f"User message:\nhi"
                                    ),
                                }
                            )
                            + "\n"
                        )
                return MagicMock(returncode=0, stdout="Reply from agy", stderr="")

            with (
                patch.object(main, "PROJECTS_ROOTS", (projects_root,)),
                patch.object(main, "ALL_ANTIGRAVITY_CLI_DIRS", [cli_dir]),
                patch("main.get_existing_db_ids", side_effect=[set(), {cid_alpha, cid_beta}]),
                patch("main.run_agy_command", side_effect=fake_run_agy_command),
            ):
                reply, resolved_alpha = main.run_agy_cli(
                    message="hello",
                    model_ui_name="Gemini 3.6 Flash (High)",
                    conversation_id="temp_ProjAlpha_1",
                    target="Sandbox",
                    workspace="ProjAlpha",
                )
                self.assertEqual(reply, "Reply from agy")
                # Even though cid_beta has a newer mtime (+50s vs +10s), ProjAlpha resolves cid_alpha!
                self.assertEqual(resolved_alpha, cid_alpha)

    @patch("main.verify_authorization", return_value=True)
    def test_files_endpoint_scopes_to_requested_project_workspace(self, _mock_auth):
        with tempfile.TemporaryDirectory() as projects_root:
            proj_a = os.path.join(projects_root, "FrontendApp")
            proj_b = os.path.join(projects_root, "BackendApi")
            os.mkdir(proj_a)
            os.mkdir(proj_b)
            with open(os.path.join(proj_a, "index.tsx"), "w", encoding="utf-8") as f:
                f.write("export default function App() {}")
            with open(os.path.join(proj_b, "server.py"), "w", encoding="utf-8") as f:
                f.write("print('api')")

            with patch.object(main, "PROJECTS_ROOTS", (projects_root,)):
                mock_req = MagicMock()
                res_a = asyncio.run(main.get_files(mock_req, workspace="FrontendApp"))
                res_b = asyncio.run(main.get_files(mock_req, workspace="BackendApi"))
                files_a = [item["name"] for item in json.loads(res_a.body.decode("utf-8"))["files"]]
                files_b = [item["name"] for item in json.loads(res_b.body.decode("utf-8"))["files"]]

                self.assertEqual(files_a, ["index.tsx"])
                self.assertEqual(files_b, ["server.py"])

    def test_end_to_end_http_router_and_static_web_multi_project_controls(self):
        from fastapi.testclient import TestClient

        client = TestClient(main.app, client=("127.0.0.1", 51234))
        home = client.get("/", headers={"host": "127.0.0.1:8080"})
        self.assertEqual(home.status_code, 200)
        self.assertIn("multiProjectModeBtn", home.text)
        self.assertIn("multiProjectTargetBar", home.text)
        self.assertIn("activeTasksHeaderBtn", home.text)
        self.assertTrue(main.is_tunnel_allowed_path("/api/chat-tasks/batch"))

        barrier = threading.Barrier(2)

        def fake_cli(msg, model, cid, target, workspace, *a, **kw):
            barrier.wait(timeout=2.0)
            return f"Live HTTP reply from {workspace}", f"live_{workspace}"

        fake_model_entry = {
            "id": "Gemini 3.6 Flash (High)",
            "provider": "agy",
            "capabilities": {
                "effort": [],
                "speed": [],
                "thinking": False,
                "thinking_required": False,
            },
        }

        with tempfile.TemporaryDirectory() as proot, tempfile.TemporaryDirectory() as ddir:
            os.mkdir(os.path.join(proot, "ServiceA"))
            os.mkdir(os.path.join(proot, "ServiceB"))
            with open(os.path.join(proot, "ServiceB", "app.py"), "w", encoding="utf-8") as f:
                f.write("x = 1\n")

            with (
                patch.object(main, "PROJECTS_ROOTS", (proot,)),
                patch.object(
                    main, "CANONICAL_CONVERSATIONS_FILE", os.path.join(ddir, "c.json")
                ),
                patch.object(
                    main, "CONVERSATION_METADATA_FILE", os.path.join(ddir, "m.json")
                ),
                patch("main.resolve_chat_model", return_value=fake_model_entry),
                patch("main.run_selected_cli", side_effect=fake_cli),
            ):
                r_files = client.get(
                    "/api/files?workspace=ServiceB", headers={"host": "127.0.0.1:8080"}
                )
                self.assertEqual(r_files.status_code, 200)
                self.assertEqual(r_files.json()["files"][0]["name"], "app.py")

                r_batch = client.post(
                    "/api/chat-tasks/batch",
                    headers={"host": "127.0.0.1:8080"},
                    json={
                        "message": "Run health audit",
                        "model": "Gemini 3.6 Flash (High)",
                        "provider": "agy",
                        "workspaces": ["ServiceA", "ServiceB"],
                        "target": "Sandbox",
                    },
                )
                self.assertEqual(r_batch.status_code, 200)
                bdata = r_batch.json()
                self.assertEqual(bdata["count"], 2)

                statuses = []
                for _ in range(50):
                    statuses = [
                        client.get(
                            f"/api/chat-tasks/{t['task_id']}",
                            headers={"host": "127.0.0.1:8080"},
                        ).json()["status"]
                        for t in bdata["tasks"]
                    ]
                    if all(s == "success" for s in statuses):
                        break
                    time.sleep(0.05)
                self.assertEqual(statuses, ["success", "success"])


if __name__ == "__main__":
    unittest.main()
