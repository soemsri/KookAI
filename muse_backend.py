"""Meta Muse Code CLI integration helpers.

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


MUSE_MODEL_MAP = {
    "Muse Spark 1.2": "muse-spark-1.2",
}

MUSE_EFFORT_MAP = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}

MUSE_MODEL_EFFORTS = {
    "Muse Spark 1.2": {"low", "medium", "high"},
}

MUSE_CONVERSATION_PREFIX = "muse_"


def configure_muse_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases and effort capabilities for Meta Muse models."""
    for model in models:
        if model.get("provider") != "muse" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        MUSE_MODEL_MAP[model_id] = cli_model
        if label:
            MUSE_MODEL_MAP[label] = cli_model

        capabilities = model.get("capabilities", {})
        effort_values = capabilities.get("effort", [])
        supported_efforts = {
            MUSE_EFFORT_MAP[effort.lower()]
            for effort in effort_values
            if isinstance(effort, str) and effort.lower() in MUSE_EFFORT_MAP
        }
        if supported_efforts:
            MUSE_MODEL_EFFORTS[model_id] = supported_efforts
            if label:
                MUSE_MODEL_EFFORTS[label] = supported_efforts
        else:
            MUSE_MODEL_EFFORTS.pop(model_id, None)
            if label:
                MUSE_MODEL_EFFORTS.pop(label, None)


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


def _clean_model_name(model_name: str) -> str:
    if not model_name:
        return ""
    import re
    return re.sub(r"\s+(Low|Medium|High)$", "", model_name.strip(), flags=re.IGNORECASE).strip()


def is_muse_model(model_name: str) -> bool:
    if not model_name:
        return False
    clean = _clean_model_name(model_name)
    return (
        clean in MUSE_MODEL_MAP
        or clean in MUSE_MODEL_MAP.values()
        or model_name in MUSE_MODEL_MAP
        or model_name in MUSE_MODEL_MAP.values()
        or "muse" in model_name.lower()
    )


def muse_model_slug(model_name: str) -> str:
    clean = _clean_model_name(model_name)
    if clean in MUSE_MODEL_MAP:
        return MUSE_MODEL_MAP[clean]
    if clean in MUSE_MODEL_MAP.values():
        return clean
    if model_name in MUSE_MODEL_MAP:
        return MUSE_MODEL_MAP[model_name]
    if model_name in MUSE_MODEL_MAP.values():
        return model_name
    return "muse-spark-1.2"


def muse_model_supports_effort(model_name: str) -> bool:
    clean = _clean_model_name(model_name)
    return clean in MUSE_MODEL_EFFORTS or model_name in MUSE_MODEL_EFFORTS or True


def normalize_muse_effort(
    effort: Optional[str],
    model_name: Optional[str] = None,
) -> tuple[str, str]:
    display_value = (effort or "Medium").strip()
    cli_value = MUSE_EFFORT_MAP.get(display_value.lower())
    if not cli_value:
        cli_value = "medium"
    canonical_display = cli_value.capitalize()
    return canonical_display, cli_value


def muse_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(MUSE_CONVERSATION_PREFIX):
        session_id = conversation_id[len(MUSE_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_muse_conversation_id(session_id: str) -> str:
    return f"{MUSE_CONVERSATION_PREFIX}{session_id}"


def _is_runnable_muse(path: str) -> bool:
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
def resolve_muse_executable() -> str:
    try:
        from cli_manager import resolve_cli_executable
        cli_found = resolve_cli_executable("muse")
        if cli_found and _is_runnable_muse(cli_found):
            return cli_found
    except Exception:
        pass

    configured = os.environ.get("MUSE_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("muse"),
        os.path.expanduser("~/.local/bin/muse.bat"),
        os.path.expanduser("~/.local/bin/muse.cmd"),
        os.path.expanduser("~/.local/bin/muse.exe"),
        os.path.expanduser("~/.local/bin/muse"),
        os.path.expanduser("~/.local/muse.exe"),
        os.path.expanduser("~/.local/muse"),
        os.path.expanduser("~/.muse/bin/muse.bat"),
        os.path.expanduser("~/.muse/bin/muse.cmd"),
        os.path.expanduser("~/.muse/bin/muse.exe"),
        os.path.expanduser("~/.muse/bin/muse"),
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_muse(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Meta Muse Code CLI was found. Install it, run `muse login`, "
        "or set MUSE_CLI_PATH."
    )


def build_muse_command(
    muse_path: str,
    prompt: str,
    model_name: str,
    effort: Optional[str] = "Medium",
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
    cwd_path: Optional[str] = None,
) -> list[str]:
    """Build a non-interactive Muse Code command with resumable sessions."""
    command = [
        muse_path,
        "--no-auto-update",
        "-p",
        prompt,
        "--model",
        muse_model_slug(model_name),
        "--output-format",
        "streaming-json",
    ]
    if cwd_path:
        command.extend(["--cwd", cwd_path])

    if muse_model_supports_effort(model_name):
        _, effort_cli = normalize_muse_effort(effort, model_name)
        command.extend(["--effort", effort_cli])

    session_id = muse_session_id(conversation_id)
    if session_id:
        command.extend(["--resume", session_id])

    if (target or "Sandbox").strip().lower() not in {"real", "unrestricted"}:
        command.extend(["--sandbox", "workspace"])
    meta_key = os.environ.get("META_API_KEY", "").strip() or os.environ.get("MUSE_API_KEY", "").strip()
    if meta_key:
        command.extend(["--api-key", meta_key])
    command.append("--always-approve")
    return command


def parse_muse_streaming_json(output: str) -> dict[str, Any]:
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

    if not text_parts:
        plain_lines = [
            line for line in (output or "").splitlines()
            if line.strip() and not line.strip().startswith("{")
        ]
        if plain_lines:
            text_parts = plain_lines

    return {
        "session_id": session_id,
        "final_message": "\n".join(text_parts) if text_parts else "",
        "errors": errors,
        "stop_reason": stop_reason,
    }


def classify_muse_progress_line(
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
        return {"type": "progress", "message": "Muse is reasoning."}
    if event_type == "auto_compact_started":
        return {"type": "progress", "message": "Muse is compacting the conversation."}
    if event_type == "auto_compact_completed":
        return {"type": "progress", "message": "Muse compacted the conversation."}
    if event_type == "max_turns_reached":
        return {"type": "error", "message": "Muse reached the maximum number of turns."}
    if event_type == "error":
        message = event.get("message") or event.get("error") or "Muse task failed."
        return {"type": "error", "message": str(message)[:500]}
    return None
