"""
Adversarial Verification Suite for Milestone 2
Role: Empirical Challenger (challenger_m2_2)

This suite stress-tests:
1. Retry Engine:
   - Transient error simulation (ConnectionResetError, HTTP 503, HTTP 429).
   - Exponential backoff scaling: delay = base_delay * (2 ** (attempt - 1)).
   - Retry limit enforcement (max_retries thresholds).
   - Non-transient error immediate failure (no retry, no delay).
   - Empirical bug verification: SQLite analysis_jobs.retry_count silent drop.
2. Timeout Handling & Thread Isolation:
   - Hanging task simulation.
   - Empirical bug verification: lack of task timeout enforcement in execute_with_retry.
   - Empirical bug verification: orphaned self.task_pool (0 tasks submitted).
   - Thread pool exhaustion and master orchestrator stalling under hanging tasks.
3. State Machine Invariants:
   - Valid lifecycle transitions (QUEUED -> EXTRACTING -> PROCESSING -> VALIDATING -> COMPLETED / PARTIAL / FAILED).
   - Timestamp invariants (completed_at NULL during execution, populated on terminal).
   - Modules completed tracking in SQLite.
   - Thread-safe deduplication locking under 20-thread concurrency.
4. Backward Compatibility:
   - services.job_service facade behavior.
   - Case-insensitive JobStatus bridges.
"""

import unittest
import time
import uuid
import threading
from unittest.mock import patch, MagicMock
from concurrent.futures import TimeoutError as FutureTimeoutError

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
import services.job_service as job_service


class TestMilestone2AdversarialStress(unittest.TestCase):
    """Adversarial stress test suite verifying M2 claims and finding failure modes."""

    @classmethod
    def setUpClass(cls):
        init_relational_db()

    def setUp(self):
        # 2 master orchestrator workers, 4 worker task workers
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=2, max_task_workers=4)

    # =========================================================================
    # 1. RETRY ENGINE STRESS TESTS
    # =========================================================================

    def test_transient_connection_reset_retry_and_exponential_backoff_curve(self):
        """
        Verify exponential backoff scaling for ConnectionResetError:
        Delay between attempt 1 and 2 = base_delay * (2^0) = 0.04s
        Delay between attempt 2 and 3 = base_delay * (2^1) = 0.08s
        Total elapsed must be >= 0.12s.
        """
        attempts = 0
        call_timestamps = []

        def flaky_socket():
            nonlocal attempts
            attempts += 1
            call_timestamps.append(time.time())
            if attempts < 3:
                raise ConnectionResetError("Connection forcibly closed by remote host")
            return {"status": "ok"}

        base_delay = 0.04
        start_t = time.time()
        res = self.orchestrator.execute_with_retry(
            flaky_socket,
            task_name="test_reset",
            max_retries=3,
            base_delay=base_delay,
            backoff_factor=2.0
        )
        total_time = time.time() - start_t

        self.assertEqual(res["status"], "ok")
        self.assertEqual(attempts, 3)
        self.assertEqual(len(call_timestamps), 3)

        d1 = call_timestamps[1] - call_timestamps[0]
        d2 = call_timestamps[2] - call_timestamps[1]

        self.assertGreaterEqual(d1, 0.035, f"Delay 1 was too brief: {d1:.4f}s")
        self.assertGreaterEqual(d2, 0.070, f"Delay 2 was too brief: {d2:.4f}s")
        self.assertGreater(d2, d1, "Backoff delay must scale strictly exponentially")
        self.assertGreaterEqual(total_time, 0.11)

    def test_transient_http_503_and_429_retry_exhaustion_limit(self):
        """
        Verify that persistent HTTP 503 and 429 errors strictly exhaust at max_retries.
        """
        # Test HTTP 503 exhaustion at 3 retries
        c_503 = 0
        def fail_503():
            nonlocal c_503
            c_503 += 1
            raise Exception("503 UNAVAILABLE: High demand spike")

        with self.assertRaises(Exception) as ctx_503:
            self.orchestrator.execute_with_retry(
                fail_503, task_name="t_503", max_retries=3, base_delay=0.01
            )
        self.assertIn("503", str(ctx_503.exception))
        self.assertEqual(c_503, 3, "Must attempt exactly max_retries times")

        # Test HTTP 429 exhaustion at 4 retries
        c_429 = 0
        def fail_429():
            nonlocal c_429
            c_429 += 1
            raise Exception("429 RESOURCE_EXHAUSTED: Rate quota reached")

        with self.assertRaises(Exception) as ctx_429:
            self.orchestrator.execute_with_retry(
                fail_429, task_name="t_429", max_retries=4, base_delay=0.01
            )
        self.assertIn("429", str(ctx_429.exception))
        self.assertEqual(c_429, 4, "Must attempt exactly max_retries times")

    def test_non_transient_error_fails_immediately_without_retry(self):
        """
        Verify that fatal / non-transient errors (e.g. ValueError, KeyError,
        TranscriptsDisabled) abort on attempt 1 without sleep or retries.
        """
        attempts = 0
        def non_transient():
            nonlocal attempts
            attempts += 1
            raise ValueError("Invalid YouTube URL: unrecognized video format")

        t0 = time.time()
        with self.assertRaises(ValueError):
            self.orchestrator.execute_with_retry(
                non_transient, task_name="t_fatal", max_retries=5, base_delay=0.1
            )
        elapsed = time.time() - t0

        self.assertEqual(attempts, 1, "Non-transient error must not retry")
        self.assertLess(elapsed, 0.05, "Non-transient error must not sleep")

    def test_adversarial_finding_sqlite_drops_retry_count(self):
        """
        REMEDIATION VERIFICATION 1:
        Verify that update_job_status persists retry_count to SQLite analysis_jobs table
        during transient error retries in execute_with_retry.
        """
        vid = f"retry_drop_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        attempts = 0
        def flaky_task():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionResetError("Transient network failure")
            return "recovered"

        self.orchestrator.execute_with_retry(
            flaky_task,
            task_name="flaky_persist",
            max_retries=3,
            base_delay=0.01,
            job_id=job_id
        )

        # 1. In-memory dictionary correctly records 2 retries
        in_mem_job = self.orchestrator.get_job(job_id)
        self.assertEqual(in_mem_job["retry_count"], 2)

        # 2. SQLite record in analysis_jobs must persist retry_count
        db_job = get_analysis_job(job_id)
        self.assertEqual(
            db_job["retry_count"], 2,
            "REMEDIATED: SQLite analysis_jobs.retry_count is properly updated and persisted"
        )

    # =========================================================================
    # 2. TIMEOUT HANDLING & THREAD ISOLATION STRESS TESTS
    # =========================================================================

    def test_adversarial_finding_task_timeout_not_enforced(self):
        """
        REMEDIATION VERIFICATION 2:
        Verify that execute_with_retry enforces task timeouts and thread pool isolation.
        A hanging task that exceeds timeout raises TimeoutError and terminates without
        blocking the caller thread for the full duration.
        """
        def hanging_task():
            time.sleep(0.5)
            return "finished_after_hang"

        start_t = time.time()
        with self.assertRaises((TimeoutError, FutureTimeoutError)):
            self.orchestrator.execute_with_retry(
                hanging_task,
                task_name="metadata",
                max_retries=1,
                timeout=0.1
            )
        elapsed = time.time() - start_t

        self.assertLess(
            elapsed, 0.35,
            "REMEDIATED: execute_with_retry enforces timeout and terminates hanging task quickly"
        )

    def test_adversarial_finding_task_pool_is_orphaned(self):
        """
        REMEDIATION VERIFICATION 3:
        Verify that self.task_pool ThreadPoolExecutor is actively utilized by
        execute_with_retry for all pipeline worker tasks (metadata, transcript,
        summary, chapters, claims, learning, entities, export_pdf).
        """
        # Track calls to task_pool.submit
        with patch.object(self.orchestrator.task_pool, "submit", wraps=self.orchestrator.task_pool.submit) as mock_submit:
            # Run a simulated pipeline
            vid = f"orphan_pool_{uuid.uuid4().hex[:6]}"
            job_id = self.orchestrator.create_job(video_id=vid)

            with patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
                 patch("services.orchestrator.run_metadata_worker") as mock_meta, \
                 patch("services.orchestrator.run_transcript_worker") as mock_trans:

                mock_meta.return_value = WorkerResult(
                    module="metadata", success=True,
                    data={"title": "T", "author": "A", "duration": "01:00", "duration_seconds": 60, "thumbnail_url": ""}
                )
                mock_trans.return_value = WorkerResult(
                    module="transcript", success=True,
                    data={"segments": [{"text": "hi", "start": 0, "duration": 5}], "formatted_duration": "01:00", "duration_seconds": 60, "ui_sample": []}
                )
                mock_ai.return_value = {
                    "video_overview": {"title": "T", "summary": "S"},
                    "chapters": [{"title": "C", "start_time": "00:00"}],
                    "creator_repurposing": {"youtube_chapters_raw": "00:00 C"}
                }

                self.orchestrator.run_pipeline(job_id, video_id=vid)

            self.assertEqual(
                mock_submit.call_count, 8,
                "REMEDIATED: task_pool.submit was called for all 8 modular pipeline workers"
            )

    def test_thread_pool_exhaustion_on_blocking_tasks(self):
        """
        EMPIRICAL FINDING 4:
        Because tasks are not isolated with timeouts in a separate worker pool,
        hanging tasks running in job_pool exhaust all job_pool threads and stall
        master orchestration.
        """
        hang_event_1 = threading.Event()
        hang_event_2 = threading.Event()

        def hanging_job(ev):
            ev.wait(timeout=1.0)

        # self.orchestrator has max_job_workers=2
        f1 = self.orchestrator.job_pool.submit(hanging_job, hang_event_1)
        f2 = self.orchestrator.job_pool.submit(hanging_job, hang_event_2)

        # 3rd job is submitted
        quick_started = threading.Event()
        def quick_job():
            quick_started.set()
            return "quick_finished"

        f3 = self.orchestrator.job_pool.submit(quick_job)

        # The 3rd job CANNOT start because all job_pool workers are blocked by hanging tasks!
        is_started = quick_started.wait(timeout=0.08)
        self.assertFalse(
            is_started,
            "Master orchestrator job_pool is stalled because hanging tasks exhaust all available threads!"
        )

        # Clean up
        hang_event_1.set()
        hang_event_2.set()
        f3.result(timeout=2.0)

    # =========================================================================
    # 3. STATE MACHINE INVARIANTS & INTEGRITY TESTS
    # =========================================================================

    def test_sqlite_state_progression_invariants(self):
        """
        Verify SQLite lifecycle transitions across all stages:
        QUEUED (stage 0) -> EXTRACTING (stages 1-3) -> PROCESSING (stages 4-7)
        -> VALIDATING (stage 8) -> COMPLETED (stage 9).
        Verify completed_at is strictly NULL until terminal transition.
        """
        vid = f"inv_vid_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        # Stage 0: QUEUED
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "QUEUED")
        self.assertEqual(job["stage"], 0)
        self.assertIsNone(job["completed_at"])

        # Stage 1: EXTRACTING
        self.orchestrator.update_stage(job_id, 1, "Fetching metadata", progress=10)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "EXTRACTING")
        self.assertEqual(job["stage"], 1)
        self.assertIsNone(job["completed_at"])

        # Stage 3: EXTRACTING
        self.orchestrator.update_stage(job_id, 3, "Normalizing timestamps", progress=35)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "EXTRACTING")
        self.assertEqual(job["stage"], 3)
        self.assertIsNone(job["completed_at"])

        # Stage 4: PROCESSING
        self.orchestrator.update_stage(job_id, 4, "Building temporal model", progress=45)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "PROCESSING")
        self.assertEqual(job["stage"], 4)
        self.assertIsNone(job["completed_at"])

        # Stage 7: PROCESSING
        self.orchestrator.update_stage(job_id, 7, "Generating learning material", progress=80)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "PROCESSING")
        self.assertEqual(job["stage"], 7)
        self.assertIsNone(job["completed_at"])

        # Stage 8: VALIDATING
        self.orchestrator.update_stage(job_id, 8, "Building knowledge graph", progress=90)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "VALIDATING")
        self.assertEqual(job["stage"], 8)
        self.assertIsNone(job["completed_at"])

        # Stage 9: COMPLETED
        result_payload = {"_meta": {"title": "State Progression"}, "_module_status": {"summary": "COMPLETED"}}
        self.orchestrator.complete_job(job_id, result_payload, is_partial=False)
        job = get_analysis_job(job_id)
        self.assertEqual(job["status"], "COMPLETED")
        self.assertEqual(job["stage"], 9)
        self.assertEqual(job["progress"], 100)
        self.assertIsNotNone(job["completed_at"])

    def test_sqlite_partial_failure_invariants(self):
        """
        Verify that auxiliary failure transitions job to PARTIAL in SQLite,
        records completed modules, and populates completed_at.
        """
        vid = f"inv_partial_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        result_payload = {
            "_meta": {"title": "Partial Invariant"},
            "_module_status": {
                "metadata": "COMPLETED",
                "transcript": "COMPLETED",
                "summary": "COMPLETED",
                "export_pdf": "FAILED"
            }
        }
        self.orchestrator.complete_job(job_id, result_payload, is_partial=True)
        job = get_analysis_job(job_id)

        self.assertEqual(job["status"], "PARTIAL")
        self.assertEqual(job["stage"], 9)
        self.assertIsNotNone(job["completed_at"])
        self.assertIn("summary", job["modules_completed"])
        self.assertIn("metadata", job["modules_completed"])
        self.assertNotIn("export_pdf", job["modules_completed"])

    def test_sqlite_failed_terminal_invariants(self):
        """
        Verify that fatal failure transitions job to FAILED in SQLite,
        records formatted user error, and populates completed_at.
        """
        vid = f"inv_failed_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        self.orchestrator.fail_job(job_id, "google.genai.errors.ServerError: 503 Overloaded")
        job = get_analysis_job(job_id)

        self.assertEqual(job["status"], "FAILED")
        self.assertIsNotNone(job["completed_at"])
        self.assertIn("temporary global demand spike", job["error"])

    def test_deduplication_under_high_concurrency(self):
        """
        Verify thread-safety of deduplication lock: 20 simultaneous threads
        submitting the same video_id must create exactly 1 new job and 19 attachments.
        """
        vid = f"dedup_race_{uuid.uuid4().hex[:8]}"
        results = []
        threads = []

        def worker():
            jid, is_new = self.orchestrator.submit_or_attach(vid)
            results.append((jid, is_new))

        for _ in range(20):
            t = threading.Thread(target=worker)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        job_ids = set(r[0] for r in results)
        new_count = sum(1 for r in results if r[1] is True)
        attach_count = sum(1 for r in results if r[1] is False)

        self.assertEqual(len(job_ids), 1, "All 20 submissions must resolve to the identical job ID")
        self.assertEqual(new_count, 1, "Exactly 1 submission must create the job")
        self.assertEqual(attach_count, 19, "Exactly 19 submissions must attach to the existing job")


if __name__ == "__main__":
    unittest.main()
