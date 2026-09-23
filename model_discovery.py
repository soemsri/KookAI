"""Automated model discovery and catalog synchronization for KookAI providers."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from typing import Any, Optional

from model_catalog import (
    ModelCatalogError,
    load_model_catalog,
    save_model_catalog,
    validate_model_catalog,
)
import codex_backend

LOGGER = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_last_auto_sync_time: float = 0.0

# Known seed models for Codex to ensure new flagship models are readily available
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

EFFORT_MAP = {
    "low": "Light",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra High",
    "ultra": "Ultra",
    "max": "Ultra",
}


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

    # Supported efforts
    effort_levels = []
    for r in entry.get("supported_reasoning_levels", []):
        if isinstance(r, dict):
            eff = str(r.get("effort", "")).lower()
            mapped = EFFORT_MAP.get(eff)
            if mapped and mapped not in effort_levels:
                effort_levels.append(mapped)

    if not effort_levels:
        effort_levels = ["Light", "Medium", "High", "Extra High"]

    # Speed tiers
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

    # Seed with known models first
    for model in KNOWN_CODEX_MODELS:
        discovered[model["cli_model"]] = copy.deepcopy(model)

    # Check ~/.codex/models_cache.json
    target_path = cache_path or os.path.expanduser("~/.codex/models_cache.json")
    if os.path.isfile(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                models = data.get("models", [])
                for entry in models:
                    item = parse_codex_cache_entry(entry)
                    if item:
                        cli_model = item["cli_model"]
                        # Prefer parsed entry if available, or update capabilities
                        discovered[cli_model] = item
        except Exception as exc:
            LOGGER.debug("Could not read Codex models_cache.json: %s", exc)

    return list(discovered.values())


def sync_model_catalog(
    catalog_path: str,
    *,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    """
    Sync model catalog with newly discovered models from providers.
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

        discovered_codex = discover_codex_models()

        new_models_added = []
        for candidate in discovered_codex:
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
            "Auto-synced %d new models into catalog %s: %s",
            len(new_models_added),
            catalog_path,
            [m["id"] for m in new_models_added],
        )

        # Refresh provider configurations
        codex_backend.configure_codex_catalog(catalog["models"])

        return catalog, True
