"""Multi-Tenant Harness Profile Manager for KookAI.

Enables multiple user accounts / profiles per CLI harness (e.g. Work vs Personal
Codex/Claude accounts) with isolated filesystem configurations, avoiding credential
collisions on the server.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

SUPPORTED_CLIS: set[str] = {
    "codex",
    "claude",
    "agy",
    "kimi",
    "grok",
    "muse",
    "deepseek",
    "zai",
}

DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".gemini", "kookai")
PROFILES_FILE_NAME = "harness_profiles.json"
PROFILES_SUBDIR = "profiles"

_lock = threading.Lock()


def _resolve_data_dir(data_dir: Optional[str] = None) -> str:
    resolved = data_dir or os.environ.get("KOOKAI_DATA_DIR", DEFAULT_DATA_DIR)
    os.makedirs(resolved, exist_ok=True)
    return os.path.abspath(resolved)


def _profiles_json_path(data_dir: Optional[str] = None) -> str:
    return os.path.join(_resolve_data_dir(data_dir), PROFILES_FILE_NAME)


def _profiles_base_dir(data_dir: Optional[str] = None) -> str:
    base = os.path.join(_resolve_data_dir(data_dir), PROFILES_SUBDIR)
    os.makedirs(base, exist_ok=True)
    return os.path.abspath(base)


def sanitize_profile_id(profile_id: str) -> str:
    raw = profile_id.strip()
    if not raw or ".." in raw or "/" in raw or "\\" in raw:
        raise ValueError(f"Invalid profile ID: {profile_id}")
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    if not cleaned or all(c == "_" for c in cleaned):
        raise ValueError(f"Invalid profile ID: {profile_id}")
    return cleaned[:64]


def _load_manifest_unlocked(data_dir: Optional[str] = None) -> dict[str, Any]:
    path = _profiles_json_path(data_dir)
    if not os.path.isfile(path):
        return {"profiles": [], "default_profiles": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("profiles", [])
                data.setdefault("default_profiles", {})
                return data
    except Exception as exc:
        LOGGER.error("Could not load profiles manifest from %s: %s", path, exc)
    return {"profiles": [], "default_profiles": {}}


def _save_manifest_unlocked(manifest: dict[str, Any], data_dir: Optional[str] = None) -> None:
    path = _profiles_json_path(data_dir)
    tmp_path = f"{path}.tmp.{uuid.uuid4().hex[:8]}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as exc:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        LOGGER.error("Failed to save profiles manifest to %s: %s", path, exc)
        raise


def list_profiles(
    cli_id: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all configured harness profiles, optionally filtered by CLI."""
    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        profiles = list(manifest.get("profiles", []))
        defaults = manifest.get("default_profiles", {})

    for p in profiles:
        p["is_default"] = defaults.get(p.get("cli_id")) == p.get("id")

    if cli_id:
        normalized = cli_id.lower().strip()
        profiles = [p for p in profiles if p.get("cli_id") == normalized]
    return profiles


def get_profile(
    profile_id: str,
    data_dir: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Get a specific profile by ID."""
    clean_id = sanitize_profile_id(profile_id)
    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        defaults = manifest.get("default_profiles", {})
        for p in manifest.get("profiles", []):
            if p.get("id") == clean_id:
                p_copy = dict(p)
                p_copy["is_default"] = defaults.get(p_copy.get("cli_id")) == clean_id
                return p_copy
    return None


def create_profile(
    cli_id: str,
    label: str,
    profile_id: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new isolated harness profile slot."""
    normalized_cli = cli_id.lower().strip()
    if normalized_cli not in SUPPORTED_CLIS:
        raise ValueError(f"Unsupported CLI ID: {cli_id}. Supported: {sorted(SUPPORTED_CLIS)}")

    clean_label = label.strip()
    if not clean_label:
        raise ValueError("Profile label cannot be empty")

    if profile_id:
        clean_id = sanitize_profile_id(profile_id)
    else:
        # Generate slug from label + short uuid
        prefix = re.sub(r"[^a-zA-Z0-9]", "_", clean_label.lower())[:20].strip("_") or normalized_cli
        clean_id = f"prof_{prefix}_{uuid.uuid4().hex[:6]}"

    base_dir = _profiles_base_dir(data_dir)
    profile_root = os.path.join(base_dir, clean_id)
    
    # Provider-specific configuration directory inside profile root
    if normalized_cli == "codex":
        config_dir = os.path.join(profile_root, ".codex")
    elif normalized_cli == "claude":
        config_dir = os.path.join(profile_root, ".claude")
    else:
        config_dir = profile_root

    os.makedirs(config_dir, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "id": clean_id,
        "cli_id": normalized_cli,
        "label": clean_label,
        "profile_root": profile_root,
        "config_dir": config_dir,
        "status": "ready",
        "created_at": now_iso,
        "last_used_at": None,
    }

    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        # Check duplicate ID
        for existing in manifest.get("profiles", []):
            if existing.get("id") == clean_id:
                raise ValueError(f"Profile ID '{clean_id}' already exists")

        manifest["profiles"].append(record)
        # If this is the first profile for this CLI, set it as default
        if normalized_cli not in manifest.setdefault("default_profiles", {}):
            manifest["default_profiles"][normalized_cli] = clean_id
            record["is_default"] = True
        else:
            record["is_default"] = (manifest["default_profiles"].get(normalized_cli) == clean_id)

        _save_manifest_unlocked(manifest, data_dir)

    LOGGER.info("Created harness profile '%s' (%s) for %s", clean_label, clean_id, normalized_cli)
    return record


def delete_profile(
    profile_id: str,
    delete_files: bool = True,
    data_dir: Optional[str] = None,
) -> bool:
    """Delete a profile and optionally purge its directory."""
    clean_id = sanitize_profile_id(profile_id)
    removed_record: Optional[dict[str, Any]] = None

    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        initial_len = len(manifest.get("profiles", []))
        kept_profiles = []
        for p in manifest.get("profiles", []):
            if p.get("id") == clean_id:
                removed_record = p
            else:
                kept_profiles.append(p)

        if len(kept_profiles) == initial_len or not removed_record:
            return False

        manifest["profiles"] = kept_profiles
        cli_id = removed_record.get("cli_id")
        # Update default if removed profile was the default
        if manifest.get("default_profiles", {}).get(cli_id) == clean_id:
            next_default = next(
                (p["id"] for p in kept_profiles if p.get("cli_id") == cli_id),
                None,
            )
            if next_default:
                manifest["default_profiles"][cli_id] = next_default
            else:
                manifest["default_profiles"].pop(cli_id, None)

        _save_manifest_unlocked(manifest, data_dir)

    if delete_files and removed_record:
        root_dir = removed_record.get("profile_root")
        if root_dir and os.path.isdir(root_dir):
            base_dir = _profiles_base_dir(data_dir)
            # Ensure root_dir is strictly inside base_dir
            real_root = os.path.realpath(root_dir)
            real_base = os.path.realpath(base_dir)
            if real_root.startswith(real_base) and real_root != real_base:
                shutil.rmtree(real_root, ignore_errors=True)

    LOGGER.info("Deleted harness profile '%s'", clean_id)
    return True


def set_default_profile(
    cli_id: str,
    profile_id: str,
    data_dir: Optional[str] = None,
) -> bool:
    """Designate a profile as the default for its CLI."""
    normalized_cli = cli_id.lower().strip()
    clean_id = sanitize_profile_id(profile_id)

    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        target = next(
            (p for p in manifest.get("profiles", []) if p.get("id") == clean_id and p.get("cli_id") == normalized_cli),
            None,
        )
        if not target:
            return False

        manifest.setdefault("default_profiles", {})[normalized_cli] = clean_id
        _save_manifest_unlocked(manifest, data_dir)

    return True


def get_default_profile(
    cli_id: str,
    data_dir: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve default profile for the given CLI."""
    normalized_cli = cli_id.lower().strip()
    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        default_id = manifest.get("default_profiles", {}).get(normalized_cli)
        if not default_id:
            return None
        for p in manifest.get("profiles", []):
            if p.get("id") == default_id:
                p_copy = dict(p)
                p_copy["is_default"] = True
                return p_copy
    return None


def update_profile_status(
    profile_id: str,
    status: str,
    data_dir: Optional[str] = None,
) -> bool:
    """Update status of a profile (e.g. 'ready', 'unauthenticated', 'error')."""
    clean_id = sanitize_profile_id(profile_id)
    with _lock:
        manifest = _load_manifest_unlocked(data_dir)
        target = next((p for p in manifest.get("profiles", []) if p.get("id") == clean_id), None)
        if not target:
            return False
        target["status"] = status
        target["last_used_at"] = datetime.now(timezone.utc).isoformat()
        _save_manifest_unlocked(manifest, data_dir)
    return True


def get_profile_scoped_env(
    profile_id: str,
    base_env: Optional[dict[str, str]] = None,
    data_dir: Optional[str] = None,
) -> dict[str, str]:
    """Return environment dictionary with variables scoped to the given profile."""
    profile = get_profile(profile_id, data_dir=data_dir)
    if not profile:
        raise KeyError(f"Profile '{profile_id}' not found")

    env = dict(base_env or os.environ)
    config_dir = os.path.abspath(profile["config_dir"])
    profile_root = os.path.abspath(profile["profile_root"])
    os.makedirs(config_dir, exist_ok=True)

    cli_id = profile["cli_id"]
    if cli_id == "codex":
        env["CODEX_HOME"] = config_dir
    elif cli_id == "claude":
        env["CLAUDE_CONFIG_DIR"] = config_dir
        env["HOME"] = profile_root
    else:
        # For agy, kimi, grok, muse, deepseek, zai: isolate user HOME
        env["HOME"] = profile_root

    # Mark active profile in env for tracking
    env["KOOKAI_ACTIVE_PROFILE_ID"] = profile["id"]
    env["KOOKAI_ACTIVE_PROFILE_CLI"] = cli_id
    return env
