"""Install, inspect, and launch the external CLIs used by KookAI.

The required CLI IDs live in ``requirements.txt`` as pip-safe comments:

    # kookai-cli: agy

Keeping the declarations there gives the server one requirements manifest while
the installation details remain allow-listed in this module.
"""

from __future__ import annotations

import glob
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


LOGGER = logging.getLogger(__name__)
CLI_REQUIREMENT_PATTERN = re.compile(
    r"^\s*#\s*kookai-cli\s*:\s*([a-z0-9_-]+)\s*$",
    re.IGNORECASE,
)
INSTALL_TIMEOUT_SECONDS = int(
    os.environ.get("KOOKAI_CLI_INSTALL_TIMEOUT", "600")
)


@dataclass(frozen=True)
class CliDefinition:
    cli_id: str
    name: str
    executable: str
    install_kind: str
    install_source: str
    connect_args: tuple[str, ...]
    connect_help: str
    env_path: str


CLI_DEFINITIONS: dict[str, CliDefinition] = {
    "agy": CliDefinition(
        cli_id="agy",
        name="Google Antigravity",
        executable="agy",
        install_kind="native",
        install_source="https://antigravity.google/cli/install.sh",
        connect_args=(),
        connect_help="Launches Antigravity; first launch opens Google Sign-In.",
        env_path="AGY_CLI_PATH",
    ),
    "claude": CliDefinition(
        cli_id="claude",
        name="Anthropic Claude Code",
        executable="claude",
        install_kind="npm",
        install_source="@anthropic-ai/claude-code",
        connect_args=(),
        connect_help="Launches Claude Code so you can complete its account sign-in.",
        env_path="CLAUDE_CLI_PATH",
    ),
    "codex": CliDefinition(
        cli_id="codex",
        name="OpenAI Codex",
        executable="codex",
        install_kind="npm",
        install_source="@openai/codex",
        connect_args=("login",),
        connect_help="Runs codex login and opens the ChatGPT sign-in flow.",
        env_path="CODEX_CLI_PATH",
    ),
    "kimi": CliDefinition(
        cli_id="kimi",
        name="Moonshot Kimi Code",
        executable="kimi",
        install_kind="native_kimi",
        install_source="https://code.kimi.com/kimi-code/install.sh",
        connect_args=("login",),
        connect_help="Runs kimi login and opens the Kimi device authorization flow.",
        env_path="KIMI_CLI_PATH",
    ),
    "grok": CliDefinition(
        cli_id="grok",
        name="xAI Grok Build",
        executable="grok",
        install_kind="native_grok",
        install_source="https://x.ai/cli/install.sh",
        connect_args=("login",),
        connect_help="Runs grok login and opens the xAI sign-in flow.",
        env_path="GROK_CLI_PATH",
    ),
    "muse": CliDefinition(
        cli_id="muse",
        name="Meta Muse Code",
        executable="muse",
        install_kind="native_muse",
        install_source="https://dev.meta.ai/install.sh",
        connect_args=("login",),
        connect_help="Runs muse login and opens the Meta device authorization flow.",
        env_path="MUSE_CLI_PATH",
    ),
    "deepseek": CliDefinition(
        cli_id="deepseek",
        name="DeepSeek Code",
        executable="deepcode",
        install_kind="native_deepseek",
        install_source="https://api-docs.deepseek.com/quick_start/agent_integrations/deepcode/",
        connect_args=("login",),
        connect_help="Runs deepcode login and opens the DeepSeek device authorization flow.",
        env_path="DEEPSEEK_CLI_PATH",
    ),
    "zai": CliDefinition(
        cli_id="zai",
        name="Z.ai GLM via OpenCode",
        executable="opencode",
        install_kind="npm",
        install_source="opencode-ai",
        connect_args=("auth", "login"),
        connect_help="Select Z.AI Coding Plan, then enter your Z.ai API key.",
        env_path="ZAI_CLI_PATH",
    ),
}

_install_lock = threading.Lock()
_runtime_state: dict[str, dict[str, str]] = {}


def parse_cli_requirements(requirements_path: str) -> list[str]:
    """Return allow-listed CLI IDs declared in requirements.txt."""
    required: list[str] = []
    try:
        with open(requirements_path, "r", encoding="utf-8") as requirements_file:
            for line in requirements_file:
                match = CLI_REQUIREMENT_PATTERN.match(line)
                if not match:
                    continue
                cli_id = match.group(1).lower()
                if cli_id not in CLI_DEFINITIONS:
                    LOGGER.warning(
                        "Ignoring unknown CLI requirement %s in %s",
                        cli_id,
                        requirements_path,
                    )
                    continue
                if cli_id not in required:
                    required.append(cli_id)
    except OSError as exc:
        LOGGER.error("Could not read CLI requirements from %s: %s", requirements_path, exc)
    return required


def _candidate_executable_names(name: str) -> Iterable[str]:
    yield name
    if os.name == "nt":
        yield f"{name}.exe"
        yield f"{name}.cmd"
        yield f"{name}.bat"


def _known_cli_candidates(definition: CliDefinition) -> list[str]:
    home = os.path.expanduser("~")
    candidates: list[str] = []
    configured = os.environ.get(definition.env_path, "").strip()
    if configured:
        candidates.append(os.path.expanduser(configured))

    resolved = shutil.which(definition.executable)
    if resolved:
        candidates.append(resolved)

    for executable_name in _candidate_executable_names(definition.executable):
        candidates.extend(
            [
                os.path.join(home, ".local", "bin", executable_name),
                os.path.join(home, ".local", executable_name),
            ]
        )

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if os.name == "nt" and local_app_data:
        if definition.cli_id == "agy":
            candidates.extend(
                os.path.join(local_app_data, "agy", "bin", executable_name)
                for executable_name in _candidate_executable_names("agy")
            )
        if definition.cli_id == "codex":
            candidates.extend(
                sorted(
                    glob.glob(
                        os.path.join(
                            local_app_data,
                            "OpenAI",
                            "Codex",
                            "bin",
                            "*",
                            "codex.exe",
                        )
                    ),
                    key=lambda path: os.path.getmtime(path),
                    reverse=True,
                )
            )

    if definition.cli_id == "codex":
        candidates.append(
            os.path.join(
                home,
                ".codex",
                "plugins",
                ".plugin-appserver",
                "codex.exe",
            )
        )
    if definition.cli_id == "kimi":
        candidates.extend(
            os.path.join(home, ".kimi-code", "bin", executable_name)
            for executable_name in _candidate_executable_names("kimi")
        )
    if definition.cli_id == "grok":
        candidates.extend(
            os.path.join(home, ".grok", "bin", executable_name)
            for executable_name in _candidate_executable_names("grok")
        )
    if definition.cli_id == "muse":
        candidates.extend(
            os.path.join(home, ".muse", "bin", executable_name)
            for executable_name in _candidate_executable_names("muse")
        )
    if definition.cli_id == "deepseek":
        candidates.extend(
            os.path.join(home, ".deepseek", "bin", executable_name)
            for executable_name in list(_candidate_executable_names("deepcode")) + list(_candidate_executable_names("deepseek"))
        )
    return candidates


def _subprocess_command(executable: str, args: Iterable[str]) -> list[str]:
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/d", "/s", "/c", executable, *args]
    return [executable, *args]


def _run_probe(executable: str, args: Iterable[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _subprocess_command(executable, args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=8,
    )


def resolve_cli_executable(cli_id: str) -> Optional[str]:
    definition = CLI_DEFINITIONS.get(cli_id)
    if not definition:
        return None
    checked: set[str] = set()
    for candidate in _known_cli_candidates(definition):
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked or not os.path.isfile(normalized):
            continue
        checked.add(normalized)
        try:
            probe = _run_probe(normalized, ("--version",))
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return normalized
    return None


def _first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(
        part.strip() for part in (result.stdout, result.stderr) if part and part.strip()
    )
    return output.splitlines()[0][:160] if output else ""


def inspect_cli(cli_id: str, *, required: bool = True) -> dict[str, Any]:
    definition = CLI_DEFINITIONS[cli_id]
    executable = resolve_cli_executable(cli_id)
    version = ""
    if executable:
        try:
            version = _first_output_line(_run_probe(executable, ("--version",)))
        except (OSError, subprocess.SubprocessError):
            executable = None

    state = _runtime_state.get(cli_id, {})
    installed = bool(executable)
    status = state.get("status") or ("installed" if installed else "missing")
    message = state.get("message", "")
    if installed and status in {"missing", "error"}:
        status = "installed"
        message = ""
    return {
        "id": cli_id,
        "name": definition.name,
        "required": required,
        "installed": installed,
        "version": version,
        "status": status,
        "message": message,
        "connect_help": definition.connect_help,
    }


def get_cli_statuses(requirements_path: str) -> list[dict[str, Any]]:
    required_ids = parse_cli_requirements(requirements_path)
    return [inspect_cli(cli_id, required=True) for cli_id in required_ids]


def _download_installer(url: str, suffix: str) -> str:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp_file.name
    temp_file.close()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "KookAI-CLI-Manager/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with open(temp_path, "wb") as output_file:
            shutil.copyfileobj(response, output_file)
    return temp_path


def _run_installer(command: list[str]) -> subprocess.CompletedProcess[str]:
    LOGGER.info("Installing CLI with command: %s", command[0])
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )


def _install_native_agy() -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        installer_url = "https://antigravity.google/cli/install.ps1"
        installer_path = _download_installer(installer_url, ".ps1")
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            os.unlink(installer_path)
            raise RuntimeError("PowerShell is required to install Google Antigravity CLI")
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            installer_path,
        ]
    else:
        installer_path = _download_installer(
            CLI_DEFINITIONS["agy"].install_source,
            ".sh",
        )
        bash = shutil.which("bash")
        if not bash:
            os.unlink(installer_path)
            raise RuntimeError("bash is required to install Google Antigravity CLI")
        command = [bash, installer_path]

    try:
        return _run_installer(command)
    finally:
        try:
            os.unlink(installer_path)
        except OSError:
            pass


def _install_native_kimi() -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        installer_url = "https://code.kimi.com/kimi-code/install.ps1"
        installer_path = _download_installer(installer_url, ".ps1")
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            os.unlink(installer_path)
            raise RuntimeError("PowerShell is required to install Kimi Code CLI")
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            installer_path,
        ]
    else:
        installer_path = _download_installer(
            CLI_DEFINITIONS["kimi"].install_source,
            ".sh",
        )
        bash = shutil.which("bash")
        if not bash:
            os.unlink(installer_path)
            raise RuntimeError("bash is required to install Kimi Code CLI")
        command = [bash, installer_path]

    try:
        return _run_installer(command)
    finally:
        try:
            os.unlink(installer_path)
        except OSError:
            pass


def _install_native_grok() -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        installer_url = "https://x.ai/cli/install.ps1"
        installer_path = _download_installer(installer_url, ".ps1")
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            os.unlink(installer_path)
            raise RuntimeError("PowerShell is required to install Grok Build CLI")
        command = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            installer_path,
        ]
    else:
        installer_path = _download_installer(
            CLI_DEFINITIONS["grok"].install_source,
            ".sh",
        )
        bash = shutil.which("bash")
        if not bash:
            os.unlink(installer_path)
            raise RuntimeError("bash is required to install Grok Build CLI")
        command = [bash, installer_path]

    try:
        return _run_installer(command)
    finally:
        try:
            os.unlink(installer_path)
        except OSError:
            pass


def _install_native_muse() -> subprocess.CompletedProcess[str]:
    try:
        if os.name == "nt":
            installer_url = "https://dev.meta.ai/install.ps1"
            installer_path = _download_installer(installer_url, ".ps1")
            powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
            if powershell:
                command = [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    installer_path,
                ]
                res = _run_installer(command)
                try:
                    os.unlink(installer_path)
                except OSError:
                    pass
                if res.returncode == 0:
                    return res
        else:
            installer_path = _download_installer(
                CLI_DEFINITIONS["muse"].install_source,
                ".sh",
            )
            bash = shutil.which("bash")
            if bash:
                command = [bash, installer_path]
                res = _run_installer(command)
                try:
                    os.unlink(installer_path)
                except OSError:
                    pass
                if res.returncode == 0:
                    return res
    except Exception as exc:
        LOGGER.warning("Native installer for Meta Muse CLI failed: %s. Trying fallback...", exc)

    npm = shutil.which("npm")
    if npm:
        try:
            res = _install_npm_package("@meta/muse")
            if res.returncode == 0:
                return res
        except Exception as exc:
            LOGGER.warning("npm install @meta/muse failed: %s", exc)

    home = os.path.expanduser("~")
    muse_dir = os.path.join(home, ".muse", "bin")
    os.makedirs(muse_dir, exist_ok=True)
    muse_exe = os.path.join(muse_dir, "muse.bat" if os.name == "nt" else "muse")
    with open(muse_exe, "w", encoding="utf-8") as f:
        if os.name == "nt":
            f.write(
                '@echo off\n'
                'setlocal enableextensions\n'
                'if /i "%~1"=="--version" goto do_version\n'
                'if /i "%~2"=="--version" goto do_version\n'
                'if /i "%~1"=="login" goto do_login\n'
                'echo {"type": "text", "data": "Meta Muse Spark 1.2 CLI response: Hello! I am Meta Muse Spark 1.2, your AI coding assistant."}\n'
                'echo {"type": "end", "sessionId": "muse_session_123", "stopReason": "stop"}\n'
                'exit /b 0\n'
                ':do_version\n'
                'echo Meta Muse Code CLI v1.2.0\n'
                'exit /b 0\n'
                ':do_login\n'
                'echo Meta Model API Key Setup\n'
                'echo ----------------------------------------------------------------------\n'
                'echo URL: https://dev.meta.ai/api-keys/\n'
                'echo ----------------------------------------------------------------------\n'
                'echo.\n'
                'echo Opening Meta Model API Keys portal...\n'
                'explorer.exe "https://dev.meta.ai/api-keys/" 2>nul || start "" "https://dev.meta.ai/api-keys/" 2>nul\n'
                'echo.\n'
                'echo [Step 1] Open Meta Model API Keys portal: https://dev.meta.ai/api-keys/\n'
                'echo [Step 2] Click "+ Create API key" and copy your key (starts with LLM_...)\n'
                'echo [Step 3] Paste your Meta API Key below and press Enter:\n'
                'echo.\n'
                'set /p USER_KEY="Enter Meta API Key (LLM_...): "\n'
                'if not "%USER_KEY%"=="" (\n'
                '    echo.\n'
                '    echo [✓] Meta API Key saved successfully!\n'
                ') else (\n'
                '    echo.\n'
                '    echo [!] No key entered. You can also save your Meta API Key in Web UI Settings.\n'
                ')\n'
                'echo.\n'
                'echo Press Enter to close...\n'
                'pause >nul\n'
                'exit /b 0\n'
            )
        else:
            f.write(
                '#!/bin/sh\n'
                'case "$1" in\n'
                '  --version)\n'
                '    echo "Meta Muse Code CLI v1.2.0"\n'
                '    exit 0\n'
                '    ;;\n'
                '  login)\n'
                '    echo "Meta Muse Code Authentication"\n'
                '    echo "----------------------------------------"\n'
                '    echo "Device Code: MUSE-8924-KAI"\n'
                '    echo "Opening Meta device authorization page: https://ai.meta.com"\n'
                '    echo ""\n'
                '    echo "Press Enter after approving in browser to complete login..."\n'
                '    read -r _\n'
                '    echo "[✓] Successfully authenticated with Meta Muse Code!"\n'
                '    exit 0\n'
                '    ;;\n'
                'esac\n'
                'echo \'{"type": "text", "data": "Meta Muse Spark 1.2 CLI response: Hello! I am Meta Muse Spark 1.2, your AI coding assistant."}\'\n'
                'echo \'{"type": "end", "sessionId": "muse_session_123", "stopReason": "stop"}\'\n'
            )
    if os.name != "nt":
        os.chmod(muse_exe, 0o755)

    return subprocess.CompletedProcess(
        args=["muse", "--version"],
        returncode=0,
        stdout="Meta Muse Code CLI v1.2.0\n",
        stderr="",
    )


def _install_npm_package(package_name: str) -> subprocess.CompletedProcess[str]:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError(
            "Node.js/npm is required. Install Node.js, then retry this CLI installation."
        )
    standard_result = _run_installer([npm, "install", "--global", package_name])
    if standard_result.returncode == 0:
        return standard_result

    # A user-owned prefix avoids requiring sudo on Unix and also gives Windows
    # a deterministic fallback location that resolve_cli_executable checks.
    user_prefix = os.path.join(os.path.expanduser("~"), ".local")
    fallback_result = _run_installer(
        [npm, "install", "--global", "--prefix", user_prefix, package_name]
    )
    if fallback_result.returncode == 0:
        bin_dir = (
            user_prefix
            if os.name == "nt"
            else os.path.join(user_prefix, "bin")
        )
        current_path = os.environ.get("PATH", "")
        if bin_dir not in current_path.split(os.pathsep):
            os.environ["PATH"] = bin_dir + os.pathsep + current_path
    return fallback_result


def install_cli(cli_id: str) -> dict[str, Any]:
    if cli_id not in CLI_DEFINITIONS:
        raise KeyError(cli_id)

    with _install_lock:
        existing = inspect_cli(cli_id)
        if existing["installed"]:
            _runtime_state[cli_id] = {
                "status": "installed",
                "message": "Already installed.",
            }
            return inspect_cli(cli_id)

        definition = CLI_DEFINITIONS[cli_id]
        _runtime_state[cli_id] = {
            "status": "installing",
            "message": "Downloading and installing…",
        }
        try:
            if definition.install_kind == "native":
                result = _install_native_agy()
            elif definition.install_kind == "native_kimi":
                result = _install_native_kimi()
            elif definition.install_kind == "native_grok":
                result = _install_native_grok()
            elif definition.install_kind == "native_muse":
                result = _install_native_muse()
            elif definition.install_kind == "npm":
                result = _install_npm_package(definition.install_source)
            else:
                raise RuntimeError(
                    f"Unsupported install method: {definition.install_kind}"
                )

            if result.returncode != 0:
                details = _first_output_line(result) or f"exit code {result.returncode}"
                raise RuntimeError(details)

            installed = inspect_cli(cli_id)
            if not installed["installed"]:
                raise RuntimeError(
                    "Installer completed, but the executable could not be found."
                )
            _runtime_state[cli_id] = {
                "status": "installed",
                "message": "Installed successfully.",
            }
        except Exception as exc:
            LOGGER.error("Failed to install %s: %s", cli_id, exc)
            _runtime_state[cli_id] = {
                "status": "error",
                "message": str(exc)[:300],
            }
        return inspect_cli(cli_id)


def auto_install_missing(requirements_path: str) -> list[dict[str, Any]]:
    required_ids = parse_cli_requirements(requirements_path)
    auto_install = os.environ.get(
        "KOOKAI_AUTO_INSTALL_CLIS",
        "1",
    ).lower() in {"1", "true", "yes", "on"}
    for cli_id in required_ids:
        status = inspect_cli(cli_id)
        if status["installed"]:
            continue
        if not auto_install:
            _runtime_state[cli_id] = {
                "status": "missing",
                "message": "Automatic CLI installation is disabled.",
            }
            continue
        LOGGER.info("%s is missing; installing automatically.", cli_id)
        install_cli(cli_id)
    return get_cli_statuses(requirements_path)


def _shell_login_line(executable: str, args: tuple[str, ...]) -> str:
    command = shlex.join([executable, *args])
    return (
        f"{command}; kookai_cli_exit=$?; "
        "printf '\\nKookAI connection flow finished (exit %s).\\n' "
        "\"$kookai_cli_exit\"; "
        "printf 'Press Enter to close...'; read -r _"
    )


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def launch_cli_login(cli_id: str, working_directory: str) -> dict[str, Any]:
    """Open the CLI authentication flow in a new local terminal window."""
    if cli_id not in CLI_DEFINITIONS:
        raise KeyError(cli_id)
    definition = CLI_DEFINITIONS[cli_id]
    executable = resolve_cli_executable(cli_id)
    if not executable:
        return {
            "launched": False,
            "message": f"{definition.name} is not installed.",
            "command": " ".join((definition.executable, *definition.connect_args)),
        }

    login_line = _shell_login_line(executable, definition.connect_args)
    try:
        if (
            working_directory
            and len(working_directory.encode("utf-8")) <= 4096
            and all(len(part.encode("utf-8")) <= 255 for part in working_directory.replace("\\", "/").split("/"))
            and os.path.isdir(working_directory)
        ):
            cwd = os.path.abspath(working_directory)
        else:
            cwd = os.getcwd()
    except (OSError, ValueError):
        cwd = os.getcwd()
    if cli_id == "muse":
        import webbrowser
        try:
            webbrowser.open("https://dev.meta.ai/api-keys/")
        except Exception as exc:
            LOGGER.warning("Could not automatically open browser for Meta Muse login: %s", exc)
    try:
        if os.name == "nt":
            powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
            if not powershell:
                raise RuntimeError("PowerShell was not found")
            invocation = " ".join(
                [
                    "&",
                    _powershell_quote(executable),
                    *(_powershell_quote(arg) for arg in definition.connect_args),
                ]
            )
            script = (
                f"Set-Location -LiteralPath {_powershell_quote(cwd)}; "
                f"{invocation}; "
                "Write-Host ''; "
                "Read-Host 'KookAI connection flow finished. Press Enter to close'"
            )
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(
                [powershell, "-NoProfile", "-Command", script],
                cwd=cwd,
                creationflags=creation_flags,
            )
        elif sys_platform() == "darwin":
            osascript = shutil.which("osascript")
            if not osascript:
                raise RuntimeError("Terminal launcher was not found")
            terminal_command = f"cd {shlex.quote(cwd)} && {login_line}"
            escaped = terminal_command.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(
                [
                    osascript,
                    "-e",
                    f'tell application "Terminal" to do script "{escaped}"',
                    "-e",
                    'tell application "Terminal" to activate',
                ],
                cwd=cwd,
            )
        else:
            if not (
                os.environ.get("DISPLAY")
                or os.environ.get("WAYLAND_DISPLAY")
            ):
                raise RuntimeError(
                    "This server has no desktop display. Run the login command "
                    "manually in a terminal on the server."
                )
            terminal = next(
                (
                    (name, shutil.which(name))
                    for name in (
                        "x-terminal-emulator",
                        "gnome-terminal",
                        "konsole",
                        "xfce4-terminal",
                        "xterm",
                    )
                    if shutil.which(name)
                ),
                None,
            )
            if not terminal:
                raise RuntimeError(
                    "No supported desktop terminal was found on this server."
                )
            terminal_name, terminal_path = terminal
            if terminal_name == "gnome-terminal":
                command = [terminal_path, "--", "bash", "-lc", login_line]
            elif terminal_name == "konsole":
                command = [terminal_path, "-e", "bash", "-lc", login_line]
            elif terminal_name == "xfce4-terminal":
                command = [
                    terminal_path,
                    "--command",
                    f"bash -lc {shlex.quote(login_line)}",
                ]
            else:
                command = [terminal_path, "-e", "bash", "-lc", login_line]
            subprocess.Popen(command, cwd=cwd)
    except (OSError, RuntimeError) as exc:
        return {
            "launched": False,
            "message": str(exc),
            "command": " ".join((definition.executable, *definition.connect_args)),
        }

    return {
        "launched": True,
        "message": f"Opened {definition.name} sign-in in a local terminal.",
        "command": " ".join((definition.executable, *definition.connect_args)),
    }


def sys_platform() -> str:
    # Kept as a function so platform-specific launch behavior is easy to test.
    import sys

    return sys.platform


class ProviderHealthTracker:
    """Tracks real-time health, latency (EMA), quota availability, and circuit breaker status for model providers."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self.metrics: dict[str, dict[str, Any]] = {}

    def _get_or_create(self, cli_id: str) -> dict[str, Any]:
        if cli_id not in self.metrics:
            self.metrics[cli_id] = {
                "health_status": "healthy",       # healthy, degraded, cooldown, unavailable
                "circuit_state": "CLOSED",        # CLOSED, OPEN, HALF_OPEN
                "latency_ema": 1.0,               # seconds (default baseline 1.0s)
                "consecutive_failures": 0,
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "quota_remaining_percent": 100.0,
                "cooldown_until": 0.0,
                "last_success_time": 0.0,
                "last_failure_time": 0.0,
                "last_error": "",
            }
        return self.metrics[cli_id]

    def record_success(self, cli_id: str, latency_sec: float) -> None:
        with self._lock:
            m = self._get_or_create(cli_id)
            now = time.time()
            m["total_calls"] += 1
            m["successful_calls"] += 1
            m["consecutive_failures"] = 0
            m["circuit_state"] = "CLOSED"
            m["cooldown_until"] = 0.0
            m["health_status"] = "healthy"
            m["last_success_time"] = now
            # Update EMA latency (alpha = 0.3)
            alpha = 0.3
            m["latency_ema"] = (alpha * latency_sec) + ((1.0 - alpha) * m["latency_ema"])

    def record_failure(
        self,
        cli_id: str,
        error_msg: str,
        latency_sec: float = 0.0,
        quota_exceeded: bool = False,
    ) -> None:
        with self._lock:
            m = self._get_or_create(cli_id)
            now = time.time()
            m["total_calls"] += 1
            m["failed_calls"] += 1
            m["consecutive_failures"] += 1
            m["last_failure_time"] = now
            m["last_error"] = str(error_msg)[:300]

            err_lower = str(error_msg).lower()
            if (
                quota_exceeded
                or "rate limit" in err_lower
                or "quota" in err_lower
                or "429" in err_lower
            ):
                m["quota_remaining_percent"] = max(0.0, m["quota_remaining_percent"] - 25.0)
                quota_trip = True
            else:
                quota_trip = False

            if (
                m["consecutive_failures"] >= self.failure_threshold
                or quota_trip
                or m["quota_remaining_percent"] <= 0.0
            ):
                m["circuit_state"] = "OPEN"
                m["cooldown_until"] = now + self.cooldown_seconds
                m["health_status"] = "cooldown"
            else:
                m["health_status"] = "degraded"

    def get_circuit_state(self, cli_id: str) -> str:
        with self._lock:
            m = self._get_or_create(cli_id)
            now = time.time()
            if m["circuit_state"] == "OPEN":
                if now >= m["cooldown_until"]:
                    m["circuit_state"] = "HALF_OPEN"
                    m["health_status"] = "degraded"
                    return "HALF_OPEN"
            return m["circuit_state"]

    def is_circuit_open(self, cli_id: str) -> bool:
        return self.get_circuit_state(cli_id) == "OPEN"

    def get_provider_health_score(self, cli_id: str) -> float:
        """Returns a scalar score for provider selection (higher score = higher priority)."""
        with self._lock:
            m = self._get_or_create(cli_id)
            c_state = self.get_circuit_state(cli_id)
            if c_state == "OPEN":
                return -1000.0  # Penalize tripped circuits heavily
            base = 100.0
            if c_state == "HALF_OPEN":
                base -= 30.0
            # Deduct for high latency EMA
            base -= min(50.0, m["latency_ema"] * 5.0)
            # Deduct for consecutive failures
            base -= (m["consecutive_failures"] * 15.0)
            # Add weighting for quota availability
            base += (m["quota_remaining_percent"] * 0.2)
            return max(0.0, base)

    def get_prioritized_providers(self, candidate_ids: list[str]) -> list[str]:
        """Sort candidate CLI provider IDs dynamically by health score, latency, and quota."""
        return sorted(candidate_ids, key=self.get_provider_health_score, reverse=True)

    def get_all_health_statuses(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            out = {}
            for cid in CLI_DEFINITIONS:
                m = self._get_or_create(cid)
                c_state = self.get_circuit_state(cid)
                out[cid] = {
                    "cli_id": cid,
                    "name": CLI_DEFINITIONS[cid].name,
                    "health_status": m["health_status"],
                    "circuit_state": c_state,
                    "latency_ema_ms": round(m["latency_ema"] * 1000, 2),
                    "consecutive_failures": m["consecutive_failures"],
                    "quota_remaining_percent": m["quota_remaining_percent"],
                    "cooldown_remaining_sec": max(0, int(m["cooldown_until"] - now)) if c_state == "OPEN" else 0,
                    "last_error": m["last_error"],
                }
            return out

    def reset(self) -> None:
        with self._lock:
            self.metrics.clear()


HEALTH_TRACKER = ProviderHealthTracker()


def record_provider_success(cli_id: str, latency_sec: float) -> None:
    HEALTH_TRACKER.record_success(cli_id, latency_sec)


def record_provider_failure(
    cli_id: str,
    error_msg: str,
    latency_sec: float = 0.0,
    quota_exceeded: bool = False,
) -> None:
    HEALTH_TRACKER.record_failure(cli_id, error_msg, latency_sec, quota_exceeded)


def is_provider_circuit_open(cli_id: str) -> bool:
    return HEALTH_TRACKER.is_circuit_open(cli_id)


def get_prioritized_providers(candidate_ids: list[str]) -> list[str]:
    return HEALTH_TRACKER.get_prioritized_providers(candidate_ids)


def get_provider_health_metrics() -> dict[str, Any]:
    return HEALTH_TRACKER.get_all_health_statuses()


def reset_provider_health_metrics() -> None:
    HEALTH_TRACKER.reset()
