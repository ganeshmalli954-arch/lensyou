"""
test_m3_verification.py
Comprehensive unit & integration test suite for Milestone 3 (Grounded AI Evidence Verification & Guardrails).

Covers:
- Feature F10: Automated Citation & Timestamp Grounding Engine (verify_grounded_claims)
- Feature F11: Dynamic Speaker Attribution (attribute_speaker_to_claim)
- Feature F12: Bloom's Taxonomy Schema Validator (validate_bloom_quiz, validate_flashcards)
- Feature F13: Nuanced Contradiction Classifier (classify_contradictions)
- Integration: Claim Worker, Learning Worker, and Orchestrator Stage 8 (VALIDATING)
"""

import unittest
import uuid
from unittest.mock import patch, MagicMock

from services.verification_service import (
    verify_grounded_claims,
    attribute_speaker_to_claim,
    validate_bloom_quiz,
    validate_flashcards,
    classify_contradictions,
    clean_option_text,
    normalize_bloom_level,
    extract_claim_text,
)
from services.workers.claim_worker import run_claim_worker
from services.workers.learning_worker import run_learning_worker
from services.orchestrator import AsyncJobOrchestrator, STATUS_VALIDATING, STATUS_COMPLETED, STATUS_PARTIAL
from services.storage_service import init_relational_db, get_analysis_job


class TestM3VerificationGroundedClaims(unittest.TestCase):
    """Tests for F10 (Grounded Claims Verification Engine) and F11 (Dynamic Speaker Attribution)."""

    def setUp(self):
        self.segments = [
            {"speaker": "Leslie Lamport", "start": 12.0, "duration": 8.0, "timestamp": "00:12",
             "text": "A distributed system is one in which the failure of a computer you didn't even know existed can render your own computer unusable."},
            {"speaker": "Prof. Bob Chen", "start": 25.0, "duration": 10.0, "timestamp": "00:25",
             "text": "As organizations scale beyond 50 engineers, microservices unlock autonomous deployments and reduce lead time."},
            {"speaker": "Dr. Alice Vance", "start": 40.0, "duration": 15.0, "timestamp": "00:40",
             "text": "Empirical studies prove that microservices increase operational overhead by 40% for small teams."},
            {"speaker": "Host", "start": 60.0, "duration": 10.0, "timestamp": "01:00",
             "text": ">> Dr. Carol King: Furthermore, automated testing is essential before embarking on architectural decomposition."}
        ]
        self.channel_author = "Tech Talks Central"

    def test_exact_boundary_zero_and_max_duration(self):
        """Claims at 00:00 and exact video duration are correctly grounded within bounds."""
        raw_claims = [
            {"statement": "Opening thesis at the start of video", "seconds": 0, "timestamp": "00:00"},
            {"statement": "Closing remark at exact end of video", "seconds": 120, "timestamp": "02:00"},
            {"statement": "Future claim with out of bounds timestamp", "seconds": 500, "timestamp": "08:20"}
        ]
        grounded, stats = verify_grounded_claims(raw_claims, self.segments, max_duration=120, channel_author=self.channel_author)

        self.assertEqual(len(grounded), 3)
        self.assertEqual(grounded[0]["seconds"], 0.0)
        self.assertEqual(grounded[0]["timestamp"], "00:00")
        self.assertEqual(grounded[1]["seconds"], 120.0)
        self.assertEqual(grounded[1]["timestamp"], "02:00")
        # Out-of-bounds claim must be strictly clamped to max_duration
        self.assertLessEqual(grounded[2]["seconds"], 120.0)
        self.assertGreaterEqual(grounded[2]["seconds"], 0.0)

    def test_multi_segment_keyword_matching_and_scoring(self):
        """Claims align to transcript segments using token overlap and bigram matching."""
        raw_claims = [
            {"statement": "Autonomous deployments are unlocked beyond 50 engineers with microservices."},
            {"statement": "Failure of an unknown computer can render your system unusable in distributed architectures."}
        ]
        grounded, stats = verify_grounded_claims(raw_claims, self.segments, max_duration=120, channel_author=self.channel_author)

        # First claim should match Prof. Bob Chen (around 25s)
        self.assertAlmostEqual(grounded[0]["seconds"], 25.0, delta=5.0)
        self.assertEqual(grounded[0]["speaker"], "Prof. Bob Chen")
        self.assertTrue(grounded[0]["verified"])
        self.assertGreaterEqual(grounded[0]["confidence_score"], 0.50)

        # Second claim should match Leslie Lamport (around 12s)
        self.assertAlmostEqual(grounded[1]["seconds"], 12.0, delta=5.0)
        self.assertEqual(grounded[1]["speaker"], "Leslie Lamport")
        self.assertTrue(grounded[1]["verified"])
        self.assertGreaterEqual(grounded[1]["confidence_score"], 0.50)

    def test_dynamic_speaker_attribution_prevents_blanket_author(self):
        """Quotes are dynamically attributed to genuine speakers and not defaulted to channel author."""
        claim_with_author = {
            "statement": "A distributed system is one in which the failure of a computer you didn't even know existed...",
            "speaker": self.channel_author,  # Erroneous author default
            "timestamp": "00:12",
            "seconds": 12
        }
        grounded, _ = verify_grounded_claims([claim_with_author], self.segments, max_duration=120, channel_author=self.channel_author)

        # Speaker must be corrected to Leslie Lamport from segment metadata
        self.assertEqual(grounded[0]["speaker"], "Leslie Lamport")
        self.assertNotEqual(grounded[0]["speaker"], self.channel_author)
        self.assertTrue(grounded[0]["speaker_verified"])

    def test_in_text_dialogue_cue_speaker_detection(self):
        """Dialogue cue '>> Dr. Carol King:' inside segment text is parsed for speaker attribution."""
        claim = {
            "statement": "Automated testing is essential before architectural decomposition.",
            "timestamp": "01:00",
            "seconds": 60
        }
        grounded, _ = verify_grounded_claims([claim], self.segments, max_duration=120, channel_author=self.channel_author)

        self.assertEqual(grounded[0]["speaker"], "Dr. Carol King")
        self.assertTrue(grounded[0]["speaker_verified"])

    def test_empty_claims_and_empty_segments_graceful(self):
        """Empty claims list or empty segments list do not raise exceptions."""
        grounded, stats = verify_grounded_claims([], self.segments, max_duration=100)
        self.assertEqual(grounded, [])
        self.assertEqual(stats["total_claims"], 0)
        self.assertEqual(stats["grounding_rate"], 1.0)

        raw_claims = [{"statement": "Some orphaned claim"}]
        grounded_no_segs, stats_no_segs = verify_grounded_claims(raw_claims, [], max_duration=100)
        self.assertEqual(len(grounded_no_segs), 1)
        self.assertEqual(grounded_no_segs[0]["seconds"], 0.0)


class TestM3VerificationBloomQuizAndFlashcards(unittest.TestCase):
    """Tests for F12 (Bloom's Taxonomy Quiz & Flashcard Schema Guardrails)."""

    def test_validate_bloom_quiz_valid_items(self):
        """Well-formed Bloom quiz items pass validation with normalized tiers."""
        quiz = [
            {
                "question": "What is the primary benefit of asynchronous queuing in microservice architectures?",
                "options": ["A. Buffering requests", "B. Synchronous blocking", "C. Dropping messages", "D. Increasing lock contention"],
                "correct_index": 0,
                "bloom_level": "understand",
                "explanation": "Queuing decouples producers from consumers via buffering."
            },
            {
                "question": "How would you design a circuit breaker to prevent cascade failures?",
                "options": ["1. Monitor failure rate", "2. Ignore all timeouts", "3. Restart server on error", "4. Block all traffic permanently"],
                "correct_index": "0",  # String 0
                "bloom_level": "Apply",
                "explanation": "Circuit breakers open when failure threshold is reached."
            }
        ]
        validated, all_valid = validate_bloom_quiz(quiz)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["bloom_level"], "Understand")
        self.assertEqual(validated[1]["bloom_level"], "Apply")
        self.assertEqual(validated[0]["options"][0], "Buffering requests")  # Prefix 'A. ' stripped
        self.assertEqual(validated[1]["options"][0], "Monitor failure rate")  # Prefix '1. ' stripped
        self.assertEqual(validated[1]["correct_index"], 0)

    def test_validate_bloom_quiz_letter_option_coercion(self):
        """Option letters 'A', 'B', 'C', 'D' in correct_index are cleanly coerced to integers 0..3."""
        quiz = [{
            "question": "Which protocol guarantees at-least-once message delivery semantics?",
            "options": ["UDP", "AMQP with acknowledgments", "Raw ICMP", "SNMP traps"],
            "correct_index": "B",
            "bloom_level": "Analyze"
        }]
        validated, all_valid = validate_bloom_quiz(quiz)
        self.assertTrue(all_valid)
        self.assertEqual(validated[0]["correct_index"], 1)

    def test_validate_bloom_quiz_filters_malformed_items(self):
        """Quiz questions with short stems, != 4 options, duplicate options, or invalid Bloom tiers are rejected."""
        malformed_quiz = [
            # Short stem <= 5 chars
            {"question": "Why?", "options": ["A", "B", "C", "D"], "correct_index": 0, "bloom_level": "Understand"},
            # Only 3 options
            {"question": "Identify valid queuing tech?", "options": ["Kafka", "RabbitMQ", "SQS"], "correct_index": 0, "bloom_level": "Understand"},
            # Empty option whitespace
            {"question": "Identify valid queuing tech?", "options": ["Kafka", "   ", "SQS", "ActiveMQ"], "correct_index": 0, "bloom_level": "Understand"},
            # Duplicate options
            {"question": "Identify valid queuing tech?", "options": ["Kafka", "Kafka", "SQS", "ActiveMQ"], "correct_index": 0, "bloom_level": "Understand"},
            # Out of bounds correct_index
            {"question": "Identify valid queuing tech?", "options": ["Kafka", "RabbitMQ", "SQS", "ActiveMQ"], "correct_index": 5, "bloom_level": "Understand"},
            # Invalid Bloom cognitive level
            {"question": "Identify valid queuing tech?", "options": ["Kafka", "RabbitMQ", "SQS", "ActiveMQ"], "correct_index": 0, "bloom_level": "RandomGuessingLevel"}
        ]
        validated, all_valid = validate_bloom_quiz(malformed_quiz)
        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 0)

    def test_validate_flashcards_valid_and_filters(self):
        """Flashcards require valid front, back, distinctness, and concept tag."""
        cards = [
            {"front": "CAP Theorem", "back": "Consistency, Availability, and Partition Tolerance trade-off.", "concept": "Distributed Systems"},
            {"front": "Identical", "back": "Identical"},  # Duplicate front and back -> reject
            {"front": "A", "back": "Too short front"},    # Too short -> reject
            {"front": "Valid Front Term", "back": "Valid Back Definition"}  # Default concept applied
        ]
        validated, all_valid = validate_flashcards(cards)
        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["concept"], "Distributed Systems")
        self.assertEqual(validated[1]["concept"], "Core Concept")


class TestM3VerificationContradictionClassifier(unittest.TestCase):
    """Tests for F13 (Nuanced Contradiction Taxonomy Classifier)."""

    def test_conditional_qualification_classification(self):
        """Contradictions involving trade-offs, scales, or conditional constraints are classified as CONDITIONAL_QUALIFICATION."""
        contradictions = [
            {
                "topic": "Microservices vs Monolith scalability",
                "statement_a": {"speaker": "Dr. Alice Vance", "text": "Increases overhead for small teams", "timestamp": "00:00"},
                "statement_b": {"speaker": "Prof. Bob Chen", "text": "Unlocks autonomous deployments at scale", "timestamp": "00:16"},
                "nuance": "Conditional qualification depending on organizational scale and team size."
            },
            {
                "topic": "Synchronous vs Asynchronous execution cost",
                "statement_a": {"text": "Synchronous calls provide simple immediate consistency.", "timestamp": "00:12"},
                "statement_b": {"text": "Asynchronous architectures provide greater availability despite eventual consistency.", "timestamp": "00:20"},
                "nuance": "Trade-off between immediacy of consistency and resilience under high concurrent load."
            }
        ]
        classified = classify_contradictions(contradictions)
        self.assertEqual(len(classified), 2)
        self.assertEqual(classified[0]["classification"], "CONDITIONAL_QUALIFICATION")
        self.assertFalse(classified[0]["is_logical_conflict"])
        self.assertEqual(classified[1]["classification"], "CONDITIONAL_QUALIFICATION")
        self.assertFalse(classified[1]["is_logical_conflict"])

    def test_temporal_evolution_classification(self):
        """Contradictions reflecting chronological shifts or evolving paradigms are classified as TEMPORAL_EVOLUTION."""
        contradictions = [
            {
                "topic": "Data persistence paradigm",
                "statement_a": {"text": "Historically, all relational schemas relied on monolithic disk storage.", "timestamp": "02:10"},
                "statement_b": {"text": "Modern distributed architectures have evolved to tiered cloud object stores.", "timestamp": "34:15"},
                "nuance": "Evolution in storage technology over the past decade."
            }
        ]
        classified = classify_contradictions(contradictions)
        self.assertEqual(classified[0]["classification"], "TEMPORAL_EVOLUTION")
        self.assertFalse(classified[0]["is_logical_conflict"])

    def test_perspective_divergence_classification(self):
        """Contradictions between distinct speakers or viewpoints are classified as PERSPECTIVE_DIVERGENCE."""
        contradictions = [
            {
                "topic": "Code testing methodology",
                "statement_a": {"speaker": "Speaker Alpha", "text": "Test-driven development is non-negotiable for enterprise stability."},
                "statement_b": {"speaker": "Speaker Beta", "text": "Type-driven design and end-to-end integration tests render unit TDD redundant."},
                "nuance": "Different engineering viewpoints between academic theory and practical startup velocity."
            }
        ]
        classified = classify_contradictions(contradictions)
        self.assertEqual(classified[0]["classification"], "PERSPECTIVE_DIVERGENCE")
        self.assertFalse(classified[0]["is_logical_conflict"])

    def test_direct_contradiction_fallback(self):
        """Contradictions with raw opposing claims and no nuance or conditionality are classified as DIRECT_CONTRADICTION."""
        contradictions = [
            {
                "topic": "System performance",
                "statement_a": {"text": "The cache hit rate was 99% during benchmark testing."},
                "statement_b": {"text": "The cache missed all requests during benchmark testing."},
                "nuance": "Direct mutually incompatible numbers."
            }
        ]
        classified = classify_contradictions(contradictions)
        self.assertEqual(classified[0]["classification"], "DIRECT_CONTRADICTION")
        self.assertTrue(classified[0]["is_logical_conflict"])


class TestM3WorkerAndOrchestratorIntegration(unittest.TestCase):
    """Tests integration of verification logic into Workers and Orchestrator Stage 8 (VALIDATING)."""

    def setUp(self):
        init_relational_db()
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=2, max_task_workers=4)

    def tearDown(self):
        self.orchestrator.shutdown(wait=False)

    def test_claim_worker_runs_grounding_and_contradiction_classification(self):
        """run_claim_worker invokes verification service and returns grounded claims + classified contradictions."""
        segments = [
            {"speaker": "Leslie Lamport", "start": 10.0, "duration": 5.0, "text": "Distributed systems require consensus algorithms."}
        ]
        metadata = {"duration_seconds": 60, "author": "Tech Channel"}
        raw_analysis = {
            "claims": [
                {"claim": "Distributed systems require consensus algorithms.", "seconds": 10, "timestamp": "00:10"}
            ],
            "contradictions": [
                {
                    "topic": "Consensus cost",
                    "statement_a": {"text": "Consensus is required."},
                    "statement_b": {"text": "Consensus can be avoided in CRDTs."},
                    "nuance": "Trade-off depending on consistency model."
                }
            ]
        }
        res = run_claim_worker(segments, metadata, raw_analysis=raw_analysis)
        self.assertTrue(res["success"])
        data = res["data"]
        self.assertIn("verification_stats", data)
        self.assertEqual(data["claims"][0]["speaker"], "Leslie Lamport")
        self.assertEqual(data["contradictions"][0]["classification"], "CONDITIONAL_QUALIFICATION")

    def test_learning_worker_runs_quiz_and_flashcard_validation(self):
        """run_learning_worker invokes Bloom taxonomy and flashcard validators."""
        raw_analysis = {
            "learning": {
                "key_definitions": [{"term": "Consensus", "definition": "Agreement on shared state."}],
                "study_notes": [{"title": "Paxos", "content": "Consensus protocol"}],
                "flashcards": [
                    {"front": "Paxos", "back": "Consensus algorithm"}
                ],
                "quiz": [
                    {
                        "question": "What problem does Paxos solve in distributed computing?",
                        "options": ["A. Consensus", "B. Routing", "C. Rendering", "D. Compression"],
                        "correct_index": 0,
                        "bloom_level": "understand"
                    }
                ]
            }
        }
        res = run_learning_worker([], {}, raw_analysis=raw_analysis)
        self.assertTrue(res["success"])
        data = res["data"]
        self.assertEqual(len(data["flashcards"]), 1)
        self.assertEqual(len(data["quizzes"]), 1)
        self.assertEqual(data["quizzes"][0]["options"][0], "Consensus")  # Cleaned prefix

    def test_orchestrator_stage_8_validating_pipeline_execution(self):
        """Orchestrator executes Stage 8 (VALIDATING) and attaches complete verification metadata."""
        vid = f"orch_v_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        segments = [
            {"speaker": "Leslie Lamport", "start": 0.0, "duration": 15.0, "timestamp": "00:00",
             "text": "A distributed system is one in which the failure of a computer you didn't even know existed can render your own computer unusable."},
            {"speaker": "Prof. Bob Chen", "start": 16.0, "duration": 20.0, "timestamp": "00:16",
             "text": "Microservices unlock autonomous deployments and reduce lead time."}
        ]

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai:

            from services.workers import WorkerResult
            mock_meta.return_value = WorkerResult(
                module="metadata", success=True,
                data={"title": "M3 Verification Lecture", "author": "Host Channel", "duration": "01:00", "duration_seconds": 60, "thumbnail_url": ""}
            )
            mock_trans.return_value = WorkerResult(
                module="transcript", success=True,
                data={"segments": segments, "formatted_duration": "01:00", "duration_seconds": 60, "ui_sample": []}
            )
            mock_ai.return_value = {
                "video_overview": {"title": "M3 Verification Lecture", "summary": "Full overview"},
                "chapters": [{"title": "Introduction", "start_time": "00:00"}],
                "creator_repurposing": {"youtube_chapters_raw": "00:00 Introduction"},
                "claims": [
                    {"statement": "Distributed systems suffer from obscure failures.", "seconds": 0, "timestamp": "00:00"},
                    {"statement": "Microservices reduce lead time.", "seconds": 16, "timestamp": "00:16"}
                ],
                "learning": {
                    "quiz": [
                        {
                            "question": "How do microservices reduce deployment lead times across teams?",
                            "options": ["Autonomous deployments", "Synchronous blocking", "Monolith builds", "Manual deploys"],
                            "correct_index": 0,
                            "bloom_level": "understand"
                        }
                    ],
                    "flashcards": [
                        {"front": "Autonomous Deployments", "back": "Independent service releases"}
                    ]
                },
                "contradictions": [
                    {
                        "topic": "Microservices vs Monoliths",
                        "statement_a": {"text": "Increases overhead"},
                        "statement_b": {"text": "Reduces lead time"},
                        "nuance": "Trade-off depending on organizational scale."
                    }
                ]
            }

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], STATUS_COMPLETED)
        result = job["result"]

        # Check verification metadata attached in Stage 8
        self.assertIn("_verification", result)
        v_meta = result["_verification"]
        self.assertEqual(v_meta["status"], "COMPLETED")
        self.assertEqual(v_meta["claim_verification_rate"], 1.0)
        self.assertEqual(v_meta["bloom_validity_rate"], 1.0)
        self.assertEqual(v_meta["claims_verified_count"], 2)
        self.assertEqual(v_meta["quiz_questions_validated"], 1)
        self.assertEqual(v_meta["contradictions_classified_count"], 1)
        self.assertIn("CONDITIONAL_QUALIFICATION", v_meta["contradiction_breakdown"])
        self.assertEqual(v_meta["contradiction_breakdown"]["CONDITIONAL_QUALIFICATION"], 1)

        # Check speaker attribution corrected from transcript
        claims = result["claims"]
        self.assertEqual(claims[0]["speaker"], "Leslie Lamport")
        self.assertEqual(claims[1]["speaker"], "Prof. Bob Chen")


if __name__ == "__main__":
    unittest.main()
