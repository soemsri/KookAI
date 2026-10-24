"""Account quota must never be synthesized from transcript sizes or profile labels."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import provider_usage as pu  # noqa: E402


def _signed_out(provider_id):
    return pu.build_provider(provider_id, pu.STATUS_NOT_LOGGED_IN, "test", description="signed out")


class QuotaIntegrityTests(unittest.TestCase):
    def request(self, status=None, profile=None):
        with patch('main.verify_authorization'), patch('main.get_default_profile', return_value=profile), \
             patch('main.antigravity_signed_in', return_value=False), \
             patch('main.fetch_claude_account_usage', return_value=_signed_out('claude')), \
             patch('main.fetch_codex_account_status', return_value={'ok': True, 'account': None, 'requiresOpenaiAuth': True, 'rateLimits': None, 'error': None, 'sawAccount': True}), \
             patch('main.fetch_antigravity_language_server_quota', return_value=status), \
             patch('main.fetch_kimi_account_usage', return_value=_signed_out('kimi')), \
             patch('main.fetch_grok_account_usage', return_value=_signed_out('grok')), \
             patch('main.fetch_muse_account_status', return_value=_signed_out('muse')), \
             patch('main.fetch_deepseek_account_usage', return_value=_signed_out('deepseek')), \
             patch('main.fetch_zai_account_usage', return_value=_signed_out('zai')):
            return TestClient(main.app).get('/api/usage-limits').json()

    def test_transcripts_are_not_account_quota(self):
        data = self.request()
        self.assertFalse(data['geminiRateLimits']['available'])
        self.assertIsNone(data['geminiWeeklyPercent'])
        self.assertIsNone(data['geminiHourlyPercent'])
        self.assertIsNone(data['antigravityPlan'])
        self.assertNotIn('ccusage', str(data))

    def test_profile_label_does_not_prove_subscription(self):
        data = self.request(profile={'id': 'ultra', 'cli_id': 'agy', 'label': 'Google AI Ultra', 'profile_root': '/isolated/ultra'})
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
        self.assertIsNone(data['providers']['antigravity']['weekly'])

    def test_malformed_fraction_is_unavailable_not_full_or_crash(self):
        for value in [None, 'invalid', -0.1, 1.1, float('nan'), float('inf'), True]:
            with self.subTest(value=value):
                data = self.request({'quotaSummary': {'groups': [{'displayName': 'Gemini', 'buckets': [
                    {'bucketId': 'weekly', 'remainingFraction': value}]}]}})
                self.assertFalse(data['geminiRateLimits']['available'])
                self.assertFalse(data['providers']['antigravity']['available'])

    def test_real_zero_and_full_quota_are_valid(self):
        data = self.request({'userStatus': {'userTier': {'name': 'Google AI Ultra'}},
            'quotaSummary': {'groups': [{'displayName': 'Gemini', 'buckets': [
                {'bucketId': 'weekly', 'remainingFraction': 0},
                {'bucketId': '5h', 'remainingFraction': 1}]}]}})
        self.assertEqual(data['geminiWeeklyPercent'], 100)
        self.assertEqual(data['geminiHourlyPercent'], 0)
        self.assertEqual(data['antigravityPlan'], 'Google AI Ultra')

    def test_signed_out_providers_never_show_a_percentage(self):
        data = self.request()
        for provider_id, provider in data['providers'].items():
            with self.subTest(provider=provider_id):
                self.assertIsNone(provider['usedPercent'])
                self.assertFalse(provider['available'])


class QuotaSourceTests(unittest.TestCase):
    def test_explicit_profile_never_borrows_default_credentials(self):
        with patch('main.os.path.isfile', side_effect=lambda p: not p.startswith('/isolated/')) as exists, \
             patch('main.urllib.request.urlopen') as network:
            self.assertIsNone(main.fetch_antigravity_cloudcode_quota('/isolated/profile'))
            self.assertTrue(all(c.args[0].replace('\\', '/').startswith('/isolated/profile/') for c in exists.call_args_list))
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
