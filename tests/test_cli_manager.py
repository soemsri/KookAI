import asyncio
import os
import subprocess
import tempfile
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
                "# kookai-cli: unknown\n"
                "# kookai-cli: codex\n"
            )
            path = file.name
        try:
            self.assertEqual(
                cli_manager.parse_cli_requirements(path),
                ["agy", "claude", "codex", "kimi"],
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


if __name__ == "__main__":
    unittest.main()
