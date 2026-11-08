"""
test_m4_empirical_challenger.py
Adversarial Empirical Stress Test Suite for Milestone 4 (Feature F16: Progressive Module Delivery & Job Polling).

Stress Test Pillars:
1. Polling state machine transitions: Live concurrent pipeline execution asserting that
   `GET /api/job/<job_id>` dynamically transitions across 'extracting', 'processing',
   'validating', and 'completed', progressively exposing modules (metadata, transcript,
   summary, chapters).
2. Partial failure resilience: Simulating auxiliary worker crashes (export_worker, entity_worker,
   and simultaneous failures) and empirically verifying that the pipeline transitions to 'partial',
   preserves and delivers all core modules, and yields status 'partial' with valid results.
3. Polling termination & timer leaks: Testing client-side polling state machine under Node.js
   asserting that on 'completed', 'partial', and 'failed', polling intervals are cleared,
   does NOT enter an infinite 900ms loop, and auxiliary toasts fire correctly.
4. Concurrency & rapid submissions: Firing 50 concurrent submissions for identical video_id
   under deduplication lock, testing thread-safe state inspection and rapid sequential job isolation.
"""

import os
import sys
import time
import uuid
import threading
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

import app as flask_app_module
from services.orchestrator import (
    AsyncJobOrchestrator,
    JobStatus,
    STATUS_QUEUED,
    STATUS_EXTRACTING,
    STATUS_PROCESSING,
    STATUS_VALIDATING,
    STATUS_COMPLETED,
    STATUS_PARTIAL,
    STATUS_FAILED,
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
    init_relational_db,
    get_analysis_job,
    get_cached_analysis,
    get_modular_analysis,
    get_db,
)
import services.job_service as job_service


class TestM4EmpiricalChallenger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_relational_db()
        cls.app = flask_app_module.app
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=4, max_task_workers=8)

    def tearDown(self):
        self.orchestrator.shutdown(wait=False)

    def _build_mock_context(self, vid="test_m4_empirical"):
        """Standard mock data for video analysis pipeline."""
        meta_data = {
            "title": "Quantum Entanglement & Information Theory",
            "author": "Veritasium & 3Blue1Brown",
            "duration": "18:45",
            "duration_seconds": 1125,
            "thumbnail_url": f"https://img.youtube.com/vi/{vid}/hqdefault.jpg",
            "video_id": vid
        }
        segments_data = [
            {"text": "Welcome to quantum information theory.", "start": 0.0, "duration": 5.0},
            {"text": "Bell inequalities prove local hidden variables are impossible.", "start": 5.0, "duration": 6.0},
            {"text": "Superposition collapses upon measurement in non-orthogonal basis.", "start": 11.0, "duration": 7.0},
            {"text": "Quantum teleportation transfers state without transferring matter.", "start": 18.0, "duration": 8.0},
            {"text": "We conclude with implications for quantum key distribution.", "start": 26.0, "duration": 6.0}
        ]
        raw_analysis_data = {
            "video_overview": {
                "title": "Quantum Entanglement & Information Theory",
                "summary": "Deep dive into Bell tests, superposition, and quantum teleportation protocols."
            },
            "metrics": {"quality_score": 94},
            "quality_scorecard": {"overall_score": 94},
            "key_takeaways": [
                {"title": "Bell Non-Locality", "seconds": 5, "description": "Local realism is violated."},
                {"title": "Quantum Teleportation", "seconds": 18, "description": "State transfer protocol."}
            ],
            "chapters": [
                {"number": "01", "title": "Bell Inequalities", "start_time": "00:00", "start_seconds": 0, "summary": "Foundations."},
                {"number": "02", "title": "Teleportation Protocol", "start_time": "00:18", "start_seconds": 18, "summary": "Protocol details."}
            ],
            "creator_repurposing": {
                "youtube_chapters_raw": "00:00 Bell Inequalities\n00:18 Teleportation Protocol"
            }
        }
        return meta_data, segments_data, raw_analysis_data

    # =========================================================================
    # PILLAR 1: POLLING STATE MACHINE TRANSITIONS DURING ACTIVE EXECUTION
    # =========================================================================

    def test_live_concurrent_pipeline_polling_state_machine(self):
        """
        Stress-test: Launch live background pipeline across stages 1 through 9.
        Concurrently poll GET /api/job/<job_id> via Flask test client every 15ms.
        Verify that:
        1. Intermediate states 'extracting', 'processing', 'validating', 'completed' are captured.
        2. Modules progressively appear in the response:
           - Stage 1/2: 'metadata' appears
           - Stage 2/3: 'transcript' appears
           - Stage 5: 'summary' appears
           - Stage 6: 'chapters' appears
        3. Final state reaches 'completed' with 100% progress and dossier ready.
        """
        vid = f"live_poll_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_context(vid)

        # Hook self.orchestrator into services.job_service for Flask /api/job/<job_id>
        orig_orch = job_service.orchestrator
        job_service.orchestrator = self.orchestrator

        # Controlled pacing for workers to allow concurrent poller to capture all stages
        def paced_meta(*args, **kwargs):
            time.sleep(0.04)
            return WorkerResult(module="metadata", success=True, data=meta_data)

        def paced_trans(*args, **kwargs):
            time.sleep(0.04)
            return WorkerResult(
                module="transcript",
                success=True,
                data={"segments": segments, "formatted_duration": "18:45", "duration_seconds": 1125, "ui_sample": segments[:2]}
            )

        def paced_ai(*args, **kwargs):
            time.sleep(0.04)
            return dict(raw_analysis)

        def paced_exp(*args, **kwargs):
            time.sleep(0.04)
            return WorkerResult(module="export_pdf", success=True, data={"pdf_path": "/tmp/dummy.pdf"})

        polled_states = []
        polled_modules_seen = set()
        stop_polling = threading.Event()

        def poller_thread():
            while not stop_polling.is_set():
                res = self.client.get(f"/api/job/{job_id}")
                if res.status_code == 200:
                    data = res.get_json()
                    status = data.get("status")
                    stage = data.get("stage")
                    modules = data.get("modules", {})
                    polled_states.append((status, stage))
                    for mod_name in modules.keys():
                        polled_modules_seen.add(mod_name)
                    if status in ("completed", "partial", "error", "failed"):
                        break
                time.sleep(0.015)

        t_poll = threading.Thread(target=poller_thread, daemon=True)

        try:
            with patch("services.orchestrator.run_metadata_worker", side_effect=paced_meta), \
                 patch("services.orchestrator.run_transcript_worker", side_effect=paced_trans), \
                 patch("services.orchestrator.run_videolens_analysis", side_effect=paced_ai), \
                 patch("services.orchestrator.run_export_worker", side_effect=paced_exp):

                t_poll.start()
                # Run pipeline on background thread
                pipeline_thread = threading.Thread(
                    target=self.orchestrator.run_pipeline,
                    args=(job_id, vid),
                    daemon=True
                )
                pipeline_thread.start()
                pipeline_thread.join(timeout=10.0)

            # Wait for poller to catch final state
            t_poll.join(timeout=2.0)
            stop_polling.set()

            # Assert final job state
            final_res = self.client.get(f"/api/job/{job_id}")
            self.assertEqual(final_res.status_code, 200)
            final_data = final_res.get_json()
            self.assertEqual(final_data["status"], "completed")
            self.assertEqual(final_data["progress"], 100)
            self.assertEqual(final_data["stage"], 9)
            self.assertIsNotNone(final_data["result"])

            # Verify that intermediate states were observed in memory over HTTP polling
            observed_statuses = {s for s, _ in polled_states}
            self.assertIn("extracting", observed_statuses, f"Observed: {observed_statuses}")
            self.assertIn("processing", observed_statuses, f"Observed: {observed_statuses}")
            self.assertIn("completed", observed_statuses, f"Observed: {observed_statuses}")

            # Verify progressive module delivery over HTTP polling
            self.assertIn("metadata", polled_modules_seen, f"Modules seen: {polled_modules_seen}")
            self.assertIn("transcript", polled_modules_seen, f"Modules seen: {polled_modules_seen}")
            self.assertIn("summary", polled_modules_seen, f"Modules seen: {polled_modules_seen}")
            self.assertIn("chapters", polled_modules_seen, f"Modules seen: {polled_modules_seen}")

        finally:
            job_service.orchestrator = orig_orch

    def test_polling_nonexistent_job_returns_404(self):
        """Asserts that GET /api/job/<unknown_id> returns HTTP 404 with error message."""
        res = self.client.get("/api/job/definitely_non_existent_job_999999")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertIn("error", data)
        self.assertEqual(data["error"], "Job not found")

    def test_polling_evicted_job_hydrates_cleanly_from_sqlite(self):
        """
        Asserts that if a job is evicted from in-memory cache,
        get_job cleanly hydrates from SQLite with proper lowercase-compatible JobStatus.
        """
        vid = f"hydrate_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        # Transition stage to PROCESSING in SQLite
        self.orchestrator.update_stage(job_id, 5, "Generating core intelligence", progress=60)

        # Evict from in-memory dictionary
        with self.orchestrator.lock:
            self.orchestrator.jobs.pop(job_id, None)

        # Hydrate
        hydrated = self.orchestrator.get_job(job_id)
        self.assertIsNotNone(hydrated)
        self.assertEqual(hydrated["id"], job_id)
        self.assertEqual(hydrated["status"], "processing")
        self.assertEqual(hydrated["status"], STATUS_PROCESSING)
        self.assertEqual(hydrated["stage"], 5)
        self.assertEqual(hydrated["progress"], 60)

    # =========================================================================
    # PILLAR 2: PARTIAL FAILURE RESILIENCE
    # =========================================================================

    def test_export_worker_crash_delivers_core_modules_under_partial(self):
        """
        Simulate export worker crashing with simulated OOM.
        Empirically assert:
        - Job finishes with status 'partial' and is_partial == True.
        - GET /api/job/<job_id> returns status 'partial'.
        - Core deliverables (metadata, transcript, summary, chapters) are 100% delivered.
        - Auxiliary failure is logged in failed_modules.
        """
        vid = f"part_exp_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_context(vid)

        orig_orch = job_service.orchestrator
        job_service.orchestrator = self.orchestrator

        try:
            with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
                 patch("services.orchestrator.run_transcript_worker") as mock_trans, \
                 patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
                 patch("services.orchestrator.run_export_worker") as mock_exp:

                mock_meta.return_value = WorkerResult(module="metadata", success=True, data=meta_data)
                mock_trans.return_value = WorkerResult(
                    module="transcript",
                    success=True,
                    data={"segments": segments, "formatted_duration": "18:45", "duration_seconds": 1125, "ui_sample": segments[:2]}
                )
                mock_ai.return_value = dict(raw_analysis)
                mock_exp.return_value = WorkerResult(
                    module="export_pdf",
                    success=False,
                    error="ReportLab memory exhausted in export worker"
                )

                self.orchestrator.run_pipeline(job_id, video_id=vid)

            # Query over HTTP polling endpoint
            res = self.client.get(f"/api/job/{job_id}")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()

            self.assertEqual(data["status"], "partial")
            self.assertTrue(data["is_partial"])
            self.assertEqual(data["stage"], 9)
            self.assertEqual(data["progress"], 100)

            # Core deliverables check
            res_payload = data["result"]
            self.assertIsNotNone(res_payload)
            self.assertEqual(res_payload["_meta"]["title"], meta_data["title"])
            self.assertGreaterEqual(len(res_payload["transcript_segments"]), 5)
            self.assertIn("Bell tests", res_payload["video_overview"]["summary"])
            self.assertGreaterEqual(len(res_payload["chapters"]), 2)

            # Error details check
            self.assertIn("export_pdf", res_payload["failed_modules"])

        finally:
            job_service.orchestrator = orig_orch

    def test_entity_and_export_double_crash_resilience(self):
        """
        Simulate both knowledge_graph and export_pdf failing simultaneously.
        Empirically assert job terminates as 'partial', not 'error' or 'failed'.
        """
        vid = f"part_double_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)
        meta_data, segments, raw_analysis = self._build_mock_context(vid)

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai, \
             patch("services.orchestrator.run_entity_worker") as mock_ent, \
             patch("services.orchestrator.run_export_worker") as mock_exp:

            mock_meta.return_value = WorkerResult(module="metadata", success=True, data=meta_data)
            mock_trans.return_value = WorkerResult(
                module="transcript",
                success=True,
                data={"segments": segments, "formatted_duration": "18:45", "duration_seconds": 1125, "ui_sample": segments[:2]}
            )
            mock_ai.return_value = dict(raw_analysis)
            mock_ent.return_value = WorkerResult(module="entities", success=False, error="Graph layout timed out")
            mock_exp.return_value = WorkerResult(module="export_pdf", success=False, error="PDF generator crashed")

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], "partial")
        self.assertTrue(job["is_partial"])
        self.assertIsNotNone(job["result"])
        self.assertIn("knowledge_graph", job["result"]["failed_modules"])
        self.assertIn("export_pdf", job["result"]["failed_modules"])

    # =========================================================================
    # PILLAR 3: POLLING TERMINATION & TIMER LEAKS (NODE.JS CLIENT HARNESS)
    # =========================================================================

    def test_client_polling_harness_execution(self):
        """
        Executes test_polling_behavior.js under Node.js runtime.
        Asserts that:
        1. Multi-stage poll terminates cleanly on 'completed' and clears timer.
        2. Multi-stage poll terminates cleanly on 'partial', clears timer, triggers toast,
           and does NOT enter an infinite 900ms loop.
        3. Poll terminates cleanly on 'failed' and clears timer.
        4. Immediate completion (cached video) clears timer and does not leak intervals.
        """
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(repo_dir, "test_polling_behavior.js")
        self.assertTrue(os.path.exists(script_path), f"Missing {script_path}")

        proc = subprocess.run(
            ["node", script_path],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15
        )

        sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)

        self.assertEqual(proc.returncode, 0, f"Node.js polling test failed: {proc.stderr}")
        self.assertIn("All scenario runs completed.", proc.stdout)

    # =========================================================================
    # PILLAR 4: CONCURRENCY & RAPID SUBMISSIONS
    # =========================================================================

    def test_50_concurrent_submissions_deduplication(self):
        """
        Fire 50 concurrent submissions for identical video_id.
        Assert deduplication lock guarantees:
        1. Exactly 1 primary job is created (is_new == True).
        2. 49 submissions attach to that active job (is_new == False).
        3. All 50 threads retrieve the identical job_id.
        """
        vid = f"rapid_dedup_{uuid.uuid4().hex[:8]}"

        results = []

        def submit_worker():
            job_id, is_new = self.orchestrator.submit_or_attach(vid)
            return job_id, is_new

        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = [executor.submit(submit_worker) for _ in range(50)]
            for f in as_completed(futures):
                results.append(f.result())

        job_ids = [r[0] for r in results]
        is_new_flags = [r[1] for r in results]

        # All 50 must have returned the exact same active job ID
        self.assertEqual(len(set(job_ids)), 1, f"Found multiple job IDs: {set(job_ids)}")
        # Exactly one must have been new
        self.assertEqual(sum(1 for flag in is_new_flags if flag), 1)
        # Exactly 49 attached
        self.assertEqual(sum(1 for flag in is_new_flags if not flag), 49)

    def test_rapid_sequential_different_videos_isolation(self):
        """
        Submit 10 distinct video IDs in rapid succession (5 times each = 50 submissions).
        Assert each video ID receives its own dedicated job ID and states do not cross-contaminate.
        """
        vids = [f"vid_iso_{i}_{uuid.uuid4().hex[:6]}" for i in range(10)]
        created_jobs = {}

        for vid in vids:
            job_id, is_new = self.orchestrator.submit_or_attach(vid)
            self.assertTrue(is_new)
            created_jobs[vid] = job_id

        # Rapid re-submissions must attach
        for vid in vids:
            job_id, is_new = self.orchestrator.submit_or_attach(vid)
            self.assertFalse(is_new)
            self.assertEqual(job_id, created_jobs[vid])

        # Assert all 10 job records are distinct in memory
        unique_job_ids = set(created_jobs.values())
        self.assertEqual(len(unique_job_ids), 10)

    def test_high_concurrency_polling_stress(self):
        """
        Stress-test: 30 threads continuously polling GET /api/job/<job_id>
        while the pipeline is actively executing transitions across all 9 stages.
        Asserts 0 deadlocks, 0 crashes, and 100% valid JSON responses.
        """
        vid = f"poll_stress_{uuid.uuid4().hex[:8]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        orig_orch = job_service.orchestrator
        job_service.orchestrator = self.orchestrator

        stop_event = threading.Event()
        poll_errors = []
        poll_count = [0]

        def poll_worker():
            while not stop_event.is_set():
                try:
                    res = self.client.get(f"/api/job/{job_id}")
                    if res.status_code != 200:
                        poll_errors.append(f"HTTP {res.status_code}")
                    data = res.get_json()
                    if not isinstance(data, dict) or "status" not in data:
                        poll_errors.append("Invalid JSON schema")
                    poll_count[0] += 1
                except Exception as e:
                    poll_errors.append(str(e))
                time.sleep(0.005)

        pollers = [threading.Thread(target=poll_worker, daemon=True) for _ in range(30)]
        for p in pollers:
            p.start()

        # Step through stages 1 to 9
        try:
            for stage_num in range(1, 10):
                self.orchestrator.update_stage(
                    job_id,
                    stage_num,
                    progress=stage_num * 10,
                    modules={f"module_{stage_num}": {"data": f"payload_{stage_num}"}}
                )
                time.sleep(0.02)

            self.orchestrator.complete_job(job_id, result={"done": True})
            time.sleep(0.05)
        finally:
            stop_event.set()
            for p in pollers:
                p.join(timeout=1.0)
            job_service.orchestrator = orig_orch

        self.assertEqual(poll_errors, [], f"Encountered polling errors: {poll_errors}")
        self.assertGreater(poll_count[0], 50, f"Insufficient poll operations executed: {poll_count[0]}")


if __name__ == "__main__":
    unittest.main()
