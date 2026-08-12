"""xAI Grok Build CLI integration helpers.

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


GROK_MODEL_MAP = {
    "Grok 4.6": "grok-4.6",
    "Grok 4.5": "grok-4.5",
    "Grok 4.20 Reasoning": "grok-4.20",
    "Grok 4.20 Non-Reasoning": "grok-4.20-non-reasoning",
    "Grok Build 0.1": "grok-build-0.1",
}

GROK_EFFORT_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}

GROK_MODEL_EFFORTS = {
    "Grok 4.6": {"low", "medium", "high"},
    "Grok 4.5": {"low", "medium", "high"},
}

GROK_CONVERSATION_PREFIX = "grok_"


def configure_grok_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases and effort capabilities for xAI models."""
    for model in models:
        if model.get("provider") != "xai" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        GROK_MODEL_MAP[model_id] = cli_model
        if label:
            GROK_MODEL_MAP[label] = cli_model

        capabilities = model.get("capabilities", {})
        effort_values = capabilities.get("effort", [])
        supported_efforts = {
            GROK_EFFORT_MAP[effort.lower()]
            for effort in effort_values
            if isinstance(effort, str) and effort.lower() in GROK_EFFORT_MAP
        }
        if supported_efforts:
            GROK_MODEL_EFFORTS[model_id] = supported_efforts
            if label:
                GROK_MODEL_EFFORTS[label] = supported_efforts
        else:
            GROK_MODEL_EFFORTS.pop(model_id, None)
            if label:
                GROK_MODEL_EFFORTS.pop(label, None)


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


def is_grok_model(model_name: str) -> bool:
    return model_name in GROK_MODEL_MAP or model_name in GROK_MODEL_MAP.values()


def grok_model_slug(model_name: str) -> str:
    if model_name in GROK_MODEL_MAP:
        return GROK_MODEL_MAP[model_name]
    if model_name in GROK_MODEL_MAP.values():
        return model_name
    raise ValueError(f"Unsupported xAI model: {model_name}")


def grok_model_supports_effort(model_name: str) -> bool:
    return model_name in GROK_MODEL_EFFORTS


def normalize_grok_effort(
    effort: Optional[str],
    model_name: Optional[str] = None,
) -> tuple[str, str]:
    display_value = (effort or "Medium").strip()
    cli_value = GROK_EFFORT_MAP.get(display_value.lower())
    if not cli_value:
        raise ValueError(f"Unsupported Grok effort: {display_value}")
    canonical_display = cli_value.capitalize()
    if model_name:
        supported = GROK_MODEL_EFFORTS.get(model_name)
        if supported is not None and cli_value not in supported:
            raise ValueError(
                f"Effort {canonical_display} is not supported by xAI model {model_name}"
            )
    return canonical_display, cli_value


def grok_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(GROK_CONVERSATION_PREFIX):
        session_id = conversation_id[len(GROK_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_grok_conversation_id(session_id: str) -> str:
    return f"{GROK_CONVERSATION_PREFIX}{session_id}"


def _is_runnable_grok(path: str) -> bool:
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
def resolve_grok_executable() -> str:
    configured = os.environ.get("GROK_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("grok"),
        os.path.expanduser("~/.local/bin/grok.exe"),
        os.path.expanduser("~/.local/bin/grok"),
        os.path.expanduser("~/.local/grok.exe"),
        os.path.expanduser("~/.local/grok"),
        os.path.expanduser("~/.grok/bin/grok.exe"),
        os.path.expanduser("~/.grok/bin/grok"),
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_grok(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Grok Build CLI was found. Install it, run `grok login`, "
        "or set GROK_CLI_PATH."
    )


def build_grok_command(
    grok_path: str,
    prompt: str,
    model_name: str,
    effort: Optional[str] = "Medium",
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
    cwd_path: Optional[str] = None,
) -> list[str]:
    """Build a non-interactive Grok Build command with resumable sessions."""
    command = [
        grok_path,
        "--no-auto-update",
        "-p",
        prompt,
        "--model",
        grok_model_slug(model_name),
        "--output-format",
        "streaming-json",
    ]
    if cwd_path:
        command.extend(["--cwd", cwd_path])

    if grok_model_supports_effort(model_name):
        _, effort_cli = normalize_grok_effort(effort, model_name)
        command.extend(["--effort", effort_cli])

    session_id = grok_session_id(conversation_id)
    if session_id:
        command.extend(["--resume", session_id])

    # Headless processes cannot answer permission prompts. In Sandbox mode the
    # OS-level workspace profile limits writes to the selected workspace and
    # temporary files; Real mode intentionally runs without that isolation.
    if (target or "Sandbox").strip().lower() not in {"real", "unrestricted"}:
        command.extend(["--sandbox", "workspace"])
    command.append("--always-approve")
    return command


def parse_grok_streaming_json(output: str) -> dict[str, Any]:
    session_id: Optional[str] = None
    text_parts: list[str] = []
    errors: list[str] = []
    stop_reason: Optional[str] = None

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

        event_type = event.get("type")
        if event_type == "text":
            data = event.get("data")
            if isinstance(data, str):
                text_parts.append(data)
        elif event_type == "end":
            event_session_id = event.get("sessionId")
            if isinstance(event_session_id, str) and event_session_id:
                session_id = event_session_id
            event_stop_reason = event.get("stopReason")
            if isinstance(event_stop_reason, str):
                stop_reason = event_stop_reason
        elif event_type == "error":
            message = event.get("message") or event.get("error")
            if message:
                errors.append(str(message))

    return {
        "session_id": session_id,
        "final_message": "".join(text_parts),
        "errors": errors,
        "stop_reason": stop_reason,
    }


def classify_grok_progress_line(
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
                "denied",
                "unauthorized",
                "not signed in",
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

    event_type = event.get("type")
    if event_type == "thought":
        return {"type": "progress", "message": "Grok is reasoning."}
    if event_type == "auto_compact_started":
        return {"type": "progress", "message": "Grok is compacting the conversation."}
    if event_type == "auto_compact_completed":
        return {"type": "progress", "message": "Grok compacted the conversation."}
    if event_type == "max_turns_reached":
        return {"type": "error", "message": "Grok reached the maximum number of turns."}
    if event_type == "error":
        message = event.get("message") or event.get("error") or "Grok task failed."
        return {"type": "error", "message": str(message)[:500]}
    return None
