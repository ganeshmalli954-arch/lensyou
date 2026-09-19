import unittest
import json
import uuid
import os
from app import app
from services.storage_service import (
    init_db, get_db, record_search_event, record_processing_event,
    update_processing_event, get_user_history, get_content_analytics,
    get_search_analytics, record_payment, get_payment_stats, get_user,
    create_user, update_user_plan, update_search_events_for_content
)
from services.auth_service import PLAN_CONFIG, get_plan_history_limit, is_owner

class TestVideoLensPartA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        from services.totp_service import disable_admin_totp
        disable_admin_totp()

    def setUp(self):
        self.client = app.test_client()
        from services.totp_service import disable_admin_totp
        disable_admin_totp()

    def test_01_public_routes(self):
        """Verify basic public routes return HTTP 200"""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/history')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/favicon.ico')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/manifest.json')
        self.assertEqual(res.status_code, 200)

        res = self.client.get('/api/config')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('features', data)

    def test_02_payment_plans_endpoint(self):
        """Verify plan configuration is correctly exposed and priced"""
        res = self.client.get('/api/payment/plans')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        plans = data.get('plans', {})
        self.assertIn('free', plans)
        self.assertIn('pack10', plans)
        self.assertIn('unlimited', plans)
        self.assertEqual(plans['pack10']['price'], 50)
        self.assertEqual(plans['unlimited']['price'], 99)

    def test_03_admin_protection_and_login(self):
        """Verify owner/admin route is protected and password login works"""
        # Unauthenticated access to /admin/ should redirect to /admin/login
        res = self.client.get('/admin/', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login', res.headers.get('Location', ''))

        # /owner should redirect to /admin/
        res = self.client.get('/owner', follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        # Login with wrong password fails
        res = self.client.post('/admin/login', data={'password': 'wrongpassword'})
        self.assertIn(b'Invalid administrator password', res.data)

        # Login with correct password succeeds
        res = self.client.post('/admin/login', data={'password': 'admin123'}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)

    def test_04_admin_api_endpoints(self):
        """Verify admin APIs return real data once authenticated"""
        with self.client.session_transaction() as sess:
            sess['is_admin'] = True

        res = self.client.get('/admin/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('cpu_percent', data)
        self.assertIn('ram_percent', data)

        res = self.client.get('/admin/api/stats')
        self.assertEqual(res.status_code, 200)
        stats = res.get_json()
        self.assertIn('total_users', stats)
        self.assertIn('total_searches', stats)
        self.assertIn('total_processing', stats)
        self.assertIn('verified_revenue', stats)

    def test_05_account_specific_search_history(self):
        """Critical Gate: Search histories of different users remain strictly isolated"""
        user_a_id = create_user('google', f'sub_a_{uuid.uuid4().hex[:8]}', 'usera@example.com', 'User Alpha', '')
        user_b_id = create_user('google', f'sub_b_{uuid.uuid4().hex[:8]}', 'userb@example.com', 'User Beta', '')

        # User A searches for Movie X and Movie Y
        record_search_event(user_id=user_a_id, query='Interstellar', content_id='INT-001', content_title='Interstellar (2014)', plan='free')
        record_search_event(user_id=user_a_id, query='Dune Part 2', content_id='DUNE-002', content_title='Dune: Part Two', plan='free')

        # User B searches for Movie X (same content)
        record_search_event(user_id=user_b_id, query='Interstellar', content_id='INT-001', content_title='Interstellar (2014)', plan='free')

        # Test User A's history via API
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_a_id

        res_a = self.client.get('/api/history')
        data_a = res_a.get_json()
        content_ids_a = [item['content_id'] for item in data_a['items']]
        self.assertIn('INT-001', content_ids_a)
        self.assertIn('DUNE-002', content_ids_a)
        self.assertEqual(data_a['total'], 2)

        # Test User B's history via API
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_b_id

        res_b = self.client.get('/api/history')
        data_b = res_b.get_json()
        content_ids_b = [item['content_id'] for item in data_b['items']]
        self.assertIn('INT-001', content_ids_b)
        self.assertNotIn('DUNE-002', content_ids_b) # User B CANNOT see User A's search!
        self.assertEqual(data_b['total'], 1)

    def test_06_repeated_search_and_aggregate_metrics(self):
        """Verify repeated searches increment counts without confusing users with events"""
        user_a_id = create_user('google', f'sub_rep_a_{uuid.uuid4().hex[:8]}', 'rep_a@example.com', 'Repeater A', '')
        user_b_id = create_user('google', f'sub_rep_b_{uuid.uuid4().hex[:8]}', 'rep_b@example.com', 'Repeater B', '')
        content_id = f"REP-VID-{uuid.uuid4().hex[:6]}"

        # User A searches 3 times
        for _ in range(3):
            record_search_event(user_id=user_a_id, query='Oppenheimer', content_id=content_id, content_title='Oppenheimer', plan='free')

        # User B searches 2 times
        for _ in range(2):
            record_search_event(user_id=user_b_id, query='Oppenheimer', content_id=content_id, content_title='Oppenheimer', plan='free')

        analytics = get_content_analytics(content_id=content_id)
        self.assertIsNotNone(analytics)
        self.assertEqual(analytics['total_searches'], 5) # 3 + 2
        self.assertEqual(analytics['unique_searchers'], 2) # Exactly 2 unique users

        users_breakdown = {u['account_id']: u['search_count'] for u in analytics['users_breakdown']}
        self.assertEqual(users_breakdown[user_a_id], 3)
        self.assertEqual(users_breakdown[user_b_id], 2)

    def test_07_processing_history_and_status(self):
        """Verify processing events track success/failure per account and per content"""
        user_id = create_user('google', f'sub_proc_{uuid.uuid4().hex[:8]}', 'proc@example.com', 'Processor', '')
        vid_success = f"VID-SUCC-{uuid.uuid4().hex[:4]}"
        vid_failed = f"VID-FAIL-{uuid.uuid4().hex[:4]}"

        # Successful processing
        p1 = record_processing_event(user_id=user_id, content_id=vid_success, content_title='Success Video', status='pending')
        update_processing_event(p1, status='success', duration='12:34', model_used='gemini-3.5-flash-lite')

        # Failed processing
        p2 = record_processing_event(user_id=user_id, content_id=vid_failed, content_title='Failed Video', status='pending')
        update_processing_event(p2, status='failed', error_info='Could not retrieve transcript')

        # Query user history with filters
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

        res_success = self.client.get('/api/history?status=success')
        self.assertTrue(any(i['content_id'] == vid_success for i in res_success.get_json()['items']))

        res_failed = self.client.get('/api/history?status=failed')
        self.assertTrue(any(i['content_id'] == vid_failed for i in res_failed.get_json()['items']))

    def test_08_paid_plan_upgrades_and_verification(self):
        """Verify ₹50 and ₹99 plans update database, create verified payment records, and enforce limits"""
        user_id = create_user('google', f'sub_pay_{uuid.uuid4().hex[:8]}', 'payer@example.com', 'Paying Customer', '')

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

        # Upgrade to ₹50 pack
        res = self.client.post('/api/payment/verify', json={'plan': 'pack10', 'provider': 'razorpay'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['amount'], 50)

        # Check DB updated
        user = get_user(user_id)
        self.assertEqual(user['plan'], 'pack10')
        self.assertEqual(user['quota_limit'], 15)

        # Upgrade to ₹99 unlimited
        res = self.client.post('/api/payment/verify', json={'plan': 'unlimited', 'provider': 'razorpay'})
        self.assertEqual(res.status_code, 200)
        user = get_user(user_id)
        self.assertEqual(user['plan'], 'unlimited')
        self.assertEqual(user['quota_limit'], -1)

        # Verify payments stats
        pay_stats = get_payment_stats()
        self.assertGreaterEqual(pay_stats['total_revenue'], 149) # 50 + 99

    def test_09_owner_auto_authorization(self):
        """Verify owner email automatically gets unrestricted owner privileges"""
        owner_email = 'ganeshmalli954@gmail.com'
        self.assertTrue(is_owner(owner_email))
        self.assertFalse(is_owner('regular_user@example.com'))

    def test_10_cookie_security_flags(self):
        """Verify session cookie security settings"""
        self.assertTrue(app.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(app.config['SESSION_COOKIE_SAMESITE'], 'Lax')

    def test_11_topic_keyword_search(self):
        """Verify unified search endpoint handles topic queries and returns results"""
        res = self.client.post('/api/search', json={'query': 'Interstellar'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('query'), 'Interstellar')
        self.assertIn('results', data)
        self.assertGreater(len(data['results']), 0)
        first = data['results'][0]
        self.assertIn('video_id', first)
        self.assertIn('title', first)

    def test_12_history_retention_bypass_prevention(self):
        """Verify user on Free plan cannot paginate beyond their 10-item retention limit"""
        user_id = create_user('google', f'sub_ret_{uuid.uuid4().hex[:8]}', 'retention@example.com', 'Retention Tester', '')
        # Add 15 searches
        for i in range(15):
            record_search_event(user_id=user_id, query=f'Topic {i}', content_id=f'VID-{i:02d}', content_title=f'Video {i}', plan='free')

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

        # Page 1: offset=0, limit=10 -> should return 10 items, total=10 (clamped by plan_limit)
        res1 = self.client.get('/api/history?limit=10&offset=0')
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1['total'], 10)
        self.assertEqual(len(data1['items']), 10)

        # Attempt pagination beyond plan limit: offset=10, limit=10 -> should return 0 items
        res2 = self.client.get('/api/history?limit=10&offset=10')
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2['total'], 10)
        self.assertEqual(len(data2['items']), 0)

        # Attempt to request oversized limit: limit=50 -> should be clamped to 10
        res3 = self.client.get('/api/history?limit=50&offset=0')
        self.assertEqual(res3.status_code, 200)
        data3 = res3.get_json()
        self.assertEqual(data3['total'], 10)
        self.assertLessEqual(len(data3['items']), 10)

    def test_13_admin_unauthenticated_api_401(self):
        """Verify unauthenticated requests to /admin/api/* return HTTP 401 JSON, not 302 redirects"""
        res_stats = self.client.get('/admin/api/stats')
        self.assertEqual(res_stats.status_code, 401)
        self.assertIn('error', res_stats.get_json())

        res_health = self.client.get('/admin/api/health')
        self.assertEqual(res_health.status_code, 401)
        self.assertIn('error', res_health.get_json())

        res_users = self.client.get('/admin/api/users')
        self.assertEqual(res_users.status_code, 401)
        self.assertIn('error', res_users.get_json())

    def test_14_owner_dev_login_auto_admin(self):
        """Verify /auth/dev-login for owner email grants admin role and session"""
        res = self.client.get('/auth/dev-login?email=ganeshmalli954@gmail.com&name=Owner', follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        # Session should now be authenticated as admin
        res_stats = self.client.get('/admin/api/stats')
        self.assertEqual(res_stats.status_code, 200)
        stats = res_stats.get_json()
        self.assertIn('total_users', stats)

    def test_15_webhook_payment_verification(self):
        """Verify webhook updates user plan and quota securely"""
        user_id = create_user('google', f'sub_wh_{uuid.uuid4().hex[:8]}', 'webhook_user@example.com', 'WH User', '')
        user_before = get_user(user_id)
        self.assertEqual(user_before['plan'], 'free')

        webhook_payload = {
            'event': 'payment.captured',
            'payload': {
                'payment': {
                    'entity': {
                        'id': f'pay_wh_{uuid.uuid4().hex[:8]}',
                        'notes': {
                            'user_id': user_id,
                            'plan': 'pack10'
                        }
                    }
                }
            }
        }
        res = self.client.post('/api/payment/webhook', json=webhook_payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))

        user_after = get_user(user_id)
        self.assertEqual(user_after['plan'], 'pack10')
        self.assertEqual(user_after['quota_limit'], 15)

    def test_16_search_events_title_enrichment(self):
        """Verify search events with initial generic placeholder titles get updated once metadata is fetched"""
        vid_id = f'test_vid_{uuid.uuid4().hex[:6]}'
        user_id = create_user('google', f'sub_enrich_{uuid.uuid4().hex[:8]}', 'enrich@example.com', 'Enrich User', '')
        
        # Record search event with placeholder
        record_search_event(user_id=user_id, query='https://youtube.com/watch?v=' + vid_id, content_id=vid_id, content_title=f'YouTube Video ({vid_id})', plan='free')
        
        # Verify initial title is placeholder
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
        res1 = self.client.get('/api/history')
        items1 = res1.get_json()['items']
        match = [i for i in items1 if i['content_id'] == vid_id]
        self.assertEqual(len(match), 1)
        self.assertIn('YouTube Video', match[0]['content_title'])

        # Now enrich title
        update_search_events_for_content(vid_id, 'Resolved Real Video Title')

        # Verify title was updated in database
        res2 = self.client.get('/api/history')
        items2 = res2.get_json()['items']
        match2 = [i for i in items2 if i['content_id'] == vid_id]
        self.assertEqual(len(match2), 1)
        self.assertEqual(match2[0]['content_title'], 'Resolved Real Video Title')

    def test_17_duration_and_unlimited_length(self):
        """Verify unlimited lecture length support, time formatting, and full timeline sampling"""
        from utils.time_utils import format_seconds, prepare_transcript_for_analysis, prepare_ui_transcript_sample
        from services.auth_service import PLAN_CONFIG

        # Verify format_seconds handles multi-hour lecture durations accurately
        self.assertEqual(format_seconds(4872), "01:21:12")
        self.assertEqual(format_seconds(10800), "03:00:00")
        self.assertEqual(format_seconds(65), "01:05")

        # Simulate a 3-hour university lecture transcript (1500 segments)
        long_segments = [
            {"text": f"Lecture slide {i} explanation on advanced topics", "start": i * 7.2, "duration": 7.0, "timestamp": format_seconds(i * 7.2)}
            for i in range(1500)
        ]

        # Ensure prepare_transcript_for_analysis handles massive text without error
        analysis_text = prepare_transcript_for_analysis(long_segments, max_chars=500000)
        self.assertTrue(len(analysis_text) > 10000)
        self.assertIn("[00:00] Lecture slide 0", analysis_text)

        # Ensure UI snippets sampling spans across the entire 3 hours
        ui_sample = prepare_ui_transcript_sample(long_segments, max_snippets=2500)
        self.assertEqual(len(ui_sample), 1500)  # All 1500 fit within 2500

        # Verify plans highlight unlimited video length
        for p in ['free', 'pack10', 'pack50', 'unlimited']:
            features_str = " ".join(PLAN_CONFIG[p]['features'])
            self.assertIn("Unlimited video length", features_str)

    def test_18_google_authenticator_and_bmc_settings(self):
        """Verify Google Authenticator (TOTP RFC 6238) 2FA and dynamic Buy Me a Coffee settings"""
        import time
        from services.totp_service import (
            generate_totp_secret, format_secret_readable, get_totp_uri,
            generate_totp_code, verify_totp_code, setup_admin_totp,
            disable_admin_totp, is_admin_2fa_enabled, get_admin_totp_secret
        )
        from config import get_bmc_url
        from services.storage_service import set_system_setting

        # 1. Base32 Secret & URI Generation
        secret = generate_totp_secret()
        self.assertEqual(len(secret), 16)
        self.assertTrue(all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in secret))
        
        readable = format_secret_readable(secret)
        self.assertEqual(len(readable.split()), 4)

        uri = get_totp_uri(secret, account="Admin", issuer="VideoLens")
        self.assertTrue(uri.startswith("otpauth://totp/VideoLens:Admin?"))
        self.assertIn(f"secret={secret}", uri)

        # 2. RFC 6238 TOTP Code Generation & Verification
        now = int(time.time())
        code = generate_totp_code(secret, now)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

        # Exact code verifies
        self.assertTrue(verify_totp_code(secret, code))
        # Wrong code fails
        self.assertFalse(verify_totp_code(secret, "999999" if code != "999999" else "000000"))
        # Invalid format fails
        self.assertFalse(verify_totp_code(secret, "abc"))
        self.assertFalse(verify_totp_code(secret, "12345"))

        # Clock drift tolerance (+/- 30s)
        prev_code = generate_totp_code(secret, now - 30)
        self.assertTrue(verify_totp_code(secret, prev_code, window=1))

        # 3. Dynamic Buy Me a Coffee setting
        initial_bmc = get_bmc_url()
        self.assertTrue(len(initial_bmc) > 0)
        
        # Test authenticated settings API
        with self.client.session_transaction() as sess:
            sess['is_admin'] = True

        res = self.client.get('/admin/api/settings')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('bmc_url', data)

        # Update BMC URL via API
        test_bmc = 'https://www.buymeacoffee.com/studentaid'
        res_post = self.client.post('/admin/api/settings', json={'bmc_url': test_bmc})
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(get_bmc_url(), test_bmc)

        # 4. Activate 2FA for Admin
        setup_admin_totp(secret, enable=True)
        self.assertTrue(is_admin_2fa_enabled())
        self.assertEqual(get_admin_totp_secret(), secret)

        # 5. Admin Login with 2FA Enforced
        # Clear session to test login flow
        with self.client.session_transaction() as sess:
            sess.clear()

        # Login with password only must fail when 2FA is active
        res_no_totp = self.client.post('/admin/login', data={'password': 'admin123'})
        self.assertIn(b'code is required', res_no_totp.data)

        # Login with invalid TOTP code must fail
        res_bad_totp = self.client.post('/admin/login', data={'password': 'admin123', 'totp_code': '000000'})
        self.assertIn(b'Invalid 6-digit Google Authenticator code', res_bad_totp.data)

        # Login with correct password and valid TOTP code must succeed
        valid_code = generate_totp_code(secret)
        res_ok = self.client.post('/admin/login', data={'password': 'admin123', 'totp_code': valid_code}, follow_redirects=False)
        self.assertEqual(res_ok.status_code, 302)

        # 6. Disable 2FA
        disable_admin_totp()
        self.assertFalse(is_admin_2fa_enabled())

        # Now password-only login succeeds again
        with self.client.session_transaction() as sess:
            sess.clear()
        res_pwd_only = self.client.post('/admin/login', data={'password': 'admin123'}, follow_redirects=False)
        self.assertEqual(res_pwd_only.status_code, 302)

if __name__ == '__main__':
    unittest.main()


