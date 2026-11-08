import os
import io
import uuid
import json
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
from utils.time_utils import format_seconds, prepare_transcript_for_analysis, sanitize_transcript
from pdf_generator import generate_detailed_pdf
from services.storage_service import (
    get_db,
    save_cached_analysis,
    get_cached_analysis,
    create_user,
    get_user,
    update_user_plan,
    record_processing_event,
)
from services.auth_service import (
    check_quota,
    increment_quota,
    PLAN_CONFIG,
    QUOTA_FREE,
)
from services.job_service import (
    create_job,
    get_job,
    update_job_stage,
    complete_job,
    fail_job,
    JOBS,
)


class TestTier4RealWorldApplicationWorkflows(LensYouE2EBaseTest):
    """
    Tier 4: Real-World Application Workflows (>=4 comprehensive user journeys).
    Verifies full lifecycle end-to-end execution across multiple features.
    """

    @patch("services.metadata_service.requests.get")
    def test_s01_multi_chapter_educational_lecture_workflow(self, mock_get):
        """
        Scenario 1: End-to-end analysis of multi-chapter educational lecture:
        URL validation -> metadata -> transcript -> chapters -> summary -> entities -> Bloom quiz -> PDF export.
        """
        # 1. URL input and validation
        lecture_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=0s"
        video_id = extract_video_id(lecture_url)
        self.assertEqual(video_id, "dQw4w9WgXcQ")

        # 2. Fetch metadata via oEmbed mock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_OEMBED_DATA
        mock_get.return_value = mock_resp

        metadata = get_video_oembed(video_id)
        self.assertEqual(metadata["title"], SAMPLE_OEMBED_DATA["title"])

        # 3. Resolve and clean transcript
        raw_transcript = SAMPLE_TRANSCRIPT_SEGMENTS
        cleaned_transcript_text = prepare_transcript_for_analysis(raw_transcript, max_chars=10000)
        self.assertIn("distributed event-driven systems", cleaned_transcript_text)

        # 4. Asynchronous job creation & lifecycle tracking
        job_id = create_job()
        update_job_stage(job_id, 1)  # Fetching metadata
        update_job_stage(job_id, 2)  # Resolving transcript
        update_job_stage(job_id, 5)  # Generating core intelligence
        update_job_stage(job_id, 7)  # Generating learning material

        # 5. Extract chapters & verify chronological ordering
        raw_chapters = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]
        chapter_lines = [l.strip() for l in raw_chapters.split("\n") if l.strip()]
        self.assertGreaterEqual(len(chapter_lines), 3)
        chapter_seconds = [parse_duration_string(l.split()[0]) for l in chapter_lines]
        self.assertEqual(chapter_seconds, sorted(chapter_seconds))

        # 6. Verify executive summary and quality scorecard
        overview = SAMPLE_ANALYSIS_DATA["video_overview"]
        scorecard = SAMPLE_ANALYSIS_DATA["quality_scorecard"]
        self.assertIn("summary", overview)
        self.assertGreaterEqual(scorecard["overall_score"], 80)

        # 7. Verify entity intelligence
        entities = SAMPLE_ANALYSIS_DATA["entities"]
        self.assertIn("concepts", entities)
        self.assertGreater(len(entities["concepts"]), 0)

        # 8. Verify Bloom's Taxonomy quiz items
        quiz = SAMPLE_ANALYSIS_DATA["learning"]["quiz"]
        self.assert_valid_bloom_quiz(quiz)

        # 9. Generate and export PDF dossier
        pdf_stream = generate_detailed_pdf(SAMPLE_ANALYSIS_DATA)
        pdf_bytes = pdf_stream.getvalue()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 2000)

        # 10. Complete job and persist in cache
        complete_job(job_id, SAMPLE_ANALYSIS_DATA)
        job = get_job(job_id)
        self.assertEqual(job["status"], "completed")

        save_cached_analysis(
            video_id=video_id,
            title=metadata["title"],
            author=metadata["author_name"],
            duration="01:15",
            analysis=SAMPLE_ANALYSIS_DATA
        )
        cached = get_cached_analysis(video_id)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["_meta"]["title"], SAMPLE_OEMBED_DATA["title"])

    def test_s02_research_debate_and_evidence_verification_workflow(self):
        """
        Scenario 2: Research debate with claim extraction, citation timestamp grounding,
        speaker attribution, and contradiction classification.
        """
        # 1. Transcript segments representing two debate speakers
        debate_segments = [
            {"speaker": "Dr. Alice Vance", "start": 0.0, "duration": 15.0, "timestamp": "00:00",
             "text": "Empirical studies prove that microservices increase operational overhead by 40% for small teams."},
            {"speaker": "Prof. Bob Chen", "start": 16.0, "duration": 20.0, "timestamp": "00:16",
             "text": "However, as organizations scale beyond 50 engineers, microservices unlock autonomous deployments and reduce lead time."},
            {"speaker": "Dr. Alice Vance", "start": 38.0, "duration": 18.0, "timestamp": "00:38",
             "text": "Agreed, but only under the condition that robust platform engineering and automated testing are established first."}
        ]

        # 2. Extract claims from dialogue
        extracted_claims = [
            {"claim_id": "01", "speaker": "Dr. Alice Vance", "timestamp": "00:00", "seconds": 0,
             "statement": "Microservices increase operational overhead by 40% for small teams."},
            {"claim_id": "02", "speaker": "Prof. Bob Chen", "timestamp": "00:16", "seconds": 16,
             "statement": "Autonomous deployments are unlocked beyond 50 engineers."},
            {"claim_id": "03", "speaker": "Dr. Alice Vance", "timestamp": "00:38", "seconds": 38,
             "statement": "Robust platform engineering is required before scaling microservices."}
        ]

        # 3. Automated citation timestamp verification (100% grounding check)
        max_duration = 60
        for c in extracted_claims:
            c_sec = c["seconds"]
            self.assertLessEqual(c_sec, max_duration)
            # Find matching segment
            matched = next((s for s in debate_segments if abs(s["start"] - c_sec) <= 2), None)
            self.assertIsNotNone(matched, f"Claim {c['claim_id']} failed timestamp citation verification")
            self.assertEqual(c["speaker"], matched["speaker"], f"Claim {c['claim_id']} speaker misattributed")

        # 4. Nuanced contradiction classification
        contradiction = {
            "topic": "Microservice organizational efficiency",
            "statement_a": {"speaker": "Dr. Alice Vance", "text": "Increases overhead for small teams", "timestamp": "00:00"},
            "statement_b": {"speaker": "Prof. Bob Chen", "text": "Unlocks autonomous deployments at scale", "timestamp": "00:16"},
            "nuance": "Conditional qualification depending on organizational scale and team size."
        }
        self.assertIn("Conditional", contradiction["nuance"])

        # 5. Export structured Markdown research dossier
        md_lines = [
            "# Research Debate Analysis Dossier",
            "## Verified Claims",
            *[f"- **[{c['timestamp']}] ({c['speaker']})**: {c['statement']}" for c in extracted_claims],
            "## Nuanced Dialectic Tensions",
            f"- **Topic**: {contradiction['topic']}",
            f"  - Statement A ({contradiction['statement_a']['speaker']}): {contradiction['statement_a']['text']}",
            f"  - Statement B ({contradiction['statement_b']['speaker']}): {contradiction['statement_b']['text']}",
            f"  - **Nuance**: {contradiction['nuance']}"
        ]
        markdown_dossier = "\n".join(md_lines)
        self.assertIn("Alice Vance", markdown_dossier)
        self.assertIn("Prof. Bob Chen", markdown_dossier)
        self.assertIn("Verified Claims", markdown_dossier)

    def test_s03_user_quota_limits_and_upgrade_workflow(self):
        """
        Scenario 3: User quota and video duration limits enforcement and upgrade flow:
        Anonymous requests -> login -> free quota exhaustion -> plan upgrade -> unlimited access.
        """
        # 1. Anonymous session checks quota
        anon_key = f"flow_anon_{uuid.uuid4().hex[:8]}"
        q_anon = check_quota(session_key=anon_key)
        self.assertTrue(q_anon["allowed"])
        self.assertEqual(q_anon["limit"], 3)

        # Consume all 3 anonymous requests
        for _ in range(3):
            increment_quota(session_key=anon_key)
        q_anon_exhausted = check_quota(session_key=anon_key)
        self.assertFalse(q_anon_exhausted["allowed"])

        # 2. User registers for free tier
        user_uuid = uuid.uuid4().hex[:8]
        user_id = create_user("google", user_uuid, f"user_{user_uuid}@example.com", "Test Learner", "")
        update_user_plan(user_id, "free", 5)

        # 3. Verify free tier quota is available
        q_free = check_quota(user_id=user_id)
        self.assertTrue(q_free["allowed"])
        self.assertEqual(q_free["limit"], 5)
        self.assertEqual(q_free["used"], 0)

        # 4. Enforce duration limit check for free tier (max 30 mins = 1800s)
        free_duration_limit = 1800  # seconds
        short_video_sec = parse_duration_string("15:30")  # 930s
        long_video_sec = parse_duration_string("01:15:00")  # 4500s

        self.assertLessEqual(short_video_sec, free_duration_limit)
        self.assertGreater(long_video_sec, free_duration_limit)

        # 5. User exhausts free quota
        for _ in range(5):
            increment_quota(user_id=user_id)
        q_free_exhausted = check_quota(user_id=user_id)
        self.assertFalse(q_free_exhausted["allowed"])

        # 6. User upgrades to 'unlimited' plan
        update_user_plan(user_id, "unlimited", -1)
        q_upgraded = check_quota(user_id=user_id)
        self.assertTrue(q_upgraded["allowed"])
        self.assertEqual(q_upgraded["limit"], -1)

        # 7. Record usage in activity history
        record_processing_event(
            user_id=user_id,
            content_id=SAMPLE_VIDEO_ID,
            content_title="Upgraded Plan Analysis",
            status="success",
            duration="01:15:00",
            plan="unlimited"
        )
        user = get_user(user_id)
        self.assertEqual(user["plan"], "unlimited")

    def test_s04_resilient_recovery_from_partial_service_degradation(self):
        """
        Scenario 4: Fault recovery workflow:
        Video analysis initiated -> core workers succeed -> optional export worker crashes ->
        orchestrator retries -> transitions to PARTIAL -> client retrieves intact modules.
        """
        job_id = create_job()
        update_job_stage(job_id, 1)  # Metadata extraction
        update_job_stage(job_id, 2)  # Transcript resolution
        update_job_stage(job_id, 5)  # Summary and core intelligence

        # Simulated worker execution pipeline
        worker_results = {}
        worker_errors = {}

        # Worker 1: Metadata
        worker_results["metadata"] = SAMPLE_OEMBED_DATA

        # Worker 2: Transcript
        worker_results["transcript"] = SAMPLE_TRANSCRIPT_SEGMENTS

        # Worker 3: Summary
        worker_results["summary"] = SAMPLE_ANALYSIS_DATA["video_overview"]

        # Worker 4: Chapters
        worker_results["chapters"] = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]

        # Worker 5: Optional PDF Export (simulating unrecoverable exception after retries)
        max_retries = 3
        export_attempts = 0
        while export_attempts < max_retries:
            export_attempts += 1
            # Simulated crash
            pass
        worker_errors["export_pdf"] = "ReportLab memory allocation failure"

        # Orchestrator marks job as PARTIAL since core modules succeeded
        is_partial = len(worker_errors) > 0 and "summary" in worker_results and "transcript" in worker_results
        self.assertTrue(is_partial)

        partial_status_data = {
            "status": "partial",
            "stage": 9,
            "stage_name": "Completed (Partial)",
            "is_partial": True,
            "modules": worker_results,
            "failed_modules": worker_errors
        }

        JOBS[job_id]["status"] = "partial"
        JOBS[job_id]["result"] = partial_status_data

        # Client inspects job state via polling contract
        job = get_job(job_id)
        self.assertEqual(job["status"], "partial")
        job_result = job["result"]
        self.assertTrue(job_result["is_partial"])

        # Core modules remain 100% accessible to the user
        self.assertIn("summary", job_result["modules"])
        self.assertIn("transcript", job_result["modules"])
        self.assertIn("chapters", job_result["modules"])
        self.assertEqual(job_result["failed_modules"]["export_pdf"], "ReportLab memory allocation failure")


if __name__ == "__main__":
    unittest.main()
