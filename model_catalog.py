"""Versioned model catalog loading, validation, and atomic updates."""

from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any, Optional


SCHEMA_VERSION = 1
PROVIDERS = {"agy", "claude", "codex", "kimi", "xai", "muse", "deepseek"}
USAGE_BUCKETS = {"gemini", "claude", "gpt", "xai", "muse", "deepseek"}
EFFORT_VALUES = {
    "Light",
    "Low",
    "Medium",
    "High",
    "Extra",
    "Extra High",
    "Ultra",
    "Max",
}
SPEED_VALUES = {"Standard", "Fast"}

_cache_lock = threading.Lock()
_cache_path = ""
_cache_mtime_ns = -1
_cache_catalog: Optional[dict[str, Any]] = None


class ModelCatalogError(ValueError):
    """Raised when a model catalog is invalid."""


def _clean_text(value: Any, field: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ModelCatalogError(f"{field} must be a string")
    clean = value.strip()
    if not clean or len(clean) > max_length or any(ord(char) < 32 for char in clean):
        raise ModelCatalogError(
            f"{field} must contain 1-{max_length} printable characters"
        )
    return clean


def _clean_string_list(
    value: Any,
    field: str,
    allowed: set[str],
) -> list[str]:
    if not isinstance(value, list):
        raise ModelCatalogError(f"{field} must be an array")
    clean: list[str] = []
    for item in value:
        if item not in allowed:
            raise ModelCatalogError(f"{field} contains unsupported value: {item}")
        if item not in clean:
            clean.append(item)
    return clean


def validate_model_catalog(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ModelCatalogError("Catalog must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ModelCatalogError(
            f"schema_version must be {SCHEMA_VERSION}"
        )

    catalog_version = _clean_text(
        payload.get("catalog_version"),
        "catalog_version",
        64,
    )
    default_model = _clean_text(
        payload.get("default_model"),
        "default_model",
        120,
    )
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or not 1 <= len(raw_models) <= 100:
        raise ModelCatalogError("models must contain 1-100 entries")

    models: list[dict[str, Any]] = []
    model_ids: set[str] = set()
    alias_owners: dict[str, str] = {}
    for index, raw_model in enumerate(raw_models):
        prefix = f"models[{index}]"
        if not isinstance(raw_model, dict):
            raise ModelCatalogError(f"{prefix} must be an object")

        model_id = _clean_text(raw_model.get("id"), f"{prefix}.id", 120)
        if model_id in model_ids:
            raise ModelCatalogError(f"Duplicate model id: {model_id}")
        model_ids.add(model_id)

        provider = _clean_text(
            raw_model.get("provider"),
            f"{prefix}.provider",
            16,
        ).lower()
        if provider not in PROVIDERS:
            raise ModelCatalogError(f"{prefix}.provider is unsupported")

        usage_bucket = _clean_text(
            raw_model.get("usage_bucket"),
            f"{prefix}.usage_bucket",
            16,
        ).lower()
        if usage_bucket not in USAGE_BUCKETS:
            raise ModelCatalogError(f"{prefix}.usage_bucket is unsupported")

        capabilities = raw_model.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ModelCatalogError(f"{prefix}.capabilities must be an object")
        effort = _clean_string_list(
            capabilities.get("effort", []),
            f"{prefix}.capabilities.effort",
            EFFORT_VALUES,
        )
        speed = _clean_string_list(
            capabilities.get("speed", []),
            f"{prefix}.capabilities.speed",
            SPEED_VALUES,
        )
        thinking = capabilities.get("thinking", False)
        thinking_required = capabilities.get("thinking_required", False)
        if not isinstance(thinking, bool) or not isinstance(thinking_required, bool):
            raise ModelCatalogError(
                f"{prefix}.capabilities thinking values must be booleans"
            )
        if thinking_required and not thinking:
            raise ModelCatalogError(
                f"{prefix}.thinking_required requires thinking=true"
            )
        if provider == "agy" and (effort or speed or thinking):
            raise ModelCatalogError(
                f"{prefix} uses agy; interactive capabilities must be empty"
            )
        if provider == "claude" and speed:
            raise ModelCatalogError(
                f"{prefix} uses claude; speed must be empty"
            )
        if provider == "codex" and thinking:
            raise ModelCatalogError(
                f"{prefix} uses codex; thinking must be false"
            )
        if provider == "kimi" and (effort or speed):
            raise ModelCatalogError(
                f"{prefix} uses kimi; effort and speed must be empty"
            )
        if provider == "xai" and speed:
            raise ModelCatalogError(
                f"{prefix} uses xai; speed must be empty"
            )
        if provider == "xai" and effort and not thinking:
            raise ModelCatalogError(
                f"{prefix} uses xai effort; thinking must be true"
            )
        if provider == "muse" and speed:
            raise ModelCatalogError(
                f"{prefix} uses muse; speed must be empty"
            )
        if provider == "muse" and effort and not thinking:
            raise ModelCatalogError(
                f"{prefix} uses muse effort; thinking must be true"
            )

        enabled = raw_model.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ModelCatalogError(f"{prefix}.enabled must be a boolean")

        label = _clean_text(
            raw_model.get("label"),
            f"{prefix}.label",
            120,
        )
        cli_model = _clean_text(
            raw_model.get("cli_model"),
            f"{prefix}.cli_model",
            160,
        )
        for alias in {model_id, label, cli_model}:
            owner = alias_owners.get(alias)
            if owner and owner != model_id:
                raise ModelCatalogError(
                    f"Model alias {alias!r} is shared by {owner!r} and {model_id!r}"
                )
            alias_owners[alias] = model_id

        models.append(
            {
                "id": model_id,
                "label": label,
                "description": _clean_text(
                    raw_model.get("description"),
                    f"{prefix}.description",
                    240,
                ),
                "provider": provider,
                "cli_model": cli_model,
                "badge": _clean_text(
                    raw_model.get("badge"),
                    f"{prefix}.badge",
                    32,
                ),
                "usage_bucket": usage_bucket,
                "enabled": enabled,
                "capabilities": {
                    "effort": effort,
                    "speed": speed,
                    "thinking": thinking,
                    "thinking_required": thinking_required,
                },
            }
        )

    default_entry = next(
        (model for model in models if model["id"] == default_model),
        None,
    )
    if not default_entry or not default_entry["enabled"]:
        raise ModelCatalogError("default_model must reference an enabled model")

    return {
        "schema_version": SCHEMA_VERSION,
        "catalog_version": catalog_version,
        "default_model": default_model,
        "models": models,
    }


def load_model_catalog(path: str) -> dict[str, Any]:
    global _cache_catalog, _cache_mtime_ns, _cache_path

    normalized_path = os.path.abspath(path)
    try:
        mtime_ns = os.stat(normalized_path).st_mtime_ns
    except OSError as exc:
        raise ModelCatalogError(f"Could not read model catalog: {exc}") from exc

    with _cache_lock:
        if (
            _cache_catalog is not None
            and _cache_path == normalized_path
            and _cache_mtime_ns == mtime_ns
        ):
            return copy.deepcopy(_cache_catalog)

        try:
            with open(normalized_path, "r", encoding="utf-8") as catalog_file:
                payload = json.load(catalog_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelCatalogError(f"Could not parse model catalog: {exc}") from exc

        catalog = validate_model_catalog(payload)
        _cache_path = normalized_path
        _cache_mtime_ns = mtime_ns
        _cache_catalog = catalog
        return copy.deepcopy(catalog)


def save_model_catalog(path: str, payload: Any) -> dict[str, Any]:
    global _cache_catalog, _cache_mtime_ns, _cache_path

    catalog = validate_model_catalog(payload)
    normalized_path = os.path.abspath(path)
    temp_path = f"{normalized_path}.tmp"
    os.makedirs(os.path.dirname(normalized_path), exist_ok=True)
    try:
        with open(temp_path, "w", encoding="utf-8") as catalog_file:
            json.dump(catalog, catalog_file, ensure_ascii=False, indent=2)
            catalog_file.write("\n")
            catalog_file.flush()
            os.fsync(catalog_file.fileno())
        os.replace(temp_path, normalized_path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass

    with _cache_lock:
        _cache_path = normalized_path
        _cache_mtime_ns = os.stat(normalized_path).st_mtime_ns
        _cache_catalog = catalog
    return copy.deepcopy(catalog)


def resolve_catalog_model(
    catalog: dict[str, Any],
    model_reference: str,
    *,
    enabled_only: bool = True,
) -> Optional[dict[str, Any]]:
    reference = (model_reference or "").strip()
    for model in catalog.get("models", []):
        if enabled_only and not model.get("enabled"):
            continue
        if reference in {model["id"], model["label"], model["cli_model"]}:
            return copy.deepcopy(model)
    return None


def public_model_catalog(
    catalog: dict[str, Any],
    *,
    include_disabled: bool = False,
) -> dict[str, Any]:
    result = copy.deepcopy(catalog)
    if not include_disabled:
        result["models"] = [
            model for model in result["models"] if model.get("enabled")
        ]
    return result
