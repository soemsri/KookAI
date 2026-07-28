"""Kimi Code CLI integration helpers.

The helpers in this module are independent from FastAPI and persistent
application state so command construction and stream parsing are easy to test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Optional


KIMI_MODEL_MAP = {
    "Kimi K3": "kimi-for-coding/k3",
}

KIMI_CONVERSATION_PREFIX = "kimi_"


def configure_kimi_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases for Kimi Code models."""
    for model in models:
        if model.get("provider") != "kimi" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        KIMI_MODEL_MAP[model_id] = cli_model
        if label:
            KIMI_MODEL_MAP[label] = cli_model


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def is_kimi_model(model_name: str) -> bool:
    return model_name in KIMI_MODEL_MAP or model_name in KIMI_MODEL_MAP.values()


def kimi_model_alias(model_name: str) -> str:
    if model_name in KIMI_MODEL_MAP:
        return KIMI_MODEL_MAP[model_name]
    if model_name in KIMI_MODEL_MAP.values():
        return model_name
    raise ValueError(f"Unsupported Kimi model: {model_name}")


def kimi_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(KIMI_CONVERSATION_PREFIX):
        session_id = conversation_id[len(KIMI_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_kimi_conversation_id(session_id: str) -> str:
    return f"{KIMI_CONVERSATION_PREFIX}{session_id}"


def _is_runnable_kimi(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
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
def resolve_kimi_executable() -> str:
    configured = os.environ.get("KIMI_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("kimi"),
        os.path.expanduser("~/.kimi-code/bin/kimi.exe"),
        os.path.expanduser("~/.kimi-code/bin/kimi"),
        os.path.expanduser("~/.local/bin/kimi.exe"),
        os.path.expanduser("~/.local/bin/kimi"),
        os.path.expanduser("~/.local/kimi.exe"),
        os.path.expanduser("~/.local/kimi"),
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_kimi(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Kimi Code CLI was found. Install it, run `kimi login`, "
        "or set KIMI_CLI_PATH."
    )


def build_kimi_command(
    kimi_path: str,
    prompt: str,
    model_name: str,
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
) -> list[str]:
    """Build a non-interactive Kimi Code command.

    Kimi prompt mode always uses its automatic permission policy. The target is
    retained in this API for parity with the other providers, while workspace
    access is constrained by Kimi's own permission configuration.
    """
    del target
    command = [
        kimi_path,
        "--model",
        kimi_model_alias(model_name),
        "--prompt",
        prompt,
        "--output-format",
        "stream-json",
    ]
    session_id = kimi_session_id(conversation_id)
    if session_id:
        command.extend(["--session", session_id])
    return command


def parse_kimi_stream_json(output: str) -> dict[str, Any]:
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

        if event.get("type") == "session.resume_hint":
            event_session_id = event.get("session_id")
            if isinstance(event_session_id, str) and event_session_id:
                session_id = event_session_id

        role = event.get("role")
        if role == "assistant":
            content = event.get("content")
            if isinstance(content, str) and content:
                assistant_parts.append(content)
        elif role == "error" or event.get("type") == "error":
            error = event.get("error") or event.get("message") or event.get("content")
            if error:
                errors.append(str(error))

    return {
        "session_id": session_id,
        "final_message": "\n".join(assistant_parts),
        "errors": errors,
    }


def classify_kimi_progress_line(
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
        return {"type": "progress", "message": "Kimi session ready."}
    if event.get("type") == "turn.step.retrying":
        message = event.get("error_message") or "Kimi is retrying the request."
        return {"type": "progress", "message": str(message)[:500]}
    if event.get("role") == "tool":
        return {"type": "progress", "message": "Kimi completed a tool call."}
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
                "message": f"Kimi is using {', '.join(clean_names)}.",
            }
    if event.get("role") == "error" or event.get("type") == "error":
        message = event.get("error") or event.get("message") or "Kimi task failed."
        return {"type": "error", "message": str(message)[:500]}
    return None
