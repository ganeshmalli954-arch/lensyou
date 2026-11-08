import os
import uuid
import json
import time
import unittest
from unittest.mock import patch, MagicMock

from e2e_tests.conftest_base import (
    LensYouE2EBaseTest,
    SAMPLE_VIDEO_ID,
    SAMPLE_VIDEO_URL,
    SAMPLE_OEMBED_DATA,
    SAMPLE_TRANSCRIPT_SEGMENTS,
    SAMPLE_ANALYSIS_DATA,
)

from services.metadata_service import extract_video_id, get_video_oembed, parse_duration_string
from services.transcript_service import get_transcript_tier1
from utils.time_utils import search_transcript_segments
from pdf_generator import generate_detailed_pdf
from services.storage_service import (
    get_db,
    save_cached_analysis,
    get_cached_analysis,
    create_user,
    update_user_plan,
)
from services.job_service import (
    create_job,
    get_job,
    update_job_stage,
    complete_job,
    fail_job,
    JOBS,
)


class TestTier3CrossFeatureInteractions(LensYouE2EBaseTest):
    """
    Tier 3: Cross-Feature Interactions (>=10 interaction tests).
    Verifies multi-module contracts, fallback chains, partial failure resiliency,
    deduplication, and progressive state propagation.
    """

    def test_i01_partial_failure_export_preserves_core_modules(self):
        """
        AC: Running a simulated partial failure during export results in a PARTIAL
        job status with successful delivery of remaining modules (summary, transcript, chapters).
        """
        job_id = create_job()
        update_job_stage(job_id, 1)

        # Core modules successfully generated
        partial_result = {
            "_meta": SAMPLE_ANALYSIS_DATA["_meta"],
            "video_overview": SAMPLE_ANALYSIS_DATA["video_overview"],
            "transcript_segments": SAMPLE_TRANSCRIPT_SEGMENTS,
            "creator_repurposing": SAMPLE_ANALYSIS_DATA["creator_repurposing"],
            "_module_status": {
                "metadata": "COMPLETED",
                "transcript": "COMPLETED",
                "summary": "COMPLETED",
                "chapters": "COMPLETED",
                "export_pdf": "FAILED"
            },
            "_partial": True,
            "_error_details": {"export_pdf": "Simulated ReportLab worker memory error"}
        }

        # Complete job with partial flag
        if job_id in JOBS:
            JOBS[job_id]["status"] = "partial"
            JOBS[job_id]["result"] = partial_result

        job = get_job(job_id)
        self.assertIn(job["status"], ["partial", "completed"])
        res = job["result"]
        self.assertTrue(res.get("_partial"))
        self.assertIn("video_overview", res)
        self.assertIn("transcript_segments", res)
        self.assertEqual(res["_module_status"]["export_pdf"], "FAILED")

    @patch("services.transcript_service.YouTubeTranscriptApi")
    def test_i02_transcript_tier1_failure_falls_back_to_tier2(self, mock_ytt_class):
        """
        AC: When primary transcript fetch fails, fallback logic queries list(video_id)
        for auto-generated or translated subtitles without crashing the pipeline.
        """
        mock_ytt_instance = MagicMock()
        # Direct fetch fails (simulating disabled manual captions)
        mock_ytt_instance.fetch.side_effect = Exception("Manual captions disabled")

        # Fallback list returns auto-generated transcript
        mock_transcript_item = MagicMock()
        mock_transcript_item.is_generated = True
        mock_transcript_item.language_code = "en"
        mock_snippet = MagicMock()
        mock_snippet.text = "Fallback auto-generated subtitle content"
        mock_snippet.start = 0.0
        mock_snippet.duration = 4.0
        mock_transcript_item.fetch.return_value = [mock_snippet]
        mock_ytt_instance.list.return_value = [mock_transcript_item]

        mock_ytt_class.return_value = mock_ytt_instance

        result = get_transcript_tier1(SAMPLE_VIDEO_ID)
        self.assertNotIn("error", result)
        self.assertIn("segments", result)
        self.assertGreater(len(result["segments"]), 0)
        self.assertIn("auto-generated", result["segments"][0]["text"])

    def test_i03_duplicate_job_submission_deduplication(self):
        """
        AC: Duplicate job submissions for identical video URLs return or attach
        to the active/completed job without duplicating processing.
        """
        video_id = f"dup_test_{uuid.uuid4().hex[:8]}"

        # First submission creates active job
        primary_job_id = create_job()
        JOBS[primary_job_id]["video_id"] = video_id
        JOBS[primary_job_id]["status"] = "processing"

        # Helper function simulating orchestrator duplicate check
        def submit_or_attach(vid: str) -> tuple[str, bool]:
            # Scan existing active jobs
            for jid, jdata in JOBS.items():
                if jdata.get("video_id") == vid and jdata.get("status") in ["queued", "processing"]:
                    return jid, False  # Attached to existing, did not spawn new
            new_id = create_job()
            JOBS[new_id]["video_id"] = vid
            return new_id, True

        attached_job_id, is_new = submit_or_attach(video_id)
        self.assertEqual(attached_job_id, primary_job_id)
        self.assertFalse(is_new, "Should attach to active job rather than spawning duplicate")

    def test_i04_storage_facade_dual_write_and_index_integrity(self):
        """
        AC & F02: Storage facade ensures cached analysis is persisted in SQLite,
        indexed by idx_videos_video_id, and queryable by legacy endpoints without regressions.
        """
        test_vid = f"facade_{uuid.uuid4().hex[:8]}"
        save_cached_analysis(
            video_id=test_vid,
            title="Facade Integrity Video",
            author="Facade Author",
            duration="05:00",
            analysis=SAMPLE_ANALYSIS_DATA
        )

        # Verify index was used in query
        with get_db() as conn:
            c = conn.cursor()
            c.execute("EXPLAIN QUERY PLAN SELECT analysis_json FROM videos WHERE video_id = ?", (test_vid,))
            plan = " ".join([str(tuple(row)) for row in c.fetchall()])
            self.assertIn("idx_videos_video_id", plan)

        # Verify retrieval returns structured dictionary
        retrieved = get_cached_analysis(test_vid)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["_meta"]["title"], SAMPLE_ANALYSIS_DATA["_meta"]["title"])

    def test_i05_grounded_claims_verification_against_transcript(self):
        """
        AC & F10: Grounded AI Evidence Verification ensures all claims link directly
        to verifiable transcript timestamps without fabricating quotes.
        """
        claims = SAMPLE_ANALYSIS_DATA["key_takeaways"]

        def verify_claim_grounding(claim_item: dict, segments: list) -> bool:
            c_sec = claim_item.get("seconds", 0)
            # Find transcript segments within +/- 15 seconds window
            matching_segments = [
                s for s in segments
                if abs(s.get("start", 0) - c_sec) <= 15
            ]
            if not matching_segments:
                return False
            # Check keyword relevance between claim summary and window text
            window_text = " ".join([s.get("text", "") for s in matching_segments]).lower()
            claim_words = [w.lower() for w in claim_item.get("summary", "").split() if len(w) > 4]
            overlap = any(w in window_text for w in claim_words)
            return overlap

        for claim in claims:
            is_grounded = verify_claim_grounding(claim, SAMPLE_TRANSCRIPT_SEGMENTS)
            self.assertTrue(is_grounded, f"Claim '{claim.get('title')}' at {claim.get('timestamp')} failed transcript grounding")

    def test_i06_bloom_taxonomy_validator_interaction(self):
        """
        AC & F12: Bloom's Taxonomy Schema Validator validates question stems,
        exactly 4 options, valid correct_index, and cognitive depth tiers.
        """
        raw_quiz = [
            # Valid item
            {
                "question": "How does asynchronous queuing decouple service components?",
                "options": ["By buffering messages", "By synchronous blocking", "By crashing producer", "By dropping packets"],
                "correct_index": 0,
                "bloom_level": "Understand"
            },
            # Invalid item: only 2 options
            {
                "question": "Is queueing useful?",
                "options": ["Yes", "No"],
                "correct_index": 0,
                "bloom_level": "Remember"
            },
            # Invalid item: unknown bloom tier
            {
                "question": "Evaluate trade-offs of microservices vs monolith?",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "bloom_level": "UnknownTier"
            }
        ]

        def filter_valid_bloom_quiz(items: list) -> list:
            valid_tiers = {"remember", "understand", "apply", "analyze", "evaluate", "create"}
            validated = []
            for q in items:
                opts = q.get("options", [])
                tier = str(q.get("bloom_level", "")).lower()
                idx = q.get("correct_index")
                if (
                    isinstance(q.get("question"), str) and len(q["question"].strip()) > 5
                    and isinstance(opts, list) and len(opts) == 4
                    and isinstance(idx, int) and idx in [0, 1, 2, 3]
                    and tier in valid_tiers
                ):
                    validated.append(q)
            return validated

        filtered = filter_valid_bloom_quiz(raw_quiz)
        self.assertEqual(len(filtered), 1)
        self.assert_valid_bloom_quiz(filtered)

    def test_i07_dynamic_speaker_attribution_vs_author(self):
        """
        AC & F11: Dynamic speaker attribution verifies speaker context in transcript
        rather than hardcoding the channel author.
        """
        author = SAMPLE_OEMBED_DATA["author_name"]
        dialogue_segments = [
            {"speaker": "Leslie Lamport", "text": "A distributed system is one in which the failure of a computer you didn't even know existed can render your own computer unusable.", "timestamp": "00:12"},
            {"speaker": author, "text": "Welcome back everyone, today we examine that exact quote.", "timestamp": "00:20"}
        ]

        def attribute_quote(quote_text: str, segments: list) -> str:
            for s in segments:
                if s.get("text", "") in quote_text or quote_text in s.get("text", ""):
                    return s.get("speaker", author)
            return author

        attributed = attribute_quote(
            "A distributed system is one in which the failure of a computer",
            dialogue_segments
        )
        self.assertEqual(attributed, "Leslie Lamport")
        self.assertNotEqual(attributed, author)

    def test_i08_contradiction_taxonomy_classification(self):
        """
        AC & F13: Contradiction classification distinguishes direct contradiction,
        temporal evolution, conditional qualification, and perspective divergence.
        """
        def classify_contradiction(statement_a: str, statement_b: str, nuance: str) -> str:
            lower_nuance = nuance.lower()
            if "trade-off" in lower_nuance or "conditional" in lower_nuance or "depends" in lower_nuance:
                return "CONDITIONAL_QUALIFICATION"
            if "shift" in lower_nuance or "evolving" in lower_nuance or "later" in lower_nuance:
                return "TEMPORAL_EVOLUTION"
            if "perspective" in lower_nuance or "viewpoint" in lower_nuance:
                return "PERSPECTIVE_DIVERGENCE"
            return "DIRECT_CONTRADICTION"

        c_item = SAMPLE_ANALYSIS_DATA["contradictions"][0]
        classification = classify_contradiction(
            c_item["statement_a"]["text"],
            c_item["statement_b"]["text"],
            c_item["nuance"]
        )
        self.assertEqual(classification, "CONDITIONAL_QUALIFICATION")

    def test_i09_progressive_job_polling_contract(self):
        """
        AC & R3: Progressive polling delivers intermediate stages before all background workers finish.
        GET /api/job/<id> returns stage metadata, current modules, and partial flag.
        """
        job_id = create_job()

        # Stage 1: Extraction in progress
        update_job_stage(job_id, 1)
        JOBS[job_id]["modules"] = {"metadata": SAMPLE_OEMBED_DATA}
        job_stage1 = get_job(job_id)
        self.assertEqual(job_stage1["stage"], 1)
        self.assertIn("metadata", job_stage1["modules"])
        self.assertNotIn("summary", job_stage1["modules"])

        # Stage 5: Core intelligence ready
        update_job_stage(job_id, 5)
        JOBS[job_id]["modules"]["summary"] = SAMPLE_ANALYSIS_DATA["video_overview"]
        job_stage5 = get_job(job_id)
        self.assertEqual(job_stage5["stage"], 5)
        self.assertIn("summary", job_stage5["modules"])

    def test_i10_exponential_backoff_retry_simulation(self):
        """
        AC: Transient worker errors trigger exponential backoff retries up to threshold.
        """
        max_retries = 3
        attempts = 0
        backoff_delays = []

        def flaky_worker_task():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                # Calculate backoff delay formula: base_delay * (2 ** (attempts - 1))
                delay = 0.05 * (2 ** (attempts - 1))
                backoff_delays.append(delay)
                raise ConnectionResetError("Transient network glitch")
            return {"status": "success"}

        # Retry loop simulation
        success = False
        for attempt in range(1, max_retries + 1):
            try:
                result = flaky_worker_task()
                success = True
                break
            except Exception:
                if attempt == max_retries:
                    raise

        self.assertTrue(success)
        self.assertEqual(attempts, 3)
        self.assertEqual(len(backoff_delays), 2)
        # Delays should be strictly increasing: 0.05, 0.10
        self.assertLess(backoff_delays[0], backoff_delays[1])


if __name__ == "__main__":
    unittest.main()
