import asyncio
import os
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import cli_manager
import main


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class AgentCommandTimeoutTests(unittest.TestCase):
    def test_active_command_can_run_longer_than_idle_timeout(self):
        script = (
            "import time\n"
            "for index in range(8):\n"
            "    print(index, flush=True)\n"
            "    time.sleep(0.04)\n"
        )
        result = main.run_agent_command(
            [sys.executable, "-u", "-c", script],
            os.getcwd(),
            timeout=0.12,
            max_runtime=0,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("7", result.stdout)

    def test_silent_command_hits_idle_timeout(self):
        with self.assertRaises(main.AgentCommandTimeout) as context:
            main.run_agent_command(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                os.getcwd(),
                timeout=0.05,
                max_runtime=0,
            )
        self.assertEqual(context.exception.reason, "idle")

    def test_optional_max_runtime_stops_active_command(self):
        script = (
            "import time\n"
            "while True:\n"
            "    print('working', flush=True)\n"
            "    time.sleep(0.02)\n"
        )
        with self.assertRaises(main.AgentCommandTimeout) as context:
            main.run_agent_command(
                [sys.executable, "-u", "-c", script],
                os.getcwd(),
                timeout=1,
                max_runtime=0.12,
            )
        self.assertEqual(context.exception.reason, "max_runtime")


class CliManagerTests(unittest.TestCase):
    def setUp(self):
        cli_manager._runtime_state.clear()

    def test_parse_cli_requirements_uses_pip_safe_comments(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(
                "fastapi>=0.139,<1\n"
                "# kookai-cli: agy\n"
                "# kookai-cli: claude\n"
                "# kookai-cli: codex\n"
                "# kookai-cli: kimi\n"
                "# kookai-cli: grok\n"
                "# kookai-cli: unknown\n"
                "# kookai-cli: codex\n"
            )
            path = file.name
        try:
            self.assertEqual(
                cli_manager.parse_cli_requirements(path),
                ["agy", "claude", "codex", "kimi", "grok"],
            )
        finally:
            os.unlink(path)

    def test_install_cli_skips_an_existing_executable(self):
        installed = {
            "id": "codex",
            "name": "OpenAI Codex",
            "installed": True,
            "status": "installed",
            "version": "codex 1.2.3",
            "message": "",
        }
        with (
            mock.patch.object(cli_manager, "inspect_cli", return_value=installed),
            mock.patch.object(cli_manager, "_install_npm_package") as npm_install,
        ):
            result = cli_manager.install_cli("codex")
        self.assertTrue(result["installed"])
        npm_install.assert_not_called()

    def test_install_cli_records_installer_failure(self):
        failed = completed(returncode=1, stderr="npm permission denied")
        with (
            mock.patch.object(
                cli_manager,
                "resolve_cli_executable",
                return_value=None,
            ),
            mock.patch.object(
                cli_manager,
                "_install_npm_package",
                return_value=failed,
            ),
        ):
            result = cli_manager.install_cli("claude")
        self.assertEqual(result["status"], "error")
        self.assertIn("npm permission denied", result["message"])

    def test_npm_installer_falls_back_to_user_owned_prefix(self):
        with (
            mock.patch.object(cli_manager.shutil, "which", return_value="/usr/bin/npm"),
            mock.patch.object(
                cli_manager,
                "_run_installer",
                side_effect=[
                    completed(returncode=1, stderr="EACCES"),
                    completed(returncode=0, stdout="installed"),
                ],
            ) as run_installer,
            mock.patch.dict(os.environ, {"PATH": "/usr/bin"}, clear=False),
        ):
            result = cli_manager._install_npm_package("@openai/codex")
        self.assertEqual(result.returncode, 0)
        fallback_command = run_installer.call_args_list[1].args[0]
        self.assertIn("--prefix", fallback_command)
        self.assertIn(
            os.path.normpath(os.path.expanduser("~/.local")),
            fallback_command,
        )

    def test_grok_uses_official_installer_and_login_command(self):
        definition = cli_manager.CLI_DEFINITIONS["grok"]

        self.assertEqual(definition.install_source, "https://x.ai/cli/install.sh")
        self.assertEqual(definition.connect_args, ("login",))
        self.assertEqual(definition.executable, "grok")

    def test_launch_codex_login_opens_a_terminal(self):
        with (
            mock.patch.object(
                cli_manager,
                "resolve_cli_executable",
                return_value="/usr/bin/codex",
            ),
            mock.patch.object(cli_manager, "sys_platform", return_value="linux"),
            mock.patch.object(
                cli_manager.shutil,
                "which",
                side_effect=lambda name: "/usr/bin/xterm" if name == "xterm" else None,
            ),
            mock.patch.object(cli_manager.os, "name", "posix"),
            mock.patch.object(cli_manager.subprocess, "Popen") as popen,
            mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False),
        ):
            result = cli_manager.launch_cli_login("codex", "/tmp")
        self.assertTrue(result["launched"])
        terminal_command = popen.call_args.args[0]
        self.assertIn("codex", terminal_command[-1])
        self.assertIn("login", terminal_command[-1])


class CliApiTests(unittest.TestCase):
    @staticmethod
    def request(host):
        return SimpleNamespace(
            client=SimpleNamespace(host=host),
            headers={},
            query_params={},
        )

    def test_localhost_can_manage_cli_connections(self):
        self.assertTrue(
            main.can_manage_cli_connections(self.request("127.0.0.1"))
        )

    def test_remote_client_cannot_manage_cli_connections(self):
        with self.assertRaises(HTTPException) as context:
            main.verify_cli_admin(self.request("198.51.100.4"))
        self.assertEqual(context.exception.status_code, 403)

    def test_cli_status_rejects_remote_clients(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(main.get_cli_status(self.request("198.51.100.4")))
        self.assertEqual(context.exception.status_code, 403)

    def test_cli_status_endpoint_reports_management_permission(self):
        statuses = [
            {
                "id": "codex",
                "name": "OpenAI Codex",
                "installed": True,
                "status": "installed",
            }
        ]
        with mock.patch.object(main, "get_cli_statuses", return_value=statuses):
            response = asyncio.run(
                main.get_cli_status(self.request("127.0.0.1"))
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"can_manage":true', response.body)

    def test_run_selected_cli_automatic_failover(self):
        progress_events = []

        def mock_progress(evt_type, msg):
            progress_events.append((evt_type, msg))

        def mock_invoke(
            prov,
            prov_model,
            message,
            conversation_id,
            target,
            workspace,
            effort,
            speed,
            thinking,
            image_paths,
            progress_callback,
        ):
            if prov == "codex":
                return (
                    "⚠️ **Codex CLI Error (Exit Code 1)**\n\nRate limit exceeded",
                    "codex-cid-1",
                )
            elif prov == "agy":
                return "Hello from fallback agy provider", "agy-cid-2"
            return "❌ **Execution Error**: Unsupported", conversation_id

        with (
            mock.patch.object(main, "_invoke_provider_backend", side_effect=mock_invoke),
            mock.patch.object(
                main, "is_provider_available", side_effect=lambda p: p in {"codex", "agy"}
            ),
        ):
            reply, cid = main.run_selected_cli(
                message="Test failover",
                model_ui_name="5.6 Sol",
                conversation_id="conv-123",
                target="Sandbox",
                workspace="agy",
                provider="codex",
                progress_callback=mock_progress,
            )

        self.assertIn("Automatic Failover", reply)
        self.assertIn("failed over to **agy**", reply)
        self.assertIn("Hello from fallback agy provider", reply)
        self.assertEqual(cid, "agy-cid-2")
        self.assertTrue(
            any("failing over to 'agy'" in msg.lower() for _, msg in progress_events)
        )

    def test_is_execution_failure_detects_timeouts_and_cli_errors(self):
        self.assertTrue(main.is_execution_failure("⏱️ **Timeout Error**: The request to `agy` CLI exceeded the 600-second limit."))
        self.assertTrue(main.is_execution_failure("⏱️ **Timeout Error**: The `agy` CLI produced no output for 600 seconds and was stopped because it may be stuck."))
        self.assertTrue(main.is_execution_failure("⚠️ **agy CLI Error (Exit Code 1)**\n\n```\nError: timeout waiting for response\n```"))
        self.assertTrue(main.is_execution_failure("❌ **Execution Error**: Failed to run `agy` CLI."))
        self.assertFalse(main.is_execution_failure("Here is the completed code you requested."))

    def test_run_selected_cli_failover_on_timeout_error(self):
        progress_events = []

        def mock_progress(evt_type, msg):
            progress_events.append((evt_type, msg))

        def mock_invoke(
            prov,
            prov_model,
            message,
            conversation_id,
            target,
            workspace,
            effort,
            speed,
            thinking,
            image_paths,
            progress_callback,
        ):
            if prov == "agy":
                return (
                    "⚠️ **agy CLI Error (Exit Code 1)**\n\n```\nError: timeout waiting for response\n```",
                    conversation_id,
                )
            elif prov == "claude":
                return "Hello from Claude fallback", "claude-cid-1"
            return "❌ **Execution Error**: Unsupported", conversation_id

        with (
            mock.patch.object(main, "_invoke_provider_backend", side_effect=mock_invoke),
            mock.patch.object(
                main, "is_provider_available", side_effect=lambda p: p in {"agy", "claude"}
            ),
        ):
            reply, cid = main.run_selected_cli(
                message="Test timeout failover",
                model_ui_name="Gemini 3.7 Flash (High)",
                conversation_id="conv-456",
                target="Sandbox",
                workspace="agy",
                provider="agy",
                progress_callback=mock_progress,
            )

        self.assertIn("Automatic Failover", reply)
        self.assertIn("failed over to **claude**", reply)
        self.assertIn("Hello from Claude fallback", reply)
        self.assertEqual(cid, "claude-cid-1")

    def test_run_agy_cli_recovers_from_timeout_response(self):
        calls = []

        def mock_run_command(cmd, cwd_path, timeout=600, progress_callback=None):
            calls.append(list(cmd))
            # First attempt with --continue returns timeout error
            if "--continue" in cmd:
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="", stderr="Error: timeout waiting for response"
                )
            # Fallback fresh conversation succeeds
            return subprocess.CompletedProcess(
                cmd, 0, stdout="Success response after recovery", stderr=""
            )

        with (
            mock.patch.object(main, "get_existing_db_ids", side_effect=[{"conv-existing"}, {"conv-existing", "conv-new"}]),
            mock.patch.object(main, "get_conversation_project", return_value="KookAI"),
            mock.patch.object(main, "run_agy_command", side_effect=mock_run_command),
            mock.patch.object(main, "kill_processes_locking_db") as mock_kill,
        ):
            reply, cid = main.run_agy_cli(
                message="Hello after timeout",
                model_ui_name="Gemini 3.7 Flash (High)",
                conversation_id="conv-existing",
                target="Sandbox",
                workspace="KookAI",
            )

        self.assertEqual(reply, "Success response after recovery")
        self.assertEqual(cid, "conv-new")
        self.assertTrue(mock_kill.called)
        self.assertGreaterEqual(len(calls), 2)
        # Verify fallback command removed --continue and --conversation
        self.assertNotIn("--continue", calls[-1])
        self.assertNotIn("--conversation", calls[-1])


if __name__ == "__main__":
    unittest.main()


