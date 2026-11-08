"""
Adversarial Challenge Test Suite for Milestone 1:
- Reconstruction fidelity (save_cached_analysis -> get_modular_analysis)
- Pure modular reconstruction (without analysis_json)
- SQLite transaction rollback safety
- SQL injection immunity across all endpoints and queries
- Corrupted, missing, and malformed data resilience
- Usage service boundaries, edge formats, and thread concurrency
"""

import unittest
import uuid
import json
import sqlite3
import threading
from unittest.mock import patch

from services.storage_service import (
    init_db, init_relational_db, get_db, resolve_database_path, CACHE,
    save_cached_analysis, save_analysis, get_cached_analysis, get_analysis,
    save_analysis_modular, get_modular_analysis,
    create_analysis_job, update_job_status, get_analysis_job, list_analysis_jobs,
    log_usage_entry, get_usage_logs, record_export, get_exports_for_video,
    get_transcript_segments, get_chapters, get_claims, get_entities,
    get_flashcards, get_quizzes, get_summaries
)
from services.usage_service import (
    check_video_duration_limit, get_tier_duration_limit, get_tier_rate_limit,
    parse_duration_seconds, check_rate_limit, RATE_LIMITER,
    log_action_usage, get_user_usage_summary, SlidingWindowRateLimiter
)

class TestMilestone1AdversarialChallenge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        init_relational_db()

    def setUp(self):
        RATE_LIMITER.reset()
        CACHE.clear()

    # =========================================================================
    # 1. RECONSTRUCTION FIDELITY TESTS
    # =========================================================================

    def test_01_reconstruction_fidelity_complete_payload(self):
        """Verify that save_cached_analysis and get_modular_analysis preserve all nested structures, lists, scores, and timestamps."""
        test_vid = f"fidelity_{uuid.uuid4().hex[:8]}"
        
        original_analysis = {
            "_meta": {
                "video_id": test_vid,
                "title": "Quantum Mechanics and Superposition Deep Dive",
                "author": "Dr. Richard Quantum",
                "duration": "42:15",
                "model_used": "gemini-1.5-flash",
                "created_at": "2026-11-07T12:00:00Z"
            },
            "video_overview": {
                "title": "Quantum Mechanics and Superposition Deep Dive",
                "channel": "Dr. Richard Quantum",
                "summary": "A comprehensive lecture on wave-particle duality, Hilbert spaces, and qubits.",
                "target_audience": "Advanced Physics Students",
                "sentiment_label": "Analytical"
            },
            "key_takeaways": [
                {"id": "01", "title": "Hilbert Space", "description": "State vectors exist in complex vector space."},
                {"id": "02", "title": "Superposition", "description": "States combine linearly until measurement."}
            ],
            "timeline": [
                {
                    "title": "Introduction to Wave Mechanics",
                    "time": "00:00",
                    "seconds": 0.0,
                    "end_seconds": 300.0,
                    "summary": "Foundations of classical vs quantum states.",
                    "key_points": ["Blackbody radiation", "Photoelectric effect"]
                },
                {
                    "title": "Qubit Formulations",
                    "time": "05:00",
                    "seconds": 300.0,
                    "end_seconds": 900.0,
                    "summary": "Bloch sphere representation and Pauli matrices.",
                    "key_points": ["Bloch sphere", "Pauli X, Y, Z"]
                }
            ],
            "factual_claims": [
                {
                    "claim": "Superposition allows simultaneous evaluation of basis states.",
                    "claim_text": "Superposition allows simultaneous evaluation of basis states.",
                    "category": "factual",
                    "timestamp": "07:30",
                    "seconds": 450.0,
                    "end_seconds": 475.0,
                    "confidence_score": 0.98,
                    "verified": True,
                    "verification_note": "Verified against transcript segment 14",
                    "transcript_segment_id": f"seg_{test_vid}_14",
                    "speaker": "Dr. Richard Quantum"
                },
                {
                    "claim": "Entanglement requires non-local correlations.",
                    "claim_text": "Entanglement requires non-local correlations.",
                    "category": "theoretical",
                    "timestamp": "18:20",
                    "seconds": 1100.0,
                    "end_seconds": 1130.0,
                    "confidence_score": 0.94,
                    "verified": True,
                    "verification_note": "Bell test experiments support this",
                    "transcript_segment_id": f"seg_{test_vid}_29",
                    "speaker": "Dr. Richard Quantum"
                }
            ],
            "key_concepts": [
                {
                    "concept": "Qubit",
                    "name": "Qubit",
                    "type": "Physics",
                    "explanation": "Two-level quantum mechanical system.",
                    "relevance_score": 0.99,
                    "mention_count": 18,
                    "first_seen_seconds": 120.0
                },
                {
                    "concept": "Bloch Sphere",
                    "name": "Bloch Sphere",
                    "type": "Geometry",
                    "explanation": "Geometrical representation of the pure state space of a qubit.",
                    "relevance_score": 0.92,
                    "mention_count": 7,
                    "first_seen_seconds": 350.0
                }
            ],
            "learning": {
                "flashcards": [
                    {
                        "front": "What does the north pole of the Bloch sphere represent?",
                        "back": "State |0>",
                        "topic": "Quantum Computing",
                        "difficulty": "medium",
                        "bloom_level": "Understand"
                    },
                    {
                        "front": "What is the consequence of the No-Cloning Theorem?",
                        "back": "Unknown quantum states cannot be copied perfectly.",
                        "topic": "Quantum Information",
                        "difficulty": "hard",
                        "bloom_level": "Analyze"
                    }
                ],
                "quiz": [
                    {
                        "question": "Which mathematical construct describes a single qubit pure state?",
                        "options": ["A 2D unit vector on the Bloch sphere", "A classical bit string", "A 4D real matrix", "A Poisson distribution"],
                        "correct_index": 0,
                        "explanation": "Pure qubit states correspond to points on the surface of the Bloch sphere.",
                        "bloom_level": "Understand",
                        "timestamp": "08:15"
                    }
                ]
            },
            "transcript_segments": [
                {
                    "text": "Welcome to our comprehensive study of quantum mechanics.",
                    "start": 0.0,
                    "duration": 4.5,
                    "end": 4.5,
                    "speaker": "Dr. Richard Quantum",
                    "is_synthesized": False
                },
                {
                    "text": "Today we will begin by constructing the state space.",
                    "start": 4.5,
                    "duration": 5.0,
                    "end": 9.5,
                    "speaker": "Dr. Richard Quantum",
                    "is_synthesized": False
                }
            ],
            # Custom nested modules
            "speaker_dynamics": {
                "dominant_speaker": "Dr. Richard Quantum",
                "pace_wpm": 142
            }
        }

        # 1. Save via save_cached_analysis
        rec_id = save_cached_analysis(
            video_id=test_vid,
            title=original_analysis['_meta']['title'],
            author=original_analysis['_meta']['author'],
            duration=original_analysis['_meta']['duration'],
            analysis=original_analysis
        )
        self.assertTrue(bool(rec_id), "save_cached_analysis must return a valid record id")

        # 2. Clear in-memory cache to force reading from disk/SQLite
        CACHE.clear()

        # 3. Read back via get_modular_analysis
        reconstructed = get_modular_analysis(test_vid)
        self.assertIsNotNone(reconstructed, "get_modular_analysis must return a reconstructed dict")

        # 4. Verify _meta fidelity
        self.assertEqual(reconstructed['_meta']['video_id'], test_vid)
        self.assertEqual(reconstructed['_meta']['title'], original_analysis['_meta']['title'])
        self.assertEqual(reconstructed['_meta']['author'], original_analysis['_meta']['author'])
        self.assertEqual(reconstructed['_meta']['duration'], original_analysis['_meta']['duration'])

        # 5. Verify video_overview fidelity
        self.assertEqual(reconstructed['video_overview']['summary'], original_analysis['video_overview']['summary'])
        self.assertEqual(reconstructed['video_overview']['target_audience'], original_analysis['video_overview']['target_audience'])
        self.assertEqual(reconstructed['video_overview']['sentiment_label'], original_analysis['video_overview']['sentiment_label'])

        # 6. Verify key_takeaways fidelity
        self.assertEqual(len(reconstructed['key_takeaways']), 2)
        self.assertEqual(reconstructed['key_takeaways'][0]['title'], "Hilbert Space")
        self.assertEqual(reconstructed['key_takeaways'][1]['title'], "Superposition")

        # 7. Verify timeline/chapters fidelity
        self.assertEqual(len(reconstructed['chapters']), 2)
        self.assertEqual(reconstructed['chapters'][0]['title'], "Introduction to Wave Mechanics")
        self.assertEqual(reconstructed['chapters'][0]['seconds'], 0.0)
        self.assertEqual(reconstructed['chapters'][0]['end_seconds'], 300.0)
        self.assertEqual(reconstructed['chapters'][0]['key_points'], ["Blackbody radiation", "Photoelectric effect"])
        self.assertEqual(reconstructed['chapters'][1]['seconds'], 300.0)

        # 8. Verify factual_claims fidelity
        self.assertEqual(len(reconstructed['factual_claims']), 2)
        c0 = reconstructed['factual_claims'][0]
        self.assertIn("Superposition", c0['claim'])
        self.assertEqual(c0['timestamp'], "07:30")
        self.assertEqual(c0['seconds'], 450.0)
        self.assertEqual(c0['end_seconds'], 475.0)
        self.assertAlmostEqual(c0['confidence_score'], 0.98, places=2)
        self.assertTrue(c0['verified'])
        self.assertEqual(c0['speaker'], "Dr. Richard Quantum")

        # 9. Verify key_concepts fidelity
        self.assertEqual(len(reconstructed['key_concepts']), 2)
        e0 = reconstructed['key_concepts'][0]
        self.assertEqual(e0['concept'], "Qubit")
        self.assertEqual(e0['type'], "Physics")
        self.assertAlmostEqual(e0['relevance_score'], 0.99, places=2)
        self.assertEqual(e0['mention_count'], 18)
        self.assertEqual(e0['first_seen_seconds'], 120.0)

        # 10. Verify flashcards & quizzes fidelity
        self.assertEqual(len(reconstructed['learning']['flashcards']), 2)
        self.assertEqual(reconstructed['learning']['flashcards'][0]['difficulty'], "medium")
        self.assertEqual(reconstructed['learning']['flashcards'][1]['difficulty'], "hard")

        self.assertEqual(len(reconstructed['learning']['quiz']), 1)
        q0 = reconstructed['learning']['quiz'][0]
        self.assertEqual(q0['correct_index'], 0)
        self.assertEqual(len(q0['options']), 4)
        self.assertEqual(q0['bloom_level'], "Understand")
        self.assertEqual(q0['timestamp'], "08:15")

        # 11. Verify transcript segments fidelity
        self.assertEqual(len(reconstructed['transcript_segments']), 2)
        self.assertEqual(reconstructed['transcript_segments'][0]['start'], 0.0)
        self.assertEqual(reconstructed['transcript_segments'][0]['duration'], 4.5)
        self.assertEqual(reconstructed['transcript_segments'][0]['speaker'], "Dr. Richard Quantum")
        self.assertFalse(reconstructed['transcript_segments'][0]['is_synthesized'])

        # 12. Verify custom module survived
        self.assertEqual(reconstructed['speaker_dynamics']['dominant_speaker'], "Dr. Richard Quantum")
        self.assertEqual(reconstructed['speaker_dynamics']['pace_wpm'], 142)

    def test_02_pure_modular_reconstruction_without_analysis_json(self):
        """Verify that when videos.analysis_json is completely NULL, get_modular_analysis reconstructs all relational entities."""
        test_vid = f"pure_rel_{uuid.uuid4().hex[:8]}"

        sample = {
            "_meta": {"video_id": test_vid, "title": "Pure Relational DB Lecture", "author": "Prof. Normalizer", "duration": "25:00"},
            "video_overview": {"summary": "Lecture on 1NF, 2NF, 3NF, and BCNF.", "target_audience": "DBA Students", "sentiment_label": "Educational"},
            "key_takeaways": [{"id": "01", "title": "Normalization", "description": "Reduces redundancy."}],
            "chapters": [{"title": "1NF", "seconds": 60.0, "end_seconds": 300.0, "time": "01:00", "summary": "Atomic values", "key_points": ["No repeating groups"]}],
            "factual_claims": [{"claim": "3NF removes transitive dependencies", "seconds": 600.0, "timestamp": "10:00", "confidence_score": 0.99, "verified": True}],
            "key_concepts": [{"concept": "Functional Dependency", "type": "Theory", "explanation": "Constraint between attributes", "relevance_score": 0.95, "mention_count": 8, "first_seen_seconds": 180.0}],
            "learning": {
                "flashcards": [{"front": "What is BCNF?", "back": "Boyce-Codd Normal Form", "difficulty": "hard", "bloom_level": "Understand"}],
                "quiz": [{"question": "What does 2NF eliminate?", "options": ["Partial dependencies", "Transitive dependencies", "Nulls", "Cycles"], "correct_index": 0, "bloom_level": "Analyze", "timestamp": "08:00"}]
            },
            "transcript_segments": [{"text": "Welcome to relational database theory.", "start": 0.0, "duration": 4.0, "speaker": "Prof. Normalizer"}]
        }

        # Save via save_cached_analysis first to populate video record & modular tables
        save_cached_analysis(test_vid, sample['_meta']['title'], sample['_meta']['author'], sample['_meta']['duration'], sample)

        # Now forcibly NULL out analysis_json in videos table to simulate missing/deleted JSON blob
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE videos SET analysis_json = NULL WHERE video_id = ?", (test_vid,))
            conn.commit()

        CACHE.clear()

        # Reconstruct purely from relational tables
        reconstructed = get_modular_analysis(test_vid)
        self.assertIsNotNone(reconstructed)

        # Meta reconstructed from videos columns
        self.assertEqual(reconstructed['_meta']['video_id'], test_vid)
        self.assertEqual(reconstructed['_meta']['title'], "Pure Relational DB Lecture")

        # Relational entities reconstructed
        self.assertIn("1NF", reconstructed['video_overview']['summary'])
        self.assertEqual(reconstructed['video_overview']['target_audience'], "DBA Students")
        self.assertEqual(len(reconstructed['key_takeaways']), 1)
        self.assertEqual(len(reconstructed['chapters']), 1)
        self.assertEqual(reconstructed['chapters'][0]['key_points'], ["No repeating groups"])
        self.assertEqual(len(reconstructed['factual_claims']), 1)
        self.assertEqual(reconstructed['factual_claims'][0]['confidence_score'], 0.99)
        self.assertEqual(len(reconstructed['key_concepts']), 1)
        self.assertEqual(reconstructed['key_concepts'][0]['concept'], "Functional Dependency")
        self.assertEqual(len(reconstructed['learning']['flashcards']), 1)
        self.assertEqual(len(reconstructed['learning']['quiz']), 1)
        self.assertEqual(len(reconstructed['transcript_segments']), 1)

    # =========================================================================
    # 2. TRANSACTION ROLLBACK TESTS
    # =========================================================================

    def test_03_transaction_rollback_on_modular_save_error(self):
        """Verify that if an unhandled error occurs during modular save, the transaction rolls back cleanly without orphan rows."""
        test_vid = f"rollback_vid_{uuid.uuid4().hex[:8]}"

        # Pre-seed initial state
        initial_data = {
            "video_overview": {"summary": "Original intact summary"},
            "chapters": [{"title": "Original Chapter", "seconds": 0, "time": "00:00"}]
        }
        ok = save_analysis_modular(test_vid, initial_data)
        self.assertTrue(ok)

        # Confirm original chapter and summary are saved
        init_chaps = get_chapters(test_vid)
        self.assertEqual(len(init_chaps), 1)
        self.assertEqual(init_chaps[0]['title'], "Original Chapter")

        init_sums = get_summaries(test_vid)
        self.assertEqual(len(init_sums), 1)
        self.assertEqual(init_sums[0]['content'], "Original intact summary")

        # Now simulate an update that crashes in the middle of save_analysis_modular
        corrupted_payload = {
            "video_overview": {"summary": "New summary that should be rolled back"},
            "chapters": [{"title": "New Chapter", "seconds": 10}],
            "claims": [{"claim": "This claim will trigger an error"}]
        }

        # Use a proxy connection on get_db that raises OperationalError when inserting into claims
        from services import storage_service
        orig_get_db = storage_service.get_db

        class FaultyCursor:
            def __init__(self, real_cursor):
                self._real = real_cursor
            def execute(self, sql, params=()):
                if "INSERT INTO claims" in sql:
                    raise sqlite3.OperationalError("Simulated disk error during claims insert")
                return self._real.execute(sql, params)
            def fetchone(self):
                return self._real.fetchone()
            def fetchall(self):
                return self._real.fetchall()
            def __getattr__(self, name):
                return getattr(self._real, name)

        class FaultyConnection:
            def __init__(self, real_conn):
                self._conn = real_conn
            def cursor(self):
                return FaultyCursor(self._conn.cursor())
            def commit(self):
                return self._conn.commit()
            def rollback(self):
                return self._conn.rollback()
            def __enter__(self):
                self._conn.__enter__()
                return self
            def __exit__(self, exc_type, exc_val, exc_tb):
                return self._conn.__exit__(exc_type, exc_val, exc_tb)
            def __getattr__(self, name):
                return getattr(self._conn, name)

        def mock_get_db():
            return FaultyConnection(orig_get_db())

        with patch('services.storage_service.get_db', side_effect=mock_get_db):
            result = save_analysis_modular(test_vid, corrupted_payload)
            self.assertFalse(result, "save_analysis_modular should return False upon exception")

        # Verify rollback: the database should retain the original chapters and summaries,
        # and NOT leave the partial new summary or delete existing chapters!
        post_chaps = get_chapters(test_vid)
        self.assertEqual(len(post_chaps), 1, "Chapters must be rolled back to original count")
        self.assertEqual(post_chaps[0]['title'], "Original Chapter", "Original chapter title must remain intact after rollback")

        post_sums = get_summaries(test_vid)
        self.assertEqual(len(post_sums), 1)
        self.assertEqual(post_sums[0]['content'], "Original intact summary")

    # =========================================================================
    # 3. SQL INJECTION IMMUNITY TESTS
    # =========================================================================

    def test_04_sql_injection_safety_across_all_endpoints(self):
        """Stress-test SQL injection safety across all queries using hostile injection strings."""
        hostile_strings = [
            "'; DROP TABLE users; --",
            "\" OR \"\"=\"",
            "' UNION SELECT * FROM sqlite_master --",
            "admin'--",
            "1; ATTACH DATABASE ':memory:' AS injected; --",
            "Robert'); DROP TABLE videos;--",
            "test' OR 1=1; --"
        ]

        for hostile in hostile_strings:
            vid = f"sqli_{uuid.uuid4().hex[:6]}_{hostile}"
            user = f"user_{hostile}"
            session = f"sess_{hostile}"
            job_id = f"job_{uuid.uuid4().hex[:6]}_{hostile}"

            # 1. save_cached_analysis with hostile inputs
            rec_id = save_cached_analysis(
                video_id=vid,
                title=f"Hostile Title {hostile}",
                author=f"Author {hostile}",
                duration="10:00",
                analysis={"summary": f"Content {hostile}"},
                user_id=user,
                session_key=session
            )
            self.assertTrue(bool(rec_id), f"save_cached_analysis should safely handle hostile string: {hostile}")

            # 2. get_cached_analysis & get_modular_analysis
            cached = get_cached_analysis(vid)
            self.assertIsNotNone(cached)
            modular = get_modular_analysis(vid)
            self.assertIsNotNone(modular)

            # 3. create_analysis_job & update_job_status
            job = create_analysis_job(job_id=job_id, video_id=vid, user_id=user, session_key=session)
            self.assertIsNotNone(job)
            self.assertEqual(job['id'], job_id)

            ok_up = update_job_status(job_id, status=f"STAT_{hostile}", error=f"ERR_{hostile}", stage=1)
            self.assertTrue(ok_up)

            job_read = get_analysis_job(job_id)
            self.assertIsNotNone(job_read)
            self.assertEqual(job_read['status'], f"STAT_{hostile}")

            # 4. list_analysis_jobs with hostile status & user_id
            jobs = list_analysis_jobs(status=f"STAT_{hostile}", user_id=user)
            self.assertTrue(any(j['id'] == job_id for j in jobs))

            # 5. log_usage_entry & get_usage_logs
            log_id = log_usage_entry(
                user_id=user,
                session_key=session,
                ip_address="127.0.0.1",
                action=f"act_{hostile}",
                video_id=vid
            )
            self.assertTrue(bool(log_id))

            logs = get_usage_logs(user_id=user, action=f"act_{hostile}")
            self.assertTrue(len(logs) >= 1)

            # 6. get_user_usage_summary with hostile user_id
            summary = get_user_usage_summary(user_id=user)
            self.assertGreaterEqual(summary['total_events'], 1)

        # Verify critical tables were NOT dropped by any hostile string
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r['name'] for r in c.fetchall()}
            for expected in ['users', 'videos', 'analysis_jobs', 'usage_logs', 'summaries']:
                self.assertIn(expected, tables, f"Critical table {expected} must survive SQL injection attempts")

    # =========================================================================
    # 4. CORRUPTED & MALFORMED DATA RESILIENCE
    # =========================================================================

    def test_05_corrupted_and_missing_field_resilience(self):
        """Verify resilience against corrupted JSON, missing fields, malformed numbers, and None values."""
        
        # 1. Non-existent video returns None safely
        self.assertIsNone(get_cached_analysis("definitely_non_existent_video_id"))
        self.assertIsNone(get_modular_analysis("definitely_non_existent_video_id"))
        self.assertIsNone(get_cached_analysis(None))
        self.assertIsNone(get_modular_analysis(None))
        self.assertIsNone(get_cached_analysis(""))
        self.assertIsNone(get_modular_analysis(""))

        # 2. Corrupted JSON string in videos.analysis_json
        corrupt_vid = f"corrupt_{uuid.uuid4().hex[:6]}"
        with get_db() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO videos (id, video_id, title, analysis_json, created_at) VALUES (?, ?, ?, ?, ?)",
                      (str(uuid.uuid4()), corrupt_vid, "Corrupt Video", "{this is: not valid json at all!", "2026-11-07T00:00:00"))
            conn.commit()

        # Calling get_cached_analysis or get_modular_analysis should NOT raise JSONDecodeError
        res_cached = get_cached_analysis(corrupt_vid)
        # Should gracefully return None or fallback without crashing
        self.assertTrue(res_cached is None or isinstance(res_cached, dict))

        res_modular = get_modular_analysis(corrupt_vid)
        self.assertTrue(res_modular is None or isinstance(res_modular, dict))

        # 3. Malformed items in modular save:
        malformed_vid = f"malformed_{uuid.uuid4().hex[:6]}"
        malformed_modules = {
            "summary": 12345,  # Number instead of string
            "video_overview": "not a dict",  # String instead of dict
            "chapters": [
                None,  # None item in list
                {},    # Empty dict
                {"title": None, "seconds": "not_a_number", "key_points": "not_a_list"}
            ],
            "factual_claims": [
                None,
                {"claim": None, "confidence_score": "invalid_percent%", "seconds": "abc"}
            ],
            "key_concepts": [
                {"concept": 999, "relevance_score": "not_a_float", "mention_count": "three"}
            ],
            "learning": {
                "flashcards": [None, {"front": None, "back": None}],
                "quiz": [None, {"question": None, "options": "not_a_list", "correct_index": "zero"}]
            },
            "transcript_segments": [
                {"text": "Sample", "start": "zero", "duration": "ten"}
            ]
        }

        # Should handle gracefully without unhandled crashes
        saved = save_analysis_modular(malformed_vid, malformed_modules)
        # Even if it succeeds partially or fails, it must not throw an unhandled exception
        self.assertIsInstance(saved, bool)

    # =========================================================================
    # 5. USAGE SERVICE BOUNDARY & CONCURRENCY TESTS
    # =========================================================================

    def test_06_duration_parsing_and_tier_boundary_edge_cases(self):
        """Test duration parsing and tier limits with extreme values."""
        # Extreme / malformed values
        self.assertEqual(parse_duration_seconds(None), 0)
        self.assertEqual(parse_duration_seconds(""), 0)
        self.assertEqual(parse_duration_seconds("abc"), 0)
        self.assertEqual(parse_duration_seconds(-500), 0)
        self.assertEqual(parse_duration_seconds(120.75), 120)

        # Standard formats
        self.assertEqual(parse_duration_seconds("45"), 45)
        self.assertEqual(parse_duration_seconds("14:20"), 860)
        self.assertEqual(parse_duration_seconds("01:30:15"), 5415)
        self.assertEqual(parse_duration_seconds("PT1H30M"), 5400)
        self.assertEqual(parse_duration_seconds("PT45S"), 45)

        # Tier boundaries: exactly at limit vs 1 second over
        # Anonymous limit is 1800s
        self.assertTrue(check_video_duration_limit(1800, plan='anonymous')['allowed'])
        self.assertFalse(check_video_duration_limit(1801, plan='anonymous')['allowed'])

        # Free tier limit is 5400s
        self.assertTrue(check_video_duration_limit(5400, plan='free')['allowed'])
        self.assertFalse(check_video_duration_limit(5401, plan='free')['allowed'])

        # Paid tiers: arbitrary large numbers allowed
        self.assertTrue(check_video_duration_limit(9999999, plan='pack10')['allowed'])
        self.assertTrue(check_video_duration_limit(9999999, plan='unlimited')['allowed'])

    def test_07_rate_limiter_multithreaded_concurrency(self):
        """Verify thread-safety of SlidingWindowRateLimiter under concurrent requests."""
        limiter = SlidingWindowRateLimiter()
        test_key = f"concurrent_key_{uuid.uuid4().hex[:6]}"
        limit = 50
        allowed_count = 0
        blocked_count = 0
        lock = threading.Lock()

        def make_request():
            nonlocal allowed_count, blocked_count
            allowed, _ = limiter.check(test_key, limit=limit, window_seconds=10)
            with lock:
                if allowed:
                    allowed_count += 1
                else:
                    blocked_count += 1

        threads = [threading.Thread(target=make_request) for _ in range(80)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(allowed_count, limit, f"Exactly {limit} requests should be allowed concurrently")
        self.assertEqual(blocked_count, 30, "Remaining 30 requests must be blocked")

if __name__ == '__main__':
    unittest.main()
