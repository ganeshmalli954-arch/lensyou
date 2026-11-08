"""
test_m2_empirical_challenger.py
Adversarial Empirical Stress Test Suite for Milestone 2:
1. Partial failure scenarios: simulate worker crashes in export_worker and entity_worker
   and empirically assert that the pipeline delivers metadata, transcript, summary,
   and chapters under status PARTIAL.
2. Concurrent deduplication: fire 50 concurrent requests for identical video_id and
   assert exactly 1 primary worker pipeline executes while remaining 49 attach to active job.
3. ReportLab XML parser: test strings with complex ampersand sequences
   ('AT&T & R&D &amp; Q&A <tag> &not &apos;'), verifying zero XML parsing crashes across
   sanitize_text, Paragraph frags, and full document builds.
"""
import unittest
import uuid
import time
import io
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

from services.orchestrator import (
    AsyncJobOrchestrator, JobStatus,
    STATUS_QUEUED, STATUS_EXTRACTING, STATUS_PROCESSING,
    STATUS_VALIDATING, STATUS_COMPLETED, STATUS_PARTIAL, STATUS_FAILED
)
from services.workers import (
    WorkerResult,
    run_metadata_worker,
    run_transcript_worker,
    run_summary_worker,
    run_chapter_worker,
    run_claim_worker,
    run_learning_worker,
    run_entity_worker,
    run_export_worker,
)
from services.storage_service import (
    init_relational_db, get_analysis_job, get_db,
    get_cached_analysis, get_modular_analysis
)
import services.job_service as job_service
from pdf_generator import sanitize_text, generate_detailed_pdf
from reportlab.platypus import Paragraph, SimpleDocTemplate
from reportlab.lib.styles import getSampleStyleSheet


class TestAdversarialPartialFailure(unittest.TestCase):
    """
    Stress-test partial failure scenarios:
    Simulate worker crashes in export_worker, entity_worker, and both simultaneously.
    Assert that the pipeline delivers metadata, transcript, summary, and chapters
    under status PARTIAL in both in-memory state and SQLite relational persistence.
    """

    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def setUp(self):
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=4, max_task_workers=8)

    def _build_mock_pipeline_context(self):
        """Build standard mock data for essential extraction workers."""
        meta_data = {
            "title": "Quantum Computing & Quantum Algorithms",
            "author": "Dr. Eleanor Vance",
            "duration": "12:30",
            "duration_seconds": 750,
            "thumbnail_url": "https://img.youtube.com/vi/test_partial/hqdefault.jpg",
            "video_id": "test_partial"
        }
        segments_data = [
            {"text": "Welcome to quantum computing foundations.", "start": 0.0, "duration": 4.5},
            {"text": "Today we examine qubits and superposition.", "start": 4.5, "duration": 5.0},
            {"text": "Superposition allows states |0> and |1> simultaneously.", "start": 9.5, "duration": 6.0},
            {"text": "Next we demonstrate quantum entanglement and Bell states.", "start": 15.5, "duration": 8.0},
            {"text": "Finally, we explore Shor's and Grover's algorithms.", "start": 23.5, "duration": 7.0}
        ]
        raw_analysis_data = {
            "video_overview": {
                "title": "Quantum Computing & Quantum Algorithms",
                "summary": "Comprehensive overview of qubits, superposition, entanglement, and Shor's algorithm."
            },
            "metrics": {"quality_score": 92},
            "quality_scorecard": {"overall_score": 92},
            "key_takeaways": [
                {"title": "Qubit Superposition", "seconds": 9, "description": "States exist in linear combinations."},
                {"title": "Quantum Entanglement", "seconds": 15, "description": "Correlated pairs exhibit non-local states."}
            ],
            "chapters": [
                {"number": "01", "title": "Introduction & Qubits", "start_time": "00:00", "start_seconds": 0, "summary": "Foundations."},
                {"number": "02", "title": "Superposition & Entanglement", "start_time": "00:15", "start_seconds": 15, "summary": "Quantum states."}
            ],
            "creator_repurposing": {
                "youtube_chapters_raw": "00:00 Introduction & Qubits\n00:15 Superposition & Entanglement"
            }
        }
        return meta_data, segments_data, raw_analysis_data

    def test_export_worker_crash_delivers_core_modules_as_partial(self):
        """
        Simulate export_worker crashing (e.g. ReportLab OutOfMemoryError).
        Empirically assert:
        - Job status transitions to PARTIAL (and matches 'partial', 'PARTIAL').
        - Pipeline delivers metadata, transcript, summary, and chapters intact.
        - SQLite status is canonically 'PARTIAL'.
        - export_pdf is marked FAILED in _module_status and failed_modules.
        """
        vid = f"part_exp_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_pipeline_context()

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
             patch("services.orchestrator.run_export_worker") as mock_exp:

            mock_meta.return_value = WorkerResult(module="metadata", success=True, data=meta_data)
            mock_trans.return_value = WorkerResult(
                module="transcript",
                success=True,
                data={"segments": segments, "formatted_duration": "12:30", "duration_seconds": 750, "ui_sample": segments[:2]}
            )
            mock_ai.return_value = dict(raw_analysis)
            # Simulate export worker crash returning failure
            mock_exp.return_value = WorkerResult(
                module="export_pdf",
                success=False,
                error="ReportLab worker memory limit exceeded (simulated OOM)"
            )

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        # 1. Assert job state in orchestrator memory
        job = self.orchestrator.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["status"], "PARTIAL")
        self.assertTrue(job["is_partial"])
        self.assertEqual(job["stage"], 9)
        self.assertEqual(job["progress"], 100)

        # 2. Assert core modules are delivered
        result = job["result"]
        self.assertIsNotNone(result)
        self.assertTrue(result["is_partial"])
        self.assertTrue(result["_partial"])

        # Core deliverable: metadata
        self.assertEqual(result["_meta"]["title"], "Quantum Computing & Quantum Algorithms")
        self.assertEqual(result["_meta"]["duration"], "12:30")
        self.assertEqual(job["modules"]["metadata"]["title"], "Quantum Computing & Quantum Algorithms")

        # Core deliverable: transcript
        self.assertGreaterEqual(len(result["transcript_segments"]), 5)
        self.assertEqual(job["modules"]["transcript"][0]["text"], "Welcome to quantum computing foundations.")

        # Core deliverable: summary
        self.assertIn("Comprehensive overview", result["video_overview"]["summary"])
        self.assertIn("Comprehensive overview", job["modules"]["summary"]["summary"])

        # Core deliverable: chapters
        self.assertGreaterEqual(len(job["modules"]["chapters"]), 2)
        self.assertEqual(job["modules"]["chapters"][0]["title"], "Introduction & Qubits")

        # 3. Assert module status tracking
        self.assertEqual(result["_module_status"]["export_pdf"], "FAILED")
        self.assertEqual(result["_module_status"]["metadata"], "COMPLETED")
        self.assertEqual(result["_module_status"]["transcript"], "COMPLETED")
        self.assertEqual(result["_module_status"]["summary"], "COMPLETED")
        self.assertEqual(result["_module_status"]["chapters"], "COMPLETED")
        self.assertIn("export_pdf", result["failed_modules"])

        # 4. Assert SQLite persistence state
        db_job = get_analysis_job(job_id)
        self.assertIsNotNone(db_job)
        self.assertEqual(db_job["status"], "PARTIAL")
        self.assertEqual(db_job["stage"], 9)
        self.assertIsNotNone(db_job["completed_at"])

        # 5. Assert cached analysis is retrievable with core deliverables
        cached = get_cached_analysis(vid)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["_meta"]["title"], "Quantum Computing & Quantum Algorithms")
        self.assertIn("Comprehensive overview", cached["video_overview"]["summary"])

    def test_entity_worker_crash_delivers_core_modules_as_partial(self):
        """
        Simulate entity_worker crashing (e.g. Graph layout recursion / token limit).
        Empirically assert:
        - Job status transitions to PARTIAL.
        - Core deliverables (metadata, transcript, summary, chapters) delivered intact.
        - SQLite status is PARTIAL.
        - knowledge_graph marked FAILED in _module_status.
        """
        vid = f"part_ent_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_pipeline_context()

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
             patch("services.orchestrator.run_entity_worker") as mock_ent:

            mock_meta.return_value = WorkerResult(module="metadata", success=True, data=meta_data)
            mock_trans.return_value = WorkerResult(
                module="transcript",
                success=True,
                data={"segments": segments, "formatted_duration": "12:30", "duration_seconds": 750, "ui_sample": segments[:2]}
            )
            mock_ai.return_value = dict(raw_analysis)
            # Simulate entity worker crash returning failure
            mock_ent.return_value = WorkerResult(
                module="entities",
                success=False,
                error="Knowledge graph layout token limit exceeded (simulated error)"
            )

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "PARTIAL")
        self.assertTrue(job["is_partial"])

        # Core deliverables delivered
        result = job["result"]
        self.assertEqual(result["_meta"]["title"], "Quantum Computing & Quantum Algorithms")
        self.assertGreaterEqual(len(result["transcript_segments"]), 5)
        self.assertIn("Comprehensive overview", result["video_overview"]["summary"])
        self.assertGreaterEqual(len(job["modules"]["chapters"]), 2)

        # Failure status recorded
        self.assertEqual(result["_module_status"]["knowledge_graph"], "FAILED")
        self.assertEqual(result["_module_status"]["summary"], "COMPLETED")
        self.assertEqual(result["_module_status"]["chapters"], "COMPLETED")

        # SQLite status
        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "PARTIAL")

    def test_simultaneous_export_and_entity_worker_crashes(self):
        """
        Simulate BOTH export_worker AND entity_worker crashing simultaneously.
        Empirically assert:
        - Job completes under status PARTIAL.
        - Core deliverables (metadata, transcript, summary, chapters) delivered 100% intact.
        - Both failures recorded in _module_status and failed_modules.
        - SQLite status is PARTIAL.
        """
        vid = f"part_both_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_pipeline_context()

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
             patch("services.orchestrator.run_entity_worker") as mock_ent, \
             patch("services.orchestrator.run_export_worker") as mock_exp:

            mock_meta.return_value = WorkerResult(module="metadata", success=True, data=meta_data)
            mock_trans.return_value = WorkerResult(
                module="transcript",
                success=True,
                data={"segments": segments, "formatted_duration": "12:30", "duration_seconds": 750, "ui_sample": segments[:2]}
            )
            mock_ai.return_value = dict(raw_analysis)
            mock_ent.return_value = WorkerResult(
                module="entities",
                success=False,
                error="Entity graph worker crashed with internal error"
            )
            mock_exp.return_value = WorkerResult(
                module="export_pdf",
                success=False,
                error="PDF export generator failed with I/O error"
            )

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "PARTIAL")
        self.assertTrue(job["is_partial"])

        # Core deliverables delivered
        result = job["result"]
        self.assertEqual(result["_meta"]["title"], "Quantum Computing & Quantum Algorithms")
        self.assertGreaterEqual(len(result["transcript_segments"]), 5)
        self.assertIn("Comprehensive overview", result["video_overview"]["summary"])
        self.assertGreaterEqual(len(job["modules"]["chapters"]), 2)

        # Both failed modules recorded
        self.assertEqual(result["_module_status"]["export_pdf"], "FAILED")
        self.assertEqual(result["_module_status"]["knowledge_graph"], "FAILED")
        self.assertIn("export_pdf", result["failed_modules"])
        self.assertIn("knowledge_graph", result["failed_modules"])

        # Core modules remain completed
        self.assertEqual(result["_module_status"]["metadata"], "COMPLETED")
        self.assertEqual(result["_module_status"]["transcript"], "COMPLETED")
        self.assertEqual(result["_module_status"]["summary"], "COMPLETED")
        self.assertEqual(result["_module_status"]["chapters"], "COMPLETED")

        # SQLite status is canonically PARTIAL
        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "PARTIAL")


class TestAdversarialConcurrentDeduplication(unittest.TestCase):
    """
    Stress-test concurrent deduplication:
    Fire 50 concurrent requests for an identical video_id using barriers and thread pools.
    Assert that exactly 1 primary worker pipeline executes while all 49 attach to the active job.
    """

    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def setUp(self):
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=8, max_task_workers=16)

    def test_50_concurrent_requests_simultaneous_barrier(self):
        """
        50 threads fire submit_or_attach simultaneously at the exact microsecond via threading.Barrier(50).
        Assert:
        - Exactly 1 thread receives is_new == True.
        - Exactly 49 threads receive is_new == False.
        - All 50 threads receive the identical job_id.
        - SQLite contains exactly 1 analysis_jobs record for this video_id.
        """
        vid = f"dedup_50_{uuid.uuid4().hex[:8]}"
        num_threads = 50
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads

        def worker_task(index):
            # Synchronize all 50 threads to fire concurrently
            barrier.wait()
            job_id, is_new = self.orchestrator.submit_or_attach(vid, user_id=f"u_{index}")
            results[index] = (job_id, is_new)

        threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # Inspect all results
        job_ids = [r[0] for r in results]
        is_new_flags = [r[1] for r in results]

        new_count = is_new_flags.count(True)
        attached_count = is_new_flags.count(False)

        self.assertEqual(new_count, 1, f"Expected exactly 1 new job, got {new_count}")
        self.assertEqual(attached_count, 49, f"Expected exactly 49 attached requests, got {attached_count}")

        # All 50 threads must receive identical job_id
        primary_job_id = job_ids[0]
        self.assertTrue(all(jid == primary_job_id for jid in job_ids), "All threads must share identical job_id")

        # Verify SQLite table analysis_jobs has exactly 1 record for this video_id
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) as cnt FROM analysis_jobs WHERE video_id = ?", (vid,))
            row = c.fetchone()
            self.assertEqual(row["cnt"], 1, "SQLite must contain exactly 1 job record for this video_id")

    def test_50_concurrent_requests_during_active_pipeline_execution(self):
        """
        Thread 0 creates the job and executes an active asynchronous pipeline with real stages.
        Remaining 49 concurrent threads call submit_or_attach while the pipeline is in active execution.
        Assert:
        - Exactly 1 pipeline execution runs to completion.
        - All 49 requests attach to the active job (is_new == False).
        - After pipeline completion, all callers see status COMPLETED.
        """
        vid = f"dedup_active_{uuid.uuid4().hex[:8]}"
        num_threads = 50
        results = [None] * num_threads

        pipeline_exec_counter = 0
        counter_lock = threading.Lock()

        def tracked_pipeline(job_id, video_id, **kwargs):
            nonlocal pipeline_exec_counter
            with counter_lock:
                pipeline_exec_counter += 1

            # Simulate stage progressions
            self.orchestrator.update_stage(job_id, 1, "Fetching metadata", progress=20)
            time.sleep(0.05)
            self.orchestrator.update_stage(job_id, 5, "Generating core intelligence", progress=60)
            time.sleep(0.05)
            self.orchestrator.complete_job(job_id, {"_meta": {"title": "Active Dedup Video"}})

        # Start primary thread
        primary_job_id, is_primary = self.orchestrator.submit_or_attach(vid, user_id="u_prime")
        self.assertTrue(is_primary)
        results[0] = (primary_job_id, is_primary)

        # Launch pipeline execution in background
        pipeline_thread = threading.Thread(target=tracked_pipeline, args=(primary_job_id, vid))
        pipeline_thread.start()

        # Fire 49 concurrent requests while pipeline is in active flight
        def requester_task(idx):
            time.sleep(0.01)  # Stagger slightly while pipeline is processing
            jid, is_new = self.orchestrator.submit_or_attach(vid, user_id=f"u_{idx}")
            results[idx] = (jid, is_new)

        threads = [threading.Thread(target=requester_task, args=(i,)) for i in range(1, num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        pipeline_thread.join(timeout=10.0)

        # Verify results
        new_count = [r[1] for r in results].count(True)
        attached_count = [r[1] for r in results].count(False)

        self.assertEqual(new_count, 1)
        self.assertEqual(attached_count, 49)
        self.assertTrue(all(r[0] == primary_job_id for r in results))

        # Pipeline must have executed exactly 1 time
        self.assertEqual(pipeline_exec_counter, 1)

        # Final job state is completed
        final_job = self.orchestrator.get_job(primary_job_id)
        self.assertEqual(final_job["status"], "completed")
        self.assertEqual(final_job["progress"], 100)

    def test_interleaved_concurrent_deduplication_5_videos_50_threads(self):
        """
        50 threads partitioned across 5 distinct video IDs (10 threads per video ID).
        All 50 threads fire simultaneously using Barrier(50).
        Assert:
        - Exactly 5 threads receive is_new == True (1 per video ID).
        - Exactly 45 threads receive is_new == False (9 per video ID).
        - For each video ID, all 10 threads receive the identical job_id.
        """
        num_videos = 5
        threads_per_vid = 10
        total_threads = num_videos * threads_per_vid
        video_ids = [f"interleaved_{i}_{uuid.uuid4().hex[:6]}" for i in range(num_videos)]

        barrier = threading.Barrier(total_threads)
        results = {}
        res_lock = threading.Lock()

        def worker(vid, idx):
            barrier.wait()
            jid, is_new = self.orchestrator.submit_or_attach(vid, user_id=f"u_{vid}_{idx}")
            with res_lock:
                if vid not in results:
                    results[vid] = []
                results[vid].append((jid, is_new))

        threads = []
        for vid in video_ids:
            for idx in range(threads_per_vid):
                t = threading.Thread(target=worker, args=(vid, idx))
                threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        total_new = 0
        total_attached = 0

        for vid in video_ids:
            vid_results = results[vid]
            self.assertEqual(len(vid_results), threads_per_vid)
            vid_new = [r[1] for r in vid_results].count(True)
            vid_attached = [r[1] for r in vid_results].count(False)
            self.assertEqual(vid_new, 1, f"Video {vid} should have exactly 1 new job")
            self.assertEqual(vid_attached, threads_per_vid - 1)

            # All 10 threads for this video must share identical job_id
            first_jid = vid_results[0][0]
            self.assertTrue(all(r[0] == first_jid for r in vid_results))

            total_new += vid_new
            total_attached += vid_attached

        self.assertEqual(total_new, 5)
        self.assertEqual(total_attached, 45)

    def test_deduplication_across_all_active_stages(self):
        """
        Empirically verify that submit_or_attach attaches in ALL active stages:
        QUEUED (stage 0), EXTRACTING (stage 1-3), PROCESSING (stage 4-7), VALIDATING (stage 8).
        """
        for stage_num, stage_name in [(0, "Queued"), (1, "Metadata"), (4, "Processing"), (8, "Validating")]:
            vid = f"stage_test_{stage_num}_{uuid.uuid4().hex[:6]}"
            job_id = self.orchestrator.create_job(video_id=vid)
            if stage_num > 0:
                self.orchestrator.update_stage(job_id, stage_num, stage_name)

            # Concurrent attempt to submit identical video
            att_id, is_new = self.orchestrator.submit_or_attach(vid)
            self.assertFalse(is_new, f"Should attach to active job in stage {stage_name}")
            self.assertEqual(att_id, job_id)

    def test_failed_job_allows_new_submission(self):
        """
        When a job fails (status FAILED / error), subsequent submissions for the same video_id
        must be allowed to spawn a new job (is_new == True) so user can retry.
        """
        vid = f"fail_retry_{uuid.uuid4().hex[:6]}"
        job_id_1 = self.orchestrator.create_job(video_id=vid)
        self.orchestrator.fail_job(job_id_1, "Transient network drop")

        # After failure, submission creates new job
        job_id_2, is_new = self.orchestrator.submit_or_attach(vid)
        self.assertTrue(is_new)
        self.assertNotEqual(job_id_1, job_id_2)

    def test_burst_stress_3_rounds_of_50_threads(self):
        """
        Execute 3 sequential bursts of 50 concurrent threads against 3 different videos.
        Verify 100% adherence to single-primary invariant across every burst.
        """
        for round_idx in range(3):
            vid = f"burst_r{round_idx}_{uuid.uuid4().hex[:6]}"
            num_threads = 50
            barrier = threading.Barrier(num_threads)
            results = [None] * num_threads

            def worker_burst(idx):
                barrier.wait()
                jid, is_new = self.orchestrator.submit_or_attach(vid, user_id=f"u_b{idx}")
                results[idx] = (jid, is_new)

            threads = [threading.Thread(target=worker_burst, args=(i,)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10.0)

            new_count = [r[1] for r in results].count(True)
            attached_count = [r[1] for r in results].count(False)
            self.assertEqual(new_count, 1, f"Round {round_idx} failed: got {new_count} new jobs")
            self.assertEqual(attached_count, 49)



class TestAdversarialReportLabXmlParser(unittest.TestCase):
    """
    Stress-test ReportLab XML parser:
    Test strings with complex ampersand sequences ('AT&T & R&D &amp; Q&A <tag> &not &apos;'),
    verifying zero XML parsing crashes across sanitize_text, Paragraph frags, and full doc.build.
    """

    def setUp(self):
        self.style = getSampleStyleSheet()['Normal']

    def test_target_string_ampersand_sequence_reportlab_compliance(self):
        """
        Explicitly stress-test the assignment target string:
        'AT&T & R&D &amp; Q&A <tag> &not &apos;'
        Assert:
        - sanitize_text produces strictly valid XML entities.
        - Paragraph parses without XML syntax or ParseError crashes.
        - Full SimpleDocTemplate.build completes with zero exceptions.
        - Rendered text retains all terms without trailing entity semicolons or crashes.
        """
        raw = "AT&T & R&D &amp; Q&A <tag> &not &apos;"
        sanitized = sanitize_text(raw)

        # 1. Verification of sanitized string
        self.assertIn("AT&amp;T", sanitized)
        self.assertIn("R&amp;D", sanitized)
        self.assertIn("Q&amp;A", sanitized)
        self.assertIn("&lt;tag&gt;", sanitized)
        self.assertNotIn("<tag>", sanitized)
        self.assertNotIn("AT&T", sanitized)  # No raw ampersand

        # 2. Paragraph parsing
        p = Paragraph(sanitized, self.style)
        rendered_text = "".join(f.text for f in p.frags)
        self.assertIn("AT&T", rendered_text)
        self.assertIn("R&D", rendered_text)
        self.assertIn("Q&A", rendered_text)
        self.assertIn("<tag>", rendered_text)
        self.assertNotIn("AT&T;", rendered_text)  # Zero corrupt entity semicolons!

        # 3. Full PDF document build
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf)
        doc.build([p])
        pdf_bytes = buf.getvalue()
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_exhaustive_battery_of_50_adversarial_ampersand_and_xml_strings(self):
        """
        Battery of 50+ adversarial, edge-case, and malformed entity strings.
        Assert zero XML parsing crashes across all strings when built into PDF.
        """
        test_strings = [
            "AT&T & R&D &amp; Q&A <tag> &not &apos;",
            "AT&T; &amp; &apos; &quot; &gt; &lt;",
            "Research & Development in AT&T Labs & Bell Labs",
            "Fish & Chips & Rock & Roll & 100% pure & simple",
            "&&& &&amp;&amp; &amp;&amp;amp; &amp;amp; & & &",
            "&not &not; ¬ &notexistent &nothing &note",
            "&copy; &reg; &trade; &deg; &plusmn; &para; &sect; &euro; &pound; &yen;",
            "<script>alert('xss & foo')</script>",
            "<tag attr=\"a & b &amp; c\" nested=\"<inner>\">",
            "<<broken>> <<<tags>>> >>>> < < < > > >",
            "Unclosed <b tag with & and &amp;",
            "Mixed <b>Bold & Strong</b> and <i>Italic & Fast</i>",
            "Pre-escaped &lt;div class=\"header\"&gt; &amp; Content &lt;/div&gt;",
            "Special entity &nbsp; &cent; &pound; &yen; &euro;",
            "Malformed numeric entities: &#; &#x; &#999999999; &#xZZ; &#0;",
            "Malformed entity syntax: &123; &abc; &; &---; &$$$;",
            "Mixed tags and entities: <para>AT&T</para> <font color=\"red\">R&D</font>",
            "💡 AI & Tech 🚀 100% & ⚡ Fast",
            "Multiple ampersands: A && B &&& C &&&& D",
            "Trailing ampersands: Test &",
            "Leading ampersands: & Test",
            "Consecutive isolated: & & & & &",
            "Entity lookalikes: &ampersand &company &target &noted &quarter",
            "Quotes & apostrophes: 'single' & \"double\" & `backtick`",
            "URL with ampersands: https://example.com/watch?v=123&t=45s&list=abc&index=1",
            "XML comments: <!-- Comment & note --> and <![CDATA[ Raw & data ]]>",
            "Self-closing tags: <br/> <hr/> <img src=\"x\" alt=\"&\"/>",
            "Escaped ampersand in attribute: <span title=\"A &amp; B\">text</span>",
            "Entity in entity: &amp;amp;amp;not; &amp;quot;",
            "Hex entities: &#x26; &#x3C; &#x3E; &#x27; &#x22;",
            "Decimal entities: &#38; &#60; &#62; &#39; &#34;",
            "High unicode: \u2014 \u2013 \u201c \u201d \u2022 \u2714 \u2716",
            "Control chars: \t Tab & \n Newline & \r Return",
            "Very dense ampersands: " + "AT&T & " * 50,
            "Very dense tags: " + "<tag>&amp;</tag> " * 30,
            "Code snippet: if (x > 0 && y < 10 && z != &ref) { return a & b; }",
            "Math expressions: a & b => c | d && e ^ f < g > h",
            "Financial statements: P&L statement for S&P 500 & AT&T",
            "Brands: M&Ms, H&M, Ben & Jerry's, D&D, B&H Photo, A&W",
            "Slang & shorthands: w/ & w/o & b/c & R&R & Q&A & FAQ",
            "Entity with uppercase: &AMP; &LT; &GT; &QUOT;",
            "Entity with whitespace: & amp; & not ; &lt ;",
            "HTML void tags: <meta charset=\"utf-8\"> & <input type=\"text\">",
            "Nested broken brackets: <a <b <c & d > e> f>",
            "Non-ASCII ampersands: ﹠ ＆ &",
            "Mixed languages: English & 日本語 & 中文 & Español & Français",
            "Long paragraph: " + "The quick brown fox jumps over the lazy dog & friends. " * 20,
            "Double escaped: &amp;lt;script&amp;gt;",
            "Zero width: \u200b&\u200b",
            "Raw XML paragraph tags: <para>Inner text</para>"
        ]

        # Build all strings into a single multi-page PDF document
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf)
        story = []

        for s in test_strings:
            sanitized = sanitize_text(s)
            # Ensure no unhandled exception in Paragraph creation
            try:
                p = Paragraph(sanitized, self.style)
                story.append(p)
            except Exception as e:
                self.fail(f"Paragraph creation failed for '{s}': {e}")

        # Ensure no unhandled exception during doc.build
        try:
            doc.build(story)
        except Exception as e:
            self.fail(f"SimpleDocTemplate build failed on adversarial battery: {e}")

        pdf_bytes = buf.getvalue()
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_generate_detailed_pdf_with_adversarial_strings_in_all_fields(self):
        """
        Build an exhaustive analysis_data dictionary where EVERY single field
        contains complex ampersand sequences and XML tags.
        Assert that generate_detailed_pdf builds successfully without XML crashes.
        """
        adv_str = "AT&T & R&D &amp; Q&A <tag> &not &apos; <script>alert(1)</script>"
        adversarial_payload = {
            "_meta": {
                "title": f"Adversarial Lecture: {adv_str}",
                "author": f"Dr. {adv_str}",
                "duration": "10:00",
                "tier": f"Premium {adv_str}",
                "model_used": f"Gemini {adv_str}"
            },
            "video_overview": {
                "title": f"Overview {adv_str}",
                "summary": f"Executive summary describing {adv_str} in detail with multiple & and <tags>."
            },
            "key_takeaways": [
                {"title": f"Takeaway 1: {adv_str}", "description": f"Detailed description {adv_str}", "seconds": 30},
                {"title": f"Takeaway 2: {adv_str}", "description": f"Another description {adv_str}", "seconds": 60}
            ],
            "chapters": [
                {"number": "01", "title": f"Chapter 1: {adv_str}", "start_time": "00:00", "summary": f"Chapter summary {adv_str}"},
                {"number": "02", "title": f"Chapter 2: {adv_str}", "start_time": "05:00", "summary": f"Next summary {adv_str}"}
            ],
            "claims": [
                {"claim": f"Factual claim regarding {adv_str}", "type": "Statistic", "confidence": "High", "seconds": 15}
            ],
            "contradictions": [
                f"Contradiction between {adv_str} and earlier claims"
            ],
            "learning": {
                "key_definitions": [
                    {"term": f"Definition of {adv_str}", "definition": f"Detailed definition text {adv_str}"}
                ],
                "quiz": [
                    {
                        "question": f"Which of the following describes {adv_str}?",
                        "options": [f"Option A: {adv_str}", f"Option B: {adv_str}", "Option C", "Option D"],
                        "correct_index": 0,
                        "bloom_level": "Understand"
                    }
                ]
            },
            "entities": {
                "people": [{"name": f"Entity Person {adv_str}"}],
                "companies": [{"name": f"Company {adv_str}"}],
                "tools_software": [{"name": f"Tool {adv_str}"}],
                "concepts": [{"name": f"Concept {adv_str}"}]
            }
        }

        # Generate PDF
        pdf_out = generate_detailed_pdf(adversarial_payload)
        self.assertIsNotNone(pdf_out)
        if isinstance(pdf_out, io.BytesIO):
            pdf_bytes = pdf_out.getvalue()
        else:
            pdf_bytes = bytes(pdf_out)

        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))

    def test_export_worker_adversarial_integration(self):
        """
        run_export_worker executes cleanly with adversarial payload,
        persisting export record in SQLite and returning WorkerResult(success=True).
        """
        adv_str = "AT&T & R&D &amp; Q&A <tag> &not &apos;"
        sample_analysis = {
            "_meta": {"title": f"Video {adv_str}", "author": "Tester", "duration": "05:00"},
            "video_overview": {"summary": f"Overview {adv_str}"},
            "key_takeaways": [{"title": f"Point {adv_str}", "description": f"Desc {adv_str}"}],
            "chapters": [{"number": "01", "title": f"Intro {adv_str}", "start_time": "00:00", "summary": f"Summary {adv_str}"}]
        }
        res = run_export_worker(sample_analysis, "test_adv_export_vid")
        self.assertTrue(res.success)
        self.assertTrue(res.data["pdf_generated"])
        self.assertGreater(res.data["pdf_size"], 2000)


if __name__ == "__main__":
    unittest.main()
