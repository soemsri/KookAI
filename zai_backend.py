"""Z.ai GLM integration through the officially supported OpenCode CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any, Optional


ZAI_MODEL_MAP = {
    "GLM 5.2": "zai-coding-plan/glm-5.2",
    "GLM 5 Turbo": "zai-coding-plan/glm-5-turbo",
    "GLM 4.7": "zai-coding-plan/glm-4.7",
    "GLM 4.5 Air": "zai-coding-plan/glm-4.5-air",
}
ZAI_CONVERSATION_PREFIX = "zai_"


def configure_zai_catalog(models: list[dict[str, Any]]) -> None:
    for model in models:
        if model.get("provider") != "zai" or not model.get("enabled", True):
            continue
        model_id = str(model.get("id", "")).strip()
        label = str(model.get("label", "")).strip()
        cli_model = str(model.get("cli_model", "")).strip()
        if model_id and cli_model:
            ZAI_MODEL_MAP[model_id] = cli_model
            if label:
                ZAI_MODEL_MAP[label] = cli_model


def zai_model_alias(model_name: str) -> str:
    clean = (model_name or "").strip()
    if clean in ZAI_MODEL_MAP:
        return ZAI_MODEL_MAP[clean]
    if clean in ZAI_MODEL_MAP.values():
        return clean
    raise ValueError(f"Unsupported Z.ai model: {model_name}")


def is_zai_model(model_name: str) -> bool:
    clean = (model_name or "").strip()
    return clean in ZAI_MODEL_MAP or clean in ZAI_MODEL_MAP.values()


def zai_session_id(conversation_id: Optional[str]) -> Optional[str]:
    if conversation_id and conversation_id.startswith(ZAI_CONVERSATION_PREFIX):
        value = conversation_id[len(ZAI_CONVERSATION_PREFIX):].strip()
        return value or None
    return None


def make_zai_conversation_id(session_id: str) -> str:
    return f"{ZAI_CONVERSATION_PREFIX}{session_id}"


def _is_runnable(path: str) -> bool:
    try:
        if not path or not os.path.isfile(path):
            return False
        command = [path, "--version"]
        if os.name == "nt" and os.path.splitext(path)[1].lower() in {".cmd", ".bat"}:
            command = ["cmd.exe", "/d", "/s", "/c", *command]
        return subprocess.run(
            command, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def resolve_zai_executable() -> str:
    try:
        from cli_manager import resolve_cli_executable
        managed = resolve_cli_executable("zai")
        if managed and _is_runnable(managed):
            return managed
    except Exception:
        pass
    configured = os.environ.get("ZAI_CLI_PATH", "").strip()
    candidates = [
        os.path.expanduser(configured) if configured else None,
        shutil.which("opencode"),
        os.path.expanduser("~/.local/bin/opencode"),
        os.path.expanduser("~/.local/bin/opencode.exe"),
    ]
    checked: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(candidate)
        if normalized not in checked and _is_runnable(normalized):
            return normalized
        checked.add(normalized)
    raise FileNotFoundError(
        "No runnable OpenCode CLI was found. Install it, run `opencode auth login` "
        "and select Z.AI Coding Plan, or set ZAI_CLI_PATH."
    )


def build_zai_command(
    opencode_path: str,
    prompt: str,
    model_name: str,
    target: str = "Sandbox",
    conversation_id: Optional[str] = None,
) -> list[str]:
    model_alias = zai_model_alias(model_name)
    provider_id = os.environ.get("ZAI_OPENCODE_PROVIDER", "zai-coding-plan").strip()
    if not re.fullmatch(r"[a-z0-9_-]+", provider_id):
        provider_id = "zai-coding-plan"
    if "/" in model_alias:
        model_alias = f"{provider_id}/{model_alias.rsplit('/', 1)[1]}"
    command = [
        opencode_path, "run", "--format", "json", "--model",
        model_alias,
    ]
    if (target or "Sandbox").strip().lower() in {"real", "unrestricted"}:
        command.append("--auto")
    session_id = zai_session_id(conversation_id)
    if session_id:
        command.extend(["--session", session_id])
    command.append(prompt)
    if os.name == "nt" and os.path.splitext(opencode_path)[1].lower() in {".cmd", ".bat"}:
        command = ["cmd.exe", "/d", "/s", "/c", *command]
    return command


def parse_zai_stream_json(output: str) -> dict[str, Any]:
    session_id: Optional[str] = None
    text_parts: list[str] = []
    errors: list[str] = []
    for raw_line in (output or "").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        candidate = event.get("sessionID") or event.get("session_id")
        if isinstance(candidate, str) and candidate:
            session_id = candidate
        event_type = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if event_type == "text" or part.get("type") == "text":
            value = part.get("text") or event.get("text")
            if isinstance(value, str) and value:
                text_parts.append(value)
        elif event_type == "error" or part.get("type") == "error":
            value = event.get("error") or event.get("message") or part.get("error")
            if value:
                errors.append(str(value))
    return {"session_id": session_id, "final_message": "".join(text_parts), "errors": errors}


def classify_zai_progress_line(source: str, line: str) -> Optional[dict[str, str]]:
    clean = (line or "").strip()
    if not clean:
        return None
    if source == "stderr":
        lowered = clean.lower()
        kind = "error" if any(word in lowered for word in (
            "error", "failed", "unauthorized", "forbidden", "invalid"
        )) else "progress"
        return {"type": kind, "message": clean[:500]}
    try:
        event = json.loads(clean)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    part = event.get("part") if isinstance(event.get("part"), dict) else {}
    if event_type == "step_start":
        return {"type": "progress", "message": "Z.ai GLM session started."}
    if event_type == "tool_use" or part.get("type") == "tool":
        tool = part.get("tool") or part.get("name") or "a tool"
        return {"type": "progress", "message": f"Z.ai GLM is using {tool}."}
    if event_type == "error":
        message = event.get("message") or event.get("error") or "Z.ai GLM task failed."
        return {"type": "error", "message": str(message)[:500]}
    return None
