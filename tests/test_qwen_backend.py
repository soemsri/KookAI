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
import local_backend
import main
import qwen_backend


class QwenBackendUnitTests(unittest.TestCase):
    def test_build_qwen_command_sandbox_real_and_resume(self):
        sandbox_cmd = qwen_backend.build_qwen_command(
            "/usr/local/bin/qwen",
            "secret prompt text",
            "mlx-community/Qwen3.8-27B-8bit",
            "http://127.0.0.1:52415/v1",
            target="Sandbox",
            conversation_id="temp-123",
        )
        self.assertEqual(sandbox_cmd[:7], [
            "/usr/local/bin/qwen",
            "--auth-type",
            "openai",
            "--openai-base-url",
            "http://127.0.0.1:52415/v1",
            "--model",
            "mlx-community/Qwen3.8-27B-8bit",
        ])
        self.assertIn("--output-format", sandbox_cmd)
        self.assertIn("--include-partial-messages", sandbox_cmd)
        self.assertEqual(sandbox_cmd[sandbox_cmd.index("--output-format") + 1], "stream-json")
        self.assertEqual(sandbox_cmd[sandbox_cmd.index("--approval-mode") + 1], "auto-edit")
        self.assertNotIn("--resume", sandbox_cmd)
        self.assertNotIn("secret prompt text", sandbox_cmd)

        for non_qwen_cid in ("local_abc123", "local_qwen_", None):
            cmd = qwen_backend.build_qwen_command(
                "/usr/local/bin/qwen",
                "hi",
                "qwen-local",
                "http://127.0.0.1:52415/v1",
                target="Sandbox",
                conversation_id=non_qwen_cid,
            )
            self.assertNotIn("--resume", cmd)

        real_cmd = qwen_backend.build_qwen_command(
            "/usr/local/bin/qwen",
            "run tests",
            "qwen-local",
            "http://127.0.0.1:52415/v1",
            target="Real",
            conversation_id="local_qwen_ses-999",
        )
        self.assertEqual(real_cmd[real_cmd.index("--approval-mode") + 1], "yolo")
        self.assertEqual(real_cmd[real_cmd.index("--resume") + 1], "ses-999")

    def test_build_qwen_environment_isolates_local_key_from_cloud_openai_key(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-cloud-secret"}, clear=False):
            env = qwen_backend.build_qwen_environment(
                "http://127.0.0.1:52415/v1",
                "mlx-community/Qwen3.8-27B-8bit",
            )
            self.assertEqual(env["OPENAI_BASE_URL"], "http://127.0.0.1:52415/v1")
            self.assertEqual(env["OPENAI_MODEL"], "mlx-community/Qwen3.8-27B-8bit")
            self.assertEqual(env["OPENAI_API_KEY"], "local")
            self.assertEqual(env["NO_BROWSER"], "1")

            env_with_key = qwen_backend.build_qwen_environment(
                "http://127.0.0.1:52415/v1",
                "mlx-community/Qwen3.8-27B-8bit",
                api_key="local-token-xyz",
            )
            self.assertEqual(env_with_key["OPENAI_API_KEY"], "local-token-xyz")

    def test_local_stream_budget_is_finite_and_preserves_explicit_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            env = qwen_backend.build_qwen_environment("http://localhost/v1", "local-model")
            self.assertEqual(env.get("QWEN_STREAM_MAX_LIFETIME_MS"), "1800000")
            self.assertEqual(env.get("QWEN_STREAM_IDLE_TIMEOUT_MS"), "1800000")
        for configured in ("60000", "0"):
            with mock.patch.dict(os.environ, {"QWEN_STREAM_MAX_LIFETIME_MS": configured,
                                             "QWEN_STREAM_IDLE_TIMEOUT_MS": configured}):
                env = qwen_backend.build_qwen_environment("http://localhost/v1", "local-model")
                self.assertEqual(env["QWEN_STREAM_MAX_LIFETIME_MS"], configured)
                self.assertEqual(env["QWEN_STREAM_IDLE_TIMEOUT_MS"], configured)

    def test_generation_settings_preserve_policy_and_provider_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            qwen_home = os.path.join(tmp, "qwen")
            os.makedirs(qwen_home)
            system_path = os.path.join(tmp, "system.json")
            policy = {"tools": {"exclude": ["run_shell_command"]}, "security": {"auth": {"enforcedType": "openai"}}}
            with open(system_path, "w") as stream:
                stream.write("// operator policy\n" + json.dumps(policy))
            provider = {"id": "local-model", "baseUrl": "https://cloud.example/v1", "envKey": "CLOUD_KEY",
                        "generationConfig": {"samplingParams": {"temperature": 0.2}, "extra_body": {"custom": "https://keep.example/*value*/"}}}
            sibling = {"id": "other-model", "generationConfig": {"extra_body": {"enable_thinking": True}}}
            with open(os.path.join(qwen_home, "settings.json"), "w") as stream:
                json.dump({"modelProviders": {"openai": [provider, sibling]}}, stream)
            # Project-only configuration must not be promoted into system scope.
            os.makedirs(os.path.join(tmp, ".qwen"))
            with open(os.path.join(tmp, ".qwen", "settings.json"), "w") as stream:
                json.dump({"modelProviders": {"openai": [{"id": "untrusted-model"}]}}, stream)
            env = {"QWEN_HOME": qwen_home, "QWEN_CODE_SYSTEM_SETTINGS_PATH": system_path,
                   "OPENAI_BASE_URL": "http://127.0.0.1:52415/v1", "OPENAI_API_KEY": "local"}
            original_env = dict(env)
            with qwen_backend.qwen_generation_environment(env, tmp, "local-model", False) as scoped:
                with open(scoped["QWEN_CODE_SYSTEM_SETTINGS_PATH"]) as stream:
                    result = json.load(stream)
                self.assertEqual(result["tools"], policy["tools"])
                self.assertEqual(result["security"], policy["security"])
                self.assertEqual(scoped["QWEN_HOME"], qwen_home)
                self.assertEqual(scoped["QWEN_CODE_SYSTEM_DEFAULTS_PATH"], os.path.join(tmp, "system-defaults.json"))
                selected, other = result["modelProviders"]["openai"]
                self.assertEqual(other, sibling)
                self.assertEqual(selected["generationConfig"]["samplingParams"], {"temperature": 0.2})
                self.assertEqual(selected["generationConfig"]["extra_body"], {"custom": "https://keep.example/*value*/", "enable_thinking": False})
                self.assertEqual(selected["baseUrl"], env["OPENAI_BASE_URL"])
                self.assertEqual(selected["envKey"], "OPENAI_API_KEY")
            self.assertEqual(env, original_env)
            with open(system_path) as stream:
                self.assertEqual(stream.read(), "// operator policy\n" + json.dumps(policy))

    def test_generation_settings_are_isolated_and_cleanup_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"QWEN_HOME": tmp, "QWEN_CODE_SYSTEM_SETTINGS_PATH": os.path.join(tmp, "missing.json"),
                   "OPENAI_BASE_URL": "http://localhost/v1"}
            with qwen_backend.qwen_generation_environment(env, tmp, "test", False) as first:
                first_path = first["QWEN_CODE_SYSTEM_SETTINGS_PATH"]
                with self.assertRaises(RuntimeError):
                    with qwen_backend.qwen_generation_environment(env, tmp, "test", True) as second:
                        second_path = second["QWEN_CODE_SYSTEM_SETTINGS_PATH"]
                        self.assertNotEqual(first_path, second_path)
                        with open(first_path) as stream:
                            self.assertFalse(json.load(stream)["modelProviders"]["openai"][0]["generationConfig"]["extra_body"]["enable_thinking"])
                        with open(second_path) as stream:
                            self.assertTrue(json.load(stream)["modelProviders"]["openai"][0]["generationConfig"]["extra_body"]["enable_thinking"])
                        raise RuntimeError("cancelled")
                self.assertFalse(os.path.exists(second_path))
                self.assertTrue(os.path.exists(first_path))
            self.assertFalse(os.path.exists(first_path))

    def test_generation_settings_skip_models_without_thinking_control(self):
        env = {"QWEN_CODE_SYSTEM_SETTINGS_PATH": "/do-not-read.json"}
        with mock.patch.object(qwen_backend, "_read_qwen_settings") as read:
            with qwen_backend.qwen_generation_environment(env, "/tmp", "test", None) as scoped:
                self.assertIs(scoped, env)
        read.assert_not_called()

    def test_generation_settings_reject_invalid_policy_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            system_path = os.path.join(tmp, "system.json")
            with open(system_path, "w") as stream:
                stream.write("broken policy")
            env = {"QWEN_HOME": tmp, "QWEN_CODE_SYSTEM_SETTINGS_PATH": system_path}
            with self.assertRaisesRegex(ValueError, "fix the JSON"):
                with qwen_backend.qwen_generation_environment(env, tmp, "test", False):
                    self.fail("Invalid system policy was ignored")
            with open(system_path) as stream:
                self.assertEqual(stream.read(), "broken policy")

    def test_parse_qwen_stream_json_events_and_fallbacks(self):
        output = "\n".join([
            "not json line",
            json.dumps({"type": "system", "subtype": "init", "session_id": "ses-42"}),
            json.dumps({"type": "assistant", "session_id": "ses-42", "message": {"content": [{"type": "text", "text": "\n\n"}]}}),
            json.dumps({"type": "assistant", "session_id": "ses-42", "message": {"content": [{"type": "tool_use", "name": "read_file", "input": {"file_path": "a.txt"}}]}}),
            json.dumps({"type": "assistant", "session_id": "ses-42", "message": {"content": [{"type": "text", "text": "Edited a.txt"}]}}),
            json.dumps({"type": "result", "subtype": "success", "session_id": "ses-42", "is_error": False, "result": "Done editing a.txt."}),
        ])
        parsed = qwen_backend.parse_qwen_stream_json(output)
        self.assertEqual(parsed["session_id"], "ses-42")
        self.assertEqual(parsed["final_message"], "Done editing a.txt.")
        self.assertEqual(parsed["errors"], [])

        fallback_only = "\n".join([
            json.dumps({"type": "system", "subtype": "session_start", "session_id": "ses-77"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Fallback assistant reply"}]}}),
        ])
        parsed_fallback = qwen_backend.parse_qwen_stream_json(fallback_only)
        self.assertEqual(parsed_fallback["session_id"], "ses-77")
        self.assertEqual(parsed_fallback["final_message"], "Fallback assistant reply")

        err_output = "\n".join([
            json.dumps({"type": "result", "subtype": "error", "session_id": "ses-88", "is_error": True, "result": "Bad request"}),
            json.dumps({"type": "error", "message": "Connection refused"}),
        ])
        parsed_err = qwen_backend.parse_qwen_stream_json(err_output)
        self.assertEqual(parsed_err["errors"], ["Bad request", "Connection refused"])

    def test_classify_qwen_progress_line(self):
        for delta_type, expected in (
            ("thinking_delta", "Qwen Code is thinking..."),
            ("text_delta", "Qwen Code is generating a response..."),
            ("input_json_delta", "Qwen Code is generating a response..."),
        ):
            event = {"type": "stream_event", "event": {"type": "content_block_delta",
                     "delta": {"type": delta_type, "thinking": "private reasoning", "text": "partial answer"}}}
            self.assertEqual(qwen_backend.classify_qwen_progress_line("stdout", json.dumps(event)),
                             {"type": "progress", "message": expected})
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line(
                "stdout", json.dumps({"type": "system", "subtype": "init"})
            ),
            {"type": "progress", "message": "Qwen Code session started."},
        )
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line(
                "stdout",
                json.dumps({
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "read_file"}, {"type": "tool_use", "name": "edit"}]},
                }),
            ),
            {"type": "progress", "message": "Qwen Code is using read_file, edit."},
        )
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line(
                "stdout",
                json.dumps({
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "is_error": True, "content": "ENOENT"}]},
                }),
            ),
            {"type": "progress", "message": "Qwen Code tool reported an error; continuing..."},
        )
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line(
                "stdout",
                json.dumps({"type": "result", "is_error": True, "result": "Model error"}),
            ),
            {"type": "error", "message": "Model error"},
        )
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line("stderr", "Error: ECONNREFUSED 127.0.0.1:52415"),
            {"type": "error", "message": "Error: ECONNREFUSED 127.0.0.1:52415"},
        )
        self.assertEqual(
            qwen_backend.classify_qwen_progress_line("stderr", "Loading workspace index..."),
            {"type": "progress", "message": "Loading workspace index..."},
        )

    def test_local_harness_mode_opt_out_and_discovery_description(self):
        local_backend._cache.clear()
        self.addCleanup(local_backend._cache.clear)
        with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": "qwen"}), \
             mock.patch.object(local_backend, "_request", return_value=iter([{"data": [{"id": "qwen-local"}]}])):
            with mock.patch.object(qwen_backend, "should_use_qwen_harness", return_value=True):
                with_harness = local_backend.discover_local_models(force=True)
            self.assertIn("Qwen Code harness", with_harness[0]["description"])

            with mock.patch.object(qwen_backend, "should_use_qwen_harness", return_value=False):
                without_harness = local_backend.discover_local_models(force=False)
            self.assertIn("no workspace tools", without_harness[0]["description"])

        for val in ("none", "direct", "off", "0", "false"):
            with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": val}):
                self.assertEqual(qwen_backend.local_harness_mode(), "none")
                self.assertFalse(qwen_backend.should_use_qwen_harness())


class QwenIntegrationAndRoutingTests(unittest.TestCase):
    def setUp(self):
        local_backend._cache.clear()
        env_patch = mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": "qwen", "KOOKAI_LOCAL_LLM_API_KEY": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.local_model = {
            "id": "local-test",
            "label": "Qwen3.8-27B (Local)",
            "description": "Local LLM • Qwen Code harness • workspace tools",
            "provider": "local",
            "cli_model": "local/mlx-community/Qwen3.8-27B-8bit",
            "badge": "Local",
            "usage_bucket": "local",
            "enabled": True,
            "capabilities": {"effort": [], "speed": [], "thinking": True, "thinking_required": False},
        }
        self.catalog = {
            "schema_version": 1,
            "catalog_version": "test",
            "default_model": "local-test",
            "models": [self.local_model],
        }

    def test_qwen_passes_thinking_to_cli_and_cleans_up_per_request_settings(self):
        settings_paths = []

        def capture_settings(cmd, cwd_path, **kwargs):
            env = kwargs["env"]
            settings_path = env.get("QWEN_CODE_SYSTEM_SETTINGS_PATH")
            self.assertIsNotNone(settings_path, "Thinking was discarded before launching Qwen")
            settings_paths.append(settings_path)
            with open(settings_path, encoding="utf-8") as stream:
                settings = json.load(stream)
            model_settings = settings["modelProviders"]["openai"][0]
            self.assertEqual(model_settings["generationConfig"]["extra_body"]["enable_thinking"], thinking)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "type": "result", "subtype": "success", "result": "Done", "session_id": "sid",
            }), stderr="")

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"QWEN_CODE_SYSTEM_SETTINGS_PATH": os.path.join(tmp, "system.json")}),
            mock.patch.object(main, "resolve_project_directory", return_value=tmp),
            mock.patch.object(main, "get_canonical_conversation", return_value=None),
            mock.patch.object(main, "convo_id_mapping", {}),
            mock.patch.object(main, "resolve_qwen_executable", return_value="qwen"),
            mock.patch.object(main, "run_agent_command", side_effect=capture_settings),
        ):
            for thinking in (False, True):
                reply, _ = main.run_qwen_local_cli("hello", self.local_model, "test", thinking=thinking)
                self.assertEqual(reply, "Done")
                self.assertFalse(os.path.exists(settings_paths[-1]))

    def test_run_local_llm_routes_to_qwen_harness_and_recovers_missing_session(self):
        calls = []
        progress_events = []

        def fake_run_agent(cmd, cwd_path, **kwargs):
            calls.append((list(cmd), cwd_path, kwargs.get("stdin_text", ""), kwargs.get("env", {})))
            if "--resume" in cmd:
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="Error: Session not found for stale-sid",
                )
            out = "\n".join([
                json.dumps({"type": "system", "subtype": "init", "session_id": "fresh-sid"}),
                json.dumps({"type": "result", "subtype": "success", "session_id": "fresh-sid", "is_error": False, "result": "Recovered response"}),
            ])
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = os.path.join(tmp, "MyProj")
            os.makedirs(ws_dir)
            with (
                mock.patch.object(main, "PROJECTS_ROOTS", (tmp,)),
                mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
                mock.patch.object(main, "should_use_qwen_harness", return_value=True),
                mock.patch.object(main, "resolve_qwen_executable", return_value="/usr/local/bin/qwen"),
                mock.patch.object(main, "convo_id_mapping", {}),
                mock.patch.object(
                    main,
                    "in_memory_chats",
                    {"local_qwen_stale-sid": [{"role": "user", "content": "Remember 77"}, {"role": "assistant", "content": "Noted 77"}]},
                ),
                mock.patch.object(main, "run_agent_command", side_effect=fake_run_agent),
            ):
                reply, cid = main.run_local_llm(
                    "What did I say?",
                    "local-test",
                    "local_qwen_stale-sid",
                    "MyProj",
                    target="Real",
                    progress_callback=lambda t, m: progress_events.append((t, m)),
                )

        self.assertEqual(reply, "Recovered response")
        self.assertEqual(cid, "local_qwen_fresh-sid")
        self.assertEqual(len(calls), 2)
        self.assertEqual(os.path.realpath(calls[0][1]), os.path.realpath(ws_dir))
        self.assertIn("--resume", calls[0][0])
        self.assertIn("yolo", calls[0][0])
        self.assertNotIn("--resume", calls[1][0])
        self.assertIn("[Previous Conversation History]", calls[1][2])
        self.assertIn("Remember 77", calls[1][2])
        self.assertEqual(calls[1][3]["OPENAI_API_KEY"], "local")
        self.assertTrue(any("fresh session" in msg.lower() for _, msg in progress_events))

    def test_partial_progress_is_throttled_without_hiding_errors(self):
        events = []

        def fake_run(cmd, cwd_path, **kwargs):
            classify = kwargs["progress_line_classifier"]
            line = json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                               "delta": {"type": "thinking_delta", "thinking": "not for display"}}})
            with mock.patch.object(main.time, "monotonic", side_effect=[0, 1, 5]):
                events.extend(classify("stdout", line) for _ in range(3))
            events.append(classify("stderr", "Error: server stopped"))
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({
                "type": "result", "subtype": "success", "result": "Done",
            }), stderr="")

        model = dict(self.local_model, capabilities={"thinking": False})
        with (
            mock.patch.object(main, "resolve_qwen_executable", return_value="qwen"),
            mock.patch.object(main, "run_agent_command", side_effect=fake_run),
            mock.patch.object(main, "get_canonical_conversation", return_value=None),
            mock.patch.object(main, "convo_id_mapping", {}),
        ):
            reply, _ = main.run_qwen_local_cli("hello", model, "test")
        self.assertEqual(reply, "Done")
        self.assertEqual(events, [
            {"type": "progress", "message": "Qwen Code is thinking..."}, None,
            {"type": "progress", "message": "Qwen Code is thinking..."},
            {"type": "error", "message": "Error: server stopped"},
        ])

    def test_run_local_llm_falls_back_to_complete_local_when_harness_disabled(self):
        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_qwen_harness", return_value=False),
            mock.patch.object(main, "complete_local", return_value="direct chat reply") as complete,
            mock.patch.object(main, "run_agent_command") as agent_cmd,
        ):
            reply, cid = main.run_local_llm(
                "Hello",
                "local-test",
                "local-chat-1",
                "KookAI",
                target="Sandbox",
            )
        self.assertEqual(reply, "direct chat reply")
        self.assertEqual(cid, "local-chat-1")
        complete.assert_called_once()
        agent_cmd.assert_not_called()

    def test_qwen_error_never_falls_back_to_cloud_and_preserves_failover_order(self):
        self.assertEqual(
            main.PROVIDER_FAILOVER_ORDER,
            ["agy", "claude", "codex", "kimi", "zai", "xai", "muse", "deepseek"],
        )

        failed_proc = subprocess.CompletedProcess(["qwen"], 1, stdout="", stderr="Local server crashed")
        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_qwen_harness", return_value=True),
            mock.patch.object(main, "resolve_qwen_executable", return_value="/usr/local/bin/qwen"),
            mock.patch.object(main, "run_agent_command", return_value=failed_proc),
            mock.patch.object(main, "is_provider_available") as available,
        ):
            reply, _ = main.run_selected_cli(
                "Edit file",
                "local-test",
                "conv-local-1",
                "Sandbox",
                "KookAI",
                provider="local",
            )
        self.assertIn("Qwen Code CLI Error (Exit Code 1)", reply)
        self.assertIn("Local server crashed", reply)
        available.assert_not_called()

    def test_qwen_cancellation_propagates_without_cloud_failover(self):
        cancel_event = threading.Event()
        with (
            mock.patch.object(main, "load_runtime_model_catalog", return_value=self.catalog),
            mock.patch.object(main, "should_use_qwen_harness", return_value=True),
            mock.patch.object(main, "resolve_qwen_executable", return_value="/usr/local/bin/qwen"),
            mock.patch.object(main, "run_agent_command", side_effect=main.AgentCommandCancelled("cancelled")),
            mock.patch.object(main, "is_provider_available") as available,
        ):
            with self.assertRaises(main.AgentCommandCancelled):
                main.run_selected_cli(
                    "Edit file",
                    "local-test",
                    "conv-local-2",
                    "Sandbox",
                    "KookAI",
                    provider="local",
                    cancel_event=cancel_event,
                )
        available.assert_not_called()

    def test_cli_manager_and_requirements_include_qwen(self):
        definition = cli_manager.CLI_DEFINITIONS["qwen"]
        self.assertEqual(definition.install_kind, "npm")
        self.assertEqual(definition.install_source, "@qwen-code/qwen-code")
        self.assertEqual(definition.executable, "qwen")
        self.assertEqual(definition.env_path, "QWEN_CLI_PATH")

        req_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "requirements.txt")
        self.assertIn("qwen", cli_manager.parse_cli_requirements(req_path))

    def test_cli_endpoints_accept_qwen(self):
        req = SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"),
            headers={},
            query_params={},
        )
        with mock.patch.object(
            main,
            "install_cli",
            return_value={"id": "qwen", "installed": True, "status": "installed"},
        ) as install_mock:
            res = asyncio.run(main.install_cli_requirement("qwen", req))
        self.assertEqual(res.status_code, 200)
        install_mock.assert_called_once_with("qwen")

        with (
            mock.patch.object(
                main,
                "get_cli_statuses",
                return_value=[{"id": "qwen", "installed": True, "status": "installed"}],
            ),
            mock.patch.object(
                main,
                "launch_cli_login",
                return_value={"launched": True, "message": "Opened", "command": "qwen"},
            ) as login_mock,
        ):
            res_conn = asyncio.run(main.connect_cli_account("qwen", req))
        self.assertEqual(res_conn.status_code, 200)
        login_mock.assert_called_once_with("qwen", main.APP_DIR)


if __name__ == "__main__":
    unittest.main()
