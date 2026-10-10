"""Account quota must never be synthesized from transcript sizes or profile labels."""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import main


class QuotaIntegrityTests(unittest.TestCase):
    def request(self, status=None, profile=None):
        with patch('main.verify_authorization'), patch('main.get_default_profile', return_value=profile), \
             patch('main.fetch_codex_rate_limits', return_value=None), \
             patch('main.fetch_antigravity_language_server_quota', return_value=status), \
             patch('main.fetch_antigravity_token_usage', return_value=(2375175, 821015)), \
             patch('main.run_ccusage_safely', return_value=MagicMock(returncode=1)):
            return TestClient(main.app).get('/api/usage-limits').json()

    def test_transcripts_are_not_account_quota(self):
        data = self.request()
        self.assertFalse(data['geminiRateLimits']['available'])
        self.assertIsNone(data['geminiWeeklyPercent'])
        self.assertIsNone(data['geminiHourlyPercent'])
        self.assertIsNone(data['antigravityPlan'])

    def test_profile_label_does_not_prove_subscription(self):
        data = self.request(profile={'id': 'ultra', 'label': 'Google AI Ultra'})
        self.assertIsNone(data['antigravityPlan'])
        self.assertFalse(data['geminiRateLimits']['available'])

    def test_model_quota_cannot_be_assigned_to_weekly_and_five_hour(self):
        data = self.request({'userStatus': {'cascadeModelConfigData': {'clientModelConfigs': [
            {'modelId': 'gemini', 'quotaInfo': {'remainingFraction': 0.87}}]}}})
        self.assertFalse(data['geminiRateLimits']['available'])

    def test_missing_weekly_is_not_copied_from_five_hour(self):
        data = self.request({'quotaSummary': {'groups': [{'displayName': 'Gemini', 'buckets': [
            {'bucketId': '5h', 'remainingFraction': 0.87}]}]}})
        self.assertIsNone(data['geminiRateLimits']['weekly'])
        self.assertEqual(data['geminiRateLimits']['hourly']['usedPercent'], 13)
        self.assertIsNone(data['geminiWeeklyPercent'])

    def test_malformed_fraction_is_unavailable_not_full_or_crash(self):
        for value in [None, 'invalid', -0.1, 1.1, float('nan'), float('inf'), True]:
            with self.subTest(value=value):
                data = self.request({'quotaSummary': {'groups': [{'displayName': 'Gemini', 'buckets': [
                    {'bucketId': 'weekly', 'remainingFraction': value}]}]}})
                self.assertFalse(data['geminiRateLimits']['available'])

    def test_real_zero_and_full_quota_are_valid(self):
        data = self.request({'userStatus': {'userTier': {'name': 'Google AI Ultra'}},
            'quotaSummary': {'groups': [{'displayName': 'Gemini', 'buckets': [
                {'bucketId': 'weekly', 'remainingFraction': 0},
                {'bucketId': '5h', 'remainingFraction': 1}]}]}})
        self.assertEqual(data['geminiWeeklyPercent'], 100)
        self.assertEqual(data['geminiHourlyPercent'], 0)
        self.assertEqual(data['antigravityPlan'], 'Google AI Ultra')

class QuotaSourceTests(unittest.TestCase):
    def test_explicit_profile_never_borrows_default_credentials(self):
        with patch('main.os.path.isfile', side_effect=lambda p: not p.startswith('/isolated/')) as exists, \
             patch('main.urllib.request.urlopen') as network:
            self.assertIsNone(main.fetch_antigravity_cloudcode_quota('/isolated/profile'))
            self.assertTrue(all(c.args[0].startswith('/isolated/profile/') for c in exists.call_args_list))
            network.assert_not_called()

    def test_status_only_cloud_response_still_scans_language_servers(self):
        status = {'userStatus': {'userTier': {'name': 'Google AI Ultra'}}}
        with patch('main.fetch_antigravity_cloudcode_quota', return_value=status), \
             patch('psutil.process_iter', return_value=[]) as scan:
            self.assertEqual(main.fetch_antigravity_language_server_quota(), status)
            scan.assert_called_once()

    def test_wrong_home_is_not_queried(self):
        process = MagicMock()
        process.info = {'pid': 123, 'name': 'language_server', 'cmdline': ['language_server', '--csrf_token', 'test-only']}
        with patch('main.fetch_antigravity_cloudcode_quota', return_value=None), \
             patch('psutil.process_iter', return_value=[process]), \
             patch('psutil.Process') as proc, patch('main.urllib.request.urlopen') as network:
            proc.return_value.environ.return_value = {'HOME': '/different-account'}
            self.assertIsNone(main.fetch_antigravity_language_server_quota('/selected-profile'))
            network.assert_not_called()

    def test_unknown_profile_does_not_silently_use_default(self):
        with patch('main.verify_authorization'), patch('main.get_profile', return_value=None), \
             patch('main.fetch_antigravity_language_server_quota') as fetch:
            response = TestClient(main.app).get('/api/usage-limits?profile_id=deleted-profile')
            self.assertEqual(response.status_code, 404)
            fetch.assert_not_called()
