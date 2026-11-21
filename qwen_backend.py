"""Qwen Code CLI integration helpers for KookAI Local LLM models.

The helpers in this module are intentionally independent from FastAPI and
persistent application state so command construction and stream parsing remain
easy to test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Optional


QWEN_CONVERSATION_PREFIX = "local_qwen_"
LOCAL_HARNESS_ENV = "KOOKAI_LOCAL_HARNESS"
LOCAL_HARNESS_DISABLED_VALUES = {"none", "direct", "off", "0", "false"}


def local_harness_mode() -> str:
    """Return the configured harness mode for Local LLM requests."""
    raw = os.environ.get(LOCAL_HARNESS_ENV, "qwen").strip().lower()
    if raw in LOCAL_HARNESS_DISABLED_VALUES:
        return "none"
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
    return env


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
