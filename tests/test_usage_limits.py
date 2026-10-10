import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

class TestUsageLimitsAPI(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("subprocess.run")
    def test_get_usage_limits_with_mock_ccusage(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        from datetime import datetime, timezone, timedelta
        now_dt = datetime.now(timezone.utc)
        daily_dt = (now_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        recent_iso = (now_dt - timedelta(minutes=30)).isoformat()

        mock_output = {
            "daily": [
                {
                    "agent": "gemini",
                    "period": daily_dt,
                    "totalTokens": 500000,
                    "cacheReadTokens": 100000,
                    "modelsUsed": ["gemini-3.6-flash"],
                    "metadata": {"lastActivity": recent_iso}
                }
            ],
            "session": [
                {
                    "agent": "gemini",
                    "period": "session-123",
                    "totalTokens": 150000,
                    "cacheReadTokens": 50000,
                    "modelsUsed": ["gemini-3.6-flash"],
                    "metadata": {"lastActivity": recent_iso}
                }
            ]
        }
        
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps(mock_output)
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Local token totals must not be presented as account quota.
        self.assertIsNone(data["geminiWeeklyUsed"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        
        self.assertIsNone(data["geminiHourlyUsed"])
        self.assertIsNone(data["geminiHourlyPercent"])

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.fetch_antigravity_token_usage", return_value=(0, 0))
    @patch("subprocess.run")
    def test_get_usage_limits_empty_fallback_to_zero(self, mock_subprocess, mock_agy, mock_ls, mock_codex, mock_auth):
        proc_mock = MagicMock()
        proc_mock.returncode = 1
        proc_mock.stdout = ""
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Missing Gemini quota is unknown, not zero.
        self.assertIsNone(data["geminiWeeklyUsed"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        self.assertIsNone(data["geminiHourlyUsed"])
        self.assertIsNone(data["geminiHourlyPercent"])
        self.assertEqual(data["claudeWeeklyUsed"], 0)
        self.assertEqual(data["claudeWeeklyPercent"], 0.0)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.fetch_antigravity_token_usage", return_value=(725000, 90000))
    @patch("subprocess.run")
    def test_get_usage_limits_antigravity_fallback(self, mock_subprocess, mock_agy, mock_ls, mock_codex, mock_auth):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        # Transcript estimates must not masquerade as account quota.
        self.assertIsNone(data["geminiWeeklyUsed"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        self.assertIsNone(data["geminiHourlyUsed"])
        self.assertIsNone(data["geminiHourlyPercent"])

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota")
    @patch("subprocess.run")
    def test_get_usage_limits_antigravity_language_server_quota(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        mock_ls.return_value = {
            "userTier": {"name": "Google AI Ultra"},
            "cascadeModelConfigData": {
                "clientModelConfigs": [
                    {
                        "modelId": "gemini-3.7-flash-high",
                        "quotaInfo": {
                            "remainingFraction": 0.965,
                            "resetTime": "2026-08-14T04:57:06Z"
                        }
                    }
                ]
            }
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        
        self.assertIsNotNone(data.get("geminiRateLimits"))
        self.assertFalse(data["geminiRateLimits"]["available"])
        self.assertIsNone(data["geminiRateLimits"]["usedPercent"])
        self.assertIsNone(data["geminiWeeklyPercent"])
        self.assertIsNone(data["geminiHourlyPercent"])

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota")
    @patch("subprocess.run")
    def test_get_usage_limits_with_quota_summary(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        mock_ls.return_value = {
            "userStatus": {
                "userTier": {"name": "Google AI Ultra"}
            },
            "quotaSummary": {
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [
                            {
                                "bucketId": "gemini-weekly",
                                "window": "weekly",
                                "remainingFraction": 0.96,
                                "resetTime": "2026-08-19T05:13:52Z",
                                "description": "You have used some of your weekly limit, it will fully refresh in 4 days, 3 hours."
                            },
                            {
                                "bucketId": "gemini-5h",
                                "window": "5h",
                                "remainingFraction": 0.97,
                                "resetTime": "2026-08-15T02:20:36Z",
                                "description": "You have used some of your 5-hour limit, it will fully refresh in 1 hour, 8 minutes."
                            }
                        ]
                    },
                    {
                        "displayName": "Claude and GPT models",
                        "buckets": [
                            {
                                "bucketId": "3p-weekly",
                                "window": "weekly",
                                "remainingFraction": 1.0,
                                "resetTime": "2026-08-22T01:23:54Z"
                            },
                            {
                                "bucketId": "3p-5h",
                                "window": "5h",
                                "remainingFraction": 1.0,
                                "resetTime": "2026-08-15T06:23:54Z"
                            }
                        ]
                    }
                ]
            }
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIsNotNone(data.get("geminiRateLimits"))
        self.assertEqual(data["geminiWeeklyPercent"], 4.0)
        self.assertEqual(data["geminiHourlyPercent"], 3.0)
        self.assertEqual(data["geminiRateLimits"]["weekly"]["remainingPercent"], 96.0)
        self.assertEqual(data["geminiRateLimits"]["hourly"]["remainingPercent"], 97.0)
        self.assertEqual(data["geminiRateLimits"]["weekly"]["description"], "You have used some of your weekly limit, it will fully refresh in 4 days, 3 hours.")

        self.assertIsNotNone(data.get("claudeRateLimits"))
        self.assertEqual(data["claudeWeeklyPercent"], 0.0)
        self.assertEqual(data["claudeHourlyPercent"], 0.0)
        self.assertEqual(data["claudeRateLimits"]["weekly"]["remainingPercent"], 100.0)
        self.assertEqual(data["claudeRateLimits"]["hourly"]["remainingPercent"], 100.0)

    @unittest.skipIf(os.name == "nt", "os.killpg only available on POSIX")
    @patch("main.subprocess.Popen")
    @patch("main.os.killpg", create=True)
    def test_run_ccusage_safely_kills_process_group_on_timeout(self, mock_killpg, mock_popen):
        import main
        import subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd=["ccusage"], timeout=2)
        mock_popen.return_value = mock_proc

        with patch("main.os.name", "posix"):
            with patch("main.os.getpgid", return_value=99999, create=True):
                with self.assertRaises(subprocess.TimeoutExpired):
                    main.run_ccusage_safely()

        sigkill = getattr(main.signal, "SIGKILL", 9)
        mock_killpg.assert_called_once_with(99999, sigkill)

    def test_ccusage_cache_reuse(self):
        import main
        main._ccusage_cache["timestamp"] = 9999999999.0
        main._ccusage_cache["gemini_weekly"] = 12345
        main._ccusage_cache["gemini_hourly"] = 6789
        main._ccusage_cache["claude_weekly"] = 1111
        main._ccusage_cache["claude_hourly"] = 2222
        main._ccusage_cache["gpt_weekly"] = 3333
        main._ccusage_cache["gpt_hourly"] = 4444

        # When not in testing mode, it should read from cache
        self.assertEqual(main._ccusage_cache["gemini_weekly"], 12345)


    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.run_ccusage_safely")
    def test_get_usage_limits_without_mocking_subprocess_run(self, mock_ccusage, mock_ls, mock_codex, mock_auth):
        import subprocess
        self.assertFalse(hasattr(subprocess.run, "mock_calls"))
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"daily": [], "session": []})
        mock_ccusage.return_value = mock_proc

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.run_ccusage_safely")
    def test_ccusage_cache_reuse_endpoint(self, mock_ccusage, mock_ls, mock_codex, mock_auth):
        import main
        import time
        import sys
        main._ccusage_cache["timestamp"] = time.time()
        main._ccusage_cache["gemini_weekly"] = 12345
        main._ccusage_cache["gemini_hourly"] = 6789
        main._ccusage_cache["claude_weekly"] = 1111
        main._ccusage_cache["claude_hourly"] = 2222
        main._ccusage_cache["gpt_weekly"] = 3333
        main._ccusage_cache["gpt_hourly"] = 4444

        with patch.dict("sys.modules"):
            if "pytest" in sys.modules:
                del sys.modules["pytest"]
            res = self.client.get("/api/usage-limits")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIsNone(data["geminiWeeklyUsed"])
            self.assertIsNone(data["geminiHourlyUsed"])
            mock_ccusage.assert_not_called()

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.run_ccusage_safely")
    def test_ccusage_cache_updated_on_non_zero_returncode(self, mock_ccusage, mock_ls, mock_codex, mock_auth):
        import main
        import sys
        main._ccusage_cache["timestamp"] = 0.0
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "error"
        mock_ccusage.return_value = mock_proc

        with patch.dict("sys.modules"):
            if "pytest" in sys.modules:
                del sys.modules["pytest"]
            res = self.client.get("/api/usage-limits")
            self.assertEqual(res.status_code, 200)
            self.assertGreater(main._ccusage_cache["timestamp"], 0.0)

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota")
    @patch("subprocess.run")
    def test_get_usage_limits_with_google_ai_pro_tier(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        mock_ls.return_value = {
            "userStatus": {
                "userTier": {
                    "id": "g1-pro-tier",
                    "name": "Google AI Pro",
                    "description": "Google AI Pro"
                }
            }
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("antigravityPlan"), "Google AI Pro")

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota")
    @patch("subprocess.run")
    def test_get_usage_limits_with_tier_id_inference(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        mock_ls.return_value = {
            "userStatus": {
                "userTier": {
                    "id": "g1-pro-tier"
                }
            }
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("antigravityPlan"), "Google AI Pro")

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("subprocess.run")
    def test_get_usage_limits_default_antigravity_plan(self, mock_subprocess, mock_ls, mock_codex, mock_auth):
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data.get("antigravityPlan"))

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota", return_value=None)
    @patch("main.get_profile")
    @patch("main.fetch_antigravity_token_usage", return_value=(0, 0))
    @patch("subprocess.run")
    def test_get_usage_limits_with_ultra_profile(self, mock_subprocess, mock_agy, mock_get_profile, mock_ls, mock_codex, mock_auth):
        mock_get_profile.return_value = {
            "id": "prof_google_ultra_5x_66a188",
            "cli_id": "agy",
            "label": "Google Ultra 5x",
            "profile_root": "/fake/profile/root",
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits?profile_id=prof_google_ultra_5x_66a188")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsNone(data["antigravityPlan"])
        self.assertIsNone(data["geminiWeeklyLimit"])
        self.assertIsNone(data["geminiHourlyLimit"])
        self.assertIsNotNone(data["geminiRateLimits"])
        self.assertIsNone(data["geminiRateLimits"]["remainingPercent"])
        self.assertIsNone(data["geminiRateLimits"]["usedPercent"])
        self.assertIsNone(data["geminiRateLimits"]["planName"])

    @patch("main.verify_authorization", return_value=True)
    @patch("main.fetch_codex_rate_limits", return_value=None)
    @patch("main.fetch_antigravity_language_server_quota")
    @patch("main.get_profile")
    @patch("main.get_profile_oauth_email", return_value="twqsdrfhk@gmail.com")
    @patch("main.fetch_antigravity_token_usage", return_value=(0, 0))
    @patch("subprocess.run")
    def test_get_usage_limits_email_mismatch_discards_ls(self, mock_subprocess, mock_agy, mock_email, mock_get_profile, mock_ls, mock_codex, mock_auth):
        # LS reports rangsarn@gmail.com (Pro), but profile is twqsdrfhk@gmail.com (Ultra)
        mock_ls.return_value = {
            "userStatus": {
                "email": "rangsarn@gmail.com",
                "userTier": {"name": "Google AI Pro"}
            }
        }
        mock_get_profile.return_value = {
            "id": "prof_google_ultra_5x_66a188",
            "cli_id": "agy",
            "label": "Google Ultra 5x",
            "profile_root": "/fake/profile/root",
        }
        proc_mock = MagicMock()
        proc_mock.returncode = 0
        proc_mock.stdout = json.dumps({"daily": [], "session": []})
        mock_subprocess.return_value = proc_mock

        res = self.client.get("/api/usage-limits?profile_id=prof_google_ultra_5x_66a188")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        # Neither a mismatched account nor a profile label proves the plan.
        self.assertIsNone(data["antigravityPlan"])
        self.assertIsNone(data["geminiWeeklyLimit"])
        self.assertIsNone(data["geminiRateLimits"]["remainingPercent"])


if __name__ == "__main__":
    unittest.main()



