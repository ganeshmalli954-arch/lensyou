"""
test_m3_empirical_challenger.py
Empirical Adversarial Stress Test Suite for Milestone 3 (Grounded AI Evidence Verification & Guardrails).

Adversarially challenges:
1. Feature F10 (Citation & Timestamp Grounding Engine):
   - Extreme negative timestamps (clamped strictly to 0.0 / "00:00")
   - Massive out-of-bounds timestamps (clamped strictly to max_duration)
   - Empty claims [], empty segments []
   - Polymorphic & malformed claims (None, numbers, plain strings, empty dicts, null text)
   - Disjoint vocabulary (0 keyword overlap -> maps to valid segment without crash, valid confidence score)
   - Zero and negative max_duration resilience
2. Feature F11 (Dynamic Speaker Attribution):
   - Diarization tags: 'Leslie Lamport', 'Dr. Alice Vance', 'Prof. Bob Chen'
   - WebVTT cues: <v Alice>text</v>, <v Dr. Alice Vance>text</v>
   - Dialogue prefixes: '>> Bob: text', '>> Prof. Bob Chen: text', '[Leslie Lamport]: text'
   - Channel author quote fabrication defense:
     * Unmentioned author neutralized to 'Speaker' / is_verified=False
     * Author mentioned in dialogue text preserved / is_verified=True
     * Segment diarization overrides blanket author default
3. Feature F12 & F13 Guardrails:
   - Bloom Quiz malformed option counts, duplicate options, prefix stripping, letter coercion, invalid tiers
   - Flashcards validation: short, identical, empty
   - Contradiction taxonomy: CONDITIONAL_QUALIFICATION, TEMPORAL_EVOLUTION, PERSPECTIVE_DIVERGENCE, DIRECT_CONTRADICTION
4. Stage 8 Orchestrator Integration:
   - Verification metadata integrity under pipeline execution
"""

import unittest
import uuid
from unittest.mock import patch

from services.verification_service import (
    verify_grounded_claims,
    attribute_speaker_to_claim,
    validate_bloom_quiz,
    validate_flashcards,
    classify_contradictions,
    clean_option_text,
    normalize_bloom_level,
    detect_speaker_from_text,
    parse_claim_seconds,
)
from services.orchestrator import AsyncJobOrchestrator, STATUS_COMPLETED
from services.storage_service import init_relational_db
from services.workers import WorkerResult


class TestM3GroundingBoundaryAdversarial(unittest.TestCase):
    """Extreme boundary conditions and stress tests for verify_grounded_claims (F10)."""

    def setUp(self):
        self.segments = [
            {"speaker": "Leslie Lamport", "start": 10.0, "duration": 10.0, "timestamp": "00:10",
             "text": "A distributed system is one in which the failure of a computer you did not even know existed can render your system unusable."},
            {"speaker": "Prof. Bob Chen", "start": 30.0, "duration": 15.0, "timestamp": "00:30",
             "text": "Microservices reduce deployment lead times and allow team autonomy at scale beyond 50 engineers."},
            {"speaker": "Dr. Alice Vance", "start": 60.0, "duration": 15.0, "timestamp": "01:00",
             "text": "However, operational complexity increases by 40 percent for small development teams."}
        ]
        self.channel_author = "Cloud Architecture Academy"

    def test_negative_timestamps_strictly_clamped_to_zero(self):
        """Negative timestamps in seconds (-50.0, -999.0) and formatted string ('-01:30') clamp strictly to 0.0 / '00:00'."""
        adversarial_claims = [
            {"statement": "Extreme negative numeric seconds", "seconds": -50.0},
            {"statement": "Negative formatted timestamp string", "timestamp": "-01:30"},
            {"statement": "Sub-second negative value", "seconds": -0.05},
            {"statement": "Massive negative value", "seconds": -9999999.0},
            {"statement": "Negative hours formatted string", "timestamp": "-02:15:30"}
        ]
        grounded, stats = verify_grounded_claims(
            adversarial_claims, self.segments, max_duration=3600, channel_author=self.channel_author
        )

        self.assertEqual(len(grounded), len(adversarial_claims))
        for claim in grounded:
            self.assertGreaterEqual(claim["seconds"], 0.0, f"Failed clamping for: {claim}")
            self.assertLessEqual(claim["seconds"], 3600.0)
            self.assertNotEqual(claim["timestamp"][0], "-", f"Timestamp should not be negative: {claim['timestamp']}")

        # Claims without keyword matches fall back to 0.0 / 00:00
        self.assertEqual(grounded[0]["seconds"], 0.0)
        self.assertEqual(grounded[0]["timestamp"], "00:00")
        self.assertEqual(grounded[1]["seconds"], 0.0)
        self.assertEqual(grounded[1]["timestamp"], "00:00")

    def test_massive_timestamps_strictly_clamped_to_max_duration(self):
        """Massive out-of-bounds timestamps (seconds: 9999999, timestamp: '99:59:59') clamp strictly to max_duration."""
        max_dur = 3600
        adversarial_claims = [
            {"statement": "Massive seconds out of bounds", "seconds": 9999999.0},
            {"statement": "High timestamp string", "timestamp": "99:59:59"},
            {"statement": "Slightly over max duration", "seconds": 3605.0},
            {"statement": "Astronomical seconds", "seconds": 1e12}
        ]
        grounded, stats = verify_grounded_claims(
            adversarial_claims, self.segments, max_duration=max_dur, channel_author=self.channel_author
        )

        self.assertEqual(len(grounded), len(adversarial_claims))
        for claim in grounded:
            self.assertLessEqual(claim["seconds"], float(max_dur), f"Exceeded max_duration: {claim}")
            self.assertGreaterEqual(claim["seconds"], 0.0)

        # Claims without keyword match fall back to clamped max_duration (3600.0 / 01:00:00)
        self.assertEqual(grounded[0]["seconds"], 3600.0)
        self.assertEqual(grounded[0]["timestamp"], "01:00:00")

    def test_empty_claims_and_empty_segments_resilience(self):
        """Passing empty claims [] or empty segments [] must return valid structures without crashing."""
        # Empty claims with segments
        grounded, stats = verify_grounded_claims([], self.segments, max_duration=120)
        self.assertEqual(grounded, [])
        self.assertEqual(stats["total_claims"], 0)
        self.assertEqual(stats["grounding_rate"], 1.0)
        self.assertEqual(stats["max_duration_sec"], 120)

        # Claims with empty segments
        raw_claims = [
            {"statement": "Claim without segments", "seconds": 45.0},
            {"statement": "Another claim without segments"}
        ]
        grounded_no_segs, stats_no_segs = verify_grounded_claims(raw_claims, [], max_duration=120)
        self.assertEqual(len(grounded_no_segs), 2)
        self.assertEqual(grounded_no_segs[0]["seconds"], 45.0)
        self.assertEqual(grounded_no_segs[0]["matched_segment_id"], "seg_fallback")
        self.assertEqual(grounded_no_segs[1]["seconds"], 0.0)
        self.assertEqual(grounded_no_segs[1]["matched_segment_id"], "seg_fallback")
        self.assertFalse(grounded_no_segs[1]["verified"])

        # Both empty
        grounded_both_empty, stats_both = verify_grounded_claims([], [], max_duration=120)
        self.assertEqual(grounded_both_empty, [])
        self.assertEqual(stats_both["total_claims"], 0)

    def test_polymorphic_and_malformed_claim_items(self):
        """Non-dict items (None, int, str, list, bool) and claims with empty/null strings process safely."""
        malformed_inputs = [
            None,
            12345,
            "Plain string statement about distributed systems and paxos",
            ["Nested list claim"],
            True,
            {"statement": None},
            {"claim": ""},
            {"statement": "     "},
            {"random_unrelated_key": "some value"}
        ]
        grounded, stats = verify_grounded_claims(malformed_inputs, self.segments, max_duration=120)

        self.assertEqual(len(grounded), len(malformed_inputs))
        for claim in grounded:
            self.assertIsInstance(claim, dict)
            self.assertIn("seconds", claim)
            self.assertIn("timestamp", claim)
            self.assertIn("confidence_score", claim)
            self.assertIn("matched_segment_id", claim)
            self.assertIn("speaker", claim)
            self.assertGreaterEqual(claim["seconds"], 0.0)
            self.assertLessEqual(claim["seconds"], 120.0)

    def test_completely_disjoint_vocabulary_mapping(self):
        """Claims with completely disjoint vocabulary (0 keyword overlap) map safely without crashing and yield valid confidence scores."""
        disjoint_claims = [
            {"statement": "Xylophonic quarnix blorf zenzibar"},  # 0 overlap, no hint_sec
            {"statement": "Quasiparticle hadron annihilation", "seconds": 30.0},  # 0 overlap, hint_sec=30.0
            {"statement": "Abc def ghi jkl mno"}  # short words, 0 overlap
        ]
        grounded, stats = verify_grounded_claims(disjoint_claims, self.segments, max_duration=120)

        self.assertEqual(len(grounded), 3)

        # First claim has 0 overlap and no hint -> falls back to start of video seg_0
        self.assertEqual(grounded[0]["seconds"], 0.0)
        self.assertEqual(grounded[0]["timestamp"], "00:00")
        self.assertEqual(grounded[0]["matched_segment_id"], "seg_0")
        self.assertFalse(grounded[0]["verified"])
        self.assertEqual(grounded[0]["confidence_score"], 0.30)

        # Second claim has 0 overlap but hint 30.0 -> aligns to nearest segment (around 30.0)
        self.assertEqual(grounded[1]["seconds"], 30.0)
        self.assertEqual(grounded[1]["timestamp"], "00:30")
        self.assertTrue(grounded[1]["verified"])
        self.assertEqual(grounded[1]["confidence_score"], 0.50)

        # Third claim has 0 overlap -> falls back to start
        self.assertEqual(grounded[2]["seconds"], 0.0)
        self.assertFalse(grounded[2]["verified"])

        # Stats must accurately reflect non-verified claims
        self.assertEqual(stats["verified_count"], 1)
        self.assertAlmostEqual(stats["average_confidence"], (0.30 + 0.50 + 0.30) / 3, places=2)

    def test_zero_and_negative_max_duration_normalization(self):
        """max_duration <= 0 is dynamically normalized from transcript segments or defaults to 7200."""
        claims = [{"statement": "Sample claim", "seconds": 40.0}]

        # max_duration = 0 with segments (segments max is 60.0 + 15.0 = 75)
        grounded, stats = verify_grounded_claims(claims, self.segments, max_duration=0)
        self.assertEqual(stats["max_duration_sec"], 75)
        self.assertLessEqual(grounded[0]["seconds"], 75.0)

        # max_duration = -100 with empty segments -> defaults to 7200
        grounded_empty, stats_empty = verify_grounded_claims(claims, [], max_duration=-100)
        self.assertEqual(stats_empty["max_duration_sec"], 7200)


class TestM3SpeakerAttributionAdversarial(unittest.TestCase):
    """Adversarial stress tests for Dynamic Speaker Attribution (F11)."""

    def setUp(self):
        self.channel_author = "The Tech Lead Show"

    def test_diarization_tags_attribution(self):
        """Segment speaker diarization tags ('Leslie Lamport', 'Dr. Alice Vance', 'Prof. Bob Chen') take attribution precedence."""
        test_cases = [
            ("Leslie Lamport", "Distributed consensus is subtle."),
            ("Dr. Alice Vance", "Empirical measurement shows operational overhead."),
            ("Prof. Bob Chen", "Autonomous deployments reduce release friction.")
        ]
        for expected_speaker, text in test_cases:
            seg = {"speaker": expected_speaker, "text": text}
            claim = {"statement": text}
            speaker, is_verified = attribute_speaker_to_claim(claim, seg, channel_author=self.channel_author)
            self.assertEqual(speaker, expected_speaker)
            self.assertTrue(is_verified)

    def test_webvtt_cues_and_dialogue_prefixes(self):
        """WebVTT cues (<v Name>text</v>) and dialogue prefixes (>> Name: text, [Name]: text) are accurately parsed."""
        cue_cases = [
            ("<v Alice>We need automated regression pipelines.</v>", "Alice"),
            ("<v Dr. Alice Vance>We need automated regression pipelines.</v>", "Dr. Alice Vance"),
            (">> Bob: I completely agree with the architectural direction.", "Bob"),
            (">> Prof. Bob Chen: I completely agree with the architectural direction.", "Prof. Bob Chen"),
            ("[Leslie Lamport]: Byzantine fault tolerance is non-trivial.", "Leslie Lamport"),
            ("Testing is key, as Dr. Carol King argued during the keynote.", "Dr. Carol King"),
            ("We should adopt microservices, according to Dr. Alice Vance.", "Dr. Alice Vance")
        ]
        for cue_text, expected_speaker in cue_cases:
            seg = {"text": cue_text, "speaker": "Host"}  # Segment metadata is generic Host
            claim = {"statement": "Automated pipelines and testing."}
            speaker, is_verified = attribute_speaker_to_claim(claim, seg, channel_author=self.channel_author)
            self.assertEqual(speaker, expected_speaker, f"Failed parsing cue: '{cue_text}'")
            self.assertTrue(is_verified)

    def test_channel_author_quote_fabrication_defense(self):
        """
        Anti-fabrication defense:
        If quote has no dialogue cue and claims speaker equals channel author,
        attribution must neutralize to 'Speaker' / is_verified=False unless the author is explicitly in dialogue.
        """
        # Case A: Quote has speaker == channel_author, but transcript does NOT mention author
        seg_no_author = {
            "speaker": "Speaker",
            "text": "In this architecture, database connections are pooled synchronously."
        }
        claim_fabricated = {
            "statement": "Database connections are pooled synchronously.",
            "speaker": self.channel_author  # LLM erroneously blanket-attributed to channel author
        }
        speaker, is_verified = attribute_speaker_to_claim(claim_fabricated, seg_no_author, channel_author=self.channel_author)
        self.assertEqual(speaker, "Speaker", "Failed to neutralize fabricated author attribution")
        self.assertFalse(is_verified)

        # Case B: Case insensitivity and whitespace tolerance in author matching
        claim_messy_author = {
            "statement": "Database connections are pooled synchronously.",
            "speaker": "  the tech lead show  "
        }
        speaker_b, is_verified_b = attribute_speaker_to_claim(claim_messy_author, seg_no_author, channel_author=self.channel_author)
        self.assertEqual(speaker_b, "Speaker")
        self.assertFalse(is_verified_b)

        # Case C: Author is legitimately mentioned in segment dialogue text -> attribution preserved
        seg_with_author = {
            "speaker": "Host",
            "text": f"According to {self.channel_author}, microservices require rigorous observability."
        }
        speaker_c, is_verified_c = attribute_speaker_to_claim(claim_fabricated, seg_with_author, channel_author=self.channel_author)
        self.assertEqual(speaker_c, self.channel_author)
        self.assertTrue(is_verified_c)

        # Case D: Segment has genuine named speaker ('Prof. Bob Chen') while claim erroneously has author
        seg_with_named_speaker = {
            "speaker": "Prof. Bob Chen",
            "text": "Microservices require rigorous observability."
        }
        speaker_d, is_verified_d = attribute_speaker_to_claim(claim_fabricated, seg_with_named_speaker, channel_author=self.channel_author)
        self.assertEqual(speaker_d, "Prof. Bob Chen")
        self.assertTrue(is_verified_d)


class TestM3LearningAndContradictionStress(unittest.TestCase):
    """Stress tests for Bloom's Taxonomy Quiz, Flashcard guardrails (F12), and Contradictions (F13)."""

    def test_bloom_quiz_strict_option_counts_and_duplicates(self):
        """Quiz questions must have exactly 4 distinct options; short stems, 2/3/5 options, or duplicates are rejected."""
        invalid_items = [
            # 2 options
            {"question": "Is static typing beneficial?", "options": ["Yes", "No"], "correct_index": 0, "bloom_level": "Understand"},
            # 3 options
            {"question": "Which database is relational?", "options": ["PostgreSQL", "MongoDB", "Redis"], "correct_index": 0, "bloom_level": "Understand"},
            # 5 options
            {"question": "Which protocol is reliable?", "options": ["TCP", "UDP", "ICMP", "IP", "ARP"], "correct_index": 0, "bloom_level": "Understand"},
            # Duplicate options (case-insensitive)
            {"question": "Identify valid message broker?", "options": ["Kafka", "kafka", "RabbitMQ", "ActiveMQ"], "correct_index": 0, "bloom_level": "Understand"},
            # Short stem <= 5 chars
            {"question": "Why?", "options": ["A", "B", "C", "D"], "correct_index": 0, "bloom_level": "Understand"},
            # Invalid Bloom level string
            {"question": "What is the primary benefit of TDD?", "options": ["Quality", "Speed", "Cost", "Fun"], "correct_index": 0, "bloom_level": "RandomTier"}
        ]
        validated, all_valid = validate_bloom_quiz(invalid_items)
        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 0, "Malformed quiz items must be completely filtered out")

    def test_bloom_quiz_answer_coercion_and_prefix_stripping(self):
        """Options with prefixes ('A. ', 'B) ', '(C)') are stripped and letter correct_index ('A'..'D') coerced to 0..3."""
        valid_raw_quiz = [
            {
                "question": "Which mechanism prevents cascading failures in microservice networks?",
                "options": ["A) Circuit breaker", "B. Bulkhead isolation", "(C) Rate limiting", "4. Retry backoff"],
                "correct_index": "B",
                "bloom_level": "analyzing"
            },
            {
                "question": "What does Paxos establish across asynchronous distributed nodes?",
                "options": ["1. State machine consensus", "2. Message encryption", "3. Cache eviction", "4. Data compression"],
                "correct_index": "0",
                "bloom_level": "understanding"
            }
        ]
        validated, all_valid = validate_bloom_quiz(valid_raw_quiz)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 2)

        # Check prefix stripping
        self.assertEqual(validated[0]["options"][0], "Circuit breaker")
        self.assertEqual(validated[0]["options"][1], "Bulkhead isolation")
        self.assertEqual(validated[0]["options"][2], "Rate limiting")
        self.assertEqual(validated[0]["options"][3], "Retry backoff")
        self.assertEqual(validated[0]["correct_index"], 1)  # 'B' -> 1
        self.assertEqual(validated[0]["bloom_level"], "Analyze")

        self.assertEqual(validated[1]["options"][0], "State machine consensus")
        self.assertEqual(validated[1]["correct_index"], 0)  # "0" -> 0
        self.assertEqual(validated[1]["bloom_level"], "Understand")

    def test_flashcard_guardrails_validation(self):
        """Flashcards reject identical front/back, short length (<2), and apply default concept tags."""
        flashcards = [
            {"front": "ACID", "back": "Atomicity, Consistency, Isolation, Durability", "concept": "Databases"},
            {"front": "CAP", "back": "Consistency, Availability, Partition tolerance"},  # Default concept
            {"front": "Same", "back": "same"},  # Reject: identical front and back
            {"front": "X", "back": "Valid definition"},  # Reject: front too short
            {"front": "Valid term", "back": "Y"},  # Reject: back too short
            None,  # Reject non-dict
            {"front": "", "back": ""}  # Reject empty
        ]
        validated, all_valid = validate_flashcards(flashcards)
        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["concept"], "Databases")
        self.assertEqual(validated[1]["concept"], "Core Concept")

    def test_nuanced_contradiction_taxonomy_classification(self):
        """Contradictions are mapped into 4 distinct categories with correct logical conflict flags."""
        test_data = [
            # 1. CONDITIONAL_QUALIFICATION
            {
                "topic": "Microservices vs Monolith",
                "statement_a": {"text": "Microservices increase operational burden."},
                "statement_b": {"text": "Microservices accelerate developer velocity."},
                "nuance": "Conditional qualification based on team scale and operational maturity."
            },
            # 2. TEMPORAL_EVOLUTION
            {
                "topic": "Frontend build tools",
                "statement_a": {"text": "Webpack was the industry standard bundler."},
                "statement_b": {"text": "Modern ecosystems have transitioned to Vite and esbuild."},
                "nuance": "Historical progression and evolution of JavaScript tooling over time."
            },
            # 3. PERSPECTIVE_DIVERGENCE
            {
                "topic": "Concurrency paradigms",
                "statement_a": {"speaker": "Dr. Vance", "text": "Actor models guarantee dead-lock freedom."},
                "statement_b": {"speaker": "Prof. Chen", "text": "CSP channels provide cleaner synchronization."},
                "nuance": "Competing academic viewpoints on concurrent system design."
            },
            # 4. DIRECT_CONTRADICTION
            {
                "topic": "Latency metrics",
                "statement_a": {"text": "The p99 latency was exactly 5 milliseconds."},
                "statement_b": {"text": "The p99 latency was measured at 500 milliseconds."},
                "nuance": ""
            }
        ]
        classified = classify_contradictions(test_data)
        self.assertEqual(len(classified), 4)

        self.assertEqual(classified[0]["classification"], "CONDITIONAL_QUALIFICATION")
        self.assertFalse(classified[0]["is_logical_conflict"])

        self.assertEqual(classified[1]["classification"], "TEMPORAL_EVOLUTION")
        self.assertFalse(classified[1]["is_logical_conflict"])

        self.assertEqual(classified[2]["classification"], "PERSPECTIVE_DIVERGENCE")
        self.assertFalse(classified[2]["is_logical_conflict"])

        self.assertEqual(classified[3]["classification"], "DIRECT_CONTRADICTION")
        self.assertTrue(classified[3]["is_logical_conflict"])


class TestM3PipelineEndToEndIntegration(unittest.TestCase):
    """End-to-end integration of Stage 8 (VALIDATING) in AsyncJobOrchestrator."""

    def setUp(self):
        init_relational_db()
        self.orchestrator = AsyncJobOrchestrator(max_job_workers=2, max_task_workers=4)

    def tearDown(self):
        self.orchestrator.shutdown(wait=False)

    def test_full_pipeline_stage_8_attaches_verification_metadata(self):
        """Pipeline execution through Stage 8 validates evidence and writes _verification metadata to job result."""
        vid = f"challenger_v_{uuid.uuid4().hex[:6]}"
        job_id = self.orchestrator.create_job(video_id=vid)

        segments = [
            {"speaker": "Leslie Lamport", "start": 0.0, "duration": 20.0, "timestamp": "00:00",
             "text": "A distributed system is one in which the failure of a computer you did not know existed makes your system unusable."},
            {"speaker": "Prof. Bob Chen", "start": 21.0, "duration": 20.0, "timestamp": "00:21",
             "text": "Microservices reduce deployment lead times and allow team autonomy."}
        ]

        with patch("services.orchestrator.run_metadata_worker") as mock_meta, \
             patch("services.orchestrator.run_transcript_worker") as mock_trans, \
             patch("services.orchestrator.run_videolens_analysis") as mock_ai:

            mock_meta.return_value = WorkerResult(
                module="metadata", success=True,
                data={"title": "M3 Challenger Video", "author": "Host Channel", "duration": "01:00", "duration_seconds": 60, "thumbnail_url": ""}
            )
            mock_trans.return_value = WorkerResult(
                module="transcript", success=True,
                data={"segments": segments, "formatted_duration": "01:00", "duration_seconds": 60, "ui_sample": []}
            )
            mock_ai.return_value = {
                "video_overview": {"title": "M3 Challenger Video", "summary": "Detailed video analysis."},
                "chapters": [{"title": "Intro", "start_time": "00:00"}],
                "creator_repurposing": {"youtube_chapters_raw": "00:00 Intro"},
                "claims": [
                    {"statement": "Distributed systems suffer from hidden node failures.", "seconds": 0, "timestamp": "00:00"},
                    {"statement": "Microservices reduce deployment lead times.", "seconds": 21, "timestamp": "00:21"}
                ],
                "learning": {
                    "quiz": [
                        {
                            "question": "What is the primary advantage of microservice architectures?",
                            "options": ["A. Team autonomy", "B. Single point of failure", "C. Monolithic lockstep", "D. Manual deployments"],
                            "correct_index": "A",
                            "bloom_level": "understand"
                        }
                    ],
                    "flashcards": [
                        {"front": "Microservices", "back": "Decoupled deployable services"}
                    ]
                },
                "contradictions": [
                    {
                        "topic": "Microservices trade-offs",
                        "statement_a": {"text": "Increases complexity"},
                        "statement_b": {"text": "Improves velocity"},
                        "nuance": "Conditional qualification based on team capacity."
                    }
                ]
            }

            self.orchestrator.run_pipeline(job_id, video_id=vid)

        job = self.orchestrator.get_job(job_id)
        self.assertEqual(job["status"], STATUS_COMPLETED)
        result = job["result"]

        self.assertIn("_verification", result)
        v = result["_verification"]
        self.assertEqual(v["status"], "COMPLETED")
        self.assertEqual(v["claim_verification_rate"], 1.0)
        self.assertEqual(v["bloom_validity_rate"], 1.0)
        self.assertEqual(v["claims_verified_count"], 2)
        self.assertEqual(v["quiz_questions_validated"], 1)
        self.assertEqual(v["contradictions_classified_count"], 1)
        self.assertEqual(v["contradiction_breakdown"]["CONDITIONAL_QUALIFICATION"], 1)

        # Check speaker attribution resolution
        claims = result["claims"]
        self.assertEqual(claims[0]["speaker"], "Leslie Lamport")
        self.assertEqual(claims[1]["speaker"], "Prof. Bob Chen")


if __name__ == "__main__":
    unittest.main()
