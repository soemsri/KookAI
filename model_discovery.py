"""Automated model discovery and catalog synchronization for all KookAI providers."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

from model_catalog import (
    ModelCatalogError,
    load_model_catalog,
    save_model_catalog,
    validate_model_catalog,
)
from cli_manager import resolve_cli_executable

LOGGER = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_last_auto_sync_time: float = 0.0

# ---------------------------------------------------------------------------
# Seed registries for all supported providers
# ---------------------------------------------------------------------------

KNOWN_CODEX_MODELS: list[dict[str, Any]] = [
    {
        "id": "6 Astra",
        "label": "6 Astra",
        "description": "Our most capable model for complex, demanding work",
        "provider": "codex",
        "cli_model": "gpt-6-astra",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High", "Ultra"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "6 Sol",
        "label": "6 Sol",
        "description": "Codex GPT-6 Sol for complex, open-ended work",
        "provider": "codex",
        "cli_model": "gpt-6-sol",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High", "Ultra"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "6 Luna",
        "label": "6 Luna",
        "description": "Codex GPT-6 Luna for clear, repeatable work",
        "provider": "codex",
        "cli_model": "gpt-6-luna",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "6 Terra",
        "label": "6 Terra",
        "description": "Codex GPT-6 Terra everyday all-rounder",
        "provider": "codex",
        "cli_model": "gpt-6-terra",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High", "Ultra"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "5.6 Sol",
        "label": "5.6 Sol",
        "description": "Codex for complex, open-ended work",
        "provider": "codex",
        "cli_model": "gpt-5.6-sol",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High", "Ultra"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "5.6 Terra",
        "label": "5.6 Terra",
        "description": "Codex everyday all-rounder",
        "provider": "codex",
        "cli_model": "gpt-5.6-terra",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High", "Ultra"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "5.6 Luna",
        "label": "5.6 Luna",
        "description": "Codex for clear, repeatable work",
        "provider": "codex",
        "cli_model": "gpt-5.6-luna",
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": ["Light", "Medium", "High", "Extra High"],
            "speed": ["Standard", "Fast"],
            "thinking": False,
            "thinking_required": False,
        },
    },
]

KNOWN_AGY_MODELS: list[dict[str, Any]] = [
    {
        "id": "Gemini 3.8 Flash (High)",
        "label": "Gemini 3.8 Flash (High)",
        "description": "Fastest response, ideal for coding tasks",
        "provider": "agy",
        "cli_model": "gemini-3.8-flash-high",
        "badge": "Flash",
        "usage_bucket": "gemini",
        "enabled": True,
        "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
    },
    {
        "id": "Gemini 3.8 Flash (Medium)",
        "label": "Gemini 3.8 Flash (Medium)",
        "description": "Balanced speed and performance",
        "provider": "agy",
        "cli_model": "gemini-3.8-flash-medium",
        "badge": "Flash",
        "usage_bucket": "gemini",
        "enabled": True,
        "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
    },
    {
        "id": "Gemini 3.8 Flash (Low)",
        "label": "Gemini 3.8 Flash (Low)",
        "description": "Fast, low resource usage",
        "provider": "agy",
        "cli_model": "gemini-3.8-flash-low",
        "badge": "Flash",
        "usage_bucket": "gemini",
        "enabled": True,
        "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
    },
    {
        "id": "Gemini 3.7 Flash (High)",
        "label": "Gemini 3.7 Flash (High)",
        "description": "Fastest response, ideal for coding tasks",
        "provider": "agy",
        "cli_model": "gemini-3.7-flash-high",
        "badge": "Flash",
        "usage_bucket": "gemini",
        "enabled": True,
        "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
    },
    {
        "id": "Gemini 3.1 Pro (High)",
        "label": "Gemini 3.1 Pro (High)",
        "description": "High intelligence, ideal for complex problem solving",
        "provider": "agy",
        "cli_model": "gemini-3.1-pro-high",
        "badge": "Pro",
        "usage_bucket": "gemini",
        "enabled": True,
        "capabilities": {"effort": [], "speed": [], "thinking": False, "thinking_required": False},
    },
]

KNOWN_CLAUDE_MODELS: list[dict[str, Any]] = [
    {
        "id": "Fable 5",
        "label": "Fable 5",
        "description": "Anthropic Fable 5 next-generation agent model",
        "provider": "claude",
        "cli_model": "fable",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Extra", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Opus 5",
        "label": "Opus 5",
        "description": "Anthropic Opus 5 premier reasoning and architectural model",
        "provider": "claude",
        "cli_model": "opus",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Extra", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Sonnet 5",
        "label": "Sonnet 5",
        "description": "Anthropic Sonnet 5 balanced performance and speed",
        "provider": "claude",
        "cli_model": "sonnet",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Extra", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Haiku 4.5",
        "label": "Haiku 4.5",
        "description": "Anthropic Haiku 4.5 lightning fast execution",
        "provider": "claude",
        "cli_model": "haiku",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": False,
            "thinking_required": False,
        },
    },
    {
        "id": "Opus 4.8",
        "label": "Opus 4.8",
        "description": "Anthropic Opus 4.8 high-tier reasoning",
        "provider": "claude",
        "cli_model": "claude-opus-4-8",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Extra", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Opus 4.7",
        "label": "Opus 4.7",
        "description": "Anthropic Opus 4.7 advanced coding intelligence",
        "provider": "claude",
        "cli_model": "claude-opus-4-7",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Extra", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Sonnet 4.6",
        "label": "Sonnet 4.6",
        "description": "Anthropic Sonnet 4.6 high efficiency agent",
        "provider": "claude",
        "cli_model": "claude-sonnet-4-6",
        "badge": "Claude",
        "usage_bucket": "claude",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High", "Max"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

KNOWN_GROK_MODELS: list[dict[str, Any]] = [
    {
        "id": "Grok 4.6",
        "label": "Grok 4.6",
        "description": "xAI Grok 4.6 frontier agent model",
        "provider": "xai",
        "cli_model": "grok-4.6",
        "badge": "Grok",
        "usage_bucket": "xai",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Grok 4.5",
        "label": "Grok 4.5",
        "description": "xAI Grok 4.5 high capability model",
        "provider": "xai",
        "cli_model": "grok-4.5",
        "badge": "Grok",
        "usage_bucket": "xai",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Grok 4.20 Reasoning",
        "label": "Grok 4.20 Reasoning",
        "description": "xAI Grok 4.20 deep reasoning model",
        "provider": "xai",
        "cli_model": "grok-4.20",
        "badge": "Grok",
        "usage_bucket": "xai",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Grok Build 0.1",
        "label": "Grok Build 0.1",
        "description": "xAI Grok developer build preview",
        "provider": "xai",
        "cli_model": "grok-build-0.1",
        "badge": "Grok",
        "usage_bucket": "xai",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

KNOWN_KIMI_MODELS: list[dict[str, Any]] = [
    {
        "id": "Kimi K3",
        "label": "Kimi K3",
        "description": "Moonshot Kimi K3 reasoning model for long-context coding",
        "provider": "kimi",
        "cli_model": "kimi-for-coding/k3",
        "badge": "Kimi",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Kimi K2.5",
        "label": "Kimi K2.5",
        "description": "Moonshot Kimi K2.5 fast coding model",
        "provider": "kimi",
        "cli_model": "kimi-for-coding/k2.5",
        "badge": "Kimi",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

KNOWN_MUSE_MODELS: list[dict[str, Any]] = [
    {
        "id": "Muse Spark 1.2",
        "label": "Muse Spark 1.2",
        "description": "Meta Muse Spark 1.2 interactive coding agent",
        "provider": "muse",
        "cli_model": "muse-spark-1.2",
        "badge": "Muse",
        "usage_bucket": "muse",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "Muse Spark 1.3",
        "label": "Muse Spark 1.3",
        "description": "Meta Muse Spark 1.3 enhanced speed and precision",
        "provider": "muse",
        "cli_model": "muse-spark-1.3",
        "badge": "Muse",
        "usage_bucket": "muse",
        "enabled": True,
        "capabilities": {
            "effort": ["Low", "Medium", "High"],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

KNOWN_DEEPSEEK_MODELS: list[dict[str, Any]] = [
    {
        "id": "DeepSeek Pro 0813",
        "label": "DeepSeek Pro 0813",
        "description": "DeepSeek Pro flagship coding model",
        "provider": "deepseek",
        "cli_model": "deepseek-pro-0813",
        "badge": "DeepSeek",
        "usage_bucket": "deepseek",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "DeepSeek V4",
        "label": "DeepSeek V4",
        "description": "DeepSeek V4 next-generation model",
        "provider": "deepseek",
        "cli_model": "deepseek-v4",
        "badge": "DeepSeek",
        "usage_bucket": "deepseek",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "DeepSeek R1",
        "label": "DeepSeek R1",
        "description": "DeepSeek R1 reasoning architecture",
        "provider": "deepseek",
        "cli_model": "deepseek-reasoner",
        "badge": "DeepSeek",
        "usage_bucket": "deepseek",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "DeepSeek V3",
        "label": "DeepSeek V3",
        "description": "DeepSeek V3 multi-turn conversational agent",
        "provider": "deepseek",
        "cli_model": "deepseek-chat",
        "badge": "DeepSeek",
        "usage_bucket": "deepseek",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

KNOWN_ZAI_MODELS: list[dict[str, Any]] = [
    {
        "id": "GLM 5.2",
        "label": "GLM 5.2",
        "description": "Z.ai GLM 5.2 coding and reasoning agent",
        "provider": "zai",
        "cli_model": "zai-coding-plan/glm-5.2",
        "badge": "GLM",
        "usage_bucket": "zai",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "GLM 5 Turbo",
        "label": "GLM 5 Turbo",
        "description": "Z.ai GLM 5 Turbo high-speed model",
        "provider": "zai",
        "cli_model": "zai-coding-plan/glm-5-turbo",
        "badge": "GLM",
        "usage_bucket": "zai",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "GLM 4.7",
        "label": "GLM 4.7",
        "description": "Z.ai GLM 4.7 balanced code generation",
        "provider": "zai",
        "cli_model": "zai-coding-plan/glm-4.7",
        "badge": "GLM",
        "usage_bucket": "zai",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
    {
        "id": "GLM 4.5 Air",
        "label": "GLM 4.5 Air",
        "description": "Z.ai GLM 4.5 Air lightweight agent",
        "provider": "zai",
        "cli_model": "zai-coding-plan/glm-4.5-air",
        "badge": "GLM",
        "usage_bucket": "zai",
        "enabled": True,
        "capabilities": {
            "effort": [],
            "speed": [],
            "thinking": True,
            "thinking_required": True,
        },
    },
]

EFFORT_MAP = {
    "low": "Light",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
    "ultra": "Ultra",
    "max": "Ultra",
}


# ---------------------------------------------------------------------------
# Codex Parser & Discovery
# ---------------------------------------------------------------------------

def normalize_codex_label(slug: str, display_name: Optional[str] = None) -> str:
    """Format a clean, concise model ID/label from a Codex slug or display name."""
    raw = (display_name or "").strip()
    if raw.lower().startswith("gpt-"):
        cleaned = raw[4:].strip()
    elif raw.lower().startswith("gpt "):
        cleaned = raw[4:].strip()
    else:
        cleaned = raw

    cleaned = cleaned.replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        s = slug.strip()
        if s.lower().startswith("gpt-"):
            s = s[4:]
        cleaned = s.replace("-", " ").title()

    return cleaned


def parse_codex_cache_entry(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert an entry from ~/.codex/models_cache.json into a KookAI model catalog item."""
    if not isinstance(entry, dict):
        return None

    visibility = str(entry.get("visibility", "")).lower()
    if visibility == "hide":
        return None

    slug = str(entry.get("slug", "")).strip()
    if not slug or not slug.startswith("gpt-"):
        return None

    display_name = str(entry.get("display_name", "")).strip()
    label = normalize_codex_label(slug, display_name)
    if not label:
        return None

    effort_levels = []
    for r in entry.get("supported_reasoning_levels", []):
        if isinstance(r, dict):
            eff = str(r.get("effort", "")).lower()
            mapped = EFFORT_MAP.get(eff)
            if mapped and mapped not in effort_levels:
                effort_levels.append(mapped)

    if not effort_levels:
        effort_levels = ["Light", "Medium", "High", "Extra High"]

    speed_tiers = ["Standard"]
    additional_tiers = [str(t).lower() for t in entry.get("additional_speed_tiers", [])]
    service_tiers = [
        str(t.get("id", "")).lower()
        for t in entry.get("service_tiers", [])
        if isinstance(t, dict)
    ]
    if "fast" in additional_tiers or "priority" in service_tiers or "fast" in service_tiers:
        speed_tiers.append("Fast")

    description = str(entry.get("description", "")).strip()
    if not description:
        description = f"Codex GPT {label}"

    return {
        "id": label,
        "label": label,
        "description": description[:240],
        "provider": "codex",
        "cli_model": slug,
        "badge": "Codex",
        "usage_bucket": "gpt",
        "enabled": True,
        "capabilities": {
            "effort": effort_levels,
            "speed": speed_tiers,
            "thinking": False,
            "thinking_required": False,
        },
    }


def discover_codex_models(cache_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover Codex models from local cache (~/.codex/models_cache.json) and seed registry."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_CODEX_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    target_path = cache_path or os.path.expanduser("~/.codex/models_cache.json")
    if os.path.isfile(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                models = data.get("models", [])
                for entry in models:
                    item = parse_codex_cache_entry(entry)
                    if item:
                        discovered[item["cli_model"]] = item
        except Exception as exc:
            LOGGER.debug("Could not read Codex models_cache.json: %s", exc)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# AGY / Gemini Parser & Discovery
# ---------------------------------------------------------------------------

def parse_agy_models_output(output: str) -> list[dict[str, Any]]:
    """Parse output from `agy models` CLI command into model catalog items."""
    results: list[dict[str, Any]] = []
    if not output:
        return results

    for line in output.splitlines():
        line = line.strip()
        if not line or "Fetching available models" in line:
            continue

        slug = ""
        name = ""
        if "\t" in line:
            parts = line.split("\t", 1)
            slug = parts[0].strip()
            name = parts[1].strip()
        else:
            match = re.match(r"^([a-zA-Z0-9\.\-_]+)\s{2,}(.+)$", line)
            if match:
                slug = match.group(1).strip()
                name = match.group(2).strip()

        if not slug or not name:
            continue

        slug_lower = slug.lower()
        name_lower = name.lower()

        # Route usage bucket
        if "gemini" in slug_lower or "gemini" in name_lower:
            usage_bucket = "gemini"
        elif "claude" in slug_lower or "claude" in name_lower:
            usage_bucket = "claude"
        elif "gpt" in slug_lower or "oss" in slug_lower:
            usage_bucket = "gpt"
        else:
            usage_bucket = "gemini"

        # Badge
        if "flash" in name_lower:
            badge = "Flash"
        elif "pro" in name_lower:
            badge = "Pro"
        elif "thinking" in name_lower:
            badge = "Thinking"
        else:
            badge = "Gemini"

        results.append({
            "id": name,
            "label": name,
            "description": f"Antigravity {name} model",
            "provider": "agy",
            "cli_model": slug,
            "badge": badge,
            "usage_bucket": usage_bucket,
            "enabled": True,
            "capabilities": {
                "effort": [],
                "speed": [],
                "thinking": False,
                "thinking_required": False,
            },
        })

    return results


def discover_agy_models(cli_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover AGY / Gemini models via `agy models` CLI command and seed registry."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_AGY_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    resolved_path = cli_path or resolve_cli_executable("agy") or shutil.which("agy")
    if resolved_path and os.path.isfile(resolved_path) and os.access(resolved_path, os.X_OK):
        try:
            cmd = [resolved_path, "models"]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                parsed = parse_agy_models_output(proc.stdout)
                for item in parsed:
                    discovered[item["cli_model"]] = item
        except Exception as exc:
            LOGGER.debug("Could not run agy models: %s", exc)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Claude Discovery
# ---------------------------------------------------------------------------

def discover_claude_models(cli_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover Claude Code models via seed registry and environment."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_CLAUDE_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Grok / xAI Discovery
# ---------------------------------------------------------------------------

def parse_grok_models_output(output: str) -> list[dict[str, Any]]:
    """Parse models from `grok models` CLI command output."""
    results: list[dict[str, Any]] = []
    if not output:
        return results

    seen_slugs = set()
    for line in output.splitlines():
        match = re.search(r"\b(grok-[a-zA-Z0-9\.\-_]+)\b", line)
        if not match:
            continue
        slug = match.group(1).strip()
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        # Normalize label: e.g. grok-4.5 -> Grok 4.5, grok-4.20 -> Grok 4.20
        clean_part = slug[5:].replace("-", " ").strip()
        label = f"Grok {clean_part.title()}"

        results.append({
            "id": label,
            "label": label,
            "description": f"xAI {label} agent model",
            "provider": "xai",
            "cli_model": slug,
            "badge": "Grok",
            "usage_bucket": "xai",
            "enabled": True,
            "capabilities": {
                "effort": ["Low", "Medium", "High"],
                "speed": [],
                "thinking": True,
                "thinking_required": True,
            },
        })

    return results


def discover_grok_models(cli_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover xAI Grok models via `grok models` CLI command and seed registry."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_GROK_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    resolved_path = cli_path or resolve_cli_executable("grok") or shutil.which("grok")
    if resolved_path and os.path.isfile(resolved_path) and os.access(resolved_path, os.X_OK):
        try:
            cmd = [resolved_path, "models"]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                parsed = parse_grok_models_output(proc.stdout)
                for item in parsed:
                    discovered[item["cli_model"]] = item
        except Exception as exc:
            LOGGER.debug("Could not run grok models: %s", exc)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Kimi Discovery
# ---------------------------------------------------------------------------

def discover_kimi_models(config_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover Moonshot Kimi Code models from local configuration and seeds."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_KIMI_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Muse Discovery
# ---------------------------------------------------------------------------

def discover_muse_models(cli_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover Meta Muse models from CLI environment and seeds."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_MUSE_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# DeepSeek Discovery
# ---------------------------------------------------------------------------

def discover_deepseek_models() -> list[dict[str, Any]]:
    """Discover DeepSeek models from environment and seeds."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_DEEPSEEK_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Z.ai GLM Discovery
# ---------------------------------------------------------------------------

def discover_zai_models(cli_path: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover Z.ai GLM models from OpenCode CLI environment and seeds."""
    discovered: dict[str, dict[str, Any]] = {}

    for model in KNOWN_ZAI_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    return list(discovered.values())


# ---------------------------------------------------------------------------
# Aggregator & Synchronizer
# ---------------------------------------------------------------------------

def discover_all_models() -> list[dict[str, Any]]:
    """Discover models across all supported KookAI providers."""
    candidates: list[dict[str, Any]] = []

    discovery_handlers = [
        ("Codex", discover_codex_models),
        ("AGY", discover_agy_models),
        ("Claude", discover_claude_models),
        ("Grok", discover_grok_models),
        ("Kimi", discover_kimi_models),
        ("Muse", discover_muse_models),
        ("DeepSeek", discover_deepseek_models),
        ("Z.ai", discover_zai_models),
    ]

    for name, handler in discovery_handlers:
        try:
            items = handler()
            candidates.extend(items)
        except Exception as exc:
            LOGGER.debug("Error discovering %s models: %s", name, exc)

    return candidates


def configure_all_backends(models: list[dict[str, Any]]) -> None:
    """Refresh runtime model mappings across all provider backends."""
    try:
        import codex_backend
        codex_backend.configure_codex_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring codex catalog: %s", exc)

    try:
        import claude_backend
        claude_backend.configure_claude_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring claude catalog: %s", exc)

    try:
        import kimi_backend
        kimi_backend.configure_kimi_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring kimi catalog: %s", exc)

    try:
        import grok_backend
        grok_backend.configure_grok_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring grok catalog: %s", exc)

    try:
        import muse_backend
        muse_backend.configure_muse_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring muse catalog: %s", exc)

    try:
        import deepseek_backend
        deepseek_backend.configure_deepseek_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring deepseek catalog: %s", exc)

    try:
        import zai_backend
        zai_backend.configure_zai_catalog(models)
    except Exception as exc:
        LOGGER.debug("Error configuring zai catalog: %s", exc)


def sync_model_catalog(
    catalog_path: str,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    """
    Sync model catalog with newly discovered models across all providers.
    Returns (catalog, was_updated).
    """
    global _last_auto_sync_time

    with _sync_lock:
        now = time.time()
        if not force and now - _last_auto_sync_time < 60:
            catalog = load_model_catalog(catalog_path)
            return catalog, False

        _last_auto_sync_time = now

        catalog = load_model_catalog(catalog_path)
        existing_models = catalog.get("models", [])
        existing_cli_models = {m.get("cli_model") for m in existing_models if m.get("cli_model")}
        existing_ids = {m.get("id") for m in existing_models if m.get("id")}
        existing_labels = {m.get("label") for m in existing_models if m.get("label")}

        all_candidates = discover_all_models()

        new_models_added = []
        for candidate in all_candidates:
            cli_m = candidate.get("cli_model")
            mid = candidate.get("id")
            mlabel = candidate.get("label")
            # If cli_model, id, or label is already present, skip to avoid alias clash
            if cli_m in existing_cli_models or mid in existing_ids or mlabel in existing_labels:
                continue

            existing_cli_models.add(cli_m)
            existing_ids.add(mid)
            existing_labels.add(mlabel)
            existing_models.append(candidate)
            new_models_added.append(candidate)

        if not new_models_added:
            return catalog, False

        # Generate a new catalog_version to notify clients
        base_version = str(catalog.get("catalog_version", "1.0")).split(".auto.")[0]
        catalog["catalog_version"] = f"{base_version}.auto.{int(now)}"
        catalog["models"] = existing_models

        # Validate before saving
        validate_model_catalog(catalog)

        # Save to primary catalog path
        save_model_catalog(catalog_path, catalog)
        LOGGER.info(
            "Auto-synced %d new models into catalog %s across providers: %s",
            len(new_models_added),
            catalog_path,
            [m["id"] for m in new_models_added],
        )

        # Refresh provider configurations across all backends
        configure_all_backends(catalog["models"])

        return catalog, True
