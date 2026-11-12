"""Live per-provider account usage for the KookAI usage panel.

Every fetcher in this module reads the credentials that the provider's own CLI
stored for the signed-in account on this host (or in a KookAI harness profile)
and asks that provider's usage/quota API for the current numbers.

Nothing here is estimated from local transcripts or token counts. A provider
that is not signed in, whose token expired, or that exposes no account usage
API says so through ``status``/``description`` instead of reporting a number.

Each fetcher returns the same shape (see :func:`build_provider`)::

    {
      "id": "claude", "name": "Claude Code", "cli": "claude",
      "status": "ok" | "stale" | "not_logged_in" | "token_expired" |
                "auth_rejected" | "unsupported" | "unavailable",
      "available": bool,            # True only when real windows/balances exist
      "source": "anthropic_oauth_usage",
      "account": {"email": ..., "plan": ..., "label": ...} | None,
      "windows": [{"id", "kind", "label", "usedPercent", "remainingPercent",
                   "resetTime", "description", ...}],
      "weekly": window | None, "hourly": window | None,
      "balances": [{"currency", "total", "granted", "toppedUp"}],
      "usedPercent": float | None, "remainingPercent": float | None,
      "resetTime": str | None,
      "description": str | None, "signInHint": str | None,
      "observedAt": str | None, "fetchedAt": str,
    }
"""
from __future__ import annotations

import datetime
import glob
import json
import logging
import math
import os
import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - very old interpreters
    tomllib = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 4.0
USER_AGENT = "KookAI/1.0 (usage-panel)"

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_NOT_LOGGED_IN = "not_logged_in"
STATUS_TOKEN_EXPIRED = "token_expired"
STATUS_AUTH_REJECTED = "auth_rejected"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNAVAILABLE = "unavailable"
SIGN_IN_STATUSES = {STATUS_NOT_LOGGED_IN, STATUS_TOKEN_EXPIRED, STATUS_AUTH_REJECTED}

PROVIDER_ORDER = [
    "claude",
    "codex",
    "antigravity",
    "antigravity_claude",
    "kimi",
    "grok",
    "muse",
    "deepseek",
    "zai",
]
PROVIDER_NAMES = {
    "claude": "Claude Code",
    "codex": "Codex (ChatGPT)",
    "antigravity": "Gemini (Antigravity)",
    "antigravity_claude": "Claude & GPT via Antigravity",
    "kimi": "Kimi Code",
    "grok": "Grok Build (xAI)",
    "muse": "Muse Code (Meta)",
    "deepseek": "DeepSeek",
    "zai": "GLM (Z.ai Coding Plan)",
}
# provider id -> cli_manager CLI id (what "Connect" in Settings launches)
PROVIDER_CLI = {
    "claude": "claude",
    "codex": "codex",
    "antigravity": "agy",
    "antigravity_claude": "agy",
    "kimi": "kimi",
    "grok": "grok",
    "muse": "muse",
    "deepseek": "deepseek",
    "zai": "zai",
}
SIGN_IN_HINTS = {
    "claude": "Sign in on the KookAI host with `claude auth login` (or Settings → Connections → Connect).",
    "codex": "Sign in on the KookAI host with `codex login` (or Settings → Connections → Connect).",
    "antigravity": "Sign in on the KookAI host by launching `agy` once (or Settings → Connections → Connect).",
    "antigravity_claude": "Sign in on the KookAI host by launching `agy` once (or Settings → Connections → Connect).",
    "kimi": "Sign in on the KookAI host with `kimi login` (or Settings → Connections → Connect).",
    "grok": "Sign in on the KookAI host with `grok login` (or Settings → Connections → Connect).",
    "muse": "Sign in on the KookAI host with `muse login` (or Settings → Connections → Connect).",
    "deepseek": "Save a DeepSeek API key on the KookAI host with `deepcode login` (or Settings → Connections → Connect).",
    "zai": "Run `opencode auth login` on the KookAI host, choose Z.AI Coding Plan and paste your key (or Settings → Connections → Connect).",
}


class ProviderFetchError(Exception):
    """Network-level failure while talking to a provider."""


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _expand_home(home: Optional[str]) -> str:
    if home:
        return os.path.abspath(os.path.expanduser(home))
    return os.path.expanduser("~")


def _read_json_file(path: Optional[str]) -> Any:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        LOGGER.debug("Could not read %s: %s", path, exc)
        return None


def _read_text_file(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return None


def _to_float(value: Any) -> Optional[float]:
    """Parse a number defensively: bools, NaN, inf and junk strings are rejected."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _now_iso(now: Optional[float] = None) -> str:
    return _iso_from_epoch(now if now is not None else time.time()) or ""


def _iso_from_epoch(value: Any) -> Optional[str]:
    number = _to_float(value)
    if number is None or number <= 0:
        return None
    if number > 1e11:  # milliseconds
        number = number / 1000.0
    try:
        return datetime.datetime.fromtimestamp(number, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def _iso_from_any(value: Any) -> Optional[str]:
    """Normalise an ISO string or epoch (s/ms) to ``YYYY-MM-DDTHH:MM:SSZ``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _iso_from_epoch(value)
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _iso_from_epoch(float(text))
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch_from_any(value: Any) -> Optional[float]:
    """Epoch seconds from an ISO string or epoch (s/ms); ``None`` when unknown."""
    if value is None or isinstance(value, bool):
        return None
    number = _to_float(value)
    if number is not None:
        return number / 1000.0 if number > 1e11 else number
    try:
        parsed = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _format_quantity(value: Optional[float]) -> str:
    if value is None:
        return "?"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _mask_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return None
    secret = str(secret)
    return f"…{secret[-4:]}" if len(secret) > 8 else "…"


def make_window(
    window_id: str,
    label: str,
    used_percent: Any,
    *,
    kind: str = "other",
    reset_time: Any = None,
    description: Optional[str] = None,
    **extra: Any,
) -> Optional[dict[str, Any]]:
    """One quota window. ``used_percent`` is 0-100 (values past the cap are kept in ``rawUsedPercent``)."""
    used = _to_float(used_percent)
    if used is None:
        return None
    shown = round(max(0.0, min(100.0, used)), 1)
    window = {
        "id": window_id,
        "kind": kind,
        "label": label,
        "usedPercent": shown,
        "remainingPercent": round(100.0 - shown, 1),
        "rawUsedPercent": round(used, 1),
        "resetTime": _iso_from_any(reset_time),
        "description": description,
    }
    window.update(extra)
    return window


def build_provider(
    provider_id: str,
    status: str,
    source: str,
    *,
    account: Optional[dict[str, Any]] = None,
    windows: Optional[list[Optional[dict[str, Any]]]] = None,
    balances: Optional[list[dict[str, Any]]] = None,
    description: Optional[str] = None,
    sign_in_hint: Optional[str] = None,
    observed_at: Optional[str] = None,
    fetched_at: Optional[str] = None,
    **extra: Any,
) -> dict[str, Any]:
    clean_windows = [w for w in (windows or []) if isinstance(w, dict)]
    clean_balances = [b for b in (balances or []) if isinstance(b, dict)]
    if status in (STATUS_OK, STATUS_STALE) and not clean_windows and not clean_balances:
        status = STATUS_UNAVAILABLE
        description = description or f"{PROVIDER_NAMES.get(provider_id, provider_id)} returned no usage windows."
    hourly = next((w for w in clean_windows if w.get("kind") == "five_hour"), None)
    weekly = next((w for w in clean_windows if w.get("kind") == "weekly"), None)
    primary = hourly or weekly or (clean_windows[0] if clean_windows else None)
    available = status in (STATUS_OK, STATUS_STALE)
    if sign_in_hint is None and status in SIGN_IN_STATUSES:
        sign_in_hint = SIGN_IN_HINTS.get(provider_id)
    provider = {
        "id": provider_id,
        "name": PROVIDER_NAMES.get(provider_id, provider_id),
        "cli": PROVIDER_CLI.get(provider_id),
        "status": status,
        "available": available,
        "source": source,
        "account": account,
        "windows": clean_windows,
        "weekly": weekly,
        "hourly": hourly,
        "balances": clean_balances,
        "usedPercent": primary.get("usedPercent") if primary else None,
        "remainingPercent": primary.get("remainingPercent") if primary else None,
        "resetTime": primary.get("resetTime") if primary else None,
        "description": description,
        "signInHint": sign_in_hint,
        "observedAt": observed_at,
        "fetchedAt": fetched_at or _now_iso(),
    }
    provider.update(extra)
    return provider


def _http_request(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int, Any, str]:
    """Return ``(status_code, parsed_json_or_None, raw_text)``; raise ProviderFetchError when unreachable."""
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status), _maybe_json(raw), raw
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        return int(exc.code), _maybe_json(raw), raw
    except Exception as exc:  # URLError, socket timeout, SSL, ...
        raise ProviderFetchError(str(exc.reason) if isinstance(exc, urllib.error.URLError) else str(exc)) from exc


def _maybe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


HttpFn = Callable[..., tuple[int, Any, str]]


# ---------------------------------------------------------------------------
# Claude Code — Anthropic OAuth usage API (what `/usage` in Claude Code shows)
# ---------------------------------------------------------------------------

CLAUDE_OAUTH_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLAUDE_OAUTH_PROFILE_URL = "https://api.anthropic.com/api/oauth/profile"
CLAUDE_OAUTH_BETA_HEADER = "oauth-2025-04-20"
CLAUDE_SOURCE = "anthropic_oauth_usage"
_CLAUDE_SCOPED_WINDOW_LABELS = {
    "seven_day_opus": "Weekly Limit (Opus)",
    "seven_day_sonnet": "Weekly Limit (Sonnet)",
    "seven_day_oauth_apps": "Weekly Limit (OAuth apps)",
    "seven_day_cowork": "Weekly Limit (Cowork)",
}


def claude_credential_paths(home: Optional[str] = None, config_dir: Optional[str] = None) -> list[str]:
    paths: list[str] = []
    if config_dir:
        paths.append(os.path.join(os.path.expanduser(config_dir), ".credentials.json"))
    elif home is None and os.environ.get("CLAUDE_CONFIG_DIR"):
        paths.append(os.path.join(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"]), ".credentials.json"))
    paths.append(os.path.join(_expand_home(home), ".claude", ".credentials.json"))
    return list(dict.fromkeys(paths))


def load_claude_oauth_credentials(home: Optional[str] = None, config_dir: Optional[str] = None) -> Optional[dict[str, Any]]:
    for path in claude_credential_paths(home, config_dir):
        data = _read_json_file(path)
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if isinstance(oauth, dict) and oauth.get("accessToken"):
            return {
                "accessToken": str(oauth["accessToken"]),
                "expiresAt": _to_float(oauth.get("expiresAt")),
                "subscriptionType": oauth.get("subscriptionType"),
                "rateLimitTier": oauth.get("rateLimitTier"),
                "path": path,
            }
    return None


def load_claude_local_account(home: Optional[str] = None, config_dir: Optional[str] = None) -> dict[str, Any]:
    """Email/organisation that Claude Code cached for its signed-in account (no network)."""
    candidates: list[str] = []
    if config_dir:
        candidates.append(os.path.join(os.path.expanduser(config_dir), ".claude.json"))
    elif home is None and os.environ.get("CLAUDE_CONFIG_DIR"):
        candidates.append(os.path.join(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"]), ".claude.json"))
    candidates.append(os.path.join(_expand_home(home), ".claude.json"))
    for path in dict.fromkeys(candidates):
        data = _read_json_file(path)
        account = data.get("oauthAccount") if isinstance(data, dict) else None
        if isinstance(account, dict) and (account.get("emailAddress") or account.get("organizationName")):
            return {
                "email": account.get("emailAddress"),
                "organization": account.get("organizationName"),
            }
    return {}


def claude_plan_label(subscription_type: Any, rate_limit_tier: Any) -> Optional[str]:
    base = {
        "max": "Claude Max",
        "pro": "Claude Pro",
        "team": "Claude Team",
        "enterprise": "Claude Enterprise",
        "free": "Claude Free",
    }.get(str(subscription_type or "").lower())
    multiplier = re.search(r"_(\d+)x$", str(rate_limit_tier or "").lower())
    if base and multiplier:
        return f"{base} {multiplier.group(1)}x"
    return base or (str(rate_limit_tier) if rate_limit_tier else None)


def parse_claude_oauth_usage(payload: Any) -> list[dict[str, Any]]:
    """Windows from ``GET /api/oauth/usage`` (``utilization`` is already a percentage)."""
    if not isinstance(payload, dict):
        return []
    windows: list[Optional[dict[str, Any]]] = []

    def window_from(key: str, label: str, kind: str) -> Optional[dict[str, Any]]:
        entry = payload.get(key)
        if not isinstance(entry, dict):
            return None
        description = None
        if entry.get("locked_reason"):
            description = f"Locked: {entry['locked_reason']}"
        return make_window(key, label, entry.get("utilization"), kind=kind, reset_time=entry.get("resets_at"), description=description)

    windows.append(window_from("five_hour", "Five Hour Limit", "five_hour"))
    windows.append(window_from("seven_day", "Weekly Limit", "weekly"))
    for key, label in _CLAUDE_SCOPED_WINDOW_LABELS.items():
        windows.append(window_from(key, label, "weekly_scoped"))

    limits = payload.get("limits")
    if isinstance(limits, list):
        for item in limits:
            if not isinstance(item, dict) or item.get("kind") != "weekly_scoped":
                continue  # "session"/"weekly_all" mirror five_hour/seven_day above
            scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
            model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
            name = model.get("display_name") or model.get("id") or scope.get("surface") or "scoped"
            windows.append(
                make_window(
                    f"weekly_scoped:{name}",
                    f"Weekly Limit ({name})",
                    item.get("percent"),
                    kind="weekly_scoped",
                    reset_time=item.get("resets_at"),
                    isActive=bool(item.get("is_active")),
                    severity=item.get("severity"),
                )
            )

    extra = payload.get("extra_usage")
    if isinstance(extra, dict) and extra.get("is_enabled") and _to_float(extra.get("utilization")) is not None:
        used_credits = _to_float(extra.get("used_credits"))
        monthly_limit = _to_float(extra.get("monthly_limit"))
        currency = extra.get("currency") or ""
        description = None
        if used_credits is not None and monthly_limit is not None:
            description = f"{_format_quantity(used_credits)} of {_format_quantity(monthly_limit)} {currency} extra usage spent this month".strip()
        windows.append(make_window("extra_usage", "Extra Usage (monthly)", extra.get("utilization"), kind="monthly", description=description))

    return [w for w in windows if w]


def fetch_claude_account_usage(
    home: Optional[str] = None,
    config_dir: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    now: Optional[float] = None,
    http: HttpFn = _http_request,
) -> dict[str, Any]:
    """Live Claude account windows for the Claude Code sign-in stored under ``home``/``config_dir``."""
    now = time.time() if now is None else now
    credentials = load_claude_oauth_credentials(home, config_dir)
    if not credentials:
        return build_provider(
            "claude",
            STATUS_NOT_LOGGED_IN,
            CLAUDE_SOURCE,
            description="Claude Code is not signed in on this host (no OAuth credentials found).",
        )
    local = load_claude_local_account(home, config_dir)
    account = {
        "email": local.get("email"),
        "organization": local.get("organization"),
        "plan": claude_plan_label(credentials.get("subscriptionType"), credentials.get("rateLimitTier")),
    }
    expires_at = credentials.get("expiresAt")
    if expires_at is not None and expires_at / 1000.0 <= now:
        return build_provider(
            "claude",
            STATUS_TOKEN_EXPIRED,
            CLAUDE_SOURCE,
            account=account,
            description=(
                "Claude Code's saved sign-in token has expired. Send a message with a Claude Code model, "
                "or run any `claude` command on the host, so Claude Code refreshes it."
            ),
        )

    headers = {
        "Authorization": f"Bearer {credentials['accessToken']}",
        "anthropic-beta": CLAUDE_OAUTH_BETA_HEADER,
    }
    try:
        status_code, body, _raw = http(CLAUDE_OAUTH_USAGE_URL, headers=headers, timeout=timeout)
    except ProviderFetchError as exc:
        return build_provider(
            "claude",
            STATUS_UNAVAILABLE,
            CLAUDE_SOURCE,
            account=account,
            description=f"Could not reach the Anthropic usage API: {exc}",
        )
    if status_code in (401, 403):
        return build_provider(
            "claude",
            STATUS_TOKEN_EXPIRED,
            CLAUDE_SOURCE,
            account=account,
            description=f"Anthropic rejected Claude Code's saved token (HTTP {status_code}). Run `claude auth login` again on the host.",
        )
    if status_code != 200 or not isinstance(body, dict):
        return build_provider(
            "claude",
            STATUS_UNAVAILABLE,
            CLAUDE_SOURCE,
            account=account,
            description=f"The Anthropic usage API returned HTTP {status_code}.",
        )

    windows = parse_claude_oauth_usage(body)
    if not account.get("email"):
        try:
            profile_status, profile, _ = http(CLAUDE_OAUTH_PROFILE_URL, headers=headers, timeout=timeout)
            if profile_status == 200 and isinstance(profile, dict):
                account_info = profile.get("account") if isinstance(profile.get("account"), dict) else {}
                org_info = profile.get("organization") if isinstance(profile.get("organization"), dict) else {}
                account["email"] = account_info.get("email") or account["email"]
                account["organization"] = org_info.get("name") or account["organization"]
                if not account.get("plan"):
                    account["plan"] = claude_plan_label(
                        "max" if account_info.get("has_claude_max") else ("pro" if account_info.get("has_claude_pro") else None),
                        org_info.get("rate_limit_tier"),
                    )
        except ProviderFetchError:
            pass
    return build_provider(
        "claude",
        STATUS_OK,
        CLAUDE_SOURCE,
        account=account,
        windows=windows,
        description=None if windows else "Anthropic returned no usage windows for this account.",
    )


def provider_from_claude_cli_snapshot(cli_view: dict[str, Any], *, reason: Optional[str], account: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Wrap ``claude_backend.build_claude_rate_limits`` output as a stale provider entry."""
    windows = []
    hourly = cli_view.get("hourly")
    weekly = cli_view.get("weekly")
    if isinstance(hourly, dict):
        windows.append(make_window("five_hour", "Five Hour Limit", hourly.get("usedPercent"), kind="five_hour", reset_time=hourly.get("resetTime"), description=hourly.get("description")))
    if isinstance(weekly, dict):
        windows.append(make_window("seven_day", "Weekly Limit", weekly.get("usedPercent"), kind="weekly", reset_time=weekly.get("resetTime"), description=weekly.get("description")))
    observed = cli_view.get("observedAt")
    description = "Showing the windows Claude Code reported during KookAI's most recent Claude run"
    if observed:
        description += f" ({observed})"
    description += "; usage from other Claude apps since then is not included."
    if reason:
        description = f"Live account usage is unavailable: {reason} {description}"
    return build_provider(
        "claude",
        STATUS_STALE,
        "claude_cli",
        account=account,
        windows=windows,
        description=description,
        observed_at=observed,
        limitStatus=cli_view.get("status"),
    )


# ---------------------------------------------------------------------------
# Codex — local app-server (`account/read` + `account/rateLimits/read`)
# ---------------------------------------------------------------------------

CODEX_SOURCE = "codex_app_server"
_CODEX_PLAN_LABELS = {
    "free": "ChatGPT Free",
    "plus": "ChatGPT Plus",
    "pro": "ChatGPT Pro",
    "team": "ChatGPT Team",
    "business": "ChatGPT Business",
    "enterprise": "ChatGPT Enterprise",
    "edu": "ChatGPT Edu",
}


def _codex_window(window: Any, window_id: str, fallback_label: str, fallback_kind: str) -> Optional[dict[str, Any]]:
    if not isinstance(window, dict):
        return None
    minutes = _to_float(window.get("windowDurationMins"))
    if minutes == 10080:
        label, kind = "Weekly Limit", "weekly"
    elif minutes == 300:
        label, kind = "Five Hour Limit", "five_hour"
    elif minutes and minutes >= 60:
        hours = minutes / 60.0
        label = f"{int(hours) if hours.is_integer() else round(hours, 1)} Hour Limit"
        kind = "other"
    else:
        label, kind = fallback_label, fallback_kind
    return make_window(
        window_id,
        label,
        window.get("usedPercent"),
        kind=kind,
        reset_time=window.get("resetsAt"),
        windowDurationMins=window.get("windowDurationMins"),
        resetsAt=window.get("resetsAt"),
    )


def build_codex_provider(status: Any, error: Optional[str] = None) -> dict[str, Any]:
    """Shape ``codex_backend.fetch_codex_account_status`` output (or its failure) as a provider entry."""
    if not isinstance(status, dict) or not status.get("ok"):
        detail = error or (status.get("error") if isinstance(status, dict) else None) or "the Codex CLI did not answer"
        return build_provider("codex", STATUS_UNAVAILABLE, CODEX_SOURCE, description=f"Codex account usage is unavailable: {detail}.")

    account_raw = status.get("account") if isinstance(status.get("account"), dict) else None
    err_lower = str(status.get("error") or "").lower()
    is_expired_jwt = any(
        marker in err_lower
        for marker in ("invalid_jwt", "401 unauthorized", "signing in again", "token expired")
    )
    if status.get("requiresOpenaiAuth") or (account_raw is None and status.get("sawAccount")):
        if is_expired_jwt:
            return build_provider(
                "codex",
                STATUS_TOKEN_EXPIRED,
                CODEX_SOURCE,
                description="Codex sign-in has expired on this host.",
            )
        return build_provider("codex", STATUS_NOT_LOGGED_IN, CODEX_SOURCE, description="Codex is not signed in on this host.")

    account: Optional[dict[str, Any]] = None
    if account_raw:
        plan_type = account_raw.get("planType") or account_raw.get("plan_type")
        account = {
            "email": account_raw.get("email"),
            "plan": _CODEX_PLAN_LABELS.get(str(plan_type or "").lower(), str(plan_type) if plan_type else None),
            "label": "API key" if str(account_raw.get("type") or "").lower() in {"apikey", "api_key"} else None,
        }

    rate_limits = status.get("rateLimits") if isinstance(status.get("rateLimits"), dict) else None
    if not rate_limits:
        message = status.get("error") or "the Codex app-server returned no rate limits"
        if is_expired_jwt:
            return build_provider("codex", STATUS_TOKEN_EXPIRED, CODEX_SOURCE, account=account, description="Codex sign-in has expired on this host.")
        if "authentication required" in str(message).lower():
            return build_provider("codex", STATUS_NOT_LOGGED_IN, CODEX_SOURCE, description="Codex is not signed in on this host.")
        return build_provider("codex", STATUS_UNAVAILABLE, CODEX_SOURCE, account=account, description=f"Codex account usage is unavailable: {message}.")

    if account and not account.get("plan") and rate_limits.get("planType"):
        account["plan"] = _CODEX_PLAN_LABELS.get(str(rate_limits["planType"]).lower(), str(rate_limits["planType"]))
    windows = [
        _codex_window(rate_limits.get("primary"), "primary", "Weekly Limit", "weekly"),
        _codex_window(rate_limits.get("secondary"), "secondary", "Five Hour Limit", "five_hour"),
    ]
    description = None
    if isinstance(rate_limits.get("availableResets"), int):
        description = f"{rate_limits['availableResets']} available resets."
    return build_provider(
        "codex",
        STATUS_OK,
        CODEX_SOURCE,
        account=account,
        windows=windows,
        description=description,
        limitName=rate_limits.get("limitName"),
        availableResets=rate_limits.get("availableResets"),
    )


# ---------------------------------------------------------------------------
# Antigravity — Google Cloud Code quota summary (Gemini + Claude/GPT groups)
# ---------------------------------------------------------------------------

ANTIGRAVITY_SOURCE = "antigravity"


def antigravity_token_paths(profile_root: Optional[str] = None) -> list[str]:
    root = _expand_home(profile_root)
    return [
        os.path.join(root, ".gemini", "antigravity-cli", "antigravity-oauth-token"),
        os.path.join(root, ".gemini", "antigravity", "antigravity-oauth-token"),
        os.path.join(root, ".gemini", "antigravity", "jetski-standalone-oauth-token"),
    ]


def antigravity_signed_in(profile_root: Optional[str] = None) -> bool:
    return any(os.path.isfile(path) for path in antigravity_token_paths(profile_root))


def parse_antigravity_quota_summary(quota_summary: Any) -> dict[str, dict[str, Optional[dict[str, Any]]]]:
    """Weekly/5-hour buckets per group from ``retrieveUserQuotaSummary``.

    Only ``remainingFraction`` values that are real numbers inside [0, 1] are
    accepted; anything else leaves the bucket unknown rather than guessed.
    """
    buckets: dict[str, dict[str, Optional[dict[str, Any]]]] = {
        "gemini": {"weekly": None, "hourly": None},
        "claude": {"weekly": None, "hourly": None},
    }
    groups = quota_summary.get("groups") if isinstance(quota_summary, dict) else None
    if not isinstance(groups, list):
        return buckets
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = str(group.get("displayName") or "").lower()
        if "gemini" in name:
            target = "gemini"
        elif "claude" in name or "3p" in name or "gpt" in name:
            target = "claude"
        else:
            continue
        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            bucket_id = str(bucket.get("bucketId") or "").lower()
            window = str(bucket.get("window") or "").lower()
            raw_fraction = bucket.get("remainingFraction")
            if isinstance(raw_fraction, bool):
                continue
            try:
                remaining = float(raw_fraction)
            except (TypeError, ValueError):
                continue
            if not 0.0 <= remaining <= 1.0:  # NaN also fails here
                continue
            used_pct = round(max(0.0, (1.0 - remaining) * 100.0), 1)
            remaining_pct = round(min(100.0, remaining * 100.0), 1)
            data = {
                "usedPercent": used_pct,
                "remainingPercent": remaining_pct,
                "resetTime": bucket.get("resetTime"),
                "description": bucket.get("description"),
            }
            if "weekly" in bucket_id or "weekly" in window:
                buckets[target]["weekly"] = data
            elif "5h" in bucket_id or "5h" in window or "hourly" in bucket_id:
                buckets[target]["hourly"] = data
    return buckets


def _antigravity_windows(group: dict[str, Optional[dict[str, Any]]]) -> list[Optional[dict[str, Any]]]:
    windows: list[Optional[dict[str, Any]]] = []
    hourly = group.get("hourly")
    weekly = group.get("weekly")
    if hourly:
        windows.append(make_window("five_hour", "Five Hour Limit", hourly.get("usedPercent"), kind="five_hour", reset_time=hourly.get("resetTime"), description=hourly.get("description")))
    if weekly:
        windows.append(make_window("weekly", "Weekly Limit", weekly.get("usedPercent"), kind="weekly", reset_time=weekly.get("resetTime"), description=weekly.get("description")))
    return windows


def build_antigravity_providers(
    antigravity_status: Any,
    *,
    signed_in: bool,
    plan_name: Optional[str] = None,
    email: Optional[str] = None,
    error: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Optional[dict[str, Any]]]]]:
    """Return ``(gemini_provider, claude_gpt_provider, parsed_buckets)``."""
    quota_summary = antigravity_status.get("quotaSummary") if isinstance(antigravity_status, dict) else None
    buckets = parse_antigravity_quota_summary(quota_summary)
    account = {"email": email, "plan": plan_name} if (email or plan_name) else None

    def entry(provider_id: str, group_key: str, missing_group: str) -> dict[str, Any]:
        windows = _antigravity_windows(buckets[group_key])
        if windows:
            return build_provider(provider_id, STATUS_OK, ANTIGRAVITY_SOURCE, account=account, windows=windows)
        if error:
            return build_provider(provider_id, STATUS_UNAVAILABLE, ANTIGRAVITY_SOURCE, account=account, description=f"Antigravity quota lookup failed: {error}.")
        if not signed_in and not isinstance(antigravity_status, dict):
            return build_provider(provider_id, STATUS_NOT_LOGGED_IN, ANTIGRAVITY_SOURCE, description="Antigravity is not signed in on this host.")
        if isinstance(antigravity_status, dict):
            description = f"Antigravity reported this account but no {missing_group} quota windows."
        else:
            description = "Antigravity did not return account quota. Open Antigravity to check your limits."
        return build_provider(provider_id, STATUS_UNAVAILABLE, ANTIGRAVITY_SOURCE, account=account, description=description)

    gemini = entry("antigravity", "gemini", "Gemini")
    claude = entry("antigravity_claude", "claude", "Claude/GPT")
    return gemini, claude, buckets


# ---------------------------------------------------------------------------
# Kimi Code — `GET {coding base}/usages` with the CLI's sign-in token
# ---------------------------------------------------------------------------

KIMI_SOURCE = "kimi_code_api"
KIMI_REGION_BASES = {
    "mainland-cn": "https://api.kimi.com/coding/v1",
    "global": "https://api.kimi.ai/coding/v1",
}
_KIMI_UNIT_MINUTES = {
    "TIME_UNIT_SECOND": 1 / 60.0,
    "TIME_UNIT_MINUTE": 1.0,
    "TIME_UNIT_HOUR": 60.0,
    "TIME_UNIT_DAY": 1440.0,
    "TIME_UNIT_WEEK": 10080.0,
    "SECOND": 1 / 60.0,
    "MINUTE": 1.0,
    "HOUR": 60.0,
    "DAY": 1440.0,
    "WEEK": 10080.0,
}


def kimi_home_dir(home: Optional[str] = None) -> str:
    if home is None and os.environ.get("KIMI_CODE_HOME"):
        return os.path.expanduser(os.environ["KIMI_CODE_HOME"])
    return os.path.join(_expand_home(home), ".kimi-code")


def _load_toml(path: str) -> dict[str, Any]:
    if tomllib is None or not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        LOGGER.debug("Could not parse %s: %s", path, exc)
        return {}


def load_kimi_credentials(home: Optional[str] = None, env: Optional[dict[str, str]] = None) -> Optional[dict[str, Any]]:
    """Token the Kimi Code CLI uses for the signed-in account, plus its API base."""
    env = os.environ if env is None else env
    kimi_dir = kimi_home_dir(home)
    config = _load_toml(os.path.join(kimi_dir, "config.toml"))
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    ordered = sorted(providers.items(), key=lambda item: 0 if str(item[0]).startswith("managed:kimi-code") else 1)
    for _key, provider in ordered:
        if not isinstance(provider, dict) or str(provider.get("type") or "").lower() != "kimi":
            continue
        base_url = base_url or provider.get("base_url")
        key = str(provider.get("api_key") or "").strip()
        if not key and provider.get("api_key_env"):
            key = str(env.get(str(provider["api_key_env"]), "")).strip()
        if key and not api_key:
            api_key = key

    oauth_token: Optional[str] = None
    oauth_expires: Optional[float] = None
    for path in sorted(glob.glob(os.path.join(kimi_dir, "credentials", "*.json"))):
        data = _read_json_file(path)
        if not isinstance(data, dict):
            continue
        token_block = data.get("token") if isinstance(data.get("token"), dict) else {}
        access = data.get("access_token") or token_block.get("access_token")
        if not access:
            continue
        oauth_token = str(access)
        oauth_expires = _epoch_from_any(data.get("expiry_date") or data.get("expires_at") or token_block.get("expiry_date") or token_block.get("expires_at"))
        break

    token = api_key or oauth_token or str(env.get("KIMI_CODE_API_KEY", "")).strip() or None
    if not token:
        return None
    region = (_read_text_file(os.path.join(kimi_dir, "region")) or "").strip() or "mainland-cn"
    return {
        "token": token,
        "source": "api_key" if api_key else ("oauth" if oauth_token else "env"),
        "baseUrl": (base_url or KIMI_REGION_BASES.get(region, KIMI_REGION_BASES["mainland-cn"])).rstrip("/"),
        "expiresAt": oauth_expires if not api_key else None,
        "region": region,
    }


def _kimi_window_from_detail(window_id: str, label: str, kind: str, detail: Any) -> Optional[dict[str, Any]]:
    if not isinstance(detail, dict):
        return None
    limit = _to_float(detail.get("limit"))
    used = _to_float(detail.get("used"))
    remaining = _to_float(detail.get("remaining"))
    percent = _to_float(detail.get("percentage"))
    if percent is None:
        percent = _to_float(detail.get("usedPercent"))
    if percent is None and limit:
        if used is not None:
            percent = used / limit * 100.0
        elif remaining is not None:
            percent = (limit - remaining) / limit * 100.0
    if percent is None:
        return None
    description = None
    if limit is not None and used is not None:
        description = f"{_format_quantity(used)} of {_format_quantity(limit)} used"
    return make_window(window_id, label, percent, kind=kind, reset_time=detail.get("resetTime") or detail.get("reset_time"), description=description)


def _human_minutes(minutes: float) -> str:
    if minutes % 10080 == 0:
        weeks = int(minutes // 10080)
        return "Weekly" if weeks == 1 else f"{weeks}-week"
    if minutes % 1440 == 0:
        days = int(minutes // 1440)
        return "Daily" if days == 1 else f"{days}-day"
    if minutes % 60 == 0:
        return f"{int(minutes // 60)}-hour"
    return f"{int(minutes)}-minute"


def parse_kimi_usages(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    windows: list[Optional[dict[str, Any]]] = []
    limits = payload.get("limits")
    if isinstance(limits, list):
        for item in limits:
            if not isinstance(item, dict):
                continue
            window = item.get("window") if isinstance(item.get("window"), dict) else {}
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else item
            duration = _to_float(window.get("duration"))
            unit = str(window.get("timeUnit") or window.get("time_unit") or "").upper()
            minutes = duration * _KIMI_UNIT_MINUTES.get(unit, 1.0) if duration else None
            if minutes == 300:
                windows.append(_kimi_window_from_detail("five_hour", "Five Hour Limit", "five_hour", detail))
            elif minutes == 10080:
                windows.append(_kimi_window_from_detail("weekly", "Weekly Limit", "weekly", detail))
            elif minutes:
                windows.append(_kimi_window_from_detail(f"window_{int(minutes)}m", f"{_human_minutes(minutes)} Limit", "other", detail))
            else:
                windows.append(_kimi_window_from_detail("window", "Usage Limit", "other", detail))
    usage = payload.get("usage")
    if isinstance(usage, dict) and not any(w and w.get("kind") == "weekly" for w in windows):
        windows.append(_kimi_window_from_detail("weekly", "Weekly Limit", "weekly", usage))
    return [w for w in windows if w]


def fetch_kimi_account_usage(
    home: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    now: Optional[float] = None,
    http: HttpFn = _http_request,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    credentials = load_kimi_credentials(home, env)
    if not credentials:
        return build_provider("kimi", STATUS_NOT_LOGGED_IN, KIMI_SOURCE, description="Kimi Code is not signed in on this host.")
    account = {"label": {"api_key": "API key", "oauth": "Kimi account", "env": "KIMI_CODE_API_KEY"}.get(credentials["source"]), "plan": None}
    expires_at = credentials.get("expiresAt")
    if expires_at is not None and expires_at <= now:
        return build_provider(
            "kimi",
            STATUS_TOKEN_EXPIRED,
            KIMI_SOURCE,
            account=account,
            description="Kimi Code's saved sign-in token has expired. Start `kimi` once or run `kimi login` on the host to refresh it.",
        )
    url = f"{credentials['baseUrl']}/usages"
    try:
        status_code, body, raw = http(url, headers={"Authorization": f"Bearer {credentials['token']}"}, timeout=timeout)
    except ProviderFetchError as exc:
        return build_provider("kimi", STATUS_UNAVAILABLE, KIMI_SOURCE, account=account, description=f"Could not reach the Kimi Code usage API: {exc}")
    if status_code in (401, 403):
        return build_provider("kimi", STATUS_AUTH_REJECTED, KIMI_SOURCE, account=account, description=f"Kimi rejected the saved credentials (HTTP {status_code}). Run `kimi login` again on the host.")
    if status_code != 200 or not isinstance(body, dict):
        return build_provider("kimi", STATUS_UNAVAILABLE, KIMI_SOURCE, account=account, description=f"The Kimi Code usage API returned HTTP {status_code}.")
    windows = parse_kimi_usages(body)
    return build_provider(
        "kimi",
        STATUS_OK,
        KIMI_SOURCE,
        account=account,
        windows=windows,
        description=None if windows else "Kimi returned a usage format KookAI does not recognise yet; open `kimi` and run /usage to see it.",
    )


# ---------------------------------------------------------------------------
# Grok Build — sign-in state from ~/.grok/auth.json; billing over the agent's JSON-RPC
# ---------------------------------------------------------------------------

GROK_SOURCE = "grok_agent_rpc"


def grok_home_dir(home: Optional[str] = None) -> str:
    return os.path.join(_expand_home(home), ".grok")


def load_grok_auth(home: Optional[str] = None) -> Optional[dict[str, Any]]:
    data = _read_json_file(os.path.join(grok_home_dir(home), "auth.json"))
    if not isinstance(data, dict):
        return None
    candidates = [value for value in data.values() if isinstance(value, dict)] + [data]
    for entry in candidates:
        token = entry.get("key") or entry.get("access_token") or entry.get("api_key") or entry.get("token")
        if not token:
            continue
        return {
            "email": entry.get("email"),
            "authMode": entry.get("auth_mode"),
            "teamId": entry.get("team_id"),
            "expiresAt": _epoch_from_any(entry.get("expires_at")),
        }
    return None


def _jsonrpc_stdio_exchange(
    command: list[str],
    messages: list[dict[str, Any]],
    wanted_ids: set[Any],
    *,
    timeout: float,
    env: Optional[dict[str, str]] = None,
) -> dict[Any, dict[str, Any]]:
    """Send newline-delimited JSON-RPC messages to ``command`` and collect replies for ``wanted_ids``."""
    kwargs: dict[str, Any] = {}
    if os.name == "nt":  # pragma: no cover - windows only
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **kwargs,
    )
    lines: "queue.Queue[str]" = queue.Queue()

    def pump(stream: Any) -> None:
        for line in iter(stream.readline, ""):
            lines.put(line.rstrip("\n"))

    threading.Thread(target=pump, args=(process.stdout,), daemon=True).start()
    threading.Thread(target=lambda: [None for _ in iter(process.stderr.readline, "")], daemon=True).start()
    replies: dict[Any, dict[str, Any]] = {}
    try:
        assert process.stdin is not None
        for message in messages:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline and len(replies) < len(wanted_ids):
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None:
                    break
                continue
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("id") in wanted_ids:
                replies[event["id"]] = event
        return replies
    finally:
        try:
            process.terminate()
        except Exception:
            pass


def fetch_grok_billing_via_rpc(executable: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """Ask the Grok agent (``grok agent stdio``) for ``x.ai/billing``; returns the raw JSON-RPC reply."""
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}},
                "clientInfo": {"name": "KookAI", "version": "1.0"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "x.ai/billing", "params": {}},
    ]
    replies = _jsonrpc_stdio_exchange([executable, "agent", "stdio", "--no-leader"], messages, {1, 2}, timeout=timeout)
    return replies.get(2) or {"timeout": True}


def parse_grok_billing(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []

    def val(container: Any, *keys: str) -> Optional[float]:
        for key in keys:
            node = container.get(key) if isinstance(container, dict) else None
            if isinstance(node, dict):
                node = node.get("val", node.get("value"))
            number = _to_float(node)
            if number is not None:
                return number
        return None

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    cycle = result.get("billingCycle") if isinstance(result.get("billingCycle"), dict) else result.get("billing_cycle") or {}
    monthly_limit = val(result, "monthlyLimit", "monthly_limit")
    total_used = val(usage, "totalUsed", "total_used")
    included_used = val(usage, "includedUsed", "included_used")
    on_demand_used = val(usage, "onDemandUsed", "on_demand_used")
    if monthly_limit is None or monthly_limit <= 0 or total_used is None:
        return []
    parts = [f"{_format_quantity(total_used)} of {_format_quantity(monthly_limit)} monthly credits used"]
    if included_used is not None and on_demand_used:
        parts.append(f"({_format_quantity(included_used)} included + {_format_quantity(on_demand_used)} on-demand)")
    window = make_window(
        "monthly",
        "Monthly Credits",
        total_used / monthly_limit * 100.0,
        kind="monthly",
        reset_time=(cycle or {}).get("billingPeriodEnd") or (cycle or {}).get("billing_period_end"),
        description=" ".join(parts),
    )
    return [window] if window else []


def fetch_grok_account_usage(
    home: Optional[str] = None,
    *,
    executable: Optional[str] = None,
    timeout: float = 8.0,
    now: Optional[float] = None,
    rpc: Callable[..., dict[str, Any]] = fetch_grok_billing_via_rpc,
) -> dict[str, Any]:
    now = time.time() if now is None else now
    auth = load_grok_auth(home)
    if not auth:
        return build_provider("grok", STATUS_NOT_LOGGED_IN, GROK_SOURCE, description="Grok Build is not signed in on this host.")
    account = {"email": auth.get("email"), "label": auth.get("authMode"), "plan": None}
    if auth.get("expiresAt") is not None and auth["expiresAt"] <= now:
        return build_provider("grok", STATUS_TOKEN_EXPIRED, GROK_SOURCE, account=account, description="Grok Build's sign-in has expired. Run `grok login` again on the host.")
    if executable is None:
        try:
            from grok_backend import resolve_grok_executable

            executable = resolve_grok_executable()
        except Exception as exc:
            return build_provider("grok", STATUS_UNAVAILABLE, GROK_SOURCE, account=account, description=f"Grok CLI not found: {exc}")
    try:
        reply = rpc(executable, timeout=timeout)
    except Exception as exc:
        return build_provider("grok", STATUS_UNAVAILABLE, GROK_SOURCE, account=account, description=f"Could not query the Grok agent: {exc}")
    if reply.get("timeout"):
        return build_provider("grok", STATUS_UNAVAILABLE, GROK_SOURCE, account=account, description="The Grok agent did not answer the billing request in time.")
    error = reply.get("error")
    if isinstance(error, dict):
        if error.get("code") == -32601:
            return build_provider(
                "grok",
                STATUS_UNSUPPORTED,
                GROK_SOURCE,
                account=account,
                description="This Grok Build version does not expose account usage to other apps (no x.ai/billing RPC). Open `grok` and run /usage to see it.",
            )
        return build_provider("grok", STATUS_UNAVAILABLE, GROK_SOURCE, account=account, description=f"Grok billing request failed: {error.get('message') or error}")
    windows = parse_grok_billing(reply.get("result"))
    return build_provider(
        "grok",
        STATUS_OK,
        GROK_SOURCE,
        account=account,
        windows=windows,
        description=None if windows else "Grok returned billing data without a monthly limit KookAI can display.",
    )


# ---------------------------------------------------------------------------
# Muse Code — sign-in state only (Meta has no read-only usage API)
# ---------------------------------------------------------------------------

MUSE_SOURCE = "muse_auth"
MUSE_NO_API_DESCRIPTION = (
    "Meta does not publish a read-only usage API for Muse Code, and the only endpoint known to return "
    "quota mints a new inference key on every call, so KookAI does not poll it. "
    "Check Accounts Center → Subscriptions → Muse Code, or /usage inside `muse`."
)


def muse_config_dir(home: Optional[str] = None) -> str:
    if home is None and os.environ.get("XDG_CONFIG_HOME"):
        return os.path.join(os.path.expanduser(os.environ["XDG_CONFIG_HOME"]), "muse")
    return os.path.join(_expand_home(home), ".config", "muse")


def load_muse_auth(home: Optional[str] = None) -> Optional[dict[str, Any]]:
    data = _read_json_file(os.path.join(muse_config_dir(home), "auth.json"))
    providers = data.get("providers") if isinstance(data, dict) else None
    meta = providers.get("meta") if isinstance(providers, dict) else None
    if not isinstance(meta, dict):
        return None
    return {
        "email": meta.get("user_email") or meta.get("email"),
        "name": meta.get("user_full_name") or meta.get("name"),
        "subsActive": meta.get("subs_active"),
        "mechanism": meta.get("mechanism"),
    }


def fetch_muse_account_status(home: Optional[str] = None, *, env: Optional[dict[str, str]] = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    api_key = str(env.get("META_API_KEY") or env.get("MUSE_API_KEY") or "").strip()
    auth = load_muse_auth(home)
    if auth:
        plan = None
        if auth.get("subsActive") is True:
            plan = "Subscription active"
        elif auth.get("subsActive") is False:
            plan = "No active subscription"
        account = {"email": auth.get("email"), "plan": plan, "label": auth.get("mechanism")}
        return build_provider("muse", STATUS_UNSUPPORTED, MUSE_SOURCE, account=account, description=MUSE_NO_API_DESCRIPTION)
    if api_key:
        return build_provider(
            "muse",
            STATUS_UNSUPPORTED,
            MUSE_SOURCE,
            account={"label": f"Meta API key {_mask_secret(api_key)}", "plan": "Meta Model API"},
            description="The Meta Model API key is configured, but Meta exposes no account usage endpoint for it.",
        )
    return build_provider("muse", STATUS_NOT_LOGGED_IN, MUSE_SOURCE, description="Muse Code is not signed in on this host.")


# ---------------------------------------------------------------------------
# DeepSeek — platform balance for the configured API key
# ---------------------------------------------------------------------------

DEEPSEEK_SOURCE = "deepseek_balance"
DEEPSEEK_API_HOST = "api.deepseek.com"
DEEPSEEK_BALANCE_URL = f"https://{DEEPSEEK_API_HOST}/user/balance"


def resolve_deepseek_credentials(home: Optional[str] = None, env: Optional[dict[str, str]] = None) -> Optional[dict[str, Any]]:
    env = os.environ if env is None else env
    root = _expand_home(home)
    env_key = str(env.get("DEEPSEEK_API_KEY") or "").strip()
    if env_key:
        return {"apiKey": env_key, "baseUrl": str(env.get("DEEPSEEK_BASE_URL") or f"https://{DEEPSEEK_API_HOST}"), "source": "DEEPSEEK_API_KEY"}
    config = _read_json_file(os.path.join(root, ".deepseek", "config.json"))
    if isinstance(config, dict) and str(config.get("api_key") or "").strip():
        return {"apiKey": str(config["api_key"]).strip(), "baseUrl": str(config.get("base_url") or f"https://{DEEPSEEK_API_HOST}"), "source": "~/.deepseek/config.json"}
    settings = _read_json_file(os.path.join(root, ".deepcode", "settings.json"))
    env_block = settings.get("env") if isinstance(settings, dict) and isinstance(settings.get("env"), dict) else {}
    if str(env_block.get("API_KEY") or "").strip():
        return {"apiKey": str(env_block["API_KEY"]).strip(), "baseUrl": str(env_block.get("BASE_URL") or f"https://{DEEPSEEK_API_HOST}"), "source": "~/.deepcode/settings.json"}
    return None


def parse_deepseek_balance(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    balances = []
    for info in payload.get("balance_infos") or []:
        if not isinstance(info, dict):
            continue
        total = _to_float(info.get("total_balance"))
        if total is None:
            continue
        balances.append(
            {
                "currency": str(info.get("currency") or ""),
                "total": total,
                "granted": _to_float(info.get("granted_balance")),
                "toppedUp": _to_float(info.get("topped_up_balance")),
            }
        )
    return balances


def fetch_deepseek_account_usage(
    home: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    http: HttpFn = _http_request,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    credentials = resolve_deepseek_credentials(home, env)
    if not credentials:
        return build_provider("deepseek", STATUS_NOT_LOGGED_IN, DEEPSEEK_SOURCE, description="No DeepSeek API key is configured on this host.")
    account = {"label": f"API key {_mask_secret(credentials['apiKey'])} ({credentials['source']})", "plan": "DeepSeek platform (prepaid balance)"}
    host = urllib.parse.urlparse(credentials["baseUrl"]).hostname or ""
    if host.lower() != DEEPSEEK_API_HOST:
        return build_provider(
            "deepseek",
            STATUS_UNSUPPORTED,
            DEEPSEEK_SOURCE,
            account=account,
            description=f"The configured DeepSeek key targets {host or credentials['baseUrl']}, which has no balance API KookAI can query.",
        )
    try:
        status_code, body, _raw = http(DEEPSEEK_BALANCE_URL, headers={"Authorization": f"Bearer {credentials['apiKey']}"}, timeout=timeout)
    except ProviderFetchError as exc:
        return build_provider("deepseek", STATUS_UNAVAILABLE, DEEPSEEK_SOURCE, account=account, description=f"Could not reach the DeepSeek balance API: {exc}")
    if status_code in (401, 403):
        return build_provider("deepseek", STATUS_AUTH_REJECTED, DEEPSEEK_SOURCE, account=account, description=f"DeepSeek rejected the saved API key (HTTP {status_code}).")
    if status_code != 200 or not isinstance(body, dict):
        return build_provider("deepseek", STATUS_UNAVAILABLE, DEEPSEEK_SOURCE, account=account, description=f"The DeepSeek balance API returned HTTP {status_code}.")
    balances = parse_deepseek_balance(body)
    description = None
    if balances:
        first = balances[0]
        description = f"Balance {first['total']:,.2f} {first['currency']}".strip()
        if first.get("granted") is not None and first.get("toppedUp") is not None:
            description += f" ({first['granted']:,.2f} granted + {first['toppedUp']:,.2f} topped up)"
        if body.get("is_available") is False:
            description += ". API calls are currently blocked: balance exhausted"
        description += "."
    return build_provider(
        "deepseek",
        STATUS_OK,
        DEEPSEEK_SOURCE,
        account=account,
        balances=balances,
        description=description or "DeepSeek returned no balance information.",
        isAvailable=body.get("is_available"),
    )


# ---------------------------------------------------------------------------
# Z.ai GLM Coding Plan — usage monitor for the key OpenCode stores
# ---------------------------------------------------------------------------

ZAI_SOURCE = "zai_usage_monitor"
ZAI_PLATFORM_BASES = {"zai": "https://api.z.ai", "zhipu": "https://open.bigmodel.cn"}
ZAI_QUOTA_PATH = "/api/monitor/usage/quota/limit"
_ZAI_UNIT_NAMES = {1: "second", 2: "minute", 3: "hour", 4: "day", 5: "day", 6: "week", 7: "month"}
_ZAI_TYPE_NOUNS = {"TOKENS_LIMIT": "tokens", "TIME_LIMIT": "prompts", "CREDIT_LIMIT": "credits"}


def opencode_auth_paths(home: Optional[str] = None) -> list[str]:
    paths: list[str] = []
    if home is None and os.environ.get("XDG_DATA_HOME"):
        paths.append(os.path.join(os.path.expanduser(os.environ["XDG_DATA_HOME"]), "opencode", "auth.json"))
    paths.append(os.path.join(_expand_home(home), ".local", "share", "opencode", "auth.json"))
    return list(dict.fromkeys(paths))


def load_zai_credentials(home: Optional[str] = None, env: Optional[dict[str, str]] = None) -> Optional[dict[str, Any]]:
    env = os.environ if env is None else env
    preferred = str(env.get("ZAI_OPENCODE_PROVIDER") or "").strip()
    order = [pid for pid in [preferred, "zai-coding-plan", "zai", "zhipu-coding-plan", "zhipuai-coding-plan", "zhipu", "zhipuai"] if pid]
    for path in opencode_auth_paths(home):
        auth = _read_json_file(path)
        if not isinstance(auth, dict):
            continue
        for provider_id in dict.fromkeys(order):
            entry = auth.get(provider_id)
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or entry.get("apiKey") or entry.get("access") or "").strip()
            if key:
                return {"apiKey": key, "providerId": provider_id, "platform": "zhipu" if "zhipu" in provider_id else "zai", "source": path}
    for env_name, platform in (("ZAI_API_KEY", "zai"), ("ZHIPU_API_KEY", "zhipu")):
        key = str(env.get(env_name) or "").strip()
        if key:
            return {"apiKey": key, "providerId": env_name, "platform": platform, "source": "environment"}
    return None


def parse_zai_quota_limits(payload: Any) -> tuple[list[dict[str, Any]], Optional[str]]:
    if not isinstance(payload, dict):
        return [], None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    level = data.get("level")
    windows: list[Optional[dict[str, Any]]] = []
    for item in data.get("limits") or []:
        if not isinstance(item, dict):
            continue
        limit_type = str(item.get("type") or "").upper()
        unit = item.get("unit")
        number = _to_float(item.get("number"))
        cap = _to_float(item.get("usage"))
        current = _to_float(item.get("currentValue"))
        percent = _to_float(item.get("percentage"))
        if percent is None and cap:
            if current is not None:
                percent = current / cap * 100.0
            elif _to_float(item.get("remaining")) is not None:
                percent = (cap - _to_float(item.get("remaining"))) / cap * 100.0
        if percent is None:
            continue
        noun = _ZAI_TYPE_NOUNS.get(limit_type, limit_type.replace("_", " ").lower() or "units")
        if unit == 3 and number == 5:
            window_id, label, kind = "five_hour", "Five Hour Limit", "five_hour"
        elif unit == 6 and number == 1:
            window_id, label, kind = "weekly", "Weekly Limit", "weekly"
        elif unit == 7 and number == 1:
            window_id, label, kind = "monthly", "Monthly Limit", "monthly"
        else:
            unit_name = _ZAI_UNIT_NAMES.get(unit, f"unit {unit}")
            count = int(number) if number is not None and float(number).is_integer() else number
            window_id = f"{limit_type.lower() or 'limit'}_{count}_{unit}"
            label = f"{count}-{unit_name} {noun.title()} Limit" if count is not None else f"{noun.title()} Limit"
            kind = "other"
        description = None
        if cap is not None and current is not None:
            description = f"{_format_quantity(current)} of {_format_quantity(cap)} {noun} used"
        windows.append(make_window(window_id, label, percent, kind=kind, reset_time=item.get("nextResetTime"), description=description, limitType=limit_type))
    return [w for w in windows if w], (str(level) if level else None)


def fetch_zai_account_usage(
    home: Optional[str] = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    http: HttpFn = _http_request,
    env: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    credentials = load_zai_credentials(home, env)
    if not credentials:
        return build_provider("zai", STATUS_NOT_LOGGED_IN, ZAI_SOURCE, description="No Z.ai API key is stored for OpenCode on this host.")
    account = {"label": f"{credentials['providerId']} key {_mask_secret(credentials['apiKey'])}", "plan": None}
    url = ZAI_PLATFORM_BASES[credentials["platform"]] + ZAI_QUOTA_PATH
    headers = {
        # The Z.ai usage monitor expects the raw key (no Bearer prefix).
        "Authorization": credentials["apiKey"],
        "Accept-Language": "en-US,en",
        "Content-Type": "application/json",
    }
    try:
        status_code, body, _raw = http(url, headers=headers, timeout=timeout)
    except ProviderFetchError as exc:
        return build_provider("zai", STATUS_UNAVAILABLE, ZAI_SOURCE, account=account, description=f"Could not reach the Z.ai usage API: {exc}")
    if status_code in (401, 403):
        return build_provider("zai", STATUS_AUTH_REJECTED, ZAI_SOURCE, account=account, description=f"Z.ai rejected the stored API key (HTTP {status_code}).")
    if status_code != 200 or not isinstance(body, dict):
        return build_provider("zai", STATUS_UNAVAILABLE, ZAI_SOURCE, account=account, description=f"The Z.ai usage API returned HTTP {status_code}.")
    body_code = body.get("code")
    if body.get("success") is False or (body_code is not None and str(body_code) != "200"):
        message = str(body.get("msg") or body.get("message") or f"code {body_code}")
        if "auth" in message.lower() or "token" in message.lower() or str(body_code) in {"1000", "1001", "1002", "1003", "401"}:
            return build_provider("zai", STATUS_AUTH_REJECTED, ZAI_SOURCE, account=account, description=f"Z.ai rejected the stored API key: {message}")
        return build_provider("zai", STATUS_UNAVAILABLE, ZAI_SOURCE, account=account, description=f"Z.ai usage API error: {message}")
    windows, level = parse_zai_quota_limits(body)
    if level:
        account["plan"] = f"GLM Coding Plan {level.title()}"
    return build_provider(
        "zai",
        STATUS_OK,
        ZAI_SOURCE,
        account=account,
        windows=windows,
        description=None if windows else "Z.ai returned no quota limits for this key.",
    )
