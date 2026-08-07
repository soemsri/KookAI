"""Codex CLI integration helpers.

This module intentionally contains no FastAPI or filesystem state so command
construction and JSONL parsing can be tested without starting the server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import glob
import tomllib
import time
import threading
import queue
from functools import lru_cache
from typing import Any, Optional

from claude_backend import is_claude_model
from grok_backend import is_grok_model
from kimi_backend import is_kimi_model
from muse_backend import is_muse_model


CODEX_MODEL_MAP = {
    "5.6 Sol": "gpt-5.6-sol",
    "5.6 Terra": "gpt-5.6-terra",
    "5.6 Luna": "gpt-5.6-luna",
    "5.5": "gpt-5.5",
    "5.4": "gpt-5.4",
    "5.4 Mini": "gpt-5.4-mini",
}

CODEX_EFFORT_MAP = {
    "light": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "extra high": "xhigh",
    "xhigh": "xhigh",
    "ultra": "ultra",
}

CODEX_SPEED_MAP = {
    "standard": "default",
    "default": "default",
    "fast": "priority",
}

# Fast mode currently supports the GPT-5.6 family, GPT-5.5, and GPT-5.4.
CODEX_FAST_MODELS = {
    "5.6 Sol",
    "5.6 Terra",
    "5.6 Luna",
    "5.5",
    "5.4",
}

CODEX_MODEL_EFFORTS = {
    "5.6 Sol": {"light", "medium", "high", "extra high", "ultra"},
    "5.6 Terra": {"light", "medium", "high", "extra high", "ultra"},
    "5.6 Luna": {"light", "medium", "high", "extra high"},
    "5.5": {"light", "medium", "high", "extra high"},
    "5.4": {"light", "medium", "high", "extra high"},
    "5.4 Mini": {"light", "medium", "high", "extra high"},
}

CODEX_CONVERSATION_PREFIX = "codex_"


def configure_codex_catalog(models: list[dict[str, Any]]) -> None:
    """Register enabled catalog aliases for Codex models."""
    for model in models:
        if model.get("provider") != "codex" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if not model_id or not cli_model:
            continue
        CODEX_MODEL_MAP[model_id] = cli_model
        if label:
            CODEX_MODEL_MAP[label] = cli_model

        capabilities = model.get("capabilities", {})
        effort_values = capabilities.get("effort", [])
        supported_efforts = {
            CODEX_EFFORT_MAP[effort.lower()]
            for effort in effort_values
            if isinstance(effort, str) and effort.lower() in CODEX_EFFORT_MAP
        }
        if supported_efforts:
            CODEX_MODEL_EFFORTS[model_id] = supported_efforts
            if label:
                CODEX_MODEL_EFFORTS[label] = supported_efforts
        else:
            CODEX_MODEL_EFFORTS.pop(model_id, None)
            if label:
                CODEX_MODEL_EFFORTS.pop(label, None)

        speed_values = capabilities.get("speed", [])
        if any(
            isinstance(speed, str) and speed.lower() == "fast"
            for speed in speed_values
        ):
            CODEX_FAST_MODELS.add(model_id)
            if label:
                CODEX_FAST_MODELS.add(label)
        else:
            CODEX_FAST_MODELS.discard(model_id)
            if label:
                CODEX_FAST_MODELS.discard(label)


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Return Windows flags that prevent spawned console tools from flashing."""
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


def is_codex_model(model_name: str) -> bool:
    return model_name in CODEX_MODEL_MAP or model_name in CODEX_MODEL_MAP.values()


def resolve_provider(provider: Optional[str], model_name: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized and normalized not in {"agy", "codex", "claude", "kimi", "xai", "muse"}:
        raise ValueError(f"Unsupported agent provider: {provider}")
    if normalized == "codex" and not is_codex_model(model_name):
        raise ValueError(f"Model {model_name} is not a Codex model")
    if normalized == "claude" and not is_claude_model(model_name):
        raise ValueError(f"Model {model_name} is not a Claude CLI model")
    if normalized == "kimi" and not is_kimi_model(model_name):
        raise ValueError(f"Model {model_name} is not a Kimi Code model")
    if normalized == "xai" and not is_grok_model(model_name):
        raise ValueError(f"Model {model_name} is not an xAI model")
    if normalized == "muse" and not is_muse_model(model_name):
        raise ValueError(f"Model {model_name} is not a Meta Muse model")
    if normalized == "agy" and is_codex_model(model_name):
        raise ValueError(f"Model {model_name} must use the Codex provider")
    if normalized == "agy" and is_claude_model(model_name):
        raise ValueError(f"Model {model_name} must use the Claude provider")
    if normalized == "agy" and is_kimi_model(model_name):
        raise ValueError(f"Model {model_name} must use the Kimi provider")
    if normalized == "agy" and is_grok_model(model_name):
        raise ValueError(f"Model {model_name} must use the xAI provider")
    if normalized == "agy" and is_muse_model(model_name):
        raise ValueError(f"Model {model_name} must use the Muse provider")
    if normalized:
        return normalized
    if is_codex_model(model_name):
        return "codex"
    if is_claude_model(model_name):
        return "claude"
    if is_kimi_model(model_name):
        return "kimi"
    if is_grok_model(model_name):
        return "xai"
    if is_muse_model(model_name):
        return "muse"
    return "agy"


def codex_model_slug(model_name: str) -> str:
    if model_name in CODEX_MODEL_MAP:
        return CODEX_MODEL_MAP[model_name]
    if model_name in CODEX_MODEL_MAP.values():
        return model_name
    raise ValueError(f"Unsupported Codex model: {model_name}")


def normalize_codex_effort(
    effort: Optional[str],
    model_name: Optional[str] = None,
) -> tuple[str, str]:
    display_value = (effort or "Medium").strip()
    cli_value = CODEX_EFFORT_MAP.get(display_value.lower())
    if not cli_value:
        raise ValueError(f"Unsupported Codex effort: {display_value}")
    canonical_display = {
        "low": "Light",
        "medium": "Medium",
        "high": "High",
        "xhigh": "Extra High",
        "ultra": "Ultra",
    }[cli_value]
    if model_name:
        display_model = next(
            (name for name, slug in CODEX_MODEL_MAP.items() if model_name in {name, slug}),
            model_name,
        )
        supported = CODEX_MODEL_EFFORTS.get(display_model)
        if not supported or cli_value not in supported:
            raise ValueError(
                f"Effort {canonical_display} is not supported by Codex model {display_model}"
            )
    return canonical_display, cli_value


def normalize_codex_speed(speed: Optional[str], model_name: str) -> tuple[str, str]:
    display_value = (speed or "Standard").strip()
    cli_value = CODEX_SPEED_MAP.get(display_value.lower())
    if not cli_value:
        raise ValueError(f"Unsupported Codex speed: {display_value}")
    canonical_display = "Fast" if cli_value == "priority" else "Standard"
    display_model = next(
        (name for name, slug in CODEX_MODEL_MAP.items() if model_name in {name, slug}),
        model_name,
    )
    if cli_value == "priority" and display_model not in CODEX_FAST_MODELS:
        raise ValueError(f"Fast speed is not supported by Codex model {model_name}")
    return canonical_display, cli_value


def codex_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(CODEX_CONVERSATION_PREFIX):
        session_id = conversation_id[len(CODEX_CONVERSATION_PREFIX) :].strip()
        return session_id or None
    return None


def make_codex_conversation_id(session_id: str) -> str:
    return f"{CODEX_CONVERSATION_PREFIX}{session_id}"


def _config_codex_cli_path() -> Optional[str]:
    config_path = os.path.expanduser("~/.codex/config.toml")
    if not os.path.isfile(config_path):
        return None
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        return (
            config.get("mcp_servers", {})
            .get("node_repl", {})
            .get("env", {})
            .get("CODEX_CLI_PATH")
        )
    except Exception:
        return None


def _is_runnable_codex(path: str) -> bool:
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
            **hidden_subprocess_kwargs(),
        )
        return probe.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def resolve_codex_executable() -> str:
    configured = os.environ.get("CODEX_CLI_PATH", "").strip()
    config_path = _config_codex_cli_path()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.expanduser(configured) if configured else None,
        os.path.expanduser(config_path) if config_path else None,
        os.path.expanduser("~/.codex/plugins/.plugin-appserver/codex.exe"),
    ]
    if local_app_data:
        candidates.extend(
            sorted(
                glob.glob(os.path.join(local_app_data, "OpenAI", "Codex", "bin", "*", "codex.exe")),
                key=lambda path: os.path.getmtime(path),
                reverse=True,
            )
        )
    candidates.extend([
        shutil.which("codex"),
        os.path.expanduser("~/.local/bin/codex"),
    ])

    checked = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_codex(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable Codex CLI was found. Install it, run `codex login`, "
        "or set CODEX_CLI_PATH."
    )


def build_codex_command(
    codex_path: str,
    prompt: str,
    model_name: str,
    effort: Optional[str] = "Medium",
    speed: Optional[str] = "Standard",
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
) -> list[str]:
    model_slug = codex_model_slug(model_name)
    effort_display, effort_cli = normalize_codex_effort(effort, model_name)
    _, service_tier = normalize_codex_speed(speed, model_name)

    command = [
        codex_path,
        "exec",
        "--json",
        "--color",
        "never",
        "--model",
        model_slug,
        "--skip-git-repo-check",
        "-c",
        "model_provider=openai",
        "-c",
        "approval_policy=never",
        "-c",
        f"model_reasoning_effort={effort_cli}",
        "-c",
        f"service_tier={service_tier}",
    ]
    if (target or "Sandbox").strip().lower() in {"local", "local sandbox", "sandbox"}:
        command += ["--sandbox", "workspace-write"]
    else:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    if service_tier == "priority":
        command += ["-c", "features.fast_mode=true"]
    if effort_display == "Ultra":
        command += ["-c", "features.multi_agent=true"]

    session_id = codex_session_id(conversation_id)
    if session_id:
        command += ["resume", session_id]
        for path in image_paths or []:
            command += ["--image", path]
        command.append("-")
    else:
        for path in image_paths or []:
            command += ["--image", path]
        command.append("-")
    return command


def parse_codex_jsonl(output: str) -> dict[str, Any]:
    session_id: Optional[str] = None
    final_message = ""
    errors: list[str] = []
    events: list[dict[str, Any]] = []

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

        events.append(event)
        event_type = event.get("type")
        if event_type == "thread.started":
            session_id = event.get("thread_id") or session_id
        elif event_type == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                final_message = str(item["text"])
        elif event_type in {"turn.failed", "error"}:
            error = event.get("error")
            if isinstance(error, dict):
                error = error.get("message") or json.dumps(error)
            if error:
                errors.append(str(error))

    return {
        "session_id": session_id,
        "final_message": final_message,
        "errors": errors,
        "events": events,
    }


def classify_codex_progress_line(source: str, line: str) -> Optional[dict[str, str]]:
    clean = (line or "").strip()
    if not clean:
        return None

    # Human-readable diagnostics are normally written to stderr.
    if source == "stderr":
        lowered = clean.lower()
        event_type = "error" if any(
            term in lowered
            for term in ("error", "failed", "failure", "denied", "unauthorized", "invalid")
        ) else "progress"
        return {"type": event_type, "message": clean[:500]}

    try:
        event = json.loads(clean)
    except json.JSONDecodeError:
        return {"type": "progress", "message": clean[:500]}
    if not isinstance(event, dict):
        return None

    event_type = event.get("type")
    if event_type == "thread.started":
        return {"type": "progress", "message": "Codex session started."}
    if event_type == "turn.started":
        return {"type": "progress", "message": "Codex is working..."}
    if event_type in {"turn.failed", "error"}:
        error = event.get("error") or "Codex task failed."
        if isinstance(error, dict):
            error = error.get("message") or json.dumps(error)
        return {"type": "error", "message": str(error)[:500]}

    if event_type in {"item.started", "item.completed", "item.updated"}:
        item = event.get("item") or {}
        item_type = item.get("type")
        if item_type == "command_execution":
            command = item.get("command") or item.get("aggregated_output")
            if command:
                verb = "Running" if event_type == "item.started" else "Completed"
                return {"type": "progress", "message": f"{verb}: {str(command)[:440]}"}
        if item_type in {"mcp_tool_call", "web_search", "file_change"}:
            label = item_type.replace("_", " ").title()
            return {"type": "progress", "message": f"{label}..."}
        if item_type == "reasoning":
            text = item.get("text") or item.get("summary")
            if text:
                return {"type": "progress", "message": str(text)[:500]}

    return None


def _normalize_rate_limit_window(window: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(window, dict):
        return None
    try:
        used_percent = int(window.get("usedPercent", 0))
    except (TypeError, ValueError):
        used_percent = 0
    used_percent = max(0, min(100, used_percent))
    return {
        "usedPercent": used_percent,
        "remainingPercent": max(0, 100 - used_percent),
        "windowDurationMins": window.get("windowDurationMins"),
        "resetsAt": window.get("resetsAt"),
    }


def summarize_codex_rate_limits(response_result: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return a sanitized Codex account rate-limit snapshot.

    The app-server response can include opaque reset-credit IDs and descriptions.
    This summary intentionally keeps only display-safe aggregate fields.
    """
    if not isinstance(response_result, dict):
        return None

    rate_limits = response_result.get("rateLimits")
    by_limit_id = response_result.get("rateLimitsByLimitId")
    if isinstance(by_limit_id, dict) and isinstance(by_limit_id.get("codex"), dict):
        rate_limits = by_limit_id["codex"]
    if not isinstance(rate_limits, dict):
        return None

    reset_summary = response_result.get("rateLimitResetCredits") or {}
    available_resets = reset_summary.get("availableCount")
    try:
        available_resets = int(available_resets) if available_resets is not None else None
    except (TypeError, ValueError):
        available_resets = None

    return {
        "available": True,
        "limitId": rate_limits.get("limitId"),
        "limitName": rate_limits.get("limitName"),
        "planType": rate_limits.get("planType"),
        "primary": _normalize_rate_limit_window(rate_limits.get("primary")),
        "secondary": _normalize_rate_limit_window(rate_limits.get("secondary")),
        "availableResets": available_resets,
    }


def fetch_codex_rate_limits(codex_path: Optional[str] = None, timeout_seconds: float = 10) -> Optional[dict[str, Any]]:
    """Fetch current Codex account rate limits from the local Codex app-server."""
    executable = codex_path or resolve_codex_executable()
    messages = [
        {
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "KookAI", "version": "1.0.0"},
                "capabilities": {"experimentalApi": True},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": "rate_limits",
            "method": "account/rateLimits/read",
            "params": None,
        },
    ]

    process = subprocess.Popen(
        [executable, "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(),
    )
    output_queue: queue.Queue[tuple[str, str]] = queue.Queue()

    def read_stream(stream: Any, name: str):
        for line in iter(stream.readline, ""):
            output_queue.put((name, line.rstrip("\n")))

    threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True).start()
    threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True).start()

    try:
        assert process.stdin is not None
        for message in messages:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                source, line = output_queue.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if source != "stdout" or not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("id") == "rate_limits":
                if event.get("error"):
                    return None
                return summarize_codex_rate_limits(event.get("result") or {})
        return None
    finally:
        try:
            process.terminate()
        except Exception:
            pass
