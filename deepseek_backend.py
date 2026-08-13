"""DeepSeek Code CLI integration helpers.

This module contains no FastAPI or persistent application state so command
construction and streaming JSON parsing can be tested independently.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Optional


DEEPSEEK_MODEL_MAP = {
    "DeepSeek Pro 0813": "deepseek-pro-0813",
    "DeepSeek V4": "deepseek-v4",
    "DeepSeek R1": "deepseek-reasoner",
    "DeepSeek V3": "deepseek-chat",
    "DeepSeek Coder V2.5": "deepseek-coder",
    "DeepSeek Coder 33B": "deepseek-coder-33b",
    "DeepSeek Math 7B": "deepseek-math",
}

DEEPSEEK_CONVERSATION_PREFIX = "deepseek_"


def configure_deepseek_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases for DeepSeek models."""
    for model in models:
        if model.get("provider") != "deepseek" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        DEEPSEEK_MODEL_MAP[model_id] = cli_model
        if label:
            DEEPSEEK_MODEL_MAP[label] = cli_model


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


def is_deepseek_model(model_name: str) -> bool:
    if not model_name:
        return False
    clean = model_name.strip()
    return (
        clean in DEEPSEEK_MODEL_MAP
        or clean in DEEPSEEK_MODEL_MAP.values()
        or "deepseek" in clean.lower()
        or "deepcode" in clean.lower()
    )


def deepseek_model_alias(model_name: str) -> str:
    clean = (model_name or "").strip()
    if clean in DEEPSEEK_MODEL_MAP:
        return DEEPSEEK_MODEL_MAP[clean]
    if clean in DEEPSEEK_MODEL_MAP.values():
        return clean
    if is_deepseek_model(clean):
        return clean
    raise ValueError(f"Unsupported DeepSeek model: {model_name}")


def deepseek_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(DEEPSEEK_CONVERSATION_PREFIX):
        session_id = conversation_id[len(DEEPSEEK_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_deepseek_conversation_id(session_id: str) -> str:
    return f"{DEEPSEEK_CONVERSATION_PREFIX}{session_id}"


def _is_runnable_deepseek(path: str) -> bool:
    if not path:
        return False
    try:
        if not os.path.isfile(path):
            return False
        probe = subprocess.run(
            [path, "--version"],
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
def resolve_deepseek_executable() -> str:
    try:
        from cli_manager import resolve_cli_executable
        cli_found = resolve_cli_executable("deepseek")
        if cli_found and _is_runnable_deepseek(cli_found):
            return cli_found
    except Exception:
        pass

    configured = os.environ.get("DEEPSEEK_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("deepcode"),
        shutil.which("deepseek"),
        os.path.expanduser("~/.local/bin/deepcode.exe"),
        os.path.expanduser("~/.local/bin/deepcode"),
        os.path.expanduser("~/.local/bin/deepseek.exe"),
        os.path.expanduser("~/.local/bin/deepseek"),
        os.path.expanduser("~/.deepseek/bin/deepcode.exe"),
        os.path.expanduser("~/.deepseek/bin/deepcode"),
        os.path.expanduser("~/.deepseek/bin/deepseek.exe"),
        os.path.expanduser("~/.deepseek/bin/deepseek"),
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_deepseek(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable DeepSeek Code CLI (deepcode/deepseek) was found. Install it, run `deepcode login`, "
        "or set DEEPSEEK_CLI_PATH."
    )


def build_deepseek_command(
    deepseek_path: str,
    prompt: str,
    model_name: str,
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
    cwd_path: Optional[str] = None,
) -> list[str]:
    """Build a non-interactive DeepSeek Code command."""
    del target
    command = [
        deepseek_path,
        "--model",
        deepseek_model_alias(model_name),
        "--prompt",
        prompt,
        "--output-format",
        "stream-json",
    ]
    if cwd_path:
        command.extend(["--cwd", cwd_path])

    session_id = deepseek_session_id(conversation_id)
    if session_id:
        command.extend(["--session", session_id])
    return command


def parse_deepseek_stream_json(output: str) -> dict[str, Any]:
    session_id: Optional[str] = None
    assistant_parts: list[str] = []
    errors: list[str] = []

    for raw_line in (output or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        if event.get("type") == "session.resume_hint" or event.get("type") == "session":
            event_session_id = event.get("session_id") or event.get("sessionId")
            if isinstance(event_session_id, str) and event_session_id:
                session_id = event_session_id

        role = event.get("role")
        if role == "assistant" or event.get("type") == "text":
            content = event.get("content") or event.get("data")
            if isinstance(content, str) and content:
                assistant_parts.append(content)
        elif role == "error" or event.get("type") == "error":
            error = event.get("error") or event.get("message") or event.get("content")
            if error:
                errors.append(str(error))

    if not assistant_parts:
        plain_lines = [
            line for line in (output or "").splitlines()
            if line.strip() and not line.strip().startswith("{")
        ]
        if plain_lines:
            assistant_parts = plain_lines

    return {
        "session_id": session_id,
        "final_message": "".join(assistant_parts) if assistant_parts else "",
        "errors": errors,
    }


def classify_deepseek_progress_line(
    source: str,
    line: str,
) -> Optional[dict[str, str]]:
    clean = (line or "").strip()
    if not clean:
        return None

    if source == "stderr":
        lowered = clean.lower()
        event_type = "error" if any(
            term in lowered
            for term in (
                "error",
                "failed",
                "failure",
                "denied",
                "unauthorized",
                "forbidden",
                "invalid",
            )
        ) else "progress"
        return {"type": event_type, "message": clean[:500]}

    try:
        event = json.loads(clean)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None

    if event.get("type") == "session.resume_hint":
        return {"type": "progress", "message": "DeepSeek session ready."}
    if event.get("type") == "thought" or event.get("thinking"):
        return {"type": "progress", "message": "DeepSeek is reasoning."}
    if event.get("role") == "tool":
        return {"type": "progress", "message": "DeepSeek completed a tool call."}
    if event.get("role") == "assistant" and event.get("tool_calls"):
        tool_names = [
            call.get("function", {}).get("name")
            for call in event["tool_calls"]
            if isinstance(call, dict)
        ]
        clean_names = [str(name) for name in tool_names if name]
        if clean_names:
            return {
                "type": "progress",
                "message": f"DeepSeek is using {', '.join(clean_names)}.",
            }
    if event.get("role") == "error" or event.get("type") == "error":
        message = event.get("error") or event.get("message") or "DeepSeek task failed."
        return {"type": "error", "message": str(message)[:500]}
    return None
