import unittest
import uuid
import time
import os
from unittest.mock import patch, MagicMock

from services.orchestrator import (
    AsyncJobOrchestrator, JobStatus, format_user_error,
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
    get_analysis_job, get_db, init_relational_db,
    save_analysis, get_cached_analysis
)
import services.job_service as job_service
from pdf_generator import sanitize_text


class TestMilestone2OrchestratorPipeline(unittest.TestCase):
    """
    Comprehensive Milestone 2 test suite covering:
    - F04: Asynchronous Job Orchestrator & Persistent SQLite State Machine
    - F05: Modular Worker Tasks (8 workers)
    - F06: Partial Failure Resiliency
    - F07: Exponential Backoff Retries & Timeouts
    - F08: Duplicate Job Prevention (Thread-Safe Deduplication Lock)
    - F09: Zero-Cost Infrastructure & ReportLab XML Sanitization Fix
    - Backward Compatibility of services.job_service
    """

    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def setUp(self):
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=2, max_task_workers=4)

    # -------------------------------------------------------------------------
    # 1. JobStatus Case-Insensitive Equality & Status Bridges
    # -------------------------------------------------------------------------

    def test_job_status_case_insensitivity(self):
        """JobStatus bridges uppercase SQLite states and legacy lowercase string assertions."""
        status = JobStatus("completed")
        self.assertEqual(status, "completed")
        self.assertEqual(status, "COMPLETED")
        self.assertEqual(status, "Completed")
        self.assertEqual(status, "success")
        self.assertIn(status, ["completed", "partial"])
        self.assertIn(status, ["COMPLETED", "PARTIAL"])

        status_partial = JobStatus("partial")
        self.assertEqual(status_partial, "partial")
        self.assertEqual(status_partial, "PARTIAL")

        status_err = JobStatus("error")
        self.assertEqual(status_err, "error")
        self.assertEqual(status_err, "ERROR")
        self.assertEqual(status_err, "FAILED")
        self.assertEqual(status_err, "failed")

        # Dict key and set behavior
        d = {JobStatus("completed"): 42}
        self.assertEqual(d.get(JobStatus("COMPLETED")), 42)
        self.assertEqual(d.get(JobStatus("completed")), 42)

    # -------------------------------------------------------------------------
    # 2. AsyncJobOrchestrator Lifecycle & Persistent SQLite State Machine
    # -------------------------------------------------------------------------

    def test_job_creation_and_sqlite_persistence(self):
        """create_job creates in-memory job and persists QUEUED record to SQLite."""
        vid = f"orch_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid, user_id="u_test", session_key="s_test")

        # In-memory check
        job = self.orchestrator.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["stage"], 0)
        self.assertEqual(job["video_id"], vid)

        # SQLite check
        db_job = get_analysis_job(job_id)
        self.assertIsNotNone(db_job)
        self.assertEqual(db_job["status"], "QUEUED")
        self.assertEqual(db_job["stage"], 0)
        self.assertEqual(db_job["video_id"], vid)

    def test_job_stage_progression_and_sqlite_sync(self):
        """update_stage updates stage in memory and synchronizes with SQLite."""
        vid = f"orch_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        # Stage 1: EXTRACTING
        self.orchestrator.update_stage(job_id, 1, "Fetching metadata", progress=15)
        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["stage"], 1)
        self.assertEqual(job["stage_name"], "Fetching metadata")
        self.assertEqual(job["progress"], 15)

        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "EXTRACTING")
        self.assertEqual(db_job["stage"], 1)

        # Stage 5: PROCESSING
        self.orchestrator.update_stage(job_id, 5, progress=60)
        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["stage"], 5)
        self.assertEqual(job["stage_name"], "Generating core intelligence")

        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "PROCESSING")
        self.assertEqual(db_job["stage"], 5)

        # Stage 8: VALIDATING
        self.orchestrator.update_stage(job_id, 8)
        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "VALIDATING")

    def test_complete_job_terminal_transition(self):
        """complete_job transitions job to COMPLETED with 100% progress and timestamps."""
        vid = f"orch_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        result_payload = {"_meta": {"title": "Test Lecture"}, "video_overview": {"summary": "Done"}}

        self.orchestrator.complete_job(job_id, result_payload, is_partial=False)
        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["stage"], 9)
        self.assertEqual(job["progress"], 100)
        self.assertFalse(job["is_partial"])

        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "COMPLETED")
        self.assertEqual(db_job["stage"], 9)
        self.assertIsNotNone(db_job["completed_at"])

    def test_fail_job_terminal_transition(self):
        """fail_job sets status to error and formats user-friendly error message."""
        vid = f"orch_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        self.orchestrator.fail_job(job_id, "TranscriptsDisabled: Subtitles disabled")
        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "error")
        self.assertIn("subtitles may be disabled", job["error"].lower())

        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "FAILED")
        self.assertIn("subtitles may be disabled", db_job["error"].lower())

    # -------------------------------------------------------------------------
    # 3. Modular Workers Execution (8 Workers)
    # -------------------------------------------------------------------------

    def test_worker_1_metadata_worker(self):
        """metadata_worker validates URL and parses video details."""
        # Valid URL
        res = run_metadata_worker("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertTrue(res.success)
        self.assertEqual(res.data["video_id"], "dQw4w9WgXcQ")
        self.assertIn("title", res.data)
        self.assertTrue(res.is_essential)

        # Invalid URL
        bad_res = run_metadata_worker("not_a_valid_youtube_link")
        self.assertFalse(bad_res.success)
        self.assertIn("Invalid YouTube URL", bad_res.error)

    def test_worker_2_transcript_worker(self):
        """transcript_worker extracts and formats transcript segments."""
        with patch("services.workers.transcript_worker.get_transcript_data") as mock_get_t:
            mock_get_t.return_value = {
                "segments": [{"text": "Hello world", "start": 0.0, "duration": 5.0}],
                "duration_seconds": 300,
                "formatted_duration": "05:00",
                "is_synthesized": False
            }
            res = run_transcript_worker("test_vid_123", {"duration_seconds": 300})
            # Sparse transcript (1 segment for 300s lecture) expands into structured phases
            self.assertGreaterEqual(len(res.data["segments"]), 4)
            self.assertEqual(res.data["formatted_duration"], "05:00")
            self.assertTrue(res.is_essential)

    def test_worker_3_summary_worker(self):
        """summary_worker parses video overview, metrics, quality scorecard, and takeaways."""
        sample_raw = {
            "video_overview": {"title": "Overview Title", "summary": "Executive summary"},
            "metrics": {"quality_score": 90},
            "quality_scorecard": {"overall_score": 90},
            "key_takeaways": [{"title": "Takeaway 1", "seconds": 30}],
            "engagement_curve": [{"seconds": 0, "score": 95}]
        }
        res = run_summary_worker([], {"duration_seconds": 60}, raw_analysis=sample_raw)
        self.assertTrue(res.success)
        self.assertEqual(res.data["video_overview"]["title"], "Overview Title")
        self.assertEqual(res.data["metrics"]["quality_score"], 90)

    def test_worker_4_chapter_worker_with_fallback(self):
        """chapter_worker returns chapters or synthesizes deterministic fallback chapters."""
        # Empty raw analysis triggers deterministic fallback
        res = run_chapter_worker([], {"duration_seconds": 600, "title": "Fallback Lecture"}, raw_analysis={})
        self.assertTrue(res.success)
        self.assertGreaterEqual(len(res.data["chapters"]), 2)
        self.assertIn("youtube_chapters_raw", res.data["creator_repurposing"])

    def test_worker_5_claim_worker(self):
        """claim_worker extracts claims and is non-essential."""
        sample_raw = {
            "claims": [{"claim": "AI is growing", "type": "Statistic", "confidence": "High"}],
            "contradictions": []
        }
        res = run_claim_worker([], {}, raw_analysis=sample_raw)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data["claims"]), 1)
        self.assertFalse(res.is_essential)

    def test_worker_6_learning_worker_sanitization(self):
        """learning_worker sanitizes definition term headers and validates Bloom quiz items."""
        sample_raw = {
            "learning": {
                "key_definitions": [{"term": "## *Neural Network*", "definition": "Interconnected layers"}],
                "quiz": [
                    {
                        "question": "What is backprop?",
                        "options": ["A", "B", "C", "D"],
                        "correct_index": 1,
                        "bloom_level": "Understand"
                    }
                ]
            }
        }
        res = run_learning_worker([], {}, raw_analysis=sample_raw)
        self.assertTrue(res.success)
        cleaned_term = res.data["learning"]["key_definitions"][0]["term"]
        self.assertEqual(cleaned_term, "Neural Network")  # Stripped ## and *
        self.assertEqual(len(res.data["quizzes"]), 1)
        self.assertFalse(res.is_essential)

    def test_worker_7_entity_worker(self):
        """entity_worker extracts named entities and knowledge graph nodes/links."""
        sample_raw = {
            "entities": {"people": [{"name": "Alan Turing"}], "companies": [], "tools_software": [], "concepts": []},
            "knowledge_graph": {"nodes": [{"id": "1", "label": "AI"}], "links": []}
        }
        res = run_entity_worker([], {}, raw_analysis=sample_raw)
        self.assertTrue(res.success)
        self.assertEqual(len(res.data["entities"]["people"]), 1)
        self.assertFalse(res.is_essential)

    def test_worker_8_export_worker(self):
        """export_worker generates ReportLab PDF and records export in SQLite."""
        sample_analysis = {
            "_meta": {"title": "Test Export & PDF", "author": "Tester", "duration": "05:00"},
            "video_overview": {"summary": "Short overview for PDF testing & verification."},
            "key_takeaways": [{"title": "Takeaway A", "description": "Desc"}],
            "chapters": [{"number": "01", "title": "Intro", "start_time": "00:00", "summary": "Intro"}]
        }
        res = run_export_worker(sample_analysis, "test_export_vid")
        self.assertTrue(res.success)
        self.assertTrue(res.data["pdf_generated"])
        self.assertGreater(res.data["pdf_size"], 1000)
        self.assertFalse(res.is_essential)

    # -------------------------------------------------------------------------
    # 4. Partial Failure Resiliency
    # -------------------------------------------------------------------------

    def test_partial_failure_resiliency_on_export_crash(self):
        """When optional export fails, job completes with status PARTIAL while delivering core deliverables."""
        vid = f"partial_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        with patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
             patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans:

            mock_meta.return_value = WorkerResult(
                module="metadata",
                success=True,
                data={"title": "Test Title", "author": "Author", "duration": "10:00", "duration_seconds": 600, "thumbnail_url": ""}
            )
            mock_trans.return_value = WorkerResult(
                module="transcript",
                success=True,
                data={"segments": [{"text": "Hello", "start": 0.0, "duration": 5.0}], "formatted_duration": "10:00", "duration_seconds": 600, "ui_sample": []}
            )
            mock_ai.return_value = {
                "video_overview": {"title": "Test Title", "summary": "Core summary"},
                "key_takeaways": [{"title": "Takeaway 1"}],
                "chapters": [{"title": "Chapter 1", "start_time": "00:00"}],
                "creator_repurposing": {"youtube_chapters_raw": "00:00 Chapter 1"}
            }

            # Run with simulated export failure
            self.orchestrator.run_pipeline(
                job_id,
                video_id=vid,
                simulate_failures={"export_pdf": True}
            )

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "partial")
        self.assertEqual(job["status"], "PARTIAL")  # Case-insensitive bridge
        self.assertTrue(job["is_partial"])

        res = job["result"]
        self.assertTrue(res["is_partial"])
        self.assertTrue(res["_partial"])
        self.assertEqual(res["_module_status"]["export_pdf"], "FAILED")
        self.assertEqual(res["_module_status"]["summary"], "COMPLETED")
        self.assertEqual(res["_module_status"]["transcript"], "COMPLETED")

        # SQLite status is canonically 'PARTIAL'
        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "PARTIAL")

    # -------------------------------------------------------------------------
    # 5. Exponential Backoff Retries & Error Discrimination
    # -------------------------------------------------------------------------

    def test_exponential_backoff_retry_engine(self):
        """Transient errors retry with strictly increasing backoff delays."""
        attempts = 0
        delays_recorded = []

        def flaky_task():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionResetError("Connection dropped by peer")
            return {"status": "ok"}

        start_t = time.time()
        res = self.orchestrator.execute_with_retry(
            flaky_task,
            task_name="flaky_test",
            max_retries=3,
            base_delay=0.02,
            backoff_factor=2.0
        )
        elapsed = time.time() - start_t

        self.assertEqual(res["status"], "ok")
        self.assertEqual(attempts, 3)
        # Should have waited at least 0.02 + 0.04 = 0.06s
        self.assertGreaterEqual(elapsed, 0.05)

    def test_fatal_error_fails_immediately_without_retry(self):
        """Non-transient errors (such as TranscriptsDisabled) fail immediately."""
        attempts = 0

        def fatal_task():
            nonlocal attempts
            attempts += 1
            raise ValueError("TranscriptsDisabled: Captions disabled by creator")

        with self.assertRaises(ValueError):
            self.orchestrator.execute_with_retry(fatal_task, task_name="fatal_test", max_retries=3)

        self.assertEqual(attempts, 1)  # Zero retries attempted!

    # -------------------------------------------------------------------------
    # 6. Thread-Safe Deduplication Lock
    # -------------------------------------------------------------------------

    def test_deduplication_lock_attaches_to_active_job(self):
        """Concurrent submissions for identical video_id attach to active job."""
        vid = f"dedup_vid_{uuid.uuid4().hex[:6]}"

        # First submission spawns job
        job_id_1, is_new_1 = self.orchestrator.submit_or_attach(vid)
        self.assertTrue(is_new_1)

        # Second submission attaches to the existing active job
        job_id_2, is_new_2 = self.orchestrator.submit_or_attach(vid)
        self.assertFalse(is_new_2)
        self.assertEqual(job_id_1, job_id_2)

        # Once job is completed, active entry is cleared
        self.orchestrator.complete_job(job_id_1, {"_meta": {"title": "Done"}})
        job_id_3, is_new_3 = self.orchestrator.submit_or_attach(vid)
        self.assertTrue(is_new_3)
        self.assertNotEqual(job_id_1, job_id_3)

    # -------------------------------------------------------------------------
    # 7. ReportLab XML Ampersand Sanitization Fix
    # -------------------------------------------------------------------------

    def test_reportlab_xml_ampersand_escaping(self):
        """sanitize_text safely preserves literal ampersands and escapes XML tags."""
        # Literal ampersands in titles and brands
        self.assertEqual(sanitize_text("AT&T"), "AT&amp;T")
        self.assertEqual(sanitize_text("Q&A with CEO"), "Q&amp;A with CEO")
        self.assertEqual(sanitize_text("Research & Development"), "Research &amp; Development")

        # Pre-encoded entities are normalized and escaped
        self.assertEqual(sanitize_text("&amp;"), "&amp;")
        self.assertEqual(sanitize_text("<script>alert('xss')</script>"), "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;")

        # ReportLab paragraph rendering verification
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        style = getSampleStyleSheet()['Normal']
        p = Paragraph(sanitize_text("AT&T & Q&A & <script>"), style)
        rendered_text = "".join(f.text for f in p.frags)
        self.assertEqual(rendered_text, "AT&T & Q&A & <script>")

    # -------------------------------------------------------------------------
    # 8. Backward Compatibility of services.job_service Facade
    # -------------------------------------------------------------------------

    def test_job_service_facade_backward_compatibility(self):
        """All legacy job_service methods maintain 100% backward compatibility."""
        jid = job_service.create_job()
        self.assertIn(jid, job_service.JOBS)

        job = job_service.get_job(jid)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["stage"], 0)

        job_service.update_job_stage(jid, 2)
        self.assertEqual(job_service.get_job(jid)["stage"], 2)
        self.assertEqual(job_service.get_job(jid)["stage_name"], "Resolving transcript")

        job_service.complete_job(jid, {"result": "success"})
        self.assertEqual(job_service.get_job(jid)["status"], "completed")

        # fail_job test
        jid2 = job_service.create_job()
        job_service.fail_job(jid2, "503 UNAVAILABLE: High demand")
        self.assertEqual(job_service.get_job(jid2)["status"], "error")
        self.assertIn("demand spike", job_service.get_job(jid2)["error"].lower())


if __name__ == "__main__":
    unittest.main()
