import asyncio
import json
import os
import subprocess
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import cli_manager
import dsh_backend
import local_backend
import main
import qwen_backend


class DshBackendUnitTests(unittest.TestCase):
    def test_build_dsh_command_sandbox_real_and_resume(self):
        sandbox_cmd = dsh_backend.build_dsh_command(
            "/Users/kai/.local/bin/dsh",
            "/tmp/kookai-dsh/patch.yml",
            target="Sandbox",
            conversation_id="temp-123",
        )
        self.assertEqual(
            sandbox_cmd,
            [
                "/Users/kai/.local/bin/dsh",
                "--profile",
                "headless",
                "--patch",
                "/tmp/kookai-dsh/patch.yml",
                "--permission-mode",
                "workspace-write",
                "--approval-policy",
                "never",
                "--json",
                "-",
            ],
        )

        for non_dsh_cid in ("local_abc123", "local_qwen_ses-1", "local_dsh_", None):
            cmd = dsh_backend.build_dsh_command(
                "/Users/kai/.local/bin/dsh",
                "/tmp/patch.yml",
                target="Sandbox",
                conversation_id=non_dsh_cid,
            )
            self.assertNotIn("--session-id", cmd)

        real_cmd = dsh_backend.build_dsh_command(
            "/Users/kai/.local/bin/dsh",
            "/tmp/patch.yml",
            target="Real",
            conversation_id="local_dsh_session-999",
        )
        self.assertEqual(real_cmd[real_cmd.index("--permission-mode") + 1], "danger-full-access")
        self.assertEqual(real_cmd[real_cmd.index("--approval-policy") + 1], "never")
        self.assertEqual(real_cmd[real_cmd.index("--session-id") + 1], "session-999")
        self.assertEqual(real_cmd[-1], "-")

    def test_build_dsh_environment_isolates_local_key_from_cloud_keys(self):
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-cloud-secret", "DEEPSEEK_API_KEY": "ds-cloud-secret"},
            clear=False,
        ):
            env = dsh_backend.build_dsh_environment(
                "http://127.0.0.1:11434/v1",
                "inkling-2-mini:latest",
            )
            self.assertEqual(env[dsh_backend.DSH_LOCAL_API_KEY_ENV], "local")
            self.assertEqual(env["NO_BROWSER"], "1")
            self.assertEqual(env["OPENAI_API_KEY"], "sk-cloud-secret")
            self.assertEqual(env["DEEPSEEK_API_KEY"], "ds-cloud-secret")

            env_with_key = dsh_backend.build_dsh_environment(
                "http://127.0.0.1:11434/v1",
                "inkling-2-mini:latest",
                api_key="local-secret-xyz",
            )
            self.assertEqual(env_with_key[dsh_backend.DSH_LOCAL_API_KEY_ENV], "local-secret-xyz")

    def test_dsh_patch_file_structure_thinking_overrides_and_cleanup(self):
        patch_paths = []
        for thinking, expected_effort in ((True, "low"), (False, "off")):
            with dsh_backend.dsh_patch_file(
                "http://127.0.0.1:11434/v1",
                "inkling-2-mini:latest",
                thinking=thinking,
            ) as path:
                patch_paths.append(path)
                with open(path, encoding="utf-8") as stream:
                    rows = json.load(stream)
                by_id = {row["id"]: row for row in rows}
                self.assertTrue(by_id["session-title-llm"]["disabled"])
                provider = by_id["llm-pi-ai"]["config"]["providers"][dsh_backend.DSH_LOCAL_PROVIDER_ID]
                self.assertEqual(provider["api"], "openai-completions")
                self.assertEqual(provider["baseURL"], "http://127.0.0.1:11434/v1")
                self.assertEqual(provider["apiKeyEnv"], dsh_backend.DSH_LOCAL_API_KEY_ENV)
                self.assertEqual(provider["streamIdleTimeoutMs"], dsh_backend.DEFAULT_DSH_STREAM_IDLE_TIMEOUT_MS)
                self.assertEqual(
                    provider["compat"],
                    {
                        "supportsStore": False,
                        "supportsReasoningEffort": True,
                        "thinkingFormat": "openai",
                    },
                )
                model_entry = provider["models"][0]
                self.assertEqual(model_entry["id"], "inkling-2-mini:latest")
                self.assertEqual(model_entry["contextWindow"], dsh_backend.DEFAULT_DSH_CONTEXT_WINDOW)
                self.assertEqual(model_entry["maxTokens"], dsh_backend.DEFAULT_DSH_MAX_TOKENS)
                self.assertEqual(
                    model_entry["reasoningEfforts"],
                    {"off": "none", "low": "low", "medium": "medium", "high": "high"},
                )
                self.assertEqual(
                    by_id["agent-default-model"]["config"],
                    {
                        "provider": dsh_backend.DSH_LOCAL_PROVIDER_ID,
                        "model": "inkling-2-mini:latest",
                        "reasoningEffort": expected_effort,
                    },
                )
            self.assertFalse(os.path.exists(patch_paths[-1]))

        with dsh_backend.dsh_patch_file(
            "http://127.0.0.1:11434/v1",
            "plain-model:latest",
            thinking=None,
            env={
                "KOOKAI_DSH_CONTEXT_WINDOW": "65536",
                "KOOKAI_DSH_MAX_TOKENS": "4096",
                "KOOKAI_DSH_STREAM_IDLE_TIMEOUT_MS": "900000",
            },
        ) as path:
            with open(path, encoding="utf-8") as stream:
                rows = json.load(stream)
            by_id = {row["id"]: row for row in rows}
            provider = by_id["llm-pi-ai"]["config"]["providers"][dsh_backend.DSH_LOCAL_PROVIDER_ID]
            self.assertEqual(provider["compat"], {"supportsStore": False})
            self.assertEqual(provider["streamIdleTimeoutMs"], 900000)
            model_entry = provider["models"][0]
            self.assertEqual(model_entry["contextWindow"], 65536)
            self.assertEqual(model_entry["maxTokens"], 4096)
            self.assertNotIn("reasoningEfforts", model_entry)
            self.assertEqual(
                by_id["agent-default-model"]["config"],
                {"provider": dsh_backend.DSH_LOCAL_PROVIDER_ID, "model": "plain-model:latest"},
            )

        # Verify nested isolation & cleanup on failure
        with dsh_backend.dsh_patch_file("http://127.0.0.1:11434/v1", "m", thinking=False) as first:
            with self.assertRaises(RuntimeError):
                with dsh_backend.dsh_patch_file("http://127.0.0.1:11434/v1", "m", thinking=True) as second:
                    self.assertNotEqual(first, second)
                    self.assertTrue(os.path.exists(first))
                    self.assertTrue(os.path.exists(second))
                    raise RuntimeError("boom")
            self.assertFalse(os.path.exists(second))
            self.assertTrue(os.path.exists(first))
        self.assertFalse(os.path.exists(first))

    def test_dsh_patch_document_vision_input_and_overrides(self):
        def model_input(raw_model_id, *, vision=None, env=None):
            rows = dsh_backend.build_dsh_patch_document(
                "http://192.168.1.200:8000/v1",
                raw_model_id,
                vision=vision,
                env=env,
            )
            return rows[1]["config"]["providers"][dsh_backend.DSH_LOCAL_PROVIDER_ID]["models"][0]["input"]

        self.assertEqual(model_input("deepseek-ai/DeepSeek-V4-Flash-Vision-Exp"), ["text", "image"])
        self.assertEqual(model_input("inkling-2-mini:latest"), ["text"])
        self.assertEqual(model_input("plain-model:latest", vision=True), ["text", "image"])
        self.assertEqual(model_input("deepseek-ai/DeepSeek-V4-Flash-Vision-Exp", vision=False), ["text"])
        self.assertEqual(model_input("plain-model:latest", vision=False, env={"KOOKAI_LOCAL_VISION": "1"}), ["text", "image"])
        self.assertEqual(model_input("deepseek-ai/DeepSeek-V4-Flash-Vision-Exp", vision=True, env={"KOOKAI_LOCAL_VISION": "0"}), ["text"])

    def test_parse_dsh_stream_json_events_fallbacks_and_error_dedupe(self):
        output = "\n".join([
            "not json line",
            json.dumps({"type": "session", "sessionId": "session-42", "cwd": "/tmp/ws"}),
            json.dumps({"type": "thinking", "text": "private chain of thought"}),
            json.dumps({"type": "text", "text": "Intermediate status"}),
            json.dumps({"type": "tool_call", "callId": "c1", "tool": "read", "input": {"file_path": "a.txt"}}),
            json.dumps({"type": "tool_result", "callId": "c1", "status": "completed", "result": "ok"}),
            json.dumps({"type": "text", "text": "Final summary"}),
            json.dumps({"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "completed"}}),
            json.dumps({"type": "final", "sessionId": "session-42", "reason": {"kind": "completed"}, "text": "Done editing a.txt."}),
        ])
        parsed = dsh_backend.parse_dsh_stream_json(output)
        self.assertEqual(parsed["session_id"], "session-42")
        self.assertEqual(parsed["final_message"], "Done editing a.txt.")
        self.assertEqual(parsed["errors"], [])

        fallback_only = "\n".join([
            json.dumps({"type": "session", "sessionId": "session-77"}),
            json.dumps({"type": "text", "text": "Step 1"}),
            json.dumps({"type": "text", "text": "Fallback reply"}),
        ])
        parsed_fallback = dsh_backend.parse_dsh_stream_json(fallback_only)
        self.assertEqual(parsed_fallback["session_id"], "session-77")
        self.assertEqual(parsed_fallback["final_message"], "Fallback reply")

        err_output = "\n".join([
            json.dumps({"type": "status", "phase": "turn_end", "turn": 1, "reason": {"kind": "error", "error": {"code": "LLM_ERROR", "message": "400 invalid"}}}),
            json.dumps({"type": "final", "sessionId": "session-88", "reason": {"kind": "error", "error": {"code": "LLM_ERROR", "message": "400 invalid"}}, "text": ""}),
            json.dumps({"type": "error", "message": "Connection refused"}),
        ])
        parsed_err = dsh_backend.parse_dsh_stream_json(err_output)
        self.assertEqual(parsed_err["errors"], ["LLM_ERROR: 400 invalid", "Connection refused"])

    def test_classify_dsh_progress_line_and_no_reasoning_leak(self):
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line(
                "stdout", json.dumps({"type": "session", "sessionId": "s1"})
            ),
            {"type": "progress", "message": "DeepSeek Harness session started."},
        )
        thinking_ev = dsh_backend.classify_dsh_progress_line(
            "stdout", json.dumps({"type": "thinking", "text": "SECRET_THOUGHT_TEXT"})
        )
        self.assertEqual(thinking_ev, {"type": "progress", "message": "DeepSeek Harness is thinking..."})
        self.assertNotIn("SECRET_THOUGHT_TEXT", thinking_ev["message"])
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line("stdout", json.dumps({"type": "text", "text": "hello"})),
            {"type": "progress", "message": "DeepSeek Harness is generating a response..."},
        )
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line(
                "stdout", json.dumps({"type": "tool_call", "tool": "bash", "callId": "c1", "input": {}})
            ),
            {"type": "progress", "message": "DeepSeek Harness is using bash."},
        )
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line(
                "stdout", json.dumps({"type": "tool_result", "callId": "c1", "status": "error", "result": "fail"})
            ),
            {"type": "progress", "message": "DeepSeek Harness tool reported an error; continuing..."},
        )
        self.assertIsNone(
            dsh_backend.classify_dsh_progress_line(
                "stdout", json.dumps({"type": "tool_result", "callId": "c1", "status": "completed", "result": "ok"})
            )
        )
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line(
                "stdout", json.dumps({"type": "final", "reason": {"kind": "error", "error": {"code": "E_FAIL", "message": "bad"}}, "text": ""})
            ),
            {"type": "error", "message": "E_FAIL: bad"},
        )
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line("stderr", "dsh: session \"s1\" does not exist"),
            {"type": "error", "message": "dsh: session \"s1\" does not exist"},
        )
        self.assertEqual(
            dsh_backend.classify_dsh_progress_line("stderr", "Loading workspace profile..."),
            {"type": "progress", "message": "Loading workspace profile..."},
        )

    def test_local_harness_mode_dsh_variants_and_description(self):
        local_backend._cache.clear()
        self.addCleanup(local_backend._cache.clear)
        for val in ("dsh", "deepseek-harness", "deepseek_harness"):
            with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": val}):
                self.assertEqual(qwen_backend.local_harness_mode(), "dsh")
                self.assertFalse(qwen_backend.should_use_qwen_harness())

        with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": "dsh"}), \
             mock.patch.object(local_backend, "_request", return_value=iter([{"data": [{"id": "inkling-2-mini:latest"}]}])), \
             mock.patch.object(dsh_backend, "is_dsh_available", return_value=True):
            models = local_backend.discover_local_models(force=True)
        self.assertIn("DeepSeek Harness", models[0]["description"])


class DshIntegrationAndRoutingTests(unittest.TestCase):
    def setUp(self):
        local_backend._cache.clear()
        env_patch = mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": "dsh", "KOOKAI_LOCAL_LLM_API_KEY": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.local_model = {
            "id": "local-inkling2",
            "label": "inkling-2-mini:latest (Local)",
            "description": "Local LLM • DeepSeek Harness • workspace tools",
            "provider": "local",
            "cli_model": "local/inkling-2-mini:latest",
            "badge": "Local",
            "usage_bucket": "local",
            "enabled": True,
            "capabilities": {"effort": [], "speed": [], "thinking": True, "thinking_required": False},
        }
        self.catalog = {
            "schema_version": 1,
            "catalog_version": "test",
            "default_model": "local-inkling2",
            "models": [self.local_model],
        }

    def test_run_local_llm_routes_to_dsh_persists_resumes_and_recovers(self):
        calls = []
        progress_events = []

        def fake_run_agent(cmd, cwd_path, **kwargs):
            patch_path = cmd[cmd.index("--patch") + 1]
            with open(patch_path, encoding="utf-8") as stream:
                patch_data = json.load(stream)
            calls.append((list(cmd), cwd_path, kwargs.get("stdin_text", ""), kwargs.get("env", {}), patch_data))
            if "--session-id" in cmd and cmd[cmd.index("--session-id") + 1] == "stale-sid":
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout=json.dumps({"type": "error", "message": 'session "stale-sid" does not exist'}),
                    stderr='dsh: session "stale-sid" does not exist',
                )
            sid = cmd[cmd.index("--session-id") + 1] if "--session-id" in cmd else "session-fresh-1"
            out = "\n".join([
                json.dumps({"type": "session", "sessionId": sid, "cwd": cwd_path}),
                json.dumps({"type": "final", "sessionId": sid, "reason": {"kind": "completed"}, "text": f"DSH reply ({sid})"}),
            ])
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = os.path.join(tmp, "MyProj")
            os.makedirs(ws_dir)
            with (
                mock.patch.object(main, "PROJECTS_ROOTS", (tmp,)),
                mock.patch.object(main, "CANONICAL_CONVERSATIONS_FILE", os.path.join(tmp, "conversations.json")),
                mock.patch.object(main, "CONVERSATION_METADATA_FILE", os.path.join(tmp, "metadata.json")),
                mock.patch.object(main, "get_workspace_alignment_context", return_value=""),
                mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
                mock.patch.object(main, "should_use_dsh_harness", return_value=True),
                mock.patch.object(main, "should_use_qwen_harness", return_value=False),
                mock.patch.object(main, "resolve_dsh_executable", return_value="/Users/kai/.local/bin/dsh"),
                mock.patch.object(main, "convo_id_mapping", {}),
                mock.patch.object(main, "in_memory_chats", {}),
                mock.patch.object(main, "run_agent_command", side_effect=fake_run_agent),
            ):
                # Turn 1: fresh session via build_chat_response (Sandbox, thinking=True)
                req1 = main.ChatRequest(
                    message="Hello inkling2",
                    model="local-inkling2",
                    provider="local",
                    workspace="MyProj",
                    target="Sandbox",
                    thinking=True,
                    conversation_id="temp-local-1",
                )
                res1 = main.build_chat_response(req1)
                self.assertEqual(res1["reply"], "DSH reply (session-fresh-1)")
                self.assertEqual(res1["provider"], "local")
                self.assertEqual(res1["conversation_id"], "local_dsh_session-fresh-1")
                self.assertIn("workspace-write", calls[0][0])
                self.assertNotIn("--session-id", calls[0][0])
                self.assertEqual(calls[0][4][2]["config"]["reasoningEffort"], "low")
                record = main.get_canonical_conversation("local_dsh_session-fresh-1")
                self.assertEqual(len(record["messages"]), 2)

                # Turn 2: resume existing session (Real, thinking=False)
                req2 = main.ChatRequest(
                    message="Follow up",
                    model="local-inkling2",
                    provider="local",
                    workspace="MyProj",
                    target="Real",
                    thinking=False,
                    conversation_id="local_dsh_session-fresh-1",
                )
                res2 = main.build_chat_response(req2)
                self.assertEqual(res2["conversation_id"], "local_dsh_session-fresh-1")
                self.assertIn("danger-full-access", calls[1][0])
                self.assertEqual(calls[1][0][calls[1][0].index("--session-id") + 1], "session-fresh-1")
                self.assertEqual(calls[1][4][2]["config"]["reasoningEffort"], "off")

                # Turn 3: stale session ID recovers into fresh session with canonical history
                main.in_memory_chats["local_dsh_stale-sid"] = [
                    {"role": "user", "content": "Remember 42"},
                    {"role": "assistant", "content": "Noted 42"},
                ]
                reply3, cid3 = main.run_local_llm(
                    "What did I say?",
                    "local-inkling2",
                    "local_dsh_stale-sid",
                    "MyProj",
                    target="Real",
                    progress_callback=lambda t, m: progress_events.append((t, m)),
                )
                self.assertEqual(reply3, "DSH reply (session-fresh-1)")
                self.assertEqual(cid3, "local_dsh_session-fresh-1")
                self.assertEqual(len(calls), 4)
                self.assertIn("--session-id", calls[2][0])
                self.assertNotIn("--session-id", calls[3][0])
                self.assertIn("[Previous Conversation History]", calls[3][2])
                self.assertIn("Remember 42", calls[3][2])
                self.assertEqual(calls[3][3][dsh_backend.DSH_LOCAL_API_KEY_ENV], "local")
                self.assertTrue(any("fresh session" in msg.lower() for _, msg in progress_events))

    def test_partial_progress_is_throttled_without_hiding_errors(self):
        events = []

        def fake_run(cmd, cwd_path, **kwargs):
            classify = kwargs["progress_line_classifier"]
            line = json.dumps({"type": "thinking", "text": "not for display"})
            with mock.patch.object(main.time, "monotonic", side_effect=[0, 1, 5]):
                events.extend(classify("stdout", line) for _ in range(3))
            events.append(classify("stderr", "Error: server stopped"))
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps({"type": "final", "sessionId": "sid", "reason": {"kind": "completed"}, "text": "Done"}),
                stderr="",
            )

        model = dict(self.local_model, capabilities={"thinking": False})
        with (
            mock.patch.object(main, "resolve_dsh_executable", return_value="dsh"),
            mock.patch.object(main, "run_agent_command", side_effect=fake_run),
            mock.patch.object(main, "get_canonical_conversation", return_value=None),
            mock.patch.object(main, "convo_id_mapping", {}),
        ):
            reply, _ = main.run_dsh_local_cli("hello", model, "test")
        self.assertEqual(reply, "Done")
        self.assertEqual(
            events,
            [
                {"type": "progress", "message": "DeepSeek Harness is thinking..."},
                None,
                {"type": "progress", "message": "DeepSeek Harness is thinking..."},
                {"type": "error", "message": "Error: server stopped"},
            ],
        )

    def test_dsh_error_timeout_and_cancel_never_failover_to_cloud(self):
        self.assertEqual(
            main.PROVIDER_FAILOVER_ORDER,
            ["agy", "claude", "codex", "kimi", "zai", "xai", "muse", "deepseek"],
        )

        failed_proc = subprocess.CompletedProcess(["dsh"], 1, stdout="", stderr="Local server crashed")
        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_dsh_harness", return_value=True),
            mock.patch.object(main, "resolve_dsh_executable", return_value="/Users/kai/.local/bin/dsh"),
            mock.patch.object(main, "run_agent_command", return_value=failed_proc),
            mock.patch.object(main, "is_provider_available") as available,
        ):
            reply, _ = main.run_selected_cli(
                "Edit file",
                "local-inkling2",
                "conv-dsh-1",
                "Sandbox",
                "KookAI",
                provider="local",
            )
        self.assertIn("DeepSeek Harness CLI Error (Exit Code 1)", reply)
        self.assertIn("Local server crashed", reply)
        available.assert_not_called()

        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_dsh_harness", return_value=True),
            mock.patch.object(main, "resolve_dsh_executable", return_value="/Users/kai/.local/bin/dsh"),
            mock.patch.object(main, "run_agent_command", side_effect=main.AgentCommandTimeout(["dsh"], 1800, "idle")),
            mock.patch.object(main, "is_provider_available") as available,
        ):
            timeout_reply, _ = main.run_selected_cli(
                "Edit file",
                "local-inkling2",
                "conv-dsh-timeout",
                "Sandbox",
                "KookAI",
                provider="local",
            )
        self.assertIn("`dsh` CLI produced no output for 1800 seconds", timeout_reply)
        available.assert_not_called()

        cancel_event = threading.Event()
        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_dsh_harness", return_value=True),
            mock.patch.object(main, "resolve_dsh_executable", return_value="/Users/kai/.local/bin/dsh"),
            mock.patch.object(main, "run_agent_command", side_effect=main.AgentCommandCancelled("cancelled")),
            mock.patch.object(main, "is_provider_available") as available,
        ):
            with self.assertRaises(main.AgentCommandCancelled):
                main.run_selected_cli(
                    "Edit file",
                    "local-inkling2",
                    "conv-dsh-2",
                    "Sandbox",
                    "KookAI",
                    provider="local",
                    cancel_event=cancel_event,
                )
        available.assert_not_called()

    def test_cli_manager_requirements_and_endpoints_include_dsh(self):
        definition = cli_manager.CLI_DEFINITIONS["dsh"]
        self.assertEqual(definition.install_kind, "npm")
        self.assertEqual(definition.install_source, "@deepseek-ai/dsh")
        self.assertEqual(definition.executable, "dsh")
        self.assertEqual(definition.env_path, "DSH_CLI_PATH")

        req_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
        self.assertIn("dsh", cli_manager.parse_cli_requirements(req_path))

        req = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
            query_params={},
        )
        with mock.patch.object(
            main,
            "install_cli",
            return_value={"id": "dsh", "installed": True, "status": "installed"},
        ) as install_mock:
            res = asyncio.run(main.install_cli_requirement("dsh", req))
        self.assertEqual(res.status_code, 200)
        install_mock.assert_called_once_with("dsh")

        with (
            mock.patch.object(
                main,
                "get_cli_statuses",
                return_value=[{"id": "dsh", "installed": True, "status": "installed"}],
            ),
            mock.patch.object(
                main,
                "launch_cli_login",
                return_value={"launched": True, "message": "Opened", "command": "dsh"},
            ) as login_mock,
        ):
            res_conn = asyncio.run(main.connect_cli_account("dsh", req))
        self.assertEqual(res_conn.status_code, 200)
        login_mock.assert_called_once_with("dsh", main.APP_DIR)


if __name__ == "__main__":
    unittest.main()
