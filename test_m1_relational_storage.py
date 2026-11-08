"""
Unit tests for Milestone 1:
- 12 normalized SQLite tables
- Backward-compatible storage facades
- Relational modular persistence & reconstruction
- Persistent analysis jobs state machine
- Tier duration limits & rate limiting middleware
- Usage logs tracking
"""

import unittest
import uuid
import os
import time

from services.storage_service import (
    init_db, init_relational_db, get_db,
    save_cached_analysis, save_analysis, get_cached_analysis, get_analysis,
    save_analysis_modular, get_modular_analysis,
    create_analysis_job, update_job_status, get_analysis_job, list_analysis_jobs,
    log_usage_entry, get_usage_logs, record_export, get_exports_for_video,
    get_transcript_segments, get_chapters, get_claims, get_entities,
    get_flashcards, get_quizzes, get_summaries,
    create_user, get_user
)
from services.usage_service import (
    check_video_duration_limit, get_tier_duration_limit, get_tier_rate_limit,
    parse_duration_seconds, check_rate_limit, RATE_LIMITER,
    log_action_usage, get_user_usage_summary
)

class TestMilestone1RelationalStorage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        init_relational_db()

    def setUp(self):
        RATE_LIMITER.reset()

    def test_01_all_12_relational_tables_exist(self):
        """Verify all 12 normalized SQLite tables exist in the database."""
        expected_tables = {
            'users',
            'videos',
            'analysis_jobs',
            'transcript_segments',
            'summaries',
            'chapters',
            'claims',
            'entities',
            'flashcards',
            'quizzes',
            'exports',
            'usage_logs'
        }
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = {row['name'] for row in c.fetchall()}

        for table in expected_tables:
            self.assertIn(table, existing_tables, f"Table {table} must exist in database")

    def test_02_backward_compatible_aliases_and_indices(self):
        """Verify save_analysis is an exact alias of save_cached_analysis and idx_videos_video_id exists."""
        self.assertIs(save_analysis, save_cached_analysis)
        self.assertIs(get_analysis, get_cached_analysis)

        with get_db() as conn:
            c = conn.cursor()
            c.execute("PRAGMA index_list('videos')")
            indexes = [row['name'] for row in c.fetchall()]
            self.assertIn('idx_videos_video_id', indexes)

    def test_03_save_cached_analysis_populates_both_json_and_relational_tables(self):
        """Verify save_cached_analysis writes videos.analysis_json AND populates relational tables."""
        test_vid = f"rel_vid_{uuid.uuid4().hex[:8]}"
        sample_analysis = {
            "_meta": {
                "video_id": test_vid,
                "title": "Quantum Computing 101",
                "author": "Dr. Physicist",
                "duration": "18:45",
                "model_used": "Gemini AI"
            },
            "video_overview": {
                "title": "Quantum Computing 101",
                "channel": "Dr. Physicist",
                "summary": "An introduction to qubits and superposition.",
                "target_audience": "Undergraduate students",
                "sentiment_label": "Informative"
            },
            "key_takeaways": [
                {"id": "01", "title": "Superposition", "description": "Qubits exist in multiple states."}
            ],
            "timeline": [
                {"time": "00:00", "seconds": 0, "title": "Introduction", "summary": "Welcome to quantum theory."}
            ],
            "factual_claims": [
                {"claim": "Superposition enables quantum parallelism.", "timestamp": "04:15", "seconds": 255, "confidence_score": 0.95}
            ],
            "key_concepts": [
                {"concept": "Qubit", "type": "Physics", "explanation": "Basic unit of quantum information.", "relevance_score": 0.98}
            ],
            "learning": {
                "flashcards": [
                    {"front": "What is a qubit?", "back": "Quantum bit.", "topic": "Quantum", "difficulty": "easy"}
                ],
                "quiz": [
                    {
                        "question": "What is superposition?",
                        "options": ["State mixture", "Fixed 0", "Fixed 1", "Thermal noise"],
                        "correct_index": 0,
                        "explanation": "State mixture allows parallel representations.",
                        "bloom_level": "Understand"
                    }
                ]
            },
            "transcript_segments": [
                {"text": "Welcome everyone to Quantum Computing 101.", "start": 0.0, "duration": 5.0, "speaker": "Dr. Physicist"}
            ]
        }

        row_id = save_cached_analysis(test_vid, "Quantum Computing 101", "Dr. Physicist", "18:45", sample_analysis)
        self.assertTrue(bool(row_id))

        # 1. Verify JSON in videos table
        cached = get_cached_analysis(test_vid)
        self.assertIsNotNone(cached)
        self.assertEqual(cached['_meta']['title'], "Quantum Computing 101")

        # 2. Verify relational records in normalized tables
        summaries = get_summaries(test_vid)
        self.assertEqual(len(summaries), 1)
        self.assertIn("qubits", summaries[0]['content'])

        chapters = get_chapters(test_vid)
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0]['title'], "Introduction")

        claims = get_claims(test_vid)
        self.assertEqual(len(claims), 1)
        self.assertIn("parallelism", claims[0]['claim_text'])

        entities = get_entities(test_vid)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['name'], "Qubit")

        flashcards = get_flashcards(test_vid)
        self.assertEqual(len(flashcards), 1)
        self.assertEqual(flashcards[0]['front'], "What is a qubit?")

        quizzes = get_quizzes(test_vid)
        self.assertEqual(len(quizzes), 1)
        self.assertEqual(quizzes[0]['correct_index'], 0)

        segments = get_transcript_segments(test_vid)
        self.assertEqual(len(segments), 1)
        self.assertIn("Quantum Computing 101", segments[0]['text'])

    def test_04_modular_reconstruction_without_analysis_json(self):
        """Verify get_modular_analysis can reconstruct the analysis object purely from relational tables."""
        test_vid = f"pure_rel_{uuid.uuid4().hex[:8]}"
        modules = {
            "_meta": {"video_id": test_vid, "title": "Pure Relational Lecture", "author": "Prof. DB", "duration": "10:00"},
            "video_overview": {"summary": "Reconstructed from tables", "target_audience": "Developers"},
            "chapters": [{"title": "Ch 1: Tables", "seconds": 60, "time": "01:00", "summary": "Normalized rows"}],
            "factual_claims": [{"claim": "SQLite supports relational schemas", "seconds": 120, "timestamp": "02:00"}],
            "learning": {
                "flashcards": [{"front": "Front Q", "back": "Back A"}],
                "quiz": [{"question": "Q1?", "options": ["A", "B", "C", "D"], "correct_index": 1, "bloom_level": "Apply"}]
            }
        }
        # Save modularly only
        saved = save_analysis_modular(test_vid, modules)
        self.assertTrue(saved)

        reconstructed = get_modular_analysis(test_vid)
        self.assertIsNotNone(reconstructed)
        self.assertEqual(reconstructed['video_overview']['summary'], "Reconstructed from tables")
        self.assertEqual(len(reconstructed['chapters']), 1)
        self.assertEqual(reconstructed['chapters'][0]['title'], "Ch 1: Tables")
        self.assertEqual(len(reconstructed['factual_claims']), 1)
        self.assertEqual(len(reconstructed['learning']['flashcards']), 1)
        self.assertEqual(len(reconstructed['learning']['quiz']), 1)

    def test_05_persistent_analysis_jobs_state_machine(self):
        """Verify analysis_jobs CRUD operations and state transitions."""
        job_id = f"job_test_{uuid.uuid4().hex[:8]}"
        vid = f"vid_{uuid.uuid4().hex[:6]}"
        
        # 1. Create job
        job = create_analysis_job(job_id, video_id=vid, user_id="user_123", session_key="sess_123")
        self.assertEqual(job['status'], 'QUEUED')
        self.assertEqual(job['stage'], 0)

        # 2. Update to EXTRACTING
        ok = update_job_status(job_id, status='EXTRACTING', stage=2, stage_name='extracting')
        self.assertTrue(ok)
        j2 = get_analysis_job(job_id)
        self.assertEqual(j2['status'], 'EXTRACTING')
        self.assertEqual(j2['stage'], 2)

        # 3. Complete job
        ok3 = update_job_status(job_id, status='COMPLETED', stage=9, stage_name='completed', modules_completed=['metadata', 'summary'])
        self.assertTrue(ok3)
        j3 = get_analysis_job(job_id)
        self.assertEqual(j3['status'], 'COMPLETED')
        self.assertIsNotNone(j3['completed_at'])
        self.assertIn('metadata', j3['modules_completed'])

        # 4. List jobs
        jobs = list_analysis_jobs(limit=10, status='COMPLETED')
        self.assertTrue(any(j['id'] == job_id for j in jobs))

    def test_06_tier_duration_limits_enforcement(self):
        """Verify video duration limits per plan tier (guest 30m, free 90m, paid unlimited)."""
        # Anonymous / Guest: 30 min (1800s)
        self.assertEqual(get_tier_duration_limit('anonymous'), 1800)
        self.assertEqual(get_tier_duration_limit('guest'), 1800)
        
        # 25 min video -> allowed for anonymous
        res_anon_ok = check_video_duration_limit(25 * 60, plan='anonymous')
        self.assertTrue(res_anon_ok['allowed'])

        # 35 min video -> rejected for anonymous
        res_anon_fail = check_video_duration_limit(35 * 60, plan='anonymous')
        self.assertFalse(res_anon_fail['allowed'])
        self.assertIn("exceeds the anonymous plan limit", res_anon_fail['reason'])

        # Free tier: 90 min (5400s)
        self.assertEqual(get_tier_duration_limit('free'), 5400)
        
        # 80 min video -> allowed for free
        res_free_ok = check_video_duration_limit("01:20:00", plan='free')
        self.assertTrue(res_free_ok['allowed'])

        # 100 min video -> rejected for free
        res_free_fail = check_video_duration_limit("01:40:00", plan='free')
        self.assertFalse(res_free_fail['allowed'])
        self.assertIn("exceeds the free plan limit", res_free_fail['reason'])

        # Paid tiers: unlimited
        self.assertIsNone(get_tier_duration_limit('pack10'))
        self.assertIsNone(get_tier_duration_limit('pack50'))
        self.assertIsNone(get_tier_duration_limit('unlimited'))

        # 4-hour video -> allowed for paid
        res_paid = check_video_duration_limit("04:00:00", plan='pack10')
        self.assertTrue(res_paid['allowed'])

    def test_07_rate_limiting_sliding_window(self):
        """Verify rate limiting prevents excessive requests and tracks reset window."""
        test_key = f"rate_key_{uuid.uuid4().hex[:6]}"
        limit = 5

        # First 5 requests allowed
        for i in range(limit):
            res = check_rate_limit(key=test_key, limit=limit, window_seconds=60)
            self.assertTrue(res['allowed'])

        # 6th request rejected
        blocked_res = check_rate_limit(key=test_key, limit=limit, window_seconds=60)
        self.assertFalse(blocked_res['allowed'])
        self.assertEqual(blocked_res['status'], 'rate_limited')
        self.assertGreaterEqual(blocked_res['reset_seconds'], 1)

    def test_08_usage_logs_tracking_and_summary(self):
        """Verify usage events are persisted in table usage_logs and aggregate properly."""
        test_user = f"user_{uuid.uuid4().hex[:6]}"
        
        # Log a few usage actions
        log_action_usage('analyze_video', video_id='vid_abc', duration_seconds=1200, tokens_used=1500, user_id=test_user, plan='free')
        log_action_usage('export_pdf', video_id='vid_abc', duration_seconds=0, tokens_used=0, user_id=test_user, plan='free')
        
        logs = get_usage_logs(user_id=test_user)
        self.assertGreaterEqual(len(logs), 2)
        
        summary = get_user_usage_summary(user_id=test_user)
        self.assertGreaterEqual(summary['total_events'], 2)
        self.assertEqual(summary['total_tokens'], 1500)
        self.assertEqual(summary['total_duration_seconds'], 1200)

    def test_09_exports_tracking(self):
        """Verify exports records are stored in table exports."""
        test_vid = f"export_vid_{uuid.uuid4().hex[:6]}"
        exp_id = record_export(test_vid, 'pdf', file_path='/tmp/dossier.pdf', file_size=102400)
        self.assertTrue(bool(exp_id))

        exports = get_exports_for_video(test_vid)
        self.assertEqual(len(exports), 1)
        self.assertEqual(exports[0]['export_type'], 'pdf')
        self.assertEqual(exports[0]['file_size'], 102400)

if __name__ == '__main__':
    unittest.main()
