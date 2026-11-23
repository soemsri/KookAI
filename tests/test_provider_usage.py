"""Provider usage fetchers must report the signed-in account's real numbers, or say why not."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_usage as pu  # noqa: E402


def fake_http(status=200, body=None, calls=None):
    """Return an ``http`` stand-in recording calls and answering with ``status``/``body``."""
    calls = calls if calls is not None else []

    def http(url, *, headers=None, method="GET", data=None, timeout=None):
        calls.append({"url": url, "headers": dict(headers or {}), "method": method})
        raw = json.dumps(body) if body is not None else ""
        return status, body, raw

    http.calls = calls
    return http


# Shape observed live from GET https://api.anthropic.com/api/oauth/usage (2026-10-24).
CLAUDE_USAGE_PAYLOAD = {
    "five_hour": {"utilization": 9.0, "resets_at": "2026-10-24T14:49:59.642242+00:00", "locked_reason": None},
    "seven_day": {"utilization": 14.0, "resets_at": "2026-10-30T04:59:59.642261+00:00", "locked_reason": None},
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None, "utilization": None},
    "limits": [
        {"kind": "session", "group": "session", "percent": 9, "resets_at": "2026-10-24T14:49:59.642242+00:00", "scope": None, "is_active": False},
        {"kind": "weekly_all", "group": "weekly", "percent": 14, "resets_at": "2026-10-30T04:59:59.642261+00:00", "scope": None, "is_active": False},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 25, "resets_at": "2026-10-30T04:59:59.642432+00:00",
         "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}, "is_active": True},
    ],
}


class WindowAndProviderShapeTests(unittest.TestCase):
    def test_make_window_caps_display_but_keeps_raw_value(self):
        window = pu.make_window("seven_day", "Weekly Limit", 130.0, kind="weekly", reset_at=None)
        self.assertEqual(window["usedPercent"], 100.0)
        self.assertEqual(window["remainingPercent"], 0.0)
        self.assertEqual(window["rawUsedPercent"], 130.0)
        self.assertIsNone(pu.make_window("x", "x", "not-a-number"))
        self.assertIsNone(pu.make_window("x", "x", True))

    def test_build_provider_never_reports_ok_without_data(self):
        provider = pu.build_provider("kimi", pu.STATUS_OK, "test")
        self.assertEqual(provider["status"], pu.STATUS_UNAVAILABLE)
        self.assertFalse(provider["available"])
        self.assertIn("no usage windows", provider["description"])

    def test_build_provider_adds_sign_in_hint_for_signed_out_statuses(self):
        provider = pu.build_provider("codex", pu.STATUS_NOT_LOGGED_IN, "test", description="nope")
        self.assertIn("codex login", provider["signInHint"])
        self.assertIsNone(pu.build_provider("codex", pu.STATUS_UNSUPPORTED, "test", description="x")["signInHint"])

    def test_build_provider_picks_five_hour_window_as_primary(self):
        provider = pu.build_provider(
            "claude", pu.STATUS_OK, "test",
            windows=[pu.make_window("seven_day", "Weekly", 40, kind="weekly"), pu.make_window("five_hour", "5h", 10, kind="five_hour")],
        )
        self.assertTrue(provider["available"])
        self.assertEqual(provider["usedPercent"], 10.0)
        self.assertEqual(provider["weekly"]["usedPercent"], 40.0)
        self.assertEqual(provider["hourly"]["usedPercent"], 10.0)


class ClaudeUsageTests(unittest.TestCase):
    def write_claude_home(self, home, *, expires_in_ms=3_600_000, now_ms=1_792_836_000_000):
        os.makedirs(os.path.join(home, ".claude"), exist_ok=True)
        with open(os.path.join(home, ".claude", ".credentials.json"), "w", encoding="utf-8") as handle:
            json.dump({"claudeAiOauth": {
                "accessToken": "sk-ant-oat01-test",
                "refreshToken": "sk-ant-ort01-test",
                "expiresAt": now_ms + expires_in_ms,
                "subscriptionType": "max",
                "rateLimitTier": "default_claude_max_5x",
            }}, handle)
        with open(os.path.join(home, ".claude.json"), "w", encoding="utf-8") as handle:
            json.dump({"oauthAccount": {"emailAddress": "user@example.com", "organizationName": "Example Org"}}, handle)

    def test_parse_live_payload_shape(self):
        windows = pu.parse_claude_oauth_usage(CLAUDE_USAGE_PAYLOAD)
        by_id = {w["id"]: w for w in windows}
        self.assertEqual(set(by_id), {"five_hour", "seven_day", "weekly_scoped:Fable"})
        self.assertEqual(by_id["five_hour"]["usedPercent"], 9.0)
        self.assertEqual(by_id["five_hour"]["kind"], "five_hour")
        self.assertEqual(by_id["five_hour"]["resetTime"], "2026-10-24T14:49:59Z")
        self.assertEqual(by_id["seven_day"]["usedPercent"], 14.0)
        self.assertEqual(by_id["seven_day"]["kind"], "weekly")
        self.assertEqual(by_id["weekly_scoped:Fable"]["usedPercent"], 25.0)
        self.assertTrue(by_id["weekly_scoped:Fable"]["isActive"])
        # Disabled extra usage is not a window.
        self.assertNotIn("extra_usage", by_id)

    def test_parse_includes_enabled_extra_usage_and_locked_reason(self):
        payload = {
            "five_hour": {"utilization": 100.0, "resets_at": 1792836000, "locked_reason": "rate_limited"},
            "extra_usage": {"is_enabled": True, "monthly_limit": 50, "used_credits": 12.5, "utilization": 25.0, "currency": "USD"},
        }
        by_id = {w["id"]: w for w in pu.parse_claude_oauth_usage(payload)}
        self.assertEqual(by_id["five_hour"]["description"], "Locked: rate_limited")
        self.assertEqual(by_id["five_hour"]["resetTime"], "2026-10-24T10:00:00Z")
        self.assertEqual(by_id["extra_usage"]["usedPercent"], 25.0)
        self.assertIn("12.50 of 50 USD", by_id["extra_usage"]["description"])

    def test_not_signed_in_when_no_credentials(self):
        with tempfile.TemporaryDirectory() as home:
            http = fake_http()
            provider = pu.fetch_claude_account_usage(home=home, http=http)
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)
        self.assertFalse(provider["available"])
        self.assertEqual(http.calls, [])

    def test_expired_token_is_reported_without_a_network_call(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_claude_home(home, expires_in_ms=-1)
            http = fake_http()
            provider = pu.fetch_claude_account_usage(home=home, http=http, now=1_792_836_000.0)
        self.assertEqual(provider["status"], pu.STATUS_TOKEN_EXPIRED)
        self.assertEqual(provider["account"]["email"], "user@example.com")
        self.assertEqual(provider["account"]["plan"], "Claude Max 5x")
        self.assertEqual(http.calls, [])
        self.assertIn("claude", provider["signInHint"].lower())

    def test_live_usage_uses_the_stored_oauth_token(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_claude_home(home)
            http = fake_http(200, CLAUDE_USAGE_PAYLOAD)
            provider = pu.fetch_claude_account_usage(home=home, http=http, now=1_792_836_000.0)
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertTrue(provider["available"])
        self.assertEqual(provider["source"], "anthropic_oauth_usage")
        self.assertEqual(provider["hourly"]["usedPercent"], 9.0)
        self.assertEqual(provider["weekly"]["usedPercent"], 14.0)
        self.assertEqual(provider["usedPercent"], 9.0)
        self.assertEqual(provider["account"], {"email": "user@example.com", "organization": "Example Org", "plan": "Claude Max 5x"})
        self.assertEqual(len(http.calls), 1)  # email came from the local cache, so no profile call
        self.assertEqual(http.calls[0]["url"], pu.CLAUDE_OAUTH_USAGE_URL)
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer sk-ant-oat01-test")
        self.assertEqual(http.calls[0]["headers"]["anthropic-beta"], "oauth-2025-04-20")

    def test_rejected_token_is_reported_as_expired_sign_in(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_claude_home(home)
            provider = pu.fetch_claude_account_usage(home=home, http=fake_http(401, {"error": "unauthorized"}), now=1_792_836_000.0)
        self.assertEqual(provider["status"], pu.STATUS_TOKEN_EXPIRED)
        self.assertFalse(provider["available"])
        self.assertIsNone(provider["usedPercent"])

    def test_network_failure_is_unavailable_not_zero(self):
        def failing_http(*args, **kwargs):
            raise pu.ProviderFetchError("connection refused")

        with tempfile.TemporaryDirectory() as home:
            self.write_claude_home(home)
            provider = pu.fetch_claude_account_usage(home=home, http=failing_http, now=1_792_836_000.0)
        self.assertEqual(provider["status"], pu.STATUS_UNAVAILABLE)
        self.assertIsNone(provider["usedPercent"])
        self.assertIn("connection refused", provider["description"])

    def test_profile_config_dir_is_preferred_over_home(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as config_dir:
            self.write_claude_home(home)
            with open(os.path.join(config_dir, ".credentials.json"), "w", encoding="utf-8") as handle:
                json.dump({"claudeAiOauth": {"accessToken": "profile-token", "expiresAt": 4102444800000, "subscriptionType": "pro"}}, handle)
            http = fake_http(200, CLAUDE_USAGE_PAYLOAD)
            provider = pu.fetch_claude_account_usage(home=home, config_dir=config_dir, http=http, now=1_792_836_000.0)
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer profile-token")
        self.assertEqual(provider["account"]["plan"], "Claude Pro")

    def test_cli_snapshot_fallback_is_marked_stale(self):
        cli_view = {
            "available": True, "source": "claude_cli", "status": "allowed",
            "hourly": {"usedPercent": 12.0, "remainingPercent": 88.0, "resetTime": "2026-10-24T04:40:00Z", "description": None},
            "weekly": None, "observedAt": "2026-10-24T00:00:00Z",
        }
        provider = pu.provider_from_claude_cli_snapshot(cli_view, reason="token expired.", account={"email": "u@example.com"})
        self.assertEqual(provider["status"], pu.STATUS_STALE)
        self.assertTrue(provider["available"])
        self.assertEqual(provider["source"], "claude_cli")
        self.assertEqual(provider["hourly"]["usedPercent"], 12.0)
        self.assertIsNone(provider["weekly"])
        self.assertIn("token expired.", provider["description"])
        self.assertIn("2026-10-24T00:00:00Z", provider["description"])


class CodexProviderTests(unittest.TestCase):
    def test_logged_out_app_server_is_not_signed_in(self):
        status = {"ok": True, "account": None, "requiresOpenaiAuth": True, "rateLimits": None,
                  "error": "codex account authentication required to read rate limits", "sawAccount": True}
        provider = pu.build_codex_provider(status)
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)
        self.assertFalse(provider["available"])
        self.assertIn("codex login", provider["signInHint"])

    def test_signed_in_account_windows_are_labelled_by_duration(self):
        status = {
            "ok": True, "sawAccount": True, "requiresOpenaiAuth": False,
            "account": {"type": "chatgpt", "email": "dev@example.com", "planType": "plus"},
            "rateLimits": {
                "available": True, "limitId": "codex", "limitName": None, "planType": "plus",
                "primary": {"usedPercent": 37, "remainingPercent": 63, "windowDurationMins": 10080, "resetsAt": 1793400000},
                "secondary": {"usedPercent": 5, "remainingPercent": 95, "windowDurationMins": 300, "resetsAt": 1792850000},
                "availableResets": 2,
            },
            "error": None,
        }
        provider = pu.build_codex_provider(status)
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertEqual(provider["account"], {"email": "dev@example.com", "plan": "ChatGPT Plus", "label": None})
        self.assertEqual(provider["weekly"]["usedPercent"], 37.0)
        self.assertEqual(provider["weekly"]["resetTime"], "2026-10-30T22:40:00Z")
        self.assertEqual(provider["hourly"]["usedPercent"], 5.0)
        self.assertEqual(provider["usedPercent"], 5.0)
        self.assertEqual(provider["description"], "2 available resets.")

    def test_signed_in_openai_auth_mode_with_requires_openai_auth_true_is_ok(self):
        # Codex CLI sets requiresOpenaiAuth=True whenever the active provider
        # uses OpenAI auth, even when the user IS signed in and account is non-null.
        status = {
            "ok": True, "sawAccount": True, "requiresOpenaiAuth": True,
            "account": {"type": "chatgpt", "email": "pro@example.com", "planType": "self_serve_business_prolite"},
            "rateLimits": {
                "available": True, "limitId": "codex", "limitName": None, "planType": "self_serve_business_prolite",
                "primary": {"usedPercent": 100, "remainingPercent": 0, "windowDurationMins": 10080, "resetsAt": 1794897471},
                "secondary": None,
                "availableResets": 0,
            },
            "error": None,
        }
        provider = pu.build_codex_provider(status)
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertTrue(provider["available"])
        self.assertEqual(provider["account"], {"email": "pro@example.com", "plan": "ChatGPT Pro Lite", "label": None})
        self.assertEqual(provider["weekly"]["usedPercent"], 100.0)
        self.assertEqual(provider["description"], "0 available resets.")

    def test_cli_failure_is_unavailable(self):
        provider = pu.build_codex_provider(None, error="codex not installed")
        self.assertEqual(provider["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("codex not installed", provider["description"])
        provider = pu.build_codex_provider({"ok": False, "error": "did not answer"})
        self.assertEqual(provider["status"], pu.STATUS_UNAVAILABLE)

    def test_expired_jwt_is_reported_as_token_expired(self):
        status = {
            "ok": True,
            "account": None,
            "requiresOpenaiAuth": True,
            "rateLimits": None,
            "error": "GET https://chatgpt.com/backend-api/wham/usage failed: 401 Unauthorized; invalid_jwt",
            "sawAccount": True,
        }
        provider = pu.build_codex_provider(status)
        self.assertEqual(provider["status"], pu.STATUS_TOKEN_EXPIRED)
        self.assertFalse(provider["available"])
        self.assertIn("codex login", provider["signInHint"])


class AntigravityProviderTests(unittest.TestCase):
    def test_bucket_parsing_rejects_junk_fractions(self):
        for value in [None, "invalid", -0.1, 1.1, float("nan"), float("inf"), True]:
            with self.subTest(value=value):
                buckets = pu.parse_antigravity_quota_summary({"groups": [{"displayName": "Gemini", "buckets": [{"bucketId": "weekly", "remainingFraction": value}]}]})
                self.assertIsNone(buckets["gemini"]["weekly"])

    def test_bucket_parsing_keeps_real_values_and_groups(self):
        buckets = pu.parse_antigravity_quota_summary({"groups": [
            {"displayName": "Gemini Models", "buckets": [
                {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.96, "resetTime": "2026-08-19T05:13:52Z", "description": "weekly text"},
                {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0},
            ]},
            {"displayName": "Claude and GPT models", "buckets": [{"bucketId": "3p-weekly", "remainingFraction": 1.0}]},
        ]})
        self.assertEqual(buckets["gemini"]["weekly"]["usedPercent"], 4.0)
        self.assertEqual(buckets["gemini"]["weekly"]["description"], "weekly text")
        self.assertEqual(buckets["gemini"]["hourly"]["usedPercent"], 100.0)
        self.assertEqual(buckets["claude"]["weekly"]["remainingPercent"], 100.0)
        self.assertIsNone(buckets["claude"]["hourly"])

    def test_signed_out_and_unavailable_are_distinguished(self):
        gemini, claude, _ = pu.build_antigravity_providers(None, signed_in=False)
        self.assertEqual(gemini["status"], pu.STATUS_NOT_LOGGED_IN)
        self.assertEqual(claude["status"], pu.STATUS_NOT_LOGGED_IN)
        gemini, _, _ = pu.build_antigravity_providers(None, signed_in=True, error="timed out")
        self.assertEqual(gemini["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("timed out", gemini["description"])
        gemini, claude, _ = pu.build_antigravity_providers(
            {"userStatus": {"email": "g@example.com"}, "quotaSummary": {"groups": [{"displayName": "Gemini", "buckets": [{"bucketId": "5h", "remainingFraction": 0.5}]}]}},
            signed_in=True, plan_name="Google AI Pro", email="g@example.com",
        )
        self.assertEqual(gemini["status"], pu.STATUS_OK)
        self.assertEqual(gemini["hourly"]["usedPercent"], 50.0)
        self.assertEqual(gemini["account"], {"email": "g@example.com", "plan": "Google AI Pro"})
        self.assertEqual(claude["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("no Claude/GPT quota windows", claude["description"])

    def test_antigravity_signed_in_checks_windows_credential_for_default_home_only(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as home, \
             patch("provider_usage.os.name", "nt"), \
             patch("provider_usage.os.path.expanduser", side_effect=lambda p: home if p == "~" else p), \
             patch("provider_usage.read_windows_antigravity_credential", return_value={"token": {"access_token": "tok"}}, create=True) as read_cred:
            self.assertTrue(pu.antigravity_signed_in(None))
            self.assertTrue(pu.antigravity_signed_in(home))
            self.assertEqual(read_cred.call_count, 2)

            # Explicit isolated profile must not fall back to host Windows Credential Manager.
            read_cred.reset_mock()
            with tempfile.TemporaryDirectory() as isolated:
                self.assertFalse(pu.antigravity_signed_in(isolated))
                read_cred.assert_not_called()

    def test_decode_macos_keychain_json_formats(self):
        import base64

        payload = {"token": {"access_token": "abc"}, "id_token_email": "u@example.com"}
        raw_json = json.dumps(payload)
        b64_payload = "go-keyring-base64:" + base64.b64encode(raw_json.encode("utf-8")).decode("ascii")
        hex_payload = raw_json.encode("utf-8").hex()

        self.assertEqual(pu._decode_macos_keychain_json(raw_json), payload)
        self.assertEqual(pu._decode_macos_keychain_json(b64_payload), payload)
        self.assertEqual(pu._decode_macos_keychain_json(hex_payload), payload)
        self.assertIsNone(pu._decode_macos_keychain_json("not-json"))
        self.assertIsNone(pu._decode_macos_keychain_json(""))

    def test_antigravity_signed_in_checks_macos_keychain_for_default_home_only(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as home, \
             patch("provider_usage.os.name", "posix"), \
             patch("provider_usage.sys.platform", "darwin"), \
             patch("provider_usage.os.path.expanduser", side_effect=lambda p: home if p == "~" else p), \
             patch("provider_usage.read_macos_antigravity_credential", return_value={"token": {"access_token": "tok"}}) as read_cred:
            self.assertTrue(pu.antigravity_signed_in(None))
            self.assertTrue(pu.antigravity_signed_in(home))
            self.assertEqual(read_cred.call_count, 2)

            # Explicit isolated profile must not fall back to host macOS Keychain.
            read_cred.reset_mock()
            with tempfile.TemporaryDirectory() as isolated:
                self.assertFalse(pu.antigravity_signed_in(isolated))
                read_cred.assert_not_called()

    def test_claude_oauth_checks_macos_keychain_for_default_home_only(self):
        from unittest.mock import patch

        fake_cred = {
            "accessToken": "sk-ant-keychain",
            "expiresAt": 4102444800000.0,
            "subscriptionType": "max",
            "rateLimitTier": "default_claude_max_5x",
            "path": "keychain:Claude Code-credentials",
        }
        with tempfile.TemporaryDirectory() as home, \
             patch("provider_usage.sys.platform", "darwin"), \
             patch("provider_usage.os.path.expanduser", side_effect=lambda p: home if p == "~" else p), \
             patch.dict(os.environ, {}, clear=False), \
             patch("provider_usage.read_macos_claude_credential", return_value=fake_cred) as read_cred:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(pu.load_claude_oauth_credentials(None), fake_cred)
            self.assertEqual(pu.load_claude_oauth_credentials(home), fake_cred)
            self.assertEqual(read_cred.call_count, 2)

            # Isolated home or explicit config_dir must not fall back to host macOS Keychain.
            read_cred.reset_mock()
            with tempfile.TemporaryDirectory() as isolated:
                self.assertIsNone(pu.load_claude_oauth_credentials(isolated))
                self.assertIsNone(pu.load_claude_oauth_credentials(None, config_dir=isolated))
                read_cred.assert_not_called()


class KimiProviderTests(unittest.TestCase):
    def test_not_signed_in_without_token(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".kimi-code"))
            provider = pu.fetch_kimi_account_usage(home=home, http=fake_http(), env={})
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)

    def test_oauth_credentials_and_region_pick_the_endpoint(self):
        with tempfile.TemporaryDirectory() as home:
            kdir = os.path.join(home, ".kimi-code")
            os.makedirs(os.path.join(kdir, "credentials"))
            with open(os.path.join(kdir, "region"), "w") as handle:
                handle.write("global\n")
            with open(os.path.join(kdir, "credentials", "kimi-code.json"), "w") as handle:
                json.dump({"access_token": "kimi-oauth-token", "refresh_token": "r", "expiry_date": 4102444800000}, handle)
            payload = {
                "usage": {"limit": "500", "used": "125", "remaining": "375", "resetTime": "2026-10-30T00:00:00Z"},
                "limits": [{"window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
                            "detail": {"limit": "100", "used": "40", "remaining": "60", "resetTime": "2026-10-24T15:00:00Z"}}],
            }
            http = fake_http(200, payload)
            provider = pu.fetch_kimi_account_usage(home=home, http=http, env={}, now=1_792_836_000.0)
        self.assertEqual(http.calls[0]["url"], "https://api.kimi.ai/coding/v1/usages")
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer kimi-oauth-token")
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertEqual(provider["hourly"]["usedPercent"], 40.0)
        self.assertEqual(provider["hourly"]["description"], "40 of 100 used")
        self.assertEqual(provider["weekly"]["usedPercent"], 25.0)
        self.assertEqual(provider["account"]["label"], "Kimi account")

    def test_config_api_key_is_used_and_expiry_ignored_for_keys(self):
        with tempfile.TemporaryDirectory() as home:
            kdir = os.path.join(home, ".kimi-code")
            os.makedirs(kdir)
            with open(os.path.join(kdir, "config.toml"), "w") as handle:
                handle.write('[providers."managed:kimi-code"]\ntype = "kimi"\nbase_url = "https://api.kimi.com/coding/v1"\napi_key = "sk-kimi-abc"\n')
            http = fake_http(401, {"error": {"message": "Invalid Authentication"}})
            provider = pu.fetch_kimi_account_usage(home=home, http=http, env={})
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer sk-kimi-abc")
        self.assertEqual(provider["status"], pu.STATUS_AUTH_REJECTED)

    def test_unknown_payload_shape_is_unavailable(self):
        with tempfile.TemporaryDirectory() as home:
            kdir = os.path.join(home, ".kimi-code")
            os.makedirs(os.path.join(kdir, "credentials"))
            with open(os.path.join(kdir, "credentials", "kimi-code.json"), "w") as handle:
                json.dump({"access_token": "t"}, handle)
            provider = pu.fetch_kimi_account_usage(home=home, http=fake_http(200, {"totalQuota": {"x": 1}}), env={})
        self.assertEqual(provider["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("does not recognise", provider["description"])


class GrokProviderTests(unittest.TestCase):
    def write_auth(self, home, expires_at="2099-01-01T00:00:00Z"):
        os.makedirs(os.path.join(home, ".grok"))
        with open(os.path.join(home, ".grok", "auth.json"), "w") as handle:
            json.dump({"https://auth.x.ai/scope": {"key": "jwt", "refresh_token": "r", "expires_at": expires_at, "email": "x@example.com", "auth_mode": "oauth"}}, handle)

    def test_not_signed_in_without_auth_file(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_grok_account_usage(home=home, executable="/bin/true", rpc=lambda *a, **k: {"result": {}})
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)

    def test_missing_billing_rpc_is_unsupported_not_zero(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_auth(home)
            provider = pu.fetch_grok_account_usage(home=home, executable="/bin/true", rpc=lambda *a, **k: {"error": {"code": -32601, "message": "Method not found"}})
        self.assertEqual(provider["status"], pu.STATUS_UNSUPPORTED)
        self.assertEqual(provider["account"]["email"], "x@example.com")
        self.assertIsNone(provider["usedPercent"])
        self.assertIn("/usage", provider["description"])

    def test_expired_login_is_reported(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_auth(home, expires_at="2020-01-01T00:00:00Z")
            provider = pu.fetch_grok_account_usage(home=home, executable="/bin/true", rpc=lambda *a, **k: {"result": {}})
        self.assertEqual(provider["status"], pu.STATUS_TOKEN_EXPIRED)

    def test_billing_result_becomes_monthly_window(self):
        result = {
            "billingCycle": {"billingPeriodStart": "2026-10-01T00:00:00Z", "billingPeriodEnd": "2026-11-01T00:00:00Z"},
            "monthlyLimit": {"val": 200}, "onDemandCap": {"val": 0}, "on_demand_enabled": False,
            "usage": {"includedUsed": {"val": 50}, "onDemandUsed": {"val": 0}, "totalUsed": {"val": 50}},
        }
        with tempfile.TemporaryDirectory() as home:
            self.write_auth(home)
            provider = pu.fetch_grok_account_usage(home=home, executable="/bin/true", rpc=lambda *a, **k: {"result": result})
        self.assertEqual(provider["status"], pu.STATUS_OK)
        window = provider["windows"][0]
        self.assertEqual(window["kind"], "monthly")
        self.assertEqual(window["usedPercent"], 25.0)
        self.assertEqual(window["resetTime"], "2026-11-01T00:00:00Z")


class MuseProviderTests(unittest.TestCase):
    def test_not_signed_in(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_muse_account_status(home=home, env={})
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)

    def test_signed_in_account_is_shown_but_quota_is_unsupported(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".config", "muse"))
            with open(os.path.join(home, ".config", "muse", "auth.json"), "w") as handle:
                json.dump({"schema_version": 1, "providers": {"meta": {"mechanism": "oauth", "storage": "file", "user_email": "m@example.com", "subs_active": True}}}, handle)
            provider = pu.fetch_muse_account_status(home=home, env={})
        self.assertEqual(provider["status"], pu.STATUS_UNSUPPORTED)
        self.assertFalse(provider["available"])
        self.assertEqual(provider["account"]["email"], "m@example.com")
        self.assertEqual(provider["account"]["plan"], "Subscription active")
        self.assertIn("mints a new inference key", provider["description"])

    def test_api_key_is_masked(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_muse_account_status(home=home, env={"META_API_KEY": "meta-secret-key-1234"})
        self.assertEqual(provider["status"], pu.STATUS_UNSUPPORTED)
        self.assertNotIn("meta-secret-key", provider["account"]["label"])
        self.assertIn("…1234", provider["account"]["label"])


class DeepSeekProviderTests(unittest.TestCase):
    def test_not_configured(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_deepseek_account_usage(home=home, http=fake_http(), env={})
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)

    def test_balance_from_documented_payload(self):
        # Example from https://api-docs.deepseek.com/api/get-user-balance
        payload = {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "110.00", "granted_balance": "10.00", "topped_up_balance": "100.00"}]}
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".deepcode"))
            with open(os.path.join(home, ".deepcode", "settings.json"), "w") as handle:
                json.dump({"env": {"MODEL": "deepseek-v4", "BASE_URL": "https://api.deepseek.com", "API_KEY": "sk-deepseek-1234"}}, handle)
            http = fake_http(200, payload)
            provider = pu.fetch_deepseek_account_usage(home=home, http=http, env={})
        self.assertEqual(http.calls[0]["url"], pu.DEEPSEEK_BALANCE_URL)
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer sk-deepseek-1234")
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertTrue(provider["available"])
        self.assertEqual(provider["windows"], [])
        self.assertEqual(provider["balances"], [{"currency": "CNY", "total": 110.0, "granted": 10.0, "toppedUp": 100.0}])
        self.assertIn("Balance 110.00 CNY", provider["description"])
        self.assertNotIn("sk-deepseek-1234", json.dumps(provider))

    def test_other_base_url_is_unsupported_and_bad_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_deepseek_account_usage(home=home, http=fake_http(), env={"DEEPSEEK_API_KEY": "k", "DEEPSEEK_BASE_URL": "https://ark.cn-beijing.volces.com/api/coding/v3"})
            self.assertEqual(provider["status"], pu.STATUS_UNSUPPORTED)
            provider = pu.fetch_deepseek_account_usage(home=home, http=fake_http(401, None), env={"DEEPSEEK_API_KEY": "k"})
            self.assertEqual(provider["status"], pu.STATUS_AUTH_REJECTED)


class ZaiProviderTests(unittest.TestCase):
    # Payload reported for GET /api/monitor/usage/quota/limit (onllm-dev/onWatch#122, Sept 2026).
    QUOTA_PAYLOAD = {
        "code": 200, "msg": "Operation successful", "success": True,
        "data": {"limits": [
            {"type": "CREDIT_LIMIT", "unit": 3, "number": 5, "usage": 2000, "currentValue": 402, "remaining": 1597, "percentage": 20, "nextResetTime": 1788351145586},
            {"type": "CREDIT_LIMIT", "unit": 6, "number": 1, "usage": 10000, "currentValue": 5207, "remaining": 4792, "percentage": 52, "nextResetTime": 1788784466996},
        ], "level": "lite"},
    }

    def write_opencode_auth(self, home, provider_id="zai-coding-plan"):
        os.makedirs(os.path.join(home, ".local", "share", "opencode"))
        with open(os.path.join(home, ".local", "share", "opencode", "auth.json"), "w") as handle:
            json.dump({provider_id: {"type": "api", "key": "zai-key-9876"}}, handle)

    def test_not_configured(self):
        with tempfile.TemporaryDirectory() as home:
            provider = pu.fetch_zai_account_usage(home=home, http=fake_http(), env={})
        self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)

    def test_quota_windows_and_plan_level(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_opencode_auth(home)
            http = fake_http(200, self.QUOTA_PAYLOAD)
            provider = pu.fetch_zai_account_usage(home=home, http=http, env={})
        self.assertEqual(http.calls[0]["url"], "https://api.z.ai/api/monitor/usage/quota/limit")
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "zai-key-9876")  # raw key, no Bearer
        self.assertEqual(provider["status"], pu.STATUS_OK)
        self.assertEqual(provider["hourly"]["usedPercent"], 20.0)
        self.assertEqual(provider["hourly"]["resetTime"], "2026-09-02T12:12:25Z")
        self.assertEqual(provider["hourly"]["description"], "402 of 2,000 credits used")
        self.assertEqual(provider["weekly"]["usedPercent"], 52.0)
        self.assertEqual(provider["account"]["plan"], "GLM Coding Plan Lite")
        self.assertNotIn("zai-key-9876", json.dumps(provider))

    def test_zhipu_provider_uses_bigmodel_host(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_opencode_auth(home, provider_id="zhipu")
            http = fake_http(200, self.QUOTA_PAYLOAD)
            pu.fetch_zai_account_usage(home=home, http=http, env={})
        self.assertEqual(http.calls[0]["url"], "https://open.bigmodel.cn/api/monitor/usage/quota/limit")

    def test_api_level_auth_error_is_rejected_key(self):
        with tempfile.TemporaryDirectory() as home:
            self.write_opencode_auth(home)
            body = {"code": 1001, "msg": "Authentication parameter not received in Header, unable to authenticate", "success": False}
            provider = pu.fetch_zai_account_usage(home=home, http=fake_http(200, body), env={})
        self.assertEqual(provider["status"], pu.STATUS_AUTH_REJECTED)
        self.assertIsNone(provider["usedPercent"])


if __name__ == "__main__":
    unittest.main()
