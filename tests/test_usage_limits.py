"""/api/usage-limits must report each provider's live account usage, never estimates."""
import os
import sys
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import provider_usage as pu  # noqa: E402


def signed_out(provider_id):
    return pu.build_provider(provider_id, pu.STATUS_NOT_LOGGED_IN, "test", description=f"{provider_id} is not signed in (test)")


def codex_logged_out():
    return {
        "ok": True, "account": None, "requiresOpenaiAuth": True, "rateLimits": None,
        "error": "codex account authentication required to read rate limits", "sawAccount": True,
    }


def codex_logged_in():
    return {
        "ok": True, "sawAccount": True, "requiresOpenaiAuth": False,
        "account": {"type": "chatgpt", "email": "dev@example.com", "planType": "plus"},
        "rateLimits": {
            "available": True, "limitId": "codex", "limitName": None, "planType": "plus",
            "primary": {"usedPercent": 37, "remainingPercent": 63, "windowDurationMins": 10080, "resetsAt": 1793400000},
            "secondary": {"usedPercent": 5, "remainingPercent": 95, "windowDurationMins": 300, "resetsAt": 1792850000},
            "availableResets": 0,
        },
        "error": None,
    }


def claude_live():
    return pu.build_provider(
        "claude", pu.STATUS_OK, "anthropic_oauth_usage",
        account={"email": "user@example.com", "organization": "Example Org", "plan": "Claude Max 5x"},
        windows=[
            pu.make_window("five_hour", "Five Hour Limit", 9.0, kind="five_hour", reset_time="2026-10-24T14:49:59Z"),
            pu.make_window("seven_day", "Weekly Limit", 14.0, kind="weekly", reset_time="2026-10-30T04:59:59Z"),
        ],
    )


ANTIGRAVITY_SUMMARY = {
    "userStatus": {"userTier": {"name": "Google AI Ultra"}, "email": "g@example.com"},
    "quotaSummary": {
        "groups": [
            {
                "displayName": "Gemini Models",
                "buckets": [
                    {"bucketId": "gemini-weekly", "window": "weekly", "remainingFraction": 0.96, "resetTime": "2026-08-19T05:13:52Z",
                     "description": "You have used some of your weekly limit, it will fully refresh in 4 days, 3 hours."},
                    {"bucketId": "gemini-5h", "window": "5h", "remainingFraction": 0.97, "resetTime": "2026-08-15T02:20:36Z",
                     "description": "You have used some of your 5-hour limit, it will fully refresh in 1 hour, 8 minutes."},
                ],
            },
            {
                "displayName": "Claude and GPT models",
                "buckets": [
                    {"bucketId": "3p-weekly", "window": "weekly", "remainingFraction": 1.0, "resetTime": "2026-08-22T01:23:54Z"},
                    {"bucketId": "3p-5h", "window": "5h", "remainingFraction": 1.0, "resetTime": "2026-08-15T06:23:54Z"},
                ],
            },
        ]
    },
}


class UsageLimitsTestCase(unittest.TestCase):
    """Every provider lookup is stubbed so the suite never touches the network or a CLI."""

    def setUp(self):
        self.client = TestClient(main.app)
        main._claude_rate_limits_by_profile.clear()
        self.addCleanup(main._claude_rate_limits_by_profile.clear)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("main.verify_authorization", return_value=True))
        self.stack.enter_context(patch("main.get_default_profile", return_value=None))
        self.stack.enter_context(patch("main.antigravity_signed_in", return_value=False))
        self.mocks = {
            "claude": self.stack.enter_context(patch("main.fetch_claude_account_usage", return_value=signed_out("claude"))),
            "codex": self.stack.enter_context(patch("main.fetch_codex_account_status", return_value=codex_logged_out())),
            "antigravity": self.stack.enter_context(patch("main.fetch_antigravity_language_server_quota", return_value=None)),
            "kimi": self.stack.enter_context(patch("main.fetch_kimi_account_usage", return_value=signed_out("kimi"))),
            "grok": self.stack.enter_context(patch("main.fetch_grok_account_usage", return_value=signed_out("grok"))),
            "muse": self.stack.enter_context(patch("main.fetch_muse_account_status", return_value=signed_out("muse"))),
            "deepseek": self.stack.enter_context(patch("main.fetch_deepseek_account_usage", return_value=signed_out("deepseek"))),
            "zai": self.stack.enter_context(patch("main.fetch_zai_account_usage", return_value=signed_out("zai"))),
        }

    def get(self, query=""):
        response = self.client.get(f"/api/usage-limits{query}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class TestUsageLimitsAPI(UsageLimitsTestCase):
    def test_every_provider_is_reported_even_when_signed_out(self):
        data = self.get()
        self.assertEqual(data["providerOrder"], pu.PROVIDER_ORDER)
        self.assertEqual(set(data["providers"]), set(pu.PROVIDER_ORDER))
        for provider_id, provider in data["providers"].items():
            with self.subTest(provider=provider_id):
                self.assertFalse(provider["available"])
                self.assertIsNone(provider["usedPercent"])
                self.assertEqual(provider["windows"], [])
                self.assertEqual(provider["status"], pu.STATUS_NOT_LOGGED_IN)
                self.assertTrue(provider["signInHint"])
        # No invented token budgets or zero percentages for signed-out accounts.
        for key in ("gptWeeklyPercent", "gptHourlyPercent", "gptWeeklyLimit", "gptHourlyLimit",
                    "claudeWeeklyPercent", "claudeHourlyPercent", "claudeWeeklyUsed", "claudeWeeklyLimit",
                    "geminiWeeklyPercent", "geminiHourlyPercent", "geminiWeeklyUsed", "geminiWeeklyLimit",
                    "xaiWeeklyPercent", "xaiHourlyPercent", "xaiWeeklyUsed", "xaiWeeklyLimit"):
            self.assertIsNone(data[key], key)
        self.assertIsNone(data["codexRateLimits"])
        self.assertIsNone(data["antigravityClaudeRateLimits"])
        self.assertFalse(data["claudeRateLimits"]["available"])
        self.assertEqual(data["claudeRateLimits"]["status"], pu.STATUS_NOT_LOGGED_IN)
        self.assertFalse(data["geminiRateLimits"]["available"])
        self.assertEqual(data["geminiRateLimits"]["status"], pu.STATUS_NOT_LOGGED_IN)
        self.assertIsNone(data["antigravityPlan"])

    def test_claude_live_account_usage_feeds_legacy_fields(self):
        self.mocks["claude"].return_value = claude_live()
        data = self.get()
        claude = data["providers"]["claude"]
        self.assertTrue(claude["available"])
        self.assertEqual(claude["source"], "anthropic_oauth_usage")
        self.assertEqual(claude["account"]["email"], "user@example.com")
        self.assertEqual(data["claudeRateLimits"]["hourly"]["usedPercent"], 9.0)
        self.assertEqual(data["claudeRateLimits"]["weekly"]["usedPercent"], 14.0)
        self.assertEqual(data["claudeRateLimits"]["account"]["plan"], "Claude Max 5x")
        self.assertEqual(data["claudeHourlyPercent"], 9.0)
        self.assertEqual(data["claudeWeeklyPercent"], 14.0)
        self.assertEqual(data["claudeWeeklyLimit"], 100)

    def test_claude_falls_back_to_cli_snapshot_only_when_live_lookup_fails(self):
        now = time.time()
        main.record_claude_rate_limits(None, {
            "status": "allowed", "observedAt": now,
            "hourly": {"utilization": 0.12, "resetsAt": int(now) + 3600},
            "weekly": {"utilization": 0.07, "resetsAt": int(now) + 86400},
        })
        main.record_claude_rate_limits("prof_other", {
            "status": "allowed", "observedAt": now,
            "hourly": {"utilization": 0.9, "resetsAt": int(now) + 3600}, "weekly": None,
        })
        self.mocks["claude"].return_value = pu.build_provider(
            "claude", pu.STATUS_TOKEN_EXPIRED, "anthropic_oauth_usage", description="token expired."
        )
        data = self.get()
        self.assertTrue(data["claudeRateLimits"]["available"])
        self.assertEqual(data["claudeRateLimits"]["source"], "claude_cli")
        self.assertEqual(data["claudeRateLimits"]["status"], pu.STATUS_STALE)
        self.assertEqual(data["claudeRateLimits"]["hourly"]["usedPercent"], 12.0)
        self.assertEqual(data["claudeRateLimits"]["weekly"]["usedPercent"], 7.0)
        self.assertEqual(data["claudeHourlyPercent"], 12.0)
        self.assertEqual(data["claudeWeeklyPercent"], 7.0)
        self.assertIn("token expired.", data["providers"]["claude"]["description"])
        self.assertIsNone(data["antigravityClaudeRateLimits"])

        # A live answer wins over the snapshot.
        self.mocks["claude"].return_value = claude_live()
        data = self.get()
        self.assertEqual(data["claudeRateLimits"]["source"], "anthropic_oauth_usage")
        self.assertEqual(data["claudeHourlyPercent"], 9.0)

    def test_codex_signed_in_account_feeds_legacy_gpt_fields(self):
        self.mocks["codex"].return_value = codex_logged_in()
        data = self.get()
        codex = data["providers"]["codex"]
        self.assertEqual(codex["status"], pu.STATUS_OK)
        self.assertEqual(codex["account"]["email"], "dev@example.com")
        self.assertEqual(codex["weekly"]["usedPercent"], 37.0)
        self.assertEqual(codex["hourly"]["usedPercent"], 5.0)
        self.assertEqual(data["codexRateLimits"]["primary"]["usedPercent"], 37)
        self.assertEqual(data["codexRateLimits"]["account"]["plan"], "ChatGPT Plus")
        self.assertEqual(data["gptWeeklyPercent"], 37.0)
        self.assertEqual(data["gptWeeklyLimit"], 100)
        self.assertEqual(data["gptHourlyPercent"], 5.0)

    def test_codex_cli_failure_is_unavailable_not_zero(self):
        self.mocks["codex"].side_effect = RuntimeError("codex binary missing")
        data = self.get()
        self.assertEqual(data["providers"]["codex"]["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("codex binary missing", data["providers"]["codex"]["description"])
        self.assertIsNone(data["gptWeeklyPercent"])
        self.assertIsNone(data["codexRateLimits"])

    def test_antigravity_quota_summary_feeds_gemini_and_antigravity_claude(self):
        self.mocks["antigravity"].return_value = ANTIGRAVITY_SUMMARY
        data = self.get()
        self.assertEqual(data["antigravityPlan"], "Google AI Ultra")
        self.assertEqual(data["geminiWeeklyPercent"], 4.0)
        self.assertEqual(data["geminiHourlyPercent"], 3.0)
        self.assertEqual(data["geminiRateLimits"]["weekly"]["remainingPercent"], 96.0)
        self.assertEqual(data["geminiRateLimits"]["hourly"]["remainingPercent"], 97.0)
        self.assertEqual(data["geminiRateLimits"]["weekly"]["description"],
                         "You have used some of your weekly limit, it will fully refresh in 4 days, 3 hours.")
        gemini = data["providers"]["antigravity"]
        self.assertEqual(gemini["status"], pu.STATUS_OK)
        self.assertEqual(gemini["account"], {"email": "g@example.com", "plan": "Google AI Ultra"})
        self.assertEqual(gemini["hourly"]["usedPercent"], 3.0)
        # Antigravity's "Claude and GPT models" group meters Antigravity-served
        # models; it must not be reported as the Claude Code account quota.
        agy_claude = data["antigravityClaudeRateLimits"]
        self.assertEqual(agy_claude["source"], "antigravity")
        self.assertEqual(agy_claude["weekly"]["remainingPercent"], 100.0)
        self.assertEqual(agy_claude["hourly"]["remainingPercent"], 100.0)
        self.assertEqual(data["providers"]["antigravity_claude"]["status"], pu.STATUS_OK)
        self.assertFalse(data["claudeRateLimits"]["available"])
        self.assertIsNone(data["claudeWeeklyPercent"])

    def test_antigravity_model_quota_is_not_account_quota(self):
        self.mocks["antigravity"].return_value = {
            "userTier": {"name": "Google AI Ultra"},
            "cascadeModelConfigData": {"clientModelConfigs": [
                {"modelId": "gemini-3.7-flash-high", "quotaInfo": {"remainingFraction": 0.965, "resetTime": "2026-08-14T04:57:06Z"}}
            ]},
        }
        data = self.get()
        self.assertFalse(data["geminiRateLimits"]["available"])
        self.assertIsNone(data["geminiRateLimits"]["usedPercent"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        self.assertIsNone(data["geminiHourlyPercent"])
        self.assertEqual(data["providers"]["antigravity"]["status"], pu.STATUS_UNAVAILABLE)

    def test_email_mismatch_discards_language_server_quota(self):
        profile = {"id": "prof_ultra", "cli_id": "agy", "label": "Google AI Ultra", "profile_root": "/isolated/prof_ultra", "email": "profile@example.com"}
        self.mocks["antigravity"].return_value = ANTIGRAVITY_SUMMARY  # reports g@example.com
        with patch("main.get_profile", return_value=profile):
            data = self.get("?profile_id=prof_ultra")
        self.assertFalse(data["geminiRateLimits"]["available"])
        self.assertIsNone(data["antigravityPlan"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        self.assertIn("different account", data["providers"]["antigravity"]["description"])
        self.mocks["antigravity"].assert_called_with(profile_root="/isolated/prof_ultra")

    def test_selected_profile_only_redirects_its_own_cli(self):
        profile = {"id": "prof_claude", "cli_id": "claude", "profile_root": "/profiles/claude", "config_dir": "/profiles/claude/.claude-config"}
        with patch("main.get_profile", return_value=profile):
            data = self.get("?profile_id=prof_claude")
        self.assertEqual(data["targetProfileId"], "prof_claude")
        self.mocks["claude"].assert_called_with(home="/profiles/claude", config_dir="/profiles/claude/.claude-config")
        # Other providers keep reading the host sign-in, not the Claude profile's root.
        self.mocks["antigravity"].assert_called_with(profile_root=None)
        self.mocks["kimi"].assert_called_with(home=None)

    def test_other_provider_entries_pass_through_and_failures_are_reported(self):
        self.mocks["zai"].return_value = pu.build_provider(
            "zai", pu.STATUS_OK, "zai_usage_monitor", account={"plan": "GLM Coding Plan Lite"},
            windows=[pu.make_window("five_hour", "Five Hour Limit", 20, kind="five_hour")],
        )
        self.mocks["grok"].side_effect = TimeoutError("grok timed out")
        data = self.get()
        self.assertEqual(data["providers"]["zai"]["usedPercent"], 20.0)
        self.assertEqual(data["providers"]["zai"]["account"]["plan"], "GLM Coding Plan Lite")
        self.assertEqual(data["providers"]["grok"]["status"], pu.STATUS_UNAVAILABLE)
        self.assertIn("grok timed out", data["providers"]["grok"]["description"])
        self.assertEqual(data["xaiUsageNote"], data["providers"]["grok"]["description"])

    def test_unknown_profile_is_404_and_falsy_profile_ids_are_default(self):
        with patch("main.get_profile", return_value=None):
            response = self.client.get("/api/usage-limits?profile_id=deleted-profile")
            self.assertEqual(response.status_code, 404)
        for pid in ["null", "undefined", "none", "default", "", "   "]:
            with self.subTest(profile_id=pid):
                data = self.get(f"?profile_id={pid}")
                self.assertIsNone(data["targetProfileId"])


if __name__ == "__main__":
    unittest.main()
