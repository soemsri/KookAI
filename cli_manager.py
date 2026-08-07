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
    if os.name == "nt":
        installer_url = "https://dev.meta.ai/install.ps1"
        installer_path = _download_installer(installer_url, ".ps1")
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not powershell:
            os.unlink(installer_path)
            raise RuntimeError("PowerShell is required to install Meta Muse Code CLI")
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
            CLI_DEFINITIONS["muse"].install_source,
            ".sh",
        )
        bash = shutil.which("bash")
        if not bash:
            os.unlink(installer_path)
            raise RuntimeError("bash is required to install Meta Muse Code CLI")
        command = [bash, installer_path]

    try:
        return _run_installer(command)
    finally:
        try:
            os.unlink(installer_path)
        except OSError:
            pass


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
    cwd = os.path.abspath(working_directory)
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
