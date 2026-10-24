"""Anthropic Claude Code CLI integration helpers.

The helpers in this module are intentionally independent from FastAPI and
persistent application state so command construction and stream parsing remain
easy to test.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import shutil
import subprocess
import time
from functools import lru_cache
from typing import Any, Optional


CLAUDE_SLUG_ALIASES = {
    "claude-opus-5-5-high": "claude-opus-5-5",
    "claude-opus-5-5-medium": "claude-opus-5-5",
    "claude-opus-5-5-low": "claude-opus-5-5",
    "claude-sonnet-5-5-high": "claude-sonnet-5-5",
    "claude-sonnet-5-5-medium": "claude-sonnet-5-5",
    "claude-sonnet-5-5-low": "claude-sonnet-5-5",
    "Claude Sonnet 4.6 (Thinking)": "claude-sonnet-4-6",
    "Claude Opus 4.6 (Thinking)": "claude-opus-4-6",
}

CLAUDE_PRESET_EFFORTS = {
    "Claude Opus 5.5 (High)": "High",
    "Claude Opus 5.5 (Medium)": "Medium",
    "Claude Opus 5.5 (Low)": "Low",
    "claude-opus-5-5-high": "High",
    "claude-opus-5-5-medium": "Medium",
    "claude-opus-5-5-low": "Low",
    "Claude Sonnet 5.5 (High)": "High",
    "Claude Sonnet 5.5 (Medium)": "Medium",
    "Claude Sonnet 5.5 (Low)": "Low",
    "claude-sonnet-5-5-high": "High",
    "claude-sonnet-5-5-medium": "Medium",
    "claude-sonnet-5-5-low": "Low",
}

CLAUDE_MODEL_MAP = {
    "Fable 5.1": "claude-fable-5-1",
    "Fable 5": "fable",
    "Opus 5.5": "claude-opus-5-5",
    "Claude Opus 5.5": "claude-opus-5-5",
    "Claude Opus 5.5 (High)": "claude-opus-5-5",
    "Claude Opus 5.5 (Medium)": "claude-opus-5-5",
    "Claude Opus 5.5 (Low)": "claude-opus-5-5",
    "Opus 5": "opus",
    "Sonnet 5.5": "claude-sonnet-5-5",
    "Claude Sonnet 5.5": "claude-sonnet-5-5",
    "Claude Sonnet 5.5 (High)": "claude-sonnet-5-5",
    "Claude Sonnet 5.5 (Medium)": "claude-sonnet-5-5",
    "Claude Sonnet 5.5 (Low)": "claude-sonnet-5-5",
    "Sonnet 5": "sonnet",
    "Haiku 5.5": "claude-haiku-5-5",
    "Haiku 4.5": "haiku",
    "Opus 4.8": "claude-opus-4-8",
    "Opus 4.7": "claude-opus-4-7",
    "Opus 4.6": "claude-opus-4-6",
    "Claude Opus 4.6 (Thinking)": "claude-opus-4-6",
    "Opus 3": "claude-3-opus-20240229",
    "Sonnet 4.6": "claude-sonnet-4-6",
    "Claude Sonnet 4.6 (Thinking)": "claude-sonnet-4-6",
}

CLAUDE_EFFORT_MAP = {
    "light": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "extra": "xhigh",
    "extra high": "xhigh",
    "xhigh": "xhigh",
    "ultra": "max",
    "max": "max",
}

CLAUDE_MODEL_EFFORTS = {
    "Fable 5.1": {"low", "medium", "high", "xhigh", "max"},
    "Fable 5": {"low", "medium", "high", "xhigh", "max"},
    "Opus 5.5": {"low", "medium", "high", "xhigh", "max"},
    "Claude Opus 5.5": {"low", "medium", "high", "xhigh", "max"},
    "Claude Opus 5.5 (High)": {"low", "medium", "high", "xhigh", "max"},
    "Claude Opus 5.5 (Medium)": {"low", "medium", "high", "xhigh", "max"},
    "Claude Opus 5.5 (Low)": {"low", "medium", "high", "xhigh", "max"},
    "Opus 5": {"low", "medium", "high", "xhigh", "max"},
    "Sonnet 5.5": {"low", "medium", "high", "xhigh", "max"},
    "Claude Sonnet 5.5": {"low", "medium", "high", "xhigh", "max"},
    "Claude Sonnet 5.5 (High)": {"low", "medium", "high", "xhigh", "max"},
    "Claude Sonnet 5.5 (Medium)": {"low", "medium", "high", "xhigh", "max"},
    "Claude Sonnet 5.5 (Low)": {"low", "medium", "high", "xhigh", "max"},
    "Sonnet 5": {"low", "medium", "high", "xhigh", "max"},
    "Haiku 5.5": {"low", "medium", "high", "xhigh", "max"},
    "Opus 4.8": {"low", "medium", "high", "xhigh", "max"},
    "Opus 4.7": {"low", "medium", "high", "xhigh", "max"},
    "Opus 4.6": {"low", "medium", "high", "max"},
    "Claude Opus 4.6 (Thinking)": {"low", "medium", "high", "max"},
    "Sonnet 4.6": {"low", "medium", "high", "max"},
    "Claude Sonnet 4.6 (Thinking)": {"low", "medium", "high", "max"},
}

CLAUDE_CONVERSATION_PREFIX = "claude_"


def configure_claude_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases and capabilities for Claude models."""
    for model in models:
        if model.get("provider") != "claude" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        normalized_cli = CLAUDE_SLUG_ALIASES.get(cli_model, cli_model)
        CLAUDE_MODEL_MAP[model_id] = normalized_cli
        CLAUDE_MODEL_MAP[cli_model] = normalized_cli
        if label:
            CLAUDE_MODEL_MAP[label] = normalized_cli

        capabilities = model.get("capabilities", {})
        effort_values = capabilities.get("effort", [])
        supported_efforts = {
            CLAUDE_EFFORT_MAP[effort.lower()]
            for effort in effort_values
            if isinstance(effort, str) and effort.lower() in CLAUDE_EFFORT_MAP
        }
        if supported_efforts:
            CLAUDE_MODEL_EFFORTS[model_id] = supported_efforts
            CLAUDE_MODEL_EFFORTS[cli_model] = supported_efforts
            if label:
                CLAUDE_MODEL_EFFORTS[label] = supported_efforts
        else:
            CLAUDE_MODEL_EFFORTS.pop(model_id, None)
            CLAUDE_MODEL_EFFORTS.pop(cli_model, None)
            if label:
                CLAUDE_MODEL_EFFORTS.pop(label, None)


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


def is_claude_model(model_name: str) -> bool:
    return (
        model_name in CLAUDE_MODEL_MAP
        or model_name in CLAUDE_MODEL_MAP.values()
        or model_name in CLAUDE_SLUG_ALIASES
    )


def claude_model_slug(model_name: str) -> str:
    if model_name in CLAUDE_SLUG_ALIASES:
        return CLAUDE_SLUG_ALIASES[model_name]
    if model_name in CLAUDE_MODEL_MAP:
        slug = CLAUDE_MODEL_MAP[model_name]
        return CLAUDE_SLUG_ALIASES.get(slug, slug)
    if model_name in CLAUDE_MODEL_MAP.values():
        return CLAUDE_SLUG_ALIASES.get(model_name, model_name)
    raise ValueError(f"Unsupported Claude model: {model_name}")


def claude_display_model(model_name: str) -> str:
    if model_name in CLAUDE_MODEL_EFFORTS:
        return model_name
    return next(
        (name for name, slug in CLAUDE_MODEL_MAP.items() if model_name in {name, slug}),
        model_name,
    )


def claude_model_supports_effort(model_name: str) -> bool:
    return claude_display_model(model_name) in CLAUDE_MODEL_EFFORTS


def normalize_claude_effort(
    effort: Optional[str],
    model_name: Optional[str] = None,
) -> tuple[str, str]:
    preset_effort = CLAUDE_PRESET_EFFORTS.get(model_name or "")
    if preset_effort and (effort is None or effort.strip().lower() == "medium"):
        display_value = preset_effort
    else:
        display_value = (effort or preset_effort or "Medium").strip()
    cli_value = CLAUDE_EFFORT_MAP.get(display_value.lower())
    if not cli_value:
        raise ValueError(f"Unsupported Claude effort: {display_value}")

    canonical_display = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "xhigh": "Extra",
        "max": "Max",
    }[cli_value]
    if model_name:
        display_model = claude_display_model(model_name)
        supported = CLAUDE_MODEL_EFFORTS.get(display_model)
        if supported is not None and cli_value not in supported:
            raise ValueError(
                f"Effort {canonical_display} is not supported by Claude model {display_model}"
            )
    return canonical_display, cli_value


def claude_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(CLAUDE_CONVERSATION_PREFIX):
        session_id = conversation_id[len(CLAUDE_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_claude_conversation_id(session_id: str) -> str:
    return f"{CLAUDE_CONVERSATION_PREFIX}{session_id}"


def _is_runnable_claude(path: str) -> bool:
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
def resolve_claude_executable() -> str:
    configured = os.environ.get("CLAUDE_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("claude"),
        os.path.expanduser("~/.local/bin/claude.exe"),
        os.path.expanduser("~/.local/bin/claude"),
    ]

    checked = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_claude(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Claude Code CLI was found. Install it, authenticate it, "
        "or set CLAUDE_CLI_PATH."
    )


def build_claude_command(
    claude_path: str,
    prompt: str,
    model_name: str,
    effort: Optional[str] = "Medium",
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
) -> list[str]:
    del prompt  # Prompts are deliberately sent over stdin, never argv.
    model_slug = claude_model_slug(model_name)
    command = [
        claude_path,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model_slug,
    ]

    if claude_model_supports_effort(model_name):
        _, effort_cli = normalize_claude_effort(effort, model_name)
        command.extend(["--effort", effort_cli])

    session_id = claude_session_id(conversation_id)
    if session_id:
        command.extend(["--resume", session_id])

    if (target or "Sandbox").strip().lower() in {"real", "unrestricted"}:
        command.append("--dangerously-skip-permissions")
    else:
        # Non-interactive runs cannot answer permission prompts. dontAsk keeps
        # the run safe and lets Claude continue with operations it may perform.
        command.extend(["--permission-mode", "dontAsk"])

    return command


def build_claude_environment(thinking: bool) -> dict[str, str]:
    env = os.environ.copy()
    # MAX_THINKING_TOKENS=0 is Anthropic's explicit thinking-off control.
    # CLAUDE_CODE_DISABLE_THINKING is a gateway compatibility switch and can
    # still allow models that think by default to think, so do not use it here.
    env.pop("CLAUDE_CODE_DISABLE_THINKING", None)
    if thinking:
        env.pop("MAX_THINKING_TOKENS", None)
    else:
        env["MAX_THINKING_TOKENS"] = "0"
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


def _parse_claude_rate_limit_window(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    utilization = raw.get("utilization")
    if isinstance(utilization, bool) or not isinstance(utilization, (int, float)):
        return None
    if not math.isfinite(utilization) or utilization < 0:
        return None
    resets_at = raw.get("resetsAt")
    if isinstance(resets_at, bool) or not isinstance(resets_at, (int, float)) or resets_at <= 0:
        resets_at = None
    return {
        "utilization": float(utilization),
        "resetsAt": int(resets_at) if resets_at is not None else None,
    }


def parse_claude_rate_limit_info(info: Any, observed_at: float) -> Optional[dict[str, Any]]:
    """Extract account windows from a Claude CLI ``rate_limit_event`` payload.

    ``unifiedWindows`` mirrors Anthropic's ``anthropic-ratelimit-unified-*``
    response headers: ``utilization`` is the fraction of the window used (it
    can legitimately exceed 1) and ``resetsAt`` is epoch seconds. The CLI marks
    this field internal, so a payload without it yields ``None``.
    """
    if not isinstance(info, dict):
        return None
    windows = info.get("unifiedWindows")
    if not isinstance(windows, dict):
        return None
    hourly = _parse_claude_rate_limit_window(windows.get("five_hour"))
    weekly = _parse_claude_rate_limit_window(windows.get("seven_day"))
    if not hourly and not weekly:
        return None
    status = info.get("status")
    return {
        "status": status if isinstance(status, str) else None,
        "observedAt": float(observed_at),
        "hourly": hourly,
        "weekly": weekly,
    }


def _epoch_to_iso(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_claude_rate_limits(snapshot: Optional[dict[str, Any]], now: float) -> dict[str, Any]:
    """Shape a stored rate-limit snapshot for ``/api/usage-limits``.

    The snapshot is only as fresh as the last Claude CLI run made by KookAI, so
    a window whose reset time has passed is reported as reset rather than
    repeating its stale utilization.
    """
    if not snapshot:
        return {
            "available": False,
            "source": "claude_cli",
            "weekly": None,
            "hourly": None,
            "usedPercent": None,
            "remainingPercent": None,
            "resetTime": None,
            "observedAt": None,
            "description": "No Claude account usage reported yet. Send a message with a Claude Code model to load your limits.",
        }

    def window_view(window: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not window:
            return None
        resets_at = window.get("resetsAt")
        if resets_at is not None and resets_at <= now:
            return {
                "usedPercent": 0.0,
                "remainingPercent": 100.0,
                "resetTime": None,
                "description": "This window has reset since KookAI last saw Claude usage.",
            }
        used = round(min(100.0, window["utilization"] * 100.0), 1)
        return {
            "usedPercent": used,
            "remainingPercent": round(100.0 - used, 1),
            "resetTime": _epoch_to_iso(resets_at),
            "description": None,
        }

    hourly = window_view(snapshot.get("hourly"))
    weekly = window_view(snapshot.get("weekly"))
    primary = hourly or weekly or {}
    return {
        "available": True,
        "source": "claude_cli",
        "status": snapshot.get("status"),
        "weekly": weekly,
        "hourly": hourly,
        "usedPercent": primary.get("usedPercent"),
        "remainingPercent": primary.get("remainingPercent"),
        "resetTime": primary.get("resetTime"),
        "observedAt": _epoch_to_iso(snapshot.get("observedAt")),
        "description": primary.get("description"),
    }


def parse_claude_stream_json(output: str, observed_at: Optional[float] = None) -> dict[str, Any]:
    session_id = None
    final_message = ""
    assistant_messages: list[str] = []
    errors: list[str] = []
    rate_limits: Optional[dict[str, Any]] = None

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
            if text:
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
        elif event_type == "rate_limit_event":
            parsed_limits = parse_claude_rate_limit_info(
                event.get("rate_limit_info"),
                observed_at if observed_at is not None else time.time(),
            )
            if parsed_limits:
                rate_limits = parsed_limits

    if not final_message and assistant_messages:
        final_message = assistant_messages[-1]
    return {
        "session_id": session_id,
        "final_message": final_message,
        "errors": errors,
        "rate_limits": rate_limits,
    }


def classify_claude_progress_line(source: str, line: str) -> Optional[dict[str, str]]:
    if source == "stderr":
        clean = (line or "").strip()
        return {"type": "error", "message": clean} if clean else None
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, dict):
        return None

    event_type = event.get("type")
    if event_type == "system" and event.get("subtype") == "init":
        return {"type": "progress", "message": "Claude session started."}
    if event_type == "assistant":
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else []
        if isinstance(content, list):
            tool_names = [
                block.get("name")
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            if tool_names:
                return {
                    "type": "progress",
                    "message": f"Claude is using {', '.join(str(name) for name in tool_names)}.",
                }
    if event_type == "result" and event.get("is_error"):
        message = event.get("result") or event.get("error") or "Claude task failed."
        return {"type": "error", "message": str(message)}
    return None
