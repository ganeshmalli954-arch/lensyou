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

if __name__ == '__main__':
    unittest.main()
