import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import claude_backend
import codex_backend
import local_backend
import main
import qwen_backend


class ClaudeBackendTests(unittest.TestCase):
    def test_model_provider_and_effort_mapping(self):
        self.assertEqual(claude_backend.claude_model_slug("Fable 5.1"), "claude-fable-5-1")
        self.assertEqual(claude_backend.claude_model_slug("Fable 5"), "fable")
        self.assertEqual(claude_backend.claude_model_slug("Opus 5.5"), "claude-opus-5-5")
        self.assertEqual(claude_backend.claude_model_slug("Claude Opus 5.5 (High)"), "claude-opus-5-5")
        self.assertEqual(claude_backend.claude_model_slug("claude-opus-5-5-high"), "claude-opus-5-5")
        self.assertEqual(claude_backend.claude_model_slug("Sonnet 5.5"), "claude-sonnet-5-5")
        self.assertEqual(claude_backend.claude_model_slug("Claude Sonnet 5.5 (High)"), "claude-sonnet-5-5")
        self.assertEqual(claude_backend.claude_model_slug("Haiku 5.5"), "claude-haiku-5-5")
        self.assertEqual(claude_backend.claude_model_slug("Opus 4.8"), "claude-opus-4-8")
        self.assertEqual(codex_backend.resolve_provider(None, "Opus 5.5"), "claude")
        self.assertEqual(codex_backend.resolve_provider(None, "Claude Opus 5.5 (High)"), "claude")
        self.assertEqual(codex_backend.resolve_provider(None, "Sonnet 5"), "claude")
        self.assertEqual(
            claude_backend.normalize_claude_effort("Medium", "Claude Opus 5.5 (High)"),
            ("High", "high"),
        )
        self.assertEqual(
            claude_backend.normalize_claude_effort("Medium", "Claude Opus 5.5 (Low)"),
            ("Low", "low"),
        )
        self.assertEqual(
            claude_backend.normalize_claude_effort("Extra", "Opus 5.5"),
            ("Extra", "xhigh"),
        )
        self.assertEqual(
            claude_backend.normalize_claude_effort("Extra", "Opus 5"),
            ("Extra", "xhigh"),
        )
        self.assertEqual(
            claude_backend.normalize_claude_effort("Light", "Opus 5.5"),
            ("Low", "low"),
        )
        self.assertEqual(
            claude_backend.normalize_claude_effort("Light", "Opus 5"),
            ("Low", "low"),
        )
        with self.assertRaises(ValueError):
            claude_backend.normalize_claude_effort("Extra", "Sonnet 4.6")

    def test_build_command_uses_stdin_and_safe_permissions(self):
        command = claude_backend.build_claude_command(
            "claude",
            "prompt stays off argv",
            "Sonnet 5",
            effort="Max",
            target="Sandbox",
            conversation_id="claude_session-123",
        )
        self.assertNotIn("prompt stays off argv", command)
        self.assertIn("stream-json", command)
        self.assertIn("sonnet", command)
        self.assertIn("max", command)
        self.assertIn("session-123", command)
        self.assertIn("dontAsk", command)
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_build_legacy_model_omits_unsupported_effort(self):
        command = claude_backend.build_claude_command(
            "claude",
            "hello",
            "Haiku 4.5",
            effort="Medium",
            target="Real",
        )
        self.assertNotIn("--effort", command)
        self.assertIn("--dangerously-skip-permissions", command)

    def test_parse_stream_uses_result_and_session(self):
        output = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init", "session_id": "abc"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "intermediate"}]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": False,
                        "result": "final",
                        "session_id": "abc",
                    }
                ),
            ]
        )
        parsed = claude_backend.parse_claude_stream_json(output)
        self.assertEqual(parsed["session_id"], "abc")
        self.assertEqual(parsed["final_message"], "final")
        self.assertEqual(parsed["errors"], [])

    def test_parse_stream_captures_rate_limit_event(self):
        # Payload shape observed from Claude Code 2.1.305 stream-json output.
        event = {
            "type": "rate_limit_event",
            "rate_limit_info": {
                "status": "allowed",
                "resetsAt": 1792816800,
                "rateLimitType": "five_hour",
                "overageStatus": "rejected",
                "overageDisabledReason": "org_level_disabled",
                "isUsingOverage": False,
                "unifiedWindows": {
                    "five_hour": {"utilization": 0.12, "resetsAt": 1792816800},
                    "seven_day": {"utilization": 0.07, "resetsAt": 1793336400},
                },
            },
            "session_id": "abc",
        }
        parsed = claude_backend.parse_claude_stream_json(json.dumps(event), observed_at=1792800000)
        self.assertEqual(
            parsed["rate_limits"],
            {
                "status": "allowed",
                "observedAt": 1792800000.0,
                "hourly": {"utilization": 0.12, "resetsAt": 1792816800},
                "weekly": {"utilization": 0.07, "resetsAt": 1793336400},
            },
        )

        legacy = dict(event, rate_limit_info={"status": "allowed", "resetsAt": 1792816800})
        self.assertIsNone(claude_backend.parse_claude_stream_json(json.dumps(legacy))["rate_limits"])

    def test_build_claude_rate_limits_reports_fractions_as_percent(self):
        snapshot = {
            "status": "allowed",
            "observedAt": 1792800000.0,
            "hourly": {"utilization": 0.12, "resetsAt": 1792816800},
            "weekly": {"utilization": 1.3, "resetsAt": 1793336400},
        }
        view = claude_backend.build_claude_rate_limits(snapshot, now=1792800100)
        self.assertTrue(view["available"])
        self.assertEqual(view["source"], "claude_cli")
        self.assertEqual(view["hourly"]["usedPercent"], 12.0)
        self.assertEqual(view["hourly"]["remainingPercent"], 88.0)
        self.assertEqual(view["hourly"]["resetTime"], "2026-10-24T04:40:00Z")
        # Utilization above 1 is legitimate (past the cap) and caps the display.
        self.assertEqual(view["weekly"]["usedPercent"], 100.0)
        self.assertEqual(view["weekly"]["remainingPercent"], 0.0)
        self.assertEqual(view["usedPercent"], 12.0)
        self.assertEqual(view["observedAt"], "2026-10-24T00:00:00Z")

        # Once a window's reset time passes, its stale utilization is dropped.
        later = claude_backend.build_claude_rate_limits(snapshot, now=1792816800)
        self.assertEqual(later["hourly"]["usedPercent"], 0.0)
        self.assertIsNone(later["hourly"]["resetTime"])
        self.assertEqual(later["weekly"]["usedPercent"], 100.0)

        missing = claude_backend.build_claude_rate_limits(None, now=1792800100)
        self.assertFalse(missing["available"])
        self.assertIsNone(missing["usedPercent"])
        self.assertTrue(missing["description"])

    def test_run_claude_cli_records_rate_limits_per_profile(self):
        lines = [
            json.dumps({
                "type": "rate_limit_event",
                "rate_limit_info": {
                    "status": "allowed",
                    "unifiedWindows": {"five_hour": {"utilization": 0.25, "resetsAt": 4102444800}},
                },
                "session_id": "sess-1",
            }),
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok", "session_id": "sess-1"}),
        ]

        def fake_run(cmd, cwd_path, **kwargs):
            for line in lines:
                kwargs["raw_line_callback"]("stdout", line)
            return main.subprocess.CompletedProcess(cmd, 0, "\n".join(lines), "")

        main._claude_rate_limits_by_profile.clear()
        self.addCleanup(main._claude_rate_limits_by_profile.clear)
        with tempfile.TemporaryDirectory() as temp_dir, \
                mock.patch.object(main, "run_agent_command", side_effect=fake_run), \
                mock.patch.object(main, "resolve_claude_executable", return_value="/bin/claude"), \
                mock.patch.object(main, "resolve_project_directory", return_value=temp_dir), \
                mock.patch.object(main, "CLAUDE_CONVERSATIONS_FILE", os.path.join(temp_dir, "claude.json")):
            main.run_claude_cli("hi", "Sonnet 5.5", "new-convo", profile_id="prof_work")

        self.assertIsNone(main.get_claude_rate_limits_snapshot(None))
        snapshot = main.get_claude_rate_limits_snapshot("prof_work")
        self.assertEqual(snapshot["hourly"], {"utilization": 0.25, "resetsAt": 4102444800})

    def test_thinking_environment_can_disable_and_reenable(self):
        disabled = claude_backend.build_claude_environment(False)
        self.assertEqual(disabled["MAX_THINKING_TOKENS"], "0")
        self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", disabled)
        enabled = claude_backend.build_claude_environment(True)
        self.assertNotIn("MAX_THINKING_TOKENS", enabled)
        self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", enabled)

    def test_claude_history_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = os.path.join(temp_dir, "claude_conversations.json")
            with mock.patch.object(main, "CLAUDE_CONVERSATIONS_FILE", history_path):
                main.persist_claude_exchange(
                    "claude_session-1",
                    "project",
                    "Sonnet 5",
                    "High",
                    True,
                    "hello",
                    "world",
                )
                record = main.get_claude_conversation("claude_session-1")

        self.assertIsNotNone(record)
        self.assertEqual(record["provider"], "claude")
        self.assertEqual(record["thinking"], True)
        self.assertEqual(record["messages"][-1]["content"], "world")

    def test_normalize_local_anthropic_base_url(self):
        self.assertEqual(
            claude_backend.normalize_local_anthropic_base_url("http://192.168.1.200:8000/v1"),
            "http://192.168.1.200:8000",
        )
        self.assertEqual(
            claude_backend.normalize_local_anthropic_base_url("http://192.168.1.200:8000/v1/"),
            "http://192.168.1.200:8000",
        )
        self.assertEqual(
            claude_backend.normalize_local_anthropic_base_url("http://127.0.0.1:4000/proxy/v1"),
            "http://127.0.0.1:4000/proxy",
        )
        self.assertEqual(
            claude_backend.normalize_local_anthropic_base_url("http://192.168.1.200:8000"),
            "http://192.168.1.200:8000",
        )

    def test_build_local_claude_command_uses_raw_model_and_local_prefix(self):
        sandbox_cmd = claude_backend.build_local_claude_command(
            "claude",
            "secret prompt off argv",
            "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
            target="Sandbox",
            conversation_id="claude_cloud-only-id",
        )
        self.assertNotIn("secret prompt off argv", sandbox_cmd)
        self.assertEqual(sandbox_cmd[sandbox_cmd.index("--model") + 1], "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp")
        self.assertNotIn("--effort", sandbox_cmd)
        self.assertNotIn("--resume", sandbox_cmd)
        self.assertIn("--permission-mode", sandbox_cmd)
        self.assertEqual(sandbox_cmd[sandbox_cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("--dangerously-skip-permissions", sandbox_cmd)

        real_cmd = claude_backend.build_local_claude_command(
            "claude",
            "hello",
            "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
            target="Real",
            conversation_id="local_claude_sess-42",
        )
        self.assertIn("--dangerously-skip-permissions", real_cmd)
        self.assertNotIn("--permission-mode", real_cmd)
        self.assertEqual(real_cmd[real_cmd.index("--resume") + 1], "sess-42")

    def test_build_local_claude_environment_sets_auth_and_strips_cloud_flags(self):
        ambient = {
            "ANTHROPIC_API_KEY": "sk-ant-cloud-secret",
            "ANTHROPIC_AUTH_TOKEN": "cloud-token",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_USE_VERTEX": "1",
            "CLAUDE_CODE_USE_FOUNDRY": "1",
            "CLAUDE_CODE_DISABLE_THINKING": "1",
            "MAX_THINKING_TOKENS": "0",
        }
        with mock.patch.dict(os.environ, ambient, clear=False):
            env_default = claude_backend.build_local_claude_environment(
                "http://192.168.1.200:8000/v1",
                "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
                api_key="",
                thinking=True,
            )
            self.assertEqual(env_default["ANTHROPIC_BASE_URL"], "http://192.168.1.200:8000")
            self.assertEqual(env_default["ANTHROPIC_AUTH_TOKEN"], "local")
            self.assertEqual(env_default["ANTHROPIC_API_KEY"], "local")
            self.assertEqual(env_default["NO_BROWSER"], "1")
            self.assertNotIn("CLAUDE_CODE_USE_BEDROCK", env_default)
            self.assertNotIn("CLAUDE_CODE_USE_VERTEX", env_default)
            self.assertNotIn("CLAUDE_CODE_USE_FOUNDRY", env_default)
            self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", env_default)
            self.assertNotIn("MAX_THINKING_TOKENS", env_default)

            env_keyed_off = claude_backend.build_local_claude_environment(
                "http://192.168.1.200:8000",
                "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
                api_key="123",
                thinking=False,
            )
            self.assertEqual(env_keyed_off["ANTHROPIC_AUTH_TOKEN"], "123")
            self.assertEqual(env_keyed_off["ANTHROPIC_API_KEY"], "123")
            self.assertEqual(env_keyed_off["MAX_THINKING_TOKENS"], "0")

    def test_local_harness_mode_claude_variants_and_discovery_description(self):
        local_backend._cache.clear()
        self.addCleanup(local_backend._cache.clear)
        for val in ("claude", "claude-code", "claude_code"):
            with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": val}):
                self.assertEqual(qwen_backend.local_harness_mode(), "claude")
                self.assertFalse(qwen_backend.should_use_qwen_harness())

        with mock.patch.dict(os.environ, {"KOOKAI_LOCAL_HARNESS": "claude"}), \
             mock.patch.object(local_backend, "_request", return_value=iter([{"data": [{"id": "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp"}]}])), \
             mock.patch.object(claude_backend, "is_claude_available", return_value=True):
            models = local_backend.discover_local_models(force=True)
        self.assertIn("Claude Code harness", models[0]["description"])

    def test_classify_claude_progress_line_thinking_tokens(self):
        line = json.dumps({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 5})
        self.assertEqual(
            claude_backend.classify_claude_progress_line("stdout", line),
            {"type": "progress", "message": "Claude is thinking..."},
        )

    def test_run_local_llm_routes_to_claude_persists_resumes_and_recovers(self):
        local_backend._cache.clear()
        self.addCleanup(local_backend._cache.clear)
        calls = []
        progress_events = []

        def fake_run_agent(cmd, cwd_path, **kwargs):
            calls.append((list(cmd), cwd_path, kwargs.get("stdin_text", ""), kwargs.get("env", {})))
            self.assertNotIn("profile_id", kwargs)
            if "--resume" in cmd and cmd[cmd.index("--resume") + 1] == "stale-sid":
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    stdout="",
                    stderr="Error: No conversation found with session ID: stale-sid",
                )
            sid = cmd[cmd.index("--resume") + 1] if "--resume" in cmd else "claude-fresh-1"
            out = "\n".join([
                json.dumps({"type": "system", "subtype": "init", "session_id": sid}),
                json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "result": f"Local Claude reply ({sid})"}),
            ])
            for line in out.splitlines():
                kwargs["raw_line_callback"]("stdout", line)
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        local_model = {
            "id": "local-v4",
            "label": "deepseek-ai/DeepSeek-V4-Flash-Vision-Exp (Local)",
            "description": "Local LLM • Claude Code harness • workspace tools",
            "provider": "local",
            "cli_model": "local/deepseek-ai/DeepSeek-V4-Flash-Vision-Exp",
            "badge": "Local",
            "usage_bucket": "local",
            "enabled": True,
            "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
        }
        catalog = {
            "schema_version": 1,
            "catalog_version": "test",
            "default_model": "local-v4",
            "models": [local_model],
        }

        with tempfile.TemporaryDirectory() as tmp:
            ws_dir = os.path.join(tmp, "MyProj")
            os.makedirs(ws_dir)
            with (
                mock.patch.dict(os.environ, {
                    "KOOKAI_LOCAL_HARNESS": "claude",
                    "KOOKAI_LOCAL_LLM_URL": "http://192.168.1.200:8000",
                    "KOOKAI_LOCAL_LLM_API_KEY": "123",
                }),
                mock.patch.object(main, "PROJECTS_ROOTS", (tmp,)),
                mock.patch.object(main, "CANONICAL_CONVERSATIONS_FILE", os.path.join(tmp, "conversations.json")),
                mock.patch.object(main, "CONVERSATION_METADATA_FILE", os.path.join(tmp, "metadata.json")),
                mock.patch.object(main, "get_workspace_alignment_context", return_value=""),
                mock.patch.object(main, "load_runtime_model_catalog", return_value=catalog),
                mock.patch.object(main, "should_use_claude_local_harness", return_value=True),
                mock.patch.object(main, "resolve_claude_executable", return_value="/usr/local/bin/claude"),
                mock.patch.object(main, "convo_id_mapping", {}),
                mock.patch.object(main, "in_memory_chats", {}),
                mock.patch.object(main, "record_claude_rate_limits") as record_limits,
                mock.patch.object(main, "run_agent_command", side_effect=fake_run_agent),
            ):
                # Turn 1: fresh session via build_chat_response (Sandbox)
                req1 = main.ChatRequest(
                    message="Hello local Claude",
                    model="local-v4",
                    provider="local",
                    workspace="MyProj",
                    target="Sandbox",
                    conversation_id="temp-local-1",
                )
                res1 = main.build_chat_response(req1)
                self.assertEqual(res1["reply"], "Local Claude reply (claude-fresh-1)")
                self.assertEqual(res1["provider"], "local")
                self.assertEqual(res1["conversation_id"], "local_claude_claude-fresh-1")
                self.assertIn("dontAsk", calls[0][0])
                self.assertNotIn("--resume", calls[0][0])
                self.assertEqual(calls[0][3]["ANTHROPIC_BASE_URL"], "http://192.168.1.200:8000")
                self.assertEqual(calls[0][3]["ANTHROPIC_AUTH_TOKEN"], "123")
                self.assertEqual(calls[0][3]["ANTHROPIC_API_KEY"], "123")

                # Turn 2: resume existing session (Real)
                req2 = main.ChatRequest(
                    message="Follow up",
                    model="local-v4",
                    provider="local",
                    workspace="MyProj",
                    target="Real",
                    conversation_id="local_claude_claude-fresh-1",
                )
                res2 = main.build_chat_response(req2)
                self.assertEqual(res2["conversation_id"], "local_claude_claude-fresh-1")
                self.assertIn("--dangerously-skip-permissions", calls[1][0])
                self.assertEqual(calls[1][0][calls[1][0].index("--resume") + 1], "claude-fresh-1")

                # Turn 3: stale session recovery injects canonical history
                main.in_memory_chats["local_claude_stale-sid"] = [
                    {"role": "user", "content": "Remember token 99"},
                    {"role": "assistant", "content": "Noted token 99"},
                ]
                reply3, cid3 = main.run_local_llm(
                    "What token?",
                    "local-v4",
                    "local_claude_stale-sid",
                    "MyProj",
                    progress_callback=lambda kind, msg: progress_events.append((kind, msg)),
                )
                self.assertEqual(reply3, "Local Claude reply (claude-fresh-1)")
                self.assertEqual(cid3, "local_claude_claude-fresh-1")
                self.assertIn(("progress", "Claude Code session was unavailable; starting a fresh session."), progress_events)
                self.assertIn("Remember token 99", calls[3][2])
                record_limits.assert_not_called()


if __name__ == "__main__":
    unittest.main()
