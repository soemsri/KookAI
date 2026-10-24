import json
import os
import tempfile
import unittest
from unittest import mock

import claude_backend
import codex_backend
import main


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


if __name__ == "__main__":
    unittest.main()
