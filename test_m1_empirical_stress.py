"""
Adversarial Stress Test Suite for Milestone 1 (Empirical Challenger):
- Database Operations & Concurrency Stress (concurrent reads/writes, thread safety)
- Massive Modular Payloads (300+ segments, 50+ chapters, long summaries)
- Unicode, Emojis, Ampersands, Quotes, and SQL Injection resilience
- Usage Service Duration Boundary Conditions (1799s vs 1800s vs 1801s; 5399s vs 5400s vs 5401s; ISO strings)
- Rapid Sliding-Window Rate Limiter Under Concurrent Multi-Threaded Floods
- Malformed & Adversarial Inputs Resilience
"""

import unittest
import uuid
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

from services.storage_service import (
    init_db, init_relational_db, get_db, resolve_database_path,
    save_cached_analysis, save_analysis, get_cached_analysis, get_analysis,
    save_analysis_modular, get_modular_analysis,
    create_analysis_job, update_job_status, get_analysis_job, list_analysis_jobs,
    log_usage_entry, get_usage_logs, record_export, get_exports_for_video,
    get_transcript_segments, get_chapters, get_claims, get_entities,
    get_flashcards, get_quizzes, get_summaries,
    create_user, get_user, CACHE
)
from services.usage_service import (
    check_video_duration_limit, get_tier_duration_limit, get_tier_rate_limit,
    parse_duration_seconds, check_rate_limit, SlidingWindowRateLimiter,
    RATE_LIMITER, log_action_usage, get_user_usage_summary
)


class TestMilestone1EmpiricalStress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        init_relational_db()

    def setUp(self):
        RATE_LIMITER.reset()

    # =========================================================================
    # 1. CONCURRENT READ / WRITE STRESS TESTS
    # =========================================================================

    def test_01_concurrent_writes_multiple_videos(self):
        """Stress-test 20 concurrent threads writing distinct analyses simultaneously."""
        num_threads = 20
        results = []
        video_ids = [f"conc_vid_{i}_{uuid.uuid4().hex[:6]}" for i in range(num_threads)]

        def worker_write(vid, index):
            payload = {
                "_meta": {"video_id": vid, "title": f"Concurrent Title {index}", "duration": "10:00"},
                "video_overview": {"summary": f"Summary for concurrent video {index}"},
                "chapters": [{"title": f"Chap {j}", "seconds": j * 60, "time": f"{j:02d}:00"} for j in range(5)],
                "transcript_segments": [
                    {"text": f"Segment {k} text for {vid}", "start": float(k * 2), "duration": 2.0}
                    for k in range(10)
                ]
            }
            res_id = save_cached_analysis(vid, f"Concurrent Title {index}", "Author", "10:00", payload)
            return vid, bool(res_id)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_write, vid, idx) for idx, vid in enumerate(video_ids)]
            for fut in as_completed(futures):
                results.append(fut.result())

        # Verify all 20 writes succeeded
        self.assertEqual(len(results), num_threads)
        for vid, success in results:
            self.assertTrue(success, f"Concurrent write for {vid} failed")

        # Verify all videos persist in SQLite videos and normalized tables
        with get_db() as conn:
            c = conn.cursor()
            for vid in video_ids:
                c.execute("SELECT id, title FROM videos WHERE video_id = ?", (vid,))
                row = c.fetchone()
                self.assertIsNotNone(row, f"Video {vid} missing from videos table")

                # Verify transcript segments in normalized table
                c.execute("SELECT COUNT(*) as cnt FROM transcript_segments WHERE video_id = ?", (vid,))
                cnt = c.fetchone()['cnt']
                self.assertEqual(cnt, 10, f"Video {vid} should have 10 segments in transcript_segments")

    def test_02_concurrent_mixed_readers_and_writers(self):
        """Stress-test mixed concurrent readers and writers without database locking crashes."""
        base_vid = f"readwrite_vid_{uuid.uuid4().hex[:6]}"
        initial_data = {
            "_meta": {"video_id": base_vid, "title": "Base Video"},
            "video_overview": {"summary": "Initial summary"},
            "chapters": [{"title": "Ch 1", "seconds": 0, "time": "00:00"}]
        }
        save_cached_analysis(base_vid, "Base Video", "Author", "05:00", initial_data)

        read_errors = []
        write_errors = []

        def worker_reader(idx):
            try:
                for _ in range(5):
                    data = get_modular_analysis(base_vid)
                    if not data or 'video_overview' not in data:
                        read_errors.append(f"Reader {idx}: missing overview")
            except Exception as e:
                read_errors.append(f"Reader {idx} exception: {e}")

        def worker_writer(idx):
            try:
                vid = f"mixed_w_{idx}_{uuid.uuid4().hex[:4]}"
                payload = {
                    "_meta": {"video_id": vid, "title": f"Writer {idx}"},
                    "video_overview": {"summary": f"Writer {idx} summary"},
                    "chapters": [{"title": "Ch 1", "seconds": 10, "time": "00:10"}]
                }
                ok = save_analysis_modular(vid, payload)
                if not ok:
                    write_errors.append(f"Writer {idx}: save_analysis_modular returned False")
            except Exception as e:
                write_errors.append(f"Writer {idx} exception: {e}")

        threads = []
        for i in range(8):
            threads.append(threading.Thread(target=worker_reader, args=(i,)))
            threads.append(threading.Thread(target=worker_writer, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(read_errors, [], f"Read errors occurred: {read_errors}")
        self.assertEqual(write_errors, [], f"Write errors occurred: {write_errors}")

    def test_03a_concurrent_updates_to_existing_video(self):
        """Stress-test concurrent updates to an already existing video_id: preserves exactly 1 row in videos."""
        same_vid = f"exist_race_{uuid.uuid4().hex[:6]}"
        # Seed initial record
        save_cached_analysis(same_vid, "Initial Title", "Author", "05:00", {
            "_meta": {"video_id": same_vid, "title": "Initial Title"},
            "video_overview": {"summary": "Initial"}
        })

        num_updates = 10

        def update_worker(version):
            payload = {
                "_meta": {"video_id": same_vid, "title": f"Version {version}"},
                "video_overview": {"summary": f"Summary version {version}"},
                "chapters": [{"title": f"Chapter v{version}", "seconds": version * 10, "time": "01:00"}],
                "transcript_segments": [{"text": f"Text v{version}", "start": 0.0, "duration": 5.0}]
            }
            return save_cached_analysis(same_vid, f"Version {version}", "Author", "05:00", payload)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_worker, i) for i in range(num_updates)]
            results = [f.result() for f in as_completed(futures)]

        self.assertEqual(len(results), num_updates)
        self.assertTrue(all(bool(r) for r in results))

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as cnt FROM videos WHERE video_id = ?", (same_vid,))
            self.assertEqual(c.fetchone()['cnt'], 1, "Existing video updates must maintain exactly 1 record in videos")

            # Verify relational integrity
            c.execute("SELECT COUNT(*) as cnt FROM chapters WHERE video_id = ?", (same_vid,))
            self.assertEqual(c.fetchone()['cnt'], 1)
            c.execute("SELECT COUNT(*) as cnt FROM transcript_segments WHERE video_id = ?", (same_vid,))
            self.assertEqual(c.fetchone()['cnt'], 1)

    def test_03b_probe_concurrent_initial_inserts_anomaly(self):
        """Adversarial probe: Document check-then-act race behavior during simultaneous initial creation of new video."""
        brand_new_vid = f"brand_new_race_{uuid.uuid4().hex[:6]}"
        num_threads = 6

        def insert_worker(idx):
            payload = {
                "_meta": {"video_id": brand_new_vid, "title": f"Concurrent Insert {idx}"},
                "video_overview": {"summary": f"Summary {idx}"}
            }
            return save_cached_analysis(brand_new_vid, f"Concurrent Insert {idx}", "Author", "05:00", payload)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(insert_worker, i) for i in range(num_threads)]
            results = [f.result() for f in as_completed(futures)]

        self.assertEqual(len(results), num_threads)
        self.assertTrue(all(bool(r) for r in results))

        # Even if multiple rows are inserted in videos due to check-then-act race condition,
        # verify that get_cached_analysis and get_modular_analysis still safely retrieve valid data
        cached = get_cached_analysis(brand_new_vid)
        self.assertIsNotNone(cached)
        self.assertIn("Concurrent Insert", cached['_meta']['title'])

        modular = get_modular_analysis(brand_new_vid)
        self.assertIsNotNone(modular)
        self.assertIn("Concurrent Insert", modular['_meta']['title'])

    def test_04_concurrent_analysis_jobs_lifecycle(self):
        """Stress-test concurrent job state machine creation and updates."""
        num_jobs = 15
        job_ids = [f"job_stress_{i}_{uuid.uuid4().hex[:6]}" for i in range(num_jobs)]

        def job_lifecycle(jid):
            v_id = f"vid_for_{jid}"
            created = create_analysis_job(jid, video_id=v_id, user_id="user_conc", session_key="sess_conc")
            if created['status'] != 'QUEUED':
                return False, "Initial status not QUEUED"
            ok1 = update_job_status(jid, status='EXTRACTING', stage=1, stage_name='extracting')
            if not ok1:
                return False, "Failed to update to EXTRACTING"
            ok2 = update_job_status(jid, status='PROCESSING', stage=5, stage_name='processing', progress=50)
            if not ok2:
                return False, "Failed to update to PROCESSING"
            ok3 = update_job_status(
                jid, status='COMPLETED', stage=9, stage_name='completed',
                modules_completed=['summary', 'transcript'], progress=100
            )
            if not ok3:
                return False, "Failed to update to COMPLETED"
            return True, "OK"

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(job_lifecycle, jid) for jid in job_ids]
            for fut in as_completed(futures):
                success, msg = fut.result()
                self.assertTrue(success, msg)

        for jid in job_ids:
            job = get_analysis_job(jid)
            self.assertIsNotNone(job)
            self.assertEqual(job['status'], 'COMPLETED')
            self.assertEqual(job['stage'], 9)
            self.assertEqual(job['progress'], 100)
            self.assertIsNotNone(job['completed_at'])
            self.assertIn('summary', job['modules_completed'])

    # =========================================================================
    # 2. LARGE PAYLOAD & MODULAR STRUCTURE STRESS TESTS
    # =========================================================================

    def test_05_large_modular_structure_300_segments_and_deep_trees(self):
        """Stress-test saving and modular reconstruction of 300+ segments, 50 chapters, 100 claims, 40 flashcards."""
        large_vid = f"large_vid_{uuid.uuid4().hex[:8]}"

        segments = [
            {
                "text": f"Transcript segment {i}: In-depth technical explanation of quantum electrodynamics point {i}.",
                "start": float(i * 3.5),
                "duration": 3.5,
                "speaker": f"Speaker_{i % 3}",
                "is_synthesized": (i % 5 == 0)
            }
            for i in range(300)
        ]

        chapters = [
            {
                "title": f"Chapter {i}: Detailed Exploration of Part {i}",
                "seconds": float(i * 21),
                "end_seconds": float((i + 1) * 21),
                "time": f"{int((i * 21) // 60):02d}:{int((i * 21) % 60):02d}",
                "summary": f"Comprehensive chapter summary for section {i}.",
                "key_points": [f"Key point A for ch {i}", f"Key point B for ch {i}"]
            }
            for i in range(50)
        ]

        claims = [
            {
                "claim": f"Verifiable scientific claim {i} regarding quantum states.",
                "category": "factual" if i % 2 == 0 else "speculative",
                "timestamp": f"{int((i * 10) // 60):02d}:{int((i * 10) % 60):02d}",
                "seconds": float(i * 10),
                "confidence_score": 0.85 + (i % 15) * 0.01,
                "verified": (i % 3 != 0),
                "verification_note": f"Matched segment {i}"
            }
            for i in range(100)
        ]

        flashcards = [
            {
                "front": f"Concept Q{i} - Define principle {i}?",
                "back": f"Answer for principle {i}: Definition and application.",
                "topic": "Physics",
                "difficulty": "hard" if i % 2 == 0 else "medium",
                "bloom_level": "Understand"
            }
            for i in range(40)
        ]

        quizzes = [
            {
                "question": f"Question {i}: Which statement about quantum system {i} is accurate?",
                "options": [f"Option A{i}", f"Option B{i}", f"Option C{i}", f"Option D{i}"],
                "correct_index": i % 4,
                "explanation": f"Explanation {i} based on chapter {i % 10}",
                "bloom_level": "Evaluate",
                "timestamp": f"{i:02d}:00"
            }
            for i in range(25)
        ]

        large_payload = {
            "_meta": {
                "video_id": large_vid,
                "title": "Quantum Physics Masterclass (3-Hour Special)",
                "author": "Prof. Quantum",
                "duration": "03:00:00",
                "model_used": "Gemini Pro"
            },
            "video_overview": {
                "summary": "Massive masterclass covering quantum mechanics from basics to advanced QED.",
                "target_audience": "Advanced Researchers & Graduate Students",
                "sentiment_label": "Analytical"
            },
            "key_takeaways": [f"Takeaway {i}: Important takeaway summary." for i in range(20)],
            "chapters": chapters,
            "factual_claims": claims,
            "learning": {
                "flashcards": flashcards,
                "quiz": quizzes
            },
            "transcript_segments": segments
        }

        # 1. Save modularly
        t0 = time.time()
        saved = save_analysis_modular(large_vid, large_payload)
        t_save = time.time() - t0
        self.assertTrue(saved, "Failed to save massive modular payload")
        self.assertLess(t_save, 5.0, f"Saving 300 segments took too long: {t_save:.2f}s")

        # 2. Reconstruct from relational tables
        t0 = time.time()
        reconstructed = get_modular_analysis(large_vid)
        t_load = time.time() - t0
        self.assertIsNotNone(reconstructed, "Failed to reconstruct modular analysis")
        self.assertLess(t_load, 2.0, f"Loading modular analysis took too long: {t_load:.2f}s")

        # 3. Assert exact counts and integrity
        self.assertEqual(len(reconstructed['transcript_segments']), 300)
        self.assertEqual(reconstructed['transcript_segments'][0]['text'], segments[0]['text'])
        self.assertEqual(reconstructed['transcript_segments'][299]['text'], segments[299]['text'])
        self.assertAlmostEqual(reconstructed['transcript_segments'][299]['start'], 299 * 3.5)

        self.assertEqual(len(reconstructed['chapters']), 50)
        self.assertEqual(reconstructed['chapters'][0]['title'], chapters[0]['title'])
        self.assertEqual(reconstructed['chapters'][49]['title'], chapters[49]['title'])

        self.assertEqual(len(reconstructed['factual_claims']), 100)
        self.assertEqual(len(reconstructed['learning']['flashcards']), 40)
        self.assertEqual(len(reconstructed['learning']['quiz']), 25)

    def test_06_very_long_summary_text_preservation(self):
        """Stress-test saving and retrieving summaries with 50,000+ characters of text."""
        long_vid = f"long_text_vid_{uuid.uuid4().hex[:8]}"
        paragraphs = [
            f"### Section {i}\nThis is a long analytical treatise paragraph {i} providing extensive theoretical detail "
            f"on algorithms, computational geometry, asymptotic bounds, and system architecture. " * 5
            for i in range(120)
        ]
        long_summary = "\n\n".join(paragraphs)
        self.assertGreater(len(long_summary), 50000)

        payload = {
            "_meta": {"video_id": long_vid, "title": "Mega Document"},
            "video_overview": {"summary": long_summary, "target_audience": "Engineers"}
        }

        save_cached_analysis(long_vid, "Mega Document", "Author", "01:00:00", payload)
        CACHE.pop(long_vid, None)

        retrieved = get_cached_analysis(long_vid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(len(retrieved['video_overview']['summary']), len(long_summary))
        self.assertEqual(retrieved['video_overview']['summary'], long_summary)

    def test_07_adversarial_unicode_quotes_ampersands_emoji_sql_injection(self):
        """Stress-test Unicode, emojis, ampersands, XML tags, smart quotes, and SQL injection strings."""
        unicode_vid = f"unicode_vid_{uuid.uuid4().hex[:8]}"

        adversarial_strings = {
            "emoji_title": "🚀 LensYou: Quantum & AI in 2026! 🔥 💡 👨‍💻 👩‍👩‍👧‍👦 🏳️‍🌈",
            "quotes_summary": """Testing "double quotes", 'single quotes', `backticks`, “curly quotes”, ‘smart apostrophes’, and «guillemets».""",
            "ampersands_and_xml": "Tom & Jerry &amp; Rock & Roll <script>alert('XSS')</script> <tag attr=\"val\"> &lt;tag&gt;",
            "foreign_scripts": "日本語テキスト / العربية / हिन्दी शब्दावली / Русский текст / Ελληνικά / ∑(x) = ∫ y dt √π ∞",
            "sql_injection_attempt": "'; DROP TABLE summaries; DROP TABLE users; SELECT * FROM videos WHERE '1'='1"
        }

        payload = {
            "_meta": {
                "video_id": unicode_vid,
                "title": adversarial_strings["emoji_title"],
                "author": adversarial_strings["foreign_scripts"]
            },
            "video_overview": {
                "summary": adversarial_strings["quotes_summary"],
                "target_audience": adversarial_strings["ampersands_and_xml"]
            },
            "chapters": [
                {
                    "title": adversarial_strings["sql_injection_attempt"],
                    "seconds": 0.0,
                    "time": "00:00",
                    "summary": adversarial_strings["emoji_title"],
                    "key_points": [adversarial_strings["quotes_summary"], adversarial_strings["ampersands_and_xml"]]
                }
            ],
            "factual_claims": [
                {
                    "claim": adversarial_strings["sql_injection_attempt"],
                    "timestamp": "01:00",
                    "seconds": 60.0
                }
            ],
            "transcript_segments": [
                {
                    "text": adversarial_strings["foreign_scripts"] + " " + adversarial_strings["emoji_title"],
                    "start": 0.0,
                    "duration": 5.0
                }
            ]
        }

        res_id = save_cached_analysis(unicode_vid, adversarial_strings["emoji_title"], adversarial_strings["foreign_scripts"], "10:00", payload)
        self.assertTrue(bool(res_id))
        CACHE.pop(unicode_vid, None)

        reconstructed = get_modular_analysis(unicode_vid)
        self.assertIsNotNone(reconstructed)

        self.assertEqual(reconstructed['video_overview']['summary'], adversarial_strings["quotes_summary"])
        self.assertEqual(reconstructed['video_overview']['target_audience'], adversarial_strings["ampersands_and_xml"])
        self.assertEqual(reconstructed['chapters'][0]['title'], adversarial_strings["sql_injection_attempt"])
        self.assertEqual(reconstructed['chapters'][0]['summary'], adversarial_strings["emoji_title"])
        self.assertEqual(reconstructed['chapters'][0]['key_points'][0], adversarial_strings["quotes_summary"])
        self.assertEqual(reconstructed['chapters'][0]['key_points'][1], adversarial_strings["ampersands_and_xml"])
        self.assertEqual(reconstructed['factual_claims'][0]['claim'], adversarial_strings["sql_injection_attempt"])
        self.assertEqual(reconstructed['transcript_segments'][0]['text'], adversarial_strings["foreign_scripts"] + " " + adversarial_strings["emoji_title"])

        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('summaries', 'users', 'videos')")
            found_tables = {row['name'] for row in c.fetchall()}
            self.assertEqual(found_tables, {'summaries', 'users', 'videos'}, "SQL injection must NOT drop tables!")

    # =========================================================================
    # 3. USAGE SERVICE DURATION BOUNDARIES & FORMAT TESTS
    # =========================================================================

    def test_08_duration_boundary_conditions_matrix(self):
        """Stress-test exact boundary conditions for guest (1800s) and free (5400s) tiers."""
        # --- GUEST / ANONYMOUS TIER (Limit = 1800s / 30 mins) ---
        res = check_video_duration_limit(1799, plan='anonymous')
        self.assertTrue(res['allowed'], "1799s should be allowed for anonymous")
        self.assertEqual(res['duration_seconds'], 1799)

        res = check_video_duration_limit(1800, plan='anonymous')
        self.assertTrue(res['allowed'], "Exact 1800s should be allowed for anonymous")

        res = check_video_duration_limit(1801, plan='anonymous')
        self.assertFalse(res['allowed'], "1801s should be rejected for anonymous")
        self.assertIn("exceeds the anonymous plan limit of 30 minutes", res['reason'])

        self.assertTrue(check_video_duration_limit(1799, plan='guest')['allowed'])
        self.assertTrue(check_video_duration_limit(1800, plan='guest')['allowed'])
        self.assertFalse(check_video_duration_limit(1801, plan='guest')['allowed'])

        # --- FREE TIER (Limit = 5400s / 90 mins) ---
        res = check_video_duration_limit(5399, plan='free')
        self.assertTrue(res['allowed'], "5399s should be allowed for free tier")
        self.assertEqual(res['duration_seconds'], 5399)

        res = check_video_duration_limit(5400, plan='free')
        self.assertTrue(res['allowed'], "Exact 5400s should be allowed for free tier")

        res = check_video_duration_limit(5401, plan='free')
        self.assertFalse(res['allowed'], "5401s should be rejected for free tier")
        self.assertIn("exceeds the free plan limit of 90 minutes", res['reason'])

        # --- PAID TIERS (Unlimited) ---
        for paid_plan in ['pack10', 'pack50', 'unlimited']:
            self.assertTrue(check_video_duration_limit(5401, plan=paid_plan)['allowed'])
            self.assertTrue(check_video_duration_limit(86400, plan=paid_plan)['allowed'])

    def test_09_duration_string_formats_and_edge_cases(self):
        """Stress-test duration parsing across various formats (colon, ISO 8601, float, edge cases)."""
        self.assertEqual(parse_duration_seconds("29:59"), 1799)
        self.assertEqual(parse_duration_seconds("30:00"), 1800)
        self.assertEqual(parse_duration_seconds("30:01"), 1801)
        self.assertEqual(parse_duration_seconds("01:29:59"), 5399)
        self.assertEqual(parse_duration_seconds("01:30:00"), 5400)
        self.assertEqual(parse_duration_seconds("01:30:01"), 5401)
        self.assertEqual(parse_duration_seconds("02:00:00"), 7200)

        self.assertEqual(parse_duration_seconds("PT30M"), 1800)
        self.assertEqual(parse_duration_seconds("PT1H30M"), 5400)
        self.assertEqual(parse_duration_seconds("PT29M59S"), 1799)
        self.assertEqual(parse_duration_seconds("PT30M1S"), 1801)
        self.assertEqual(parse_duration_seconds("PT1H30M1S"), 5401)

        self.assertTrue(check_video_duration_limit("29:59", plan='guest')['allowed'])
        self.assertTrue(check_video_duration_limit("30:00", plan='guest')['allowed'])
        self.assertFalse(check_video_duration_limit("30:01", plan='guest')['allowed'])

        self.assertTrue(check_video_duration_limit("01:29:59", plan='free')['allowed'])
        self.assertTrue(check_video_duration_limit("01:30:00", plan='free')['allowed'])
        self.assertFalse(check_video_duration_limit("01:30:01", plan='free')['allowed'])

        self.assertEqual(parse_duration_seconds(None), 0)
        self.assertEqual(parse_duration_seconds(0), 0)
        self.assertEqual(parse_duration_seconds(-100), 0)
        self.assertEqual(parse_duration_seconds("invalid_duration"), 0)
        self.assertEqual(parse_duration_seconds(""), 0)

        self.assertEqual(parse_duration_seconds(1800.75), 1800)
        self.assertTrue(check_video_duration_limit(1800.0, plan='guest')['allowed'])

    # =========================================================================
    # 4. RAPID RATE LIMITER UNDER CONCURRENT MULTI-THREADED FLOODS
    # =========================================================================

    def test_10_rapid_sliding_window_concurrency_stress(self):
        """Stress-test 100 concurrent threads hitting rate limiter with limit=15: exactly 15 allowed, 85 rejected."""
        test_key = f"flood_key_{uuid.uuid4().hex[:6]}"
        limit = 15
        total_requests = 100
        allowed_count = 0
        blocked_count = 0
        lock = threading.Lock()

        def make_request(idx):
            nonlocal allowed_count, blocked_count
            res = check_rate_limit(key=test_key, limit=limit, window_seconds=60)
            with lock:
                if res['allowed']:
                    allowed_count += 1
                else:
                    blocked_count += 1

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(make_request, i) for i in range(total_requests)]
            for fut in as_completed(futures):
                fut.result()

        self.assertEqual(allowed_count, limit, f"Expected exactly {limit} allowed requests, but got {allowed_count}")
        self.assertEqual(blocked_count, total_requests - limit, f"Expected {total_requests - limit} blocked requests, but got {blocked_count}")

    def test_11_sliding_window_eviction_time_travel(self):
        """Verify that older requests slide out of the window and new requests are permitted."""
        limiter = SlidingWindowRateLimiter()
        test_key = "time_travel_key"
        limit = 3
        window = 60

        base_time = 1000.0

        with patch('time.time', return_value=base_time):
            for i in range(limit):
                allowed, meta = limiter.check(test_key, limit=limit, window_seconds=window)
                self.assertTrue(allowed)
            allowed, meta = limiter.check(test_key, limit=limit, window_seconds=window)
            self.assertFalse(allowed)
            self.assertEqual(meta['reset_seconds'], 60)

        with patch('time.time', return_value=base_time + 30):
            allowed, meta = limiter.check(test_key, limit=limit, window_seconds=window)
            self.assertFalse(allowed)
            self.assertEqual(meta['reset_seconds'], 30)

        with patch('time.time', return_value=base_time + 61):
            allowed, meta = limiter.check(test_key, limit=limit, window_seconds=window)
            self.assertTrue(allowed)
            self.assertEqual(meta['count'], 1)

    def test_12_usage_logging_concurrency_and_summary_accuracy(self):
        """Verify that burst logging from multiple threads writes cleanly to usage_logs without DB deadlocks."""
        test_user = f"burst_user_{uuid.uuid4().hex[:6]}"
        num_logs = 25

        def log_worker(i):
            log_usage_entry(
                user_id=test_user,
                session_key=f"sess_{i}",
                action="test_burst_action",
                video_duration_seconds=100,
                tokens_used=50,
                plan="free",
                status="rate_limited" if i % 2 == 0 else "allowed"
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(log_worker, i) for i in range(num_logs)]
            for fut in as_completed(futures):
                fut.result()

        summary = get_user_usage_summary(user_id=test_user)
        self.assertEqual(summary['total_events'], num_logs)
        self.assertEqual(summary['total_tokens'], num_logs * 50)
        self.assertEqual(summary['total_duration_seconds'], num_logs * 100)
        expected_rate_limited = sum(1 for i in range(num_logs) if i % 2 == 0)
        self.assertEqual(summary['rate_limited_count'], expected_rate_limited)

    # =========================================================================
    # 5. MALFORMED PAYLOADS & BOUNDARY RESILIENCE
    # =========================================================================

    def test_13_malformed_and_missing_payload_resilience(self):
        """Stress-test edge cases: empty strings, None, malformed types, and non-existent IDs."""
        # Empty and None inputs
        self.assertFalse(save_analysis_modular("", {}))
        self.assertFalse(save_analysis_modular(None, {}))
        self.assertFalse(save_analysis_modular("vid_1", None))
        self.assertFalse(save_analysis_modular("vid_1", "not_a_dict"))

        self.assertIsNone(get_modular_analysis(None))
        self.assertIsNone(get_modular_analysis(""))
        self.assertIsNone(get_modular_analysis("completely_non_existent_video_id"))

        # Malformed inner types should not crash
        bad_payload = {
            "_meta": "not a dict",
            "video_overview": "not a dict",
            "chapters": "not a list",
            "factual_claims": 12345,
            "learning": None,
            "transcript_segments": "not a list"
        }
        res = save_analysis_modular("vid_malformed_1", bad_payload)
        self.assertTrue(res, "save_analysis_modular should handle malformed inner keys without crashing")

        # Non-existent job status update
        self.assertFalse(update_job_status("non_existent_job_xyz_999", status="COMPLETED"))

    def test_14_usage_service_adversarial_limits_and_keys(self):
        """Stress-test rate limits with limit <= 0 and empty keys, documenting empty-list IndexError vulnerability."""
        # Empirical Bug Finding: limit <= 0 with empty timestamp history triggers IndexError: list index out of range
        with self.assertRaises(IndexError):
            check_rate_limit(key="key_zero", limit=0)

        with self.assertRaises(IndexError):
            check_rate_limit(key="key_neg", limit=-5)

        # Fallback key when all key fields are None
        res_none_key = check_rate_limit(key=None, user_id=None, session_key=None, ip_address=None, limit=10)
        self.assertTrue(res_none_key['allowed'])


if __name__ == '__main__':
    unittest.main()
