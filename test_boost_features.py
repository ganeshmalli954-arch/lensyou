import unittest
import json
import uuid
import os
from app import app
from services.storage_service import (
    init_db, get_db, save_cached_analysis, save_analysis,
    get_cached_analysis, create_user, get_user
)
from services.job_service import create_job, get_job, run_analysis_job

class TestBoostFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = app.test_client()
        with get_db() as conn:
            conn.cursor().execute("DELETE FROM anon_sessions")
            conn.commit()

    def test_01_index_and_caching_functions(self):
        """Verify idx_videos_video_id index exists and save_analysis is alias of save_cached_analysis"""
        with get_db() as conn:
            c = conn.cursor()
            c.execute("PRAGMA index_list('videos')")
            indexes = [row['name'] for row in c.fetchall()]
            self.assertIn('idx_videos_video_id', indexes)

        self.assertIs(save_analysis, save_cached_analysis)

    def test_02_instant_cache_hit_job(self):
        """Verify cached video serves immediately in run_analysis_job with 0 YouTube/Gemini calls"""
        test_vid = f"cache_vid_{uuid.uuid4().hex[:6]}"
        sample_analysis = {
            "_meta": {
                "video_id": test_vid,
                "title": "Cached Intelligence Lecture",
                "duration": "14:20",
                "model_used": "Gemini AI (Cached)"
            },
            "video_overview": {
                "summary": "Instant cached summary test"
            }
        }
        # Save to cache
        save_cached_analysis(test_vid, "Cached Intelligence Lecture", "Test Author", "14:20", sample_analysis)

        # Create user and job
        user_id = create_user('google', f'sub_boost_{uuid.uuid4().hex[:8]}', 'boost@example.com', 'Boost User', '')
        job_id = create_job()

        # Run analysis job synchronously
        run_analysis_job(job_id, test_vid, user_id=user_id, session_key='sess_boost', key_pool=[])

        job = get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['stage'], 9)
        self.assertIsNotNone(job['result'])
        self.assertEqual(job['result']['_meta']['title'], "Cached Intelligence Lecture")

        # Verify quota incremented
        u = get_user(user_id)
        self.assertEqual(u['quota_used'], 1)

    def test_03_health_endpoint(self):
        """Verify /api/health public endpoint returns status ok and service lensyou"""
        res = self.client.get('/api/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['service'], 'lensyou')
        self.assertIn('timestamp', data)

    def test_04_public_dossier_routes(self):
        """Verify /v/<video_id> and /api/dossier/<video_id> work for cached and missing videos"""
        test_vid = f"dossier_vid_{uuid.uuid4().hex[:6]}"
        
        # Missing video returns 404
        res_missing = self.client.get(f'/api/dossier/{test_vid}')
        self.assertEqual(res_missing.status_code, 404)
        self.assertFalse(res_missing.get_json()['found'])

        # Web page returns 200 HTML
        res_page = self.client.get(f'/v/{test_vid}')
        self.assertEqual(res_page.status_code, 200)
        self.assertIn(b'LensYou', res_page.data)

        # Cache video
        sample_analysis = {
            "_meta": {"video_id": test_vid, "title": "Dossier Test Title", "duration": "05:00"},
            "video_overview": {"summary": "Public dossier summary"}
        }
        save_cached_analysis(test_vid, "Dossier Test Title", "Author", "05:00", sample_analysis)

        # Cached dossier API returns 200
        res_cached = self.client.get(f'/api/dossier/{test_vid}')
        self.assertEqual(res_cached.status_code, 200)
        data = res_cached.get_json()
        self.assertTrue(data['found'])
        self.assertTrue(data['cached'])
        self.assertEqual(data['analysis']['_meta']['title'], "Dossier Test Title")

    def test_05_admin_update_user_plan_endpoint(self):
        """Verify admin can update user plan and quota limit via API"""
        user_id = create_user('google', f'sub_adm_{uuid.uuid4().hex[:8]}', 'admin_target@example.com', 'Target User', '')
        u_init = get_user(user_id)
        self.assertEqual(u_init['plan'], 'free')
        self.assertEqual(u_init['quota_limit'], 5)

        # Unauthenticated request fails with 401
        res_unauth = self.client.post(f'/admin/api/user/{user_id}/plan', json={'plan': 'pack10'})
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticated as admin
        with self.client.session_transaction() as sess:
            sess['is_admin'] = True

        # Upgrade to pack10
        res_pack10 = self.client.post(f'/admin/api/user/{user_id}/plan', json={'plan': 'pack10'})
        self.assertEqual(res_pack10.status_code, 200)
        self.assertTrue(res_pack10.get_json()['success'])
        u_pack10 = get_user(user_id)
        self.assertEqual(u_pack10['plan'], 'pack10')
        self.assertEqual(u_pack10['quota_limit'], 15)

        # Upgrade to unlimited
        res_unlim = self.client.post(f'/admin/api/user/{user_id}/plan', json={'plan': 'unlimited'})
        self.assertEqual(res_unlim.status_code, 200)
        u_unlim = get_user(user_id)
        self.assertEqual(u_unlim['plan'], 'unlimited')
        self.assertEqual(u_unlim['quota_limit'], -1)

        # Custom quota limit
        res_custom = self.client.post(f'/admin/api/user/{user_id}/plan', json={'plan': 'custom_plan', 'quota_limit': 100})
        self.assertEqual(res_custom.status_code, 200)
        u_custom = get_user(user_id)
        self.assertEqual(u_custom['plan'], 'custom_plan')
        self.assertEqual(u_custom['quota_limit'], 100)

    def test_06_dossier_trailing_slash_and_meta_tags(self):
        """Verify /v/<video_id>/ and /api/dossier/<video_id>/ accept trailing slashes and render Open Graph tags"""
        test_vid = f"og_vid_{uuid.uuid4().hex[:6]}"
        sample_analysis = {
            "_meta": {
                "video_id": test_vid,
                "title": "Quantum Computing 101 Lecture",
                "duration": "45:10",
                "thumbnail_url": f"https://img.youtube.com/vi/{test_vid}/maxresdefault.jpg"
            },
            "video_overview": {
                "summary": "Comprehensive overview of qubits and quantum superposition."
            }
        }
        save_cached_analysis(test_vid, "Quantum Computing 101 Lecture", "Prof. Quantum", "45:10", sample_analysis)

        # Trailing slash on API
        res_api_slash = self.client.get(f'/api/dossier/{test_vid}/')
        self.assertEqual(res_api_slash.status_code, 200)
        self.assertTrue(res_api_slash.get_json()['found'])

        # Trailing slash on web page with dynamic meta tags
        res_page_slash = self.client.get(f'/v/{test_vid}/')
        self.assertEqual(res_page_slash.status_code, 200)
        html = res_page_slash.data.decode('utf-8')
        self.assertIn("Quantum Computing 101 Lecture", html)
        self.assertIn('property="og:title" content="Quantum Computing 101 Lecture"', html)
        self.assertIn('Comprehensive overview of qubits', html)

    def test_07_api_analyze_with_cache_hit_bypasses_keypool(self):
        """Verify /api/analyze does not require Gemini key pool when video is already cached"""
        from unittest.mock import patch
        test_vid = f"boost{uuid.uuid4().hex[:6]}"
        sample_analysis = {
            "_meta": {
                "video_id": test_vid,
                "title": "Zero Token Analysis Title",
                "duration": "10:00"
            },
            "video_overview": {"summary": "Cached without Gemini tokens"}
        }
        save_cached_analysis(test_vid, "Zero Token Analysis Title", "Creator", "10:00", sample_analysis)

        # Mock get_key_pool to return empty list (simulating exhausted/missing Gemini API keys)
        with patch('app.get_key_pool', return_value=[]):
            res = self.client.post('/api/analyze', json={'url': f'https://www.youtube.com/watch?v={test_vid}'})
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn('job_id', data)

            job_id = data['job_id']
            # Run job synchronously
            run_analysis_job(job_id, test_vid, user_id=None, session_key='sess_test', key_pool=[])
            job = get_job(job_id)
            self.assertEqual(job['status'], 'completed')
            self.assertEqual(job['result']['_meta']['title'], "Zero Token Analysis Title")

    def test_08_save_cached_analysis_updates_user_id(self):
        """Verify save_cached_analysis updates user_id and session_key for existing records"""
        test_vid = f"uid_vid_{uuid.uuid4().hex[:6]}"
        sample_analysis = {"_meta": {"video_id": test_vid, "title": "Test Title"}}
        
        # Save initially without user
        rec_id1 = save_cached_analysis(test_vid, "Test Title", "Author", "01:00", sample_analysis)
        self.assertTrue(bool(rec_id1))

        # Save again with user_id
        test_user = f"user_{uuid.uuid4().hex[:6]}"
        rec_id2 = save_cached_analysis(test_vid, "Test Title Updated", "Author", "01:00", sample_analysis, user_id=test_user, session_key="sess_123")
        self.assertEqual(rec_id1, rec_id2)

        with get_db() as conn:
            c = conn.cursor()
            c.execute('SELECT user_id, session_key, title FROM videos WHERE video_id = ?', (test_vid,))
            row = dict(c.fetchone())
            self.assertEqual(row['user_id'], test_user)
            self.assertEqual(row['session_key'], 'sess_123')
            self.assertEqual(row['title'], "Test Title Updated")

    def test_09_shared_dossier_sticky_banner_and_copy(self):
        """Verify shared /v/<video_id> has sticky banner, executive branding, 4 ChatGPT diffs, and segments"""
        test_vid = f"sticky_{uuid.uuid4().hex[:6]}"
        sample_analysis = {
            "_meta": {"video_id": test_vid, "title": "AI in Medicine Lecture", "duration": "01:15:00"},
            "video_overview": {"summary": "Advanced neural networks in computational pathology"}
        }
        save_cached_analysis(test_vid, "AI in Medicine Lecture", "Stanford Medical", "01:15:00", sample_analysis)

        res = self.client.get(f'/v/{test_vid}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Sticky Top Bar
        self.assertIn("sharedDossierBanner", html)
        self.assertIn("Analyzed in 50ms with LensYou AI", html)
        self.assertIn("Analyze Any Video Free →", html)

        # Executive Video Intelligence & Learning Engine (never just a summarizer)
        self.assertIn("Executive Video Intelligence &amp; Learning Engine", html)
        self.assertNotIn("AI video summarizer", html)

        # 4 Features ChatGPT cannot do
        self.assertIn("Interactive 3D Flashcards", html)
        self.assertIn("[Space]", html)
        self.assertIn("Bloom's Taxonomy Quizzes", html)
        self.assertIn("Multi-Hour Timeline Heatmaps", html)
        self.assertIn("Publication-Grade PDF Dossiers", html)

        # Target Segments
        self.assertIn("Medical &amp; Engineering Students", html)
        self.assertIn("Investors &amp; Founders", html)
        self.assertIn("Self-Improvement Junkies", html)

    def test_10_international_currency_and_pricing_support(self):
        """Verify international USD currency and pricing in /api/payment/verify"""
        user_id = create_user('google', f'sub_intl_{uuid.uuid4().hex[:8]}', 'intl@example.com', 'Global User', '')

        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

        # Upgrade via International USD pack10 ($2.99)
        res_pack = self.client.post('/api/payment/verify', json={
            'plan': 'pack10',
            'currency': 'USD',
            'amount': 2.99,
            'provider': 'stripe'
        })
        self.assertEqual(res_pack.status_code, 200)
        data = res_pack.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['currency'], 'USD')
        self.assertEqual(data['amount'], 2.99)

        # Upgrade via International USD unlimited ($4.99)
        res_unlim = self.client.post('/api/payment/verify', json={
            'plan': 'unlimited',
            'currency': 'USD',
            'amount': 4.99,
            'provider': 'stripe'
        })
        self.assertEqual(res_unlim.status_code, 200)
        data_u = res_unlim.get_json()
        self.assertTrue(data_u['success'])
        self.assertEqual(data_u['currency'], 'USD')
        self.assertEqual(data_u['amount'], 4.99)

    def test_11_render_disk_storage_path_resolution(self):
        """Verify resolve_database_path respects /var/data and environment variables"""
        from services.storage_service import resolve_database_path
        from unittest.mock import patch

        # Explicit DATABASE_PATH env var
        with patch.dict(os.environ, {'DATABASE_PATH': '/custom/path/db.sqlite'}):
            self.assertEqual(resolve_database_path(), '/custom/path/db.sqlite')

        # Simulated Render persistent disk mount at /var/data
        with patch.dict(os.environ, {}, clear=True):
            if 'DATABASE_PATH' in os.environ:
                del os.environ['DATABASE_PATH']
            with patch('os.path.exists') as mock_exists:
                mock_exists.side_effect = lambda p: p == '/var/data'
                self.assertEqual(resolve_database_path(), '/var/data/lensyou.db')

    def test_12_weekly_retention_digest_and_spaced_repetition(self):
        """Verify storing Google email and weekly retention / spaced repetition notifications"""
        from services.retention_service import (
            generate_weekly_digest_for_user, run_weekly_retention_cycle,
            get_weekly_trending_podcasts
        )
        from services.storage_service import save_cached_analysis, get_user

        # 1. Create a user with Google email
        test_email = f"learner_{uuid.uuid4().hex[:6]}@gmail.com"
        user_id = create_user('google', f'sub_g_{uuid.uuid4().hex[:6]}', test_email, 'High Performer', '')
        user = get_user(user_id)
        self.assertEqual(user['email'], test_email)

        # 2. Before any flashcards saved -> digest is top analyzed podcasts
        digest_no_decks = generate_weekly_digest_for_user(user_id, test_email, 'High Performer')
        self.assertIn("3 most analyzed podcasts on LensYou this week", digest_no_decks['title'])
        self.assertEqual(digest_no_decks['type'], 'weekly_digest')

        # 3. Save 3 analyses with flashcards for this user
        for i in range(3):
            vid = f"deck_vid_{i}_{uuid.uuid4().hex[:4]}"
            data = {
                "_meta": {"video_id": vid, "title": f"Lecture Series Part {i+1}", "duration": "01:00:00"},
                "video_overview": {"summary": f"Key principles of part {i+1}"},
                "learning": {
                    "flashcards": [
                        {"front": f"Concept {i}-1", "back": "Answer 1", "concept": "Science"},
                        {"front": f"Concept {i}-2", "back": "Answer 2", "concept": "Math"}
                    ]
                }
            }
            save_cached_analysis(vid, f"Lecture Series Part {i+1}", "Stanford", "01:00:00", data, user_id=user_id)

        # 4. With 3 decks -> digest is spaced repetition review reminder
        digest_decks = generate_weekly_digest_for_user(user_id, test_email, 'High Performer')
        self.assertIn("Saved Flashcard Decks are ready for review (Spaced Repetition)", digest_decks['title'])
        self.assertEqual(digest_decks['type'], 'spaced_repetition')
        self.assertEqual(digest_decks['deck_count'], 3)

        # 5. Check /api/notifications/retention for logged-in user
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id

        res_notif = self.client.get('/api/notifications/retention')
        self.assertEqual(res_notif.status_code, 200)
        notif_data = res_notif.get_json()
        self.assertTrue(notif_data['has_unread'])
        self.assertTrue(len(notif_data['notifications']) > 0)
        self.assertIn("Spaced Repetition", notif_data['notifications'][0]['title'])

        # 6. Check guest retention notification (weekly trending)
        with self.client.session_transaction() as sess:
            sess.clear()
        res_guest = self.client.get('/api/notifications/retention')
        self.assertEqual(res_guest.status_code, 200)
        guest_data = res_guest.get_json()
        self.assertTrue(guest_data['has_unread'])
        self.assertIn("3 most analyzed podcasts on LensYou this week", guest_data['notifications'][0]['title'])

        # 7. Run full weekly cycle
        cycle_result = run_weekly_retention_cycle()
        self.assertEqual(cycle_result['status'], 'success')
        self.assertGreaterEqual(cycle_result['users_processed'], 1)

    def test_13_blooms_taxonomy_quiz_and_keyboard_flashcards(self):
        """Verify Bloom's taxonomy quiz structure, keyboard flashcard hints, and 1-click segments"""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Bloom's taxonomy quiz header
        self.assertIn("Bloom's Taxonomy Video Mastery Quiz", html)

        # Flashcards keyboard shortcuts legend
        self.assertIn("Space", html)
        self.assertIn("Flip", html)
        self.assertIn("Prev", html)
        self.assertIn("Next", html)

        # Multi-Hour Timeline Heatmap header
        self.assertIn("Multi-Hour Timeline Heatmap &amp; Evidence Explorer", html)

        # Target Segments 1-click links
        self.assertIn("Analyze 3B1B Lecture (1-Click) →", html)
        self.assertIn("Analyze Founder Interview (1-Click) →", html)
        self.assertIn("Analyze Huberman Lab (1-Click) →", html)
        self.assertIn("qmNCJxvs080", html)

    def test_14_database_backup_service(self):
        """Verify automated database snapshot and backup cycle"""
        import tempfile
        from services.backup_service import export_database_snapshot, run_daily_backup_cycle

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot_file = export_database_snapshot(dest_dir=tmpdir)
            self.assertTrue(os.path.exists(snapshot_file))
            self.assertGreater(os.path.getsize(snapshot_file), 0)

        cycle_res = run_daily_backup_cycle()
        self.assertEqual(cycle_res['status'], 'success')
        self.assertTrue(os.path.exists(cycle_res['snapshot_path']))

if __name__ == '__main__':
    unittest.main()

