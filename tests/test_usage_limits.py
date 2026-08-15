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
        
        # Verify gemini token calculations
        # totalTokens - cacheReadTokens = 400000 for weekly
        self.assertEqual(data["geminiWeeklyUsed"], 400000)
        # (400000 / 10000000) * 100 = 4.0%
        self.assertEqual(data["geminiWeeklyPercent"], 4.0)
        
        # totalTokens - cacheReadTokens = 100000 for hourly
        self.assertEqual(data["geminiHourlyUsed"], 100000)
        # (100000 / 1000000) * 100 = 10.0%
        self.assertEqual(data["geminiHourlyPercent"], 10.0)

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
        
        # Should be 0 when no usage data exists
        self.assertEqual(data["geminiWeeklyUsed"], 0)
        self.assertEqual(data["geminiWeeklyPercent"], 0.0)
        self.assertEqual(data["geminiHourlyUsed"], 0)
        self.assertEqual(data["geminiHourlyPercent"], 0.0)
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
        
        # Should reflect Antigravity transcript scan
        self.assertEqual(data["geminiWeeklyUsed"], 725000)
        self.assertEqual(data["geminiWeeklyPercent"], 7.2)
        self.assertEqual(data["geminiHourlyUsed"], 90000)
        self.assertEqual(data["geminiHourlyPercent"], 9.0)

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
        self.assertEqual(data["geminiRateLimits"]["remainingPercent"], 96.5)
        self.assertEqual(data["geminiRateLimits"]["usedPercent"], 3.5)
        self.assertEqual(data["geminiWeeklyPercent"], 3.5)
        self.assertEqual(data["geminiHourlyPercent"], 3.5)

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

if __name__ == "__main__":
    unittest.main()

