"""DeepSeek Harness (`dsh`) CLI integration helpers for KookAI Local LLM models.

The helpers in this module are intentionally independent from FastAPI and
persistent application state so command construction, patch synthesis, and
stream parsing remain easy to test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional


DSH_CONVERSATION_PREFIX = "local_dsh_"
DSH_LOCAL_PROVIDER_ID = "kookai-local"
DSH_LOCAL_API_KEY_ENV = "KOOKAI_DSH_LOCAL_API_KEY"
DEFAULT_DSH_CONTEXT_WINDOW = 32768
DEFAULT_DSH_MAX_TOKENS = 8192
DEFAULT_DSH_STREAM_IDLE_TIMEOUT_MS = 1800000
DEFAULT_DSH_REASONING_EFFORT = "low"
VALID_DSH_REASONING_EFFORTS = {"low", "medium", "high"}


def dsh_session_id(conversation_id: Optional[str]) -> Optional[str]:
    """Extract the underlying DeepSeek Harness session ID from a KookAI conversation ID."""
    if conversation_id and conversation_id.startswith(DSH_CONVERSATION_PREFIX):
        session_id = conversation_id[len(DSH_CONVERSATION_PREFIX):].strip()
        return session_id or None
    return None


def make_dsh_conversation_id(session_id: str) -> str:
    """Wrap a DeepSeek Harness session ID in KookAI's local_dsh_ prefix."""
    return f"{DSH_CONVERSATION_PREFIX}{session_id}"


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


def _is_runnable_dsh(path: str) -> bool:
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
def resolve_dsh_executable() -> str:
    """Locate a runnable `dsh` executable or raise FileNotFoundError."""
    try:
        from cli_manager import resolve_cli_executable

        managed = resolve_cli_executable("dsh")
        if managed and _is_runnable_dsh(managed):
            return managed
    except Exception:
        pass

    configured = os.environ.get("DSH_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("dsh"),
        os.path.expanduser("~/.local/bin/dsh.cmd") if os.name == "nt" else None,
        os.path.expanduser("~/.local/bin/dsh.exe") if os.name == "nt" else None,
        os.path.expanduser("~/.local/bin/dsh"),
        os.path.expanduser("~/.local/node/bin/dsh"),
        os.path.expanduser("~/.npm-global/bin/dsh"),
        "/opt/homebrew/bin/dsh" if os.name != "nt" else None,
        "/usr/local/bin/dsh" if os.name != "nt" else None,
        "/usr/bin/dsh" if os.name != "nt" else None,
    ]

    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized in checked:
            continue
        checked.add(normalized)
        if _is_runnable_dsh(normalized):
            return normalized

    raise FileNotFoundError(
        "No runnable DeepSeek Harness CLI (`dsh`) was found. Install `@deepseek-ai/dsh` or set DSH_CLI_PATH."
    )


def is_dsh_available() -> bool:
    """Return True if a runnable DeepSeek Harness executable is installed."""
    try:
        return bool(resolve_dsh_executable())
    except (FileNotFoundError, OSError):
        return False


def should_use_dsh_harness() -> bool:
    """Return True when KOOKAI_LOCAL_HARNESS selects `dsh` and `dsh` is runnable."""
    from qwen_backend import local_harness_mode

    return local_harness_mode() == "dsh" and is_dsh_available()


def dsh_permission_mode(target: str = "Sandbox") -> str:
    """Map KookAI execution target to a DeepSeek Harness permission preset."""
    if (target or "Sandbox").strip().lower() in {"real", "unrestricted"}:
        return "danger-full-access"
    return "workspace-write"


def build_dsh_command(
    dsh_path: str,
    patch_path: str,
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
) -> list[str]:
    """Build a headless DeepSeek Harness command that reads the task from stdin."""
    command = [
        dsh_path,
        "--profile",
        "headless",
        "--patch",
        patch_path,
        "--permission-mode",
        dsh_permission_mode(target),
        "--approval-policy",
        "never",
        "--json",
    ]
    session_id = dsh_session_id(conversation_id)
    if session_id:
        command.extend(["--session-id", session_id])
    command.append("-")
    if os.name == "nt" and os.path.splitext(dsh_path)[1].lower() in {".cmd", ".bat"}:
        command = ["cmd.exe", "/d", "/s", "/c", *command]
    return command


def build_dsh_environment(
    base_url: str,
    raw_model_id: str,
    api_key: str = "",
) -> dict[str, str]:
    """Build subprocess environment with an isolated local API key variable."""
    del base_url, raw_model_id
    env = os.environ.copy()
    env[DSH_LOCAL_API_KEY_ENV] = (api_key or "").strip() or "local"
    env["NO_BROWSER"] = "1"
    return env


def _positive_int_env(env: dict[str, str], name: str, default: int) -> int:
    raw = str(env.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def build_dsh_patch_document(
    base_url: str,
    raw_model_id: str,
    *,
    thinking: Optional[bool] = None,
    env: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    """Build the DeepSeek Harness `--patch` overlay for a local OpenAI-compatible model."""
    source_env = env if env is not None else os.environ
    context_window = _positive_int_env(
        source_env, "KOOKAI_DSH_CONTEXT_WINDOW", DEFAULT_DSH_CONTEXT_WINDOW
    )
    max_tokens = _positive_int_env(
        source_env, "KOOKAI_DSH_MAX_TOKENS", DEFAULT_DSH_MAX_TOKENS
    )
    stream_idle_timeout_ms = _positive_int_env(
        source_env,
        "KOOKAI_DSH_STREAM_IDLE_TIMEOUT_MS",
        DEFAULT_DSH_STREAM_IDLE_TIMEOUT_MS,
    )
    raw_effort = str(source_env.get("KOOKAI_DSH_REASONING_EFFORT", "") or "").strip().lower()
    effort = (
        raw_effort
        if raw_effort in VALID_DSH_REASONING_EFFORTS
        else DEFAULT_DSH_REASONING_EFFORT
    )

    compat: dict[str, Any] = {"supportsStore": False}
    model_entry: dict[str, Any] = {
        "id": raw_model_id,
        "name": f"{raw_model_id} (Local)",
        "contextWindow": context_window,
        "maxTokens": max_tokens,
        "input": ["text"],
    }
    default_model: dict[str, Any] = {
        "provider": DSH_LOCAL_PROVIDER_ID,
        "model": raw_model_id,
    }

    if thinking is not None:
        compat["supportsReasoningEffort"] = True
        compat["thinkingFormat"] = "openai"
        model_entry["reasoningEfforts"] = {
            "off": "none",
            "low": "low",
            "medium": "medium",
            "high": "high",
        }
        default_model["reasoningEffort"] = effort if thinking else "off"

    return [
        {"id": "session-title-llm", "disabled": True},
        {
            "id": "llm-pi-ai",
            "config": {
                "providers": {
                    DSH_LOCAL_PROVIDER_ID: {
                        "displayName": "KookAI Local",
                        "api": "openai-completions",
                        "baseURL": base_url,
                        "apiKeyEnv": DSH_LOCAL_API_KEY_ENV,
                        "streamIdleTimeoutMs": stream_idle_timeout_ms,
                        "compat": compat,
                        "models": [model_entry],
                    }
                }
            },
        },
        {"id": "agent-default-model", "config": default_model},
    ]


@contextmanager
def dsh_patch_file(
    base_url: str,
    raw_model_id: str,
    *,
    thinking: Optional[bool] = None,
    env: Optional[dict[str, str]] = None,
):
    """Write a temporary JSON-in-YAML `--patch` file and clean it up after invocation."""
    patch_doc = build_dsh_patch_document(
        base_url,
        raw_model_id,
        thinking=thinking,
        env=env,
    )
    with tempfile.TemporaryDirectory(prefix="kookai-dsh-patch-") as directory:
        patch_path = Path(directory) / "patch.yml"
        patch_path.write_text(json.dumps(patch_doc), encoding="utf-8")
        patch_path.chmod(0o600)
        yield str(patch_path)


def _format_dsh_reason_error(reason: Any) -> Optional[str]:
    if not isinstance(reason, dict):
        return None
    kind = reason.get("kind")
    if kind == "error":
        err = reason.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or "").strip()
            msg = str(err.get("message") or "").strip()
            if code and msg:
                return f"{code}: {msg}"
            if msg or code:
                return msg or code
        if err:
            return str(err)
        return "DeepSeek Harness turn failed."
    if kind is not None and kind != "completed":
        msg = str(reason.get("message") or "").strip()
        return msg or str(kind)
    return None


def parse_dsh_stream_json(output: str) -> dict[str, Any]:
    """Parse newline-delimited JSON output from `dsh --profile headless --json`."""
    session_id: Optional[str] = None
    final_message = ""
    text_parts: list[str] = []
    errors: list[str] = []
    seen_errors: set[str] = set()

    def record_error(message: Optional[str]) -> None:
        clean = str(message or "").strip()
        if clean and clean not in seen_errors:
            seen_errors.add(clean)
            errors.append(clean)

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

        event_session_id = event.get("sessionId") or event.get("session_id")
        if isinstance(event_session_id, str) and event_session_id.strip():
            session_id = event_session_id.strip()

        event_type = event.get("type")
        if event_type == "text":
            text = event.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text)
        elif event_type == "final":
            final_text = event.get("text")
            if isinstance(final_text, str) and final_text:
                final_message = final_text
            record_error(_format_dsh_reason_error(event.get("reason")))
        elif event_type == "status" and event.get("phase") == "turn_end":
            record_error(_format_dsh_reason_error(event.get("reason")))
        elif event_type == "error":
            record_error(event.get("message") or event.get("error"))

    if not final_message and text_parts:
        final_message = text_parts[-1]
    return {
        "session_id": session_id,
        "final_message": final_message,
        "errors": errors,
    }


def classify_dsh_progress_line(source: str, line: str) -> Optional[dict[str, str]]:
    """Map one `dsh --json` stdout/stderr line into a KookAI progress event."""
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
                "econnrefused",
                "cannot",
                "not found",
                "does not exist",
                "timed out",
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
    if event_type == "session":
        return {"type": "progress", "message": "DeepSeek Harness session started."}
    if event_type == "thinking":
        return {"type": "progress", "message": "DeepSeek Harness is thinking..."}
    if event_type == "text":
        return {"type": "progress", "message": "DeepSeek Harness is generating a response..."}
    if event_type == "tool_call":
        tool_name = str(event.get("tool") or "").strip()
        if tool_name:
            return {"type": "progress", "message": f"DeepSeek Harness is using {tool_name}."}
    if event_type == "tool_result" and event.get("status") == "error":
        return {
            "type": "progress",
            "message": "DeepSeek Harness tool reported an error; continuing...",
        }
    if event_type in {"status", "final"}:
        if event_type == "status" and event.get("phase") != "turn_end":
            return None
        reason_err = _format_dsh_reason_error(event.get("reason"))
        if reason_err:
            return {"type": "error", "message": reason_err[:500]}
    if event_type == "error":
        message = event.get("message") or event.get("error") or "DeepSeek Harness error."
        return {"type": "error", "message": str(message)[:500]}
    return None
