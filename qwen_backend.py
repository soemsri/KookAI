"""Qwen Code CLI integration helpers for KookAI Local LLM models.

The helpers in this module are intentionally independent from FastAPI and
persistent application state so command construction and stream parsing remain
easy to test.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


QWEN_CONVERSATION_PREFIX = "local_qwen_"
LOCAL_HARNESS_ENV = "KOOKAI_LOCAL_HARNESS"
LOCAL_HARNESS_DISABLED_VALUES = {"none", "direct", "off", "0", "false"}
LOCAL_HARNESS_DSH_VALUES = {"dsh", "deepseek-harness", "deepseek_harness"}
LOCAL_HARNESS_CLAUDE_VALUES = {"claude", "claude-code", "claude_code"}


def local_harness_mode() -> str:
    """Return the configured harness mode for Local LLM requests."""
    raw = os.environ.get(LOCAL_HARNESS_ENV, "qwen").strip().lower()
    if raw in LOCAL_HARNESS_DISABLED_VALUES:
        return "none"
    if raw in LOCAL_HARNESS_DSH_VALUES:
        return "dsh"
    if raw in LOCAL_HARNESS_CLAUDE_VALUES:
        return "claude"
    return "qwen"


def qwen_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(QWEN_CONVERSATION_PREFIX):
        session_id = conversation_id[len(QWEN_CONVERSATION_PREFIX):].strip()
        return session_id or None
    return None


def make_qwen_conversation_id(session_id: str) -> str:
    return f"{QWEN_CONVERSATION_PREFIX}{session_id}"


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is None:
        return {}
    startupinfo = startupinfo_cls()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _is_runnable_qwen(path: str) -> bool:
    if not path:
        return False
    try:
        if not os.path.isfile(path):
            return False
        command = [path, "--version"]
        if os.name == "nt" and os.path.splitext(path)[1].lower() in {".cmd", ".bat"}:
            command = ["cmd.exe", "/d", "/s", "/c", *command]
        probe = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            **_hidden_subprocess_kwargs(),
        )
        return probe.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def resolve_qwen_executable() -> str:
    try:
        from cli_manager import resolve_cli_executable

        managed = resolve_cli_executable("qwen")
        if managed and _is_runnable_qwen(managed):
            return managed
    except Exception:
        pass

    configured = os.environ.get("QWEN_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("qwen"),
        os.path.expanduser("~/.local/bin/qwen.cmd") if os.name == "nt" else None,
        os.path.expanduser("~/.local/bin/qwen.exe") if os.name == "nt" else None,
        os.path.expanduser("~/.local/bin/qwen"),
        os.path.expanduser("~/.local/node/bin/qwen"),
        os.path.expanduser("~/.npm-global/bin/qwen"),
        "/usr/local/bin/qwen" if os.name != "nt" else None,
        "/usr/bin/qwen" if os.name != "nt" else None,
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_qwen(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Qwen Code CLI was found. Install `@qwen-code/qwen-code` or set QWEN_CLI_PATH."
    )


def is_qwen_available() -> bool:
    try:
        return bool(resolve_qwen_executable())
    except (FileNotFoundError, OSError):
        return False


def should_use_qwen_harness() -> bool:
    return local_harness_mode() == "qwen" and is_qwen_available()


def qwen_approval_mode(target: str = "Sandbox") -> str:
    if (target or "Sandbox").strip().lower() in {"real", "unrestricted"}:
        return "yolo"
    return "auto-edit"


def build_qwen_command(
    qwen_path: str,
    prompt: str,
    raw_model_id: str,
    base_url: str,
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
) -> list[str]:
    del prompt  # Prompts are deliberately sent over stdin, never argv.
    command = [
        qwen_path,
        "--auth-type",
        "openai",
        "--openai-base-url",
        base_url,
        "--model",
        raw_model_id,
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--approval-mode",
        qwen_approval_mode(target),
    ]
    session_id = qwen_session_id(conversation_id)
    if session_id:
        command.extend(["--resume", session_id])
    if os.name == "nt" and os.path.splitext(qwen_path)[1].lower() in {".cmd", ".bat"}:
        command = ["cmd.exe", "/d", "/s", "/c", *command]
    return command


def build_qwen_environment(
    base_url: str,
    raw_model_id: str,
    api_key: str = "",
) -> dict[str, str]:
    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = base_url
    # Ensure Qwen Code's OpenAI auth check succeeds and never sends an ambient
    # cloud OPENAI_API_KEY from the host environment to a local server.
    env["OPENAI_API_KEY"] = (api_key or "").strip() or "local"
    env["OPENAI_MODEL"] = raw_model_id
    env["NO_BROWSER"] = "1"
    # Slow local generation can exceed Qwen's 15-minute upstream-wait cap
    # while still streaming. Exo also buffers a complete tool call (including
    # large file contents) before emitting it, exceeding Qwen's idle default.
    # Keep both budgets finite and honor operator overrides and cancellation.
    env.setdefault("QWEN_STREAM_MAX_LIFETIME_MS", "1800000")
    env.setdefault("QWEN_STREAM_IDLE_TIMEOUT_MS", "1800000")
    return env


def _read_qwen_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    # Qwen accepts JSON with comments. Keep quoted strings (including URLs)
    # intact while removing comments, without adding a JSON5 dependency.
    content = path.read_text(encoding="utf-8-sig")
    content = re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
        lambda match: match[0] if match[0].startswith('"') else " ",
        content,
    )
    try:
        settings = json.loads(content)
    except ValueError:
        raise ValueError(f"Cannot read Qwen settings at {path}; fix the JSON before retrying") from None
    if not isinstance(settings, dict):
        raise ValueError(f"Qwen settings at {path} must be a JSON object")
    return settings


@contextmanager
def qwen_generation_environment(
    env: dict[str, str], cwd_path: str, raw_model_id: str, thinking: Optional[bool],
):
    """Apply a turn's Thinking control without editing shared Qwen settings.

    Preserve the system policy and its defaults location. Use an explicit local
    provider entry because provider-defined models ignore model.generationConfig.
    Session storage and resume IDs remain in the original Qwen home.
    """
    if thinking is None:
        yield env
        return

    if sys.platform == "darwin":
        default_system_path = "/Library/Application Support/QwenCode/settings.json"
    elif os.name == "nt":
        default_system_path = r"C:\ProgramData\qwen-code\settings.json"
    else:
        default_system_path = "/etc/qwen-code/settings.json"

    def absolute_path(value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else Path(cwd_path) / path

    system_path = absolute_path(env.get("QWEN_CODE_SYSTEM_SETTINGS_PATH") or default_system_path)
    defaults_path = absolute_path(env.get("QWEN_CODE_SYSTEM_DEFAULTS_PATH") or str(system_path.with_name("system-defaults.json")))
    qwen_home = absolute_path(env.get("QWEN_HOME") or str(Path.home() / ".qwen"))
    scopes = [_read_qwen_settings(path) for path in (
        defaults_path, qwen_home / "settings.json", system_path,
    )]
    settings = deepcopy(scopes[-1])

    def merge_objects(base, incoming):
        for key, value in incoming.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge_objects(base[key], value)
            else:
                base[key] = deepcopy(value)

    generation = {}
    models = []
    for scope in scopes:
        merge_objects(generation, (scope.get("model") or {}).get("generationConfig") or {})
        provider_models = (scope.get("modelProviders") or {}).get("openai")
        if provider_models is not None:
            models = deepcopy(provider_models)
    # Do not promote project settings into system scope: Qwen owns their trust
    # checks. This invocation pins only the selected model to KookAI's local URL.
    selected = next((model for model in models if model.get("id") == raw_model_id), None)
    if selected is None:
        selected = {"id": raw_model_id, "generationConfig": generation}
        models.append(selected)
    selected["baseUrl"] = env["OPENAI_BASE_URL"]
    selected["envKey"] = "OPENAI_API_KEY"
    selected.pop("apiKey", None)
    selected["wireApi"] = "chat-completions"
    selected.setdefault("generationConfig", {}).setdefault("extra_body", {})["enable_thinking"] = thinking
    settings.setdefault("modelProviders", {})["openai"] = models

    with tempfile.TemporaryDirectory(prefix="kookai-qwen-settings-") as directory:
        settings_path = Path(directory) / "settings.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        settings_path.chmod(0o600)
        scoped_env = dict(env)
        scoped_env["QWEN_CODE_SYSTEM_SETTINGS_PATH"] = str(settings_path)
        scoped_env["QWEN_CODE_SYSTEM_DEFAULTS_PATH"] = str(defaults_path)
        yield scoped_env


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text", ""))
        for block in content
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    )


def parse_qwen_stream_json(output: str) -> dict[str, Any]:
    session_id: Optional[str] = None
    final_message = ""
    assistant_messages: list[str] = []
    errors: list[str] = []

    for raw_line in (output or "").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_session_id = event.get("session_id")
        if isinstance(event_session_id, str) and event_session_id:
            session_id = event_session_id

        event_type = event.get("type")
        if event_type == "assistant":
            message = event.get("message")
            text = _content_text(message.get("content") if isinstance(message, dict) else None)
            if text and text.strip():
                assistant_messages.append(text)
        elif event_type == "result":
            result_text = event.get("result")
            if isinstance(result_text, str) and result_text:
                final_message = result_text
            if event.get("is_error") or event.get("subtype") not in {None, "success"}:
                error_text = event.get("error") or result_text or event.get("subtype")
                if error_text:
                    errors.append(str(error_text))
        elif event_type == "error":
            error = event.get("error") or event.get("message")
            if error:
                errors.append(str(error))

    if not final_message and assistant_messages:
        final_message = assistant_messages[-1]
    return {
        "session_id": session_id,
        "final_message": final_message,
        "errors": errors,
    }


def classify_qwen_progress_line(source: str, line: str) -> Optional[dict[str, str]]:
    clean = (line or "").strip()
    if not clean:
        return None
    if source == "stderr":
        lowered = clean.lower()
        kind = "error" if any(
            word in lowered
            for word in (
                "error",
                "failed",
                "unauthorized",
                "forbidden",
                "invalid",
                "overridden",
                "econnrefused",
                "cannot",
                "not found",
            )
        ) else "progress"
        return {"type": kind, "message": clean[:500]}

    try:
        event = json.loads(clean)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, dict):
        return None

    event_type = event.get("type")
    if event_type == "system" and event.get("subtype") in {"init", "session_start"}:
        return {"type": "progress", "message": "Qwen Code session started."}
    if event_type == "stream_event":
        stream_event = event.get("event")
        if isinstance(stream_event, dict) and stream_event.get("type") == "content_block_delta":
            delta = stream_event.get("delta")
            if not isinstance(delta, dict):
                return None
            if delta.get("type") == "thinking_delta":
                return {"type": "progress", "message": "Qwen Code is thinking..."}
            if delta.get("type") in {"text_delta", "input_json_delta"}:
                return {"type": "progress", "message": "Qwen Code is generating a response..."}
    if event_type == "assistant":
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else []
        if isinstance(content, list):
            tool_names = [
                block.get("name")
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name")
            ]
            if tool_names:
                return {
                    "type": "progress",
                    "message": f"Qwen Code is using {', '.join(str(name) for name in tool_names)}.",
                }
    if event_type == "user":
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else []
        if isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error") is True
            for block in content
        ):
            return {
                "type": "progress",
                "message": "Qwen Code tool reported an error; continuing...",
            }
    if event_type == "result" and event.get("is_error"):
        message = event.get("result") or event.get("error") or "Qwen Code task failed."
        return {"type": "error", "message": str(message)[:500]}
    if event_type == "error":
        message = event.get("error") or event.get("message") or "Qwen Code error."
        return {"type": "error", "message": str(message)[:500]}
    return None
