"""
test_m2_retest_deep_verifier.py
Adversarial Retest Verification Suite for Milestone 2
Agent: challenger_m2_retest

Validates:
1. Exact sequential persistence of retry_count in SQLite analysis_jobs table.
2. Task timeout enforcement with exponential backoff retries and bounded latency.
3. Thread pool isolation ensuring job_pool is not starved by hanging task_pool jobs.
4. Fail-fast vs Partial degradation across all 8 pipeline workers.
5. Direct update_job_status edge cases (including retry_count=0 and retry_count=None).
"""

import unittest
import time
import uuid
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch, MagicMock

from services.orchestrator import (
    AsyncJobOrchestrator, JobStatus,
    STATUS_QUEUED, STATUS_EXTRACTING, STATUS_PROCESSING,
    STATUS_VALIDATING, STATUS_COMPLETED, STATUS_PARTIAL, STATUS_FAILED
)
from services.workers import WorkerResult
from services.storage_service import (
    init_relational_db, get_analysis_job, create_analysis_job,
    update_job_status, get_db
)


class TestMilestone2RetestDeepVerification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def setUp(self):
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=2, max_task_workers=4)

    def test_direct_update_job_status_retry_count_values(self):
        """Verify update_job_status correctly updates retry_count in SQLite for various values (0, 1, 5, None)."""
        job_id = f"job_retest_{uuid.uuid4().hex[:8]}"
        create_analysis_job(job_id=job_id, video_id="vid_test_1")

        # Initial check
        job = get_analysis_job(job_id)
        self.assertEqual(job["retry_count"], 0)

        # Update to 1
        ok = update_job_status(job_id, status="PROCESSING", retry_count=1)
        self.assertTrue(ok)
        job = get_analysis_job(job_id)
        self.assertEqual(job["retry_count"], 1)

        # Update to 5
        ok = update_job_status(job_id, status="PROCESSING", retry_count=5)
        self.assertTrue(ok)
        job = get_analysis_job(job_id)
        self.assertEqual(job["retry_count"], 5)

        # Update to 0 explicitly (checking that 0 is not treated as falsy/skipped)
        ok = update_job_status(job_id, status="PROCESSING", retry_count=0)
        self.assertTrue(ok)
        job = get_analysis_job(job_id)
        self.assertEqual(job["retry_count"], 0)

        # Update without retry_count (should retain existing value 0)
        ok = update_job_status(job_id, status="VALIDATING", stage=8)
        self.assertTrue(ok)
        job = get_analysis_job(job_id)
        self.assertEqual(job["retry_count"], 0)

    def test_retry_count_persistence_exact_attempts_sequence(self):
        """
        Verify that execute_with_retry actively increments and persists retry_count
        in SQLite analysis_jobs table on each retry step.
        """
        job_id = f"job_seq_{uuid.uuid4().hex[:8]}"
        self.orchestrator.create_job(video_id="vid_seq", user_id="u_test")
        # Ensure job exists in orchestrator and DB
        with self.orchestrator.lock:
            self.orchestrator.jobs[job_id] = {
                "id": job_id, "video_id": "vid_seq", "status": STATUS_PROCESSING, "retry_count": 0
            }
        create_analysis_job(job_id=job_id, video_id="vid_seq")

        attempts = 0
        observed_db_retries = []

        def flaky_task():
            nonlocal attempts
            attempts += 1
            # Check what's in DB right now
            row = get_analysis_job(job_id)
            observed_db_retries.append((attempts, row["retry_count"]))
            if attempts < 3:
                raise ConnectionResetError(f"Transient fail {attempts}")
            return "success_attempt_3"

        res = self.orchestrator.execute_with_retry(
            flaky_task,
            task_name="test_seq",
            max_retries=3,
            base_delay=0.02,
            backoff_factor=1.5,
            job_id=job_id
        )

        self.assertEqual(res, "success_attempt_3")
        self.assertEqual(attempts, 3)

        # Check final DB state
        final_db = get_analysis_job(job_id)
        self.assertEqual(final_db["retry_count"], 2, "After 2 retries, retry_count in DB must be exactly 2")

        # In-memory orchestrator job state
        self.assertEqual(self.orchestrator.jobs[job_id]["retry_count"], 2)

    def test_task_timeout_enforcement_with_retry_and_backoff(self):
        """
        Verify that a task hanging longer than timeout raises TimeoutError,
        is retried if attempts < max_retries, and exhausts after max_retries,
        all within predictable bounded time.
        """
        job_id = f"job_tout_{uuid.uuid4().hex[:8]}"
        create_analysis_job(job_id=job_id, video_id="vid_tout")
        with self.orchestrator.lock:
            self.orchestrator.jobs[job_id] = {
                "id": job_id, "video_id": "vid_tout", "status": STATUS_PROCESSING, "retry_count": 0
            }

        call_count = 0
        def hanging_task():
            nonlocal call_count
            call_count += 1
            # Sleep longer than the 0.08s timeout
            time.sleep(0.4)
            return "should_never_reach"

        start_time = time.time()
        with self.assertRaises((TimeoutError, FutureTimeoutError)):
            self.orchestrator.execute_with_retry(
                hanging_task,
                task_name="hanging",
                max_retries=2,
                base_delay=0.03,
                timeout=0.08,
                job_id=job_id
            )
        elapsed = time.time() - start_time

        # Max retries = 2.
        # Attempt 1: 0.08s timeout -> raises TimeoutError. Backoff delay = 0.03s.
        # Attempt 2: 0.08s timeout -> raises TimeoutError. Exhausted.
        # Total expected elapsed time: ~0.16s + 0.03s = ~0.19s to 0.30s.
        # Definitely strictly LESS than 2 * 0.4s = 0.8s!
        self.assertEqual(call_count, 2, "Must attempt exactly 2 times")
        self.assertLess(elapsed, 0.45, f"Timeout was not properly enforced: elapsed {elapsed:.3f}s")
        self.assertGreaterEqual(elapsed, 0.15, f"Elapsed time too short: {elapsed:.3f}s")

        # Check DB retry count after 1 retry (attempt 1 failed, attempted attempt 2)
        final_db = get_analysis_job(job_id)
        self.assertEqual(final_db["retry_count"], 1)

    def test_thread_pool_isolation_job_pool_not_blocked_by_task_pool(self):
        """
        Verify thread pool isolation:
        Even if tasks in self.task_pool are taking time or sleeping,
        the master orchestrator self.job_pool remains completely responsive.
        """
        task_event = threading.Event()

        def slow_task():
            task_event.wait(timeout=1.0)
            return "slow_done"

        # Submit slow task via task_pool
        task_future = self.orchestrator.task_pool.submit(slow_task)

        # Concurrently submit work to job_pool - must start and complete immediately!
        job_done_event = threading.Event()
        def fast_job():
            job_done_event.set()
            return "job_done"

        job_future = self.orchestrator.job_pool.submit(fast_job)
        started_cleanly = job_done_event.wait(timeout=0.1)

        self.assertTrue(started_cleanly, "job_pool was starved by task_pool!")
        self.assertEqual(job_future.result(timeout=0.2), "job_done")

        # Cleanup slow task
        task_event.set()
        self.assertEqual(task_future.result(timeout=1.0), "slow_done")

    def test_pipeline_essential_worker_failure_aborts_to_failed(self):
        """
        Verify that failure in an essential worker (metadata or transcript or summary)
        transitions the job to FAILED.
        """
        vid = f"vid_fail_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        with patch("services.orchestrator.run_metadata_worker") as mock_meta:
            mock_meta.return_value = WorkerResult(
                module="metadata", success=False, error="Video is private or removed"
            )
            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], STATUS_FAILED)
        self.assertIn("Video is private or removed", job["error"])

        db_job = get_analysis_job(job_id)
        self.assertEqual(db_job["status"], "FAILED")
        self.assertIsNotNone(db_job["completed_at"])

    def test_all_auxiliary_workers_resilience_to_partial(self):
        """
        Verify that failures in auxiliary workers (chapters, claims, learning, entities, export_pdf)
        all independently transition job to PARTIAL without aborting the pipeline.
        """
        aux_modules = ["chapters", "claims", "learning", "entities", "export_pdf"]

        for mod in aux_modules:
            vid = f"vid_aux_{mod}_{uuid.uuid4().hex[:6]}"
            job_id = self.orchestrator.create_job(video_id=vid)

            meta = {"title": f"Test {mod}", "author": "Auth", "duration": "05:00", "duration_seconds": 300, "thumbnail_url": ""}
            segments = [{"text": "Hello world", "start": 0, "duration": 5}]
            analysis = {
                "video_overview": {"title": "T", "summary": "S"},
                "chapters": [{"title": "C", "start_time": "00:00"}],
                "creator_repurposing": {"youtube_chapters_raw": "00:00 C"}
            }

            with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
                 patch("services.orchestrator.run_transcript_worker") as mock_trans, \
                 patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
                 patch("services.orchestrator.run_summary_worker") as mock_sum, \
                 patch("services.orchestrator.run_chapter_worker") as mock_chap, \
                 patch("services.orchestrator.run_claim_worker") as mock_claim, \
                 patch("services.orchestrator.run_learning_worker") as mock_learn, \
                 patch("services.orchestrator.run_entity_worker") as mock_ent, \
                 patch("services.orchestrator.run_export_worker") as mock_exp:

                mock_meta.return_value = WorkerResult("metadata", True, meta)
                mock_trans.return_value = WorkerResult("transcript", True, {"segments": segments, "formatted_duration": "05:00", "duration_seconds": 300, "ui_sample": []})
                mock_ai.return_value = analysis
                mock_sum.return_value = WorkerResult("summary", True, {"video_overview": {"summary": "S"}})
                mock_chap.return_value = WorkerResult("chapters", True, {"chapters": []})
                mock_claim.return_value = WorkerResult("claims", True, {"claims": []})
                mock_learn.return_value = WorkerResult("learning", True, {"learning": {}})
                mock_ent.return_value = WorkerResult("entities", True, {"entities": {}, "knowledge_graph": {}})
                mock_exp.return_value = WorkerResult("export_pdf", True, {"pdf_generated": True})

                # Fail the specific target module
                target_mock = {
                    "chapters": mock_chap,
                    "claims": mock_claim,
                    "learning": mock_learn,
                    "entities": mock_ent,
                    "export_pdf": mock_exp
                }[mod]
                target_mock.return_value = WorkerResult(mod, False, error=f"Failure in {mod}")

                self.orchestrator.run_pipeline(job_id, video_id=vid)

            job = self.orchestrator.get_job(job_id)
            self.assertEqual(job["status"], STATUS_PARTIAL, f"Failed for module {mod}")
            self.assertTrue(job["is_partial"])

            db_job = get_analysis_job(job_id)
            self.assertEqual(db_job["status"], "PARTIAL")
            self.assertIsNotNone(db_job["completed_at"])


if __name__ == "__main__":
    unittest.main()
