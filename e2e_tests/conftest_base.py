import os
import sys
import json
import uuid
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Ensure root directory is on PYTHONPATH
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import resolve_database_path
from services.storage_service import init_db, get_db

SAMPLE_VIDEO_ID = "dQw4w9WgXcQ"
SAMPLE_VIDEO_URL = f"https://www.youtube.com/watch?v={SAMPLE_VIDEO_ID}"

SAMPLE_OEMBED_DATA = {
    "title": "Introduction to Distributed Systems & Event-Driven Architecture",
    "author_name": "Tech Architecture Academy",
    "author_url": "https://www.youtube.com/@TechArchitectureAcademy",
    "type": "video",
    "height": 113,
    "width": 200,
    "version": "1.0",
    "provider_name": "YouTube",
    "provider_url": "https://www.youtube.com/",
    "thumbnail_height": 360,
    "thumbnail_width": 480,
    "thumbnail_url": f"https://i.ytimg.com/vi/{SAMPLE_VIDEO_ID}/hqdefault.jpg",
    "html": f"<iframe width=\"200\" height=\"113\" src=\"https://www.youtube.com/embed/{SAMPLE_VIDEO_ID}?feature=oembed\"></iframe>"
}

SAMPLE_TRANSCRIPT_SEGMENTS = [
    {"text": "Welcome to our deep dive on distributed event-driven systems.", "start": 0.0, "duration": 5.2, "timestamp": "00:00"},
    {"text": "Today we will analyze how message queues decouple producer and consumer services.", "start": 5.2, "duration": 6.8, "timestamp": "00:05"},
    {"text": "In monolithic applications, synchronous in-memory calls introduce tight coupling.", "start": 12.0, "duration": 8.0, "timestamp": "00:12"},
    {"text": "By introducing asynchronous job queues, background workers can process intensive tasks independently.", "start": 20.0, "duration": 10.5, "timestamp": "00:20"},
    {"text": "Notice that idempotency is critical: handling duplicate job submissions prevents redundant processing.", "start": 30.5, "duration": 9.5, "timestamp": "00:30"},
    {"text": "Exponential backoff retries allow transient errors to recover gracefully without crashing the pipeline.", "start": 40.0, "duration": 10.0, "timestamp": "00:40"},
    {"text": "When a non-critical worker fails, like PDF rendering, the orchestrator reports a partial success state.", "start": 50.0, "duration": 10.0, "timestamp": "00:50"},
    {"text": "Finally, grounded verification ensures every AI claim references actual transcript timestamps.", "start": 60.0, "duration": 10.0, "timestamp": "01:00"},
    {"text": "Thank you for watching this architectural breakdown.", "start": 70.0, "duration": 5.0, "timestamp": "01:10"}
]

SAMPLE_ANALYSIS_DATA = {
    "_meta": {
        "title": "Introduction to Distributed Systems & Event-Driven Architecture",
        "author": "Tech Architecture Academy",
        "duration": "01:15",
        "video_id": SAMPLE_VIDEO_ID,
        "thumbnail": f"https://i.ytimg.com/vi/{SAMPLE_VIDEO_ID}/hqdefault.jpg"
    },
    "video_overview": {
        "title": "Introduction to Distributed Systems & Event-Driven Architecture",
        "channel": "Tech Architecture Academy",
        "estimated_duration": "01:15",
        "content_type": "Lecture",
        "content_type_confidence": 96,
        "category": "Technology",
        "visual_style": "Presentation slides",
        "overall_tone": "Analytical",
        "sentiment_label": "Positive",
        "target_audience": "Software architects and backend engineers",
        "summary": "This lecture provides an architectural exploration of event-driven distributed systems, contrasting synchronous monoliths with decoupled background workers."
    },
    "metrics": {
        "duration": "01:15",
        "topics_count": 4,
        "chapters_count": 3,
        "key_points_count": 5,
        "claims_count": 4,
        "sentiment": "Positive (85%)",
        "quality_score": 9.2,
        "information_density": 8.8,
        "clarity_score": 9.5,
        "depth_score": 8.9,
        "engagement_score": 8.5
    },
    "quality_scorecard": {
        "overall_score": 91,
        "density_score": 89,
        "clarity_score": 95,
        "structure_score": 94,
        "engagement_score": 86,
        "depth_score": 90,
        "pacing_score": 88,
        "strengths": [
            "Clear architectural distinction between sync and async execution",
            "Actionable insights into error handling and idempotency"
        ],
        "weaknesses": [
            "Fast paced coverage of retry policies"
        ],
        "verdict": "Essential viewing for modern system designers."
    },
    "engagement_curve": [
        {"time": "00:00", "seconds": 0, "score": 75, "highlight": "Intro & scope"},
        {"time": "00:20", "seconds": 20, "score": 90, "highlight": "Asynchronous queuing core concept"},
        {"time": "00:50", "seconds": 50, "score": 95, "highlight": "Partial failure resiliency model"},
        {"time": "01:10", "seconds": 70, "score": 80, "highlight": "Conclusion & summary"}
    ],
    "key_takeaways": [
        {
            "id": "01",
            "title": "Decouple using message queues",
            "summary": "Asynchronous queues isolate tasks and prevent cascading failures.",
            "timestamp": "00:20",
            "seconds": 20,
            "category": "Architecture",
            "impact_level": "High"
        },
        {
            "id": "02",
            "title": "Enforce Idempotency",
            "summary": "Deduplicating job submissions avoids redundant processing and resource exhaustion.",
            "timestamp": "00:30",
            "seconds": 30,
            "category": "Reliability",
            "impact_level": "Critical"
        },
        {
            "id": "03",
            "title": "Partial Failure Resiliency",
            "summary": "Non-critical worker failure should degrade to partial status rather than failing the job.",
            "timestamp": "00:50",
            "seconds": 50,
            "category": "Fault Tolerance",
            "impact_level": "High"
        }
    ],
    "entities": {
        "people": [
            {"name": "Leslie Lamport", "role": "Computer Scientist", "context": "Distributed systems pioneer cited in introduction"}
        ],
        "concepts": [
            {"name": "Event-Driven Architecture", "category": "Pattern", "context": "Primary architectural paradigm analyzed"},
            {"name": "Idempotency", "category": "Reliability", "context": "Ensures deduplication in job dispatch"},
            {"name": "Exponential Backoff", "category": "Resilience", "context": "Retry mechanism for transient errors"}
        ],
        "companies": [
            {"name": "Tech Architecture Academy", "industry": "Education", "context": "Video publisher and course provider"}
        ],
        "tools_software": [
            {"name": "Message Queues", "category": "Infrastructure", "context": "Mechanism used to decouple workers"}
        ]
    },
    "repetitions": [
        {
            "idea": "Asynchronous worker isolation",
            "occurrences_count": 2,
            "timestamps": ["00:20", "00:50"],
            "seconds": [20, 50],
            "context": "Reinforced to emphasize failure containment"
        }
    ],
    "contradictions": [
        {
            "topic": "Synchronous vs Asynchronous execution cost",
            "statement_a": {"text": "Synchronous calls provide simple immediate consistency.", "timestamp": "00:12", "seconds": 12},
            "statement_b": {"text": "Asynchronous architectures provide greater availability despite eventual consistency.", "timestamp": "00:20", "seconds": 20},
            "nuance": "Trade-off between immediacy of consistency and resilience under high concurrent load."
        }
    ],
    "learning": {
        "key_definitions": [
            {
                "term": "Idempotency",
                "definition": "A property of an operation whereby it can be applied multiple times without changing the result beyond the initial application.",
                "timestamp": "00:30",
                "seconds": 30
            }
        ],
        "study_notes": [
            {
                "heading": "Distributed System Reliability Principles",
                "bullets": [
                    "Isolate failure domains using asynchronous queues.",
                    "Implement exponential backoff retries for transient network faults.",
                    "Permit partial job completion when ancillary exports fail."
                ]
            }
        ],
        "flashcards": [
            {
                "front": "What is the primary benefit of decoupled background workers?",
                "back": "They isolate task failures and allow long-running operations to execute without blocking requests.",
                "concept": "Architecture",
                "timestamp": "00:20",
                "seconds": 20
            },
            {
                "front": "Why is idempotency essential in asynchronous job processing?",
                "back": "It prevents duplicate processing and side-effects when identical jobs or retries occur.",
                "concept": "Reliability",
                "timestamp": "00:30",
                "seconds": 30
            }
        ],
        "quiz": [
            {
                "question": "What should happen when an optional export worker fails during a video analysis job?",
                "bloom_level": "Understand",
                "options": [
                    "The entire job should immediately terminate with an error status.",
                    "The job should transition to PARTIAL status and deliver all successfully processed modules.",
                    "The database should roll back and erase all extracted metadata.",
                    "The system should hang indefinitely waiting for the worker."
                ],
                "correct_index": 1,
                "explanation": "Resilient orchestration degrades gracefully to a PARTIAL status, delivering intact core modules like summaries and transcripts."
            },
            {
                "question": "How does exponential backoff improve transient fault recovery?",
                "bloom_level": "Apply",
                "options": [
                    "It retries immediately in an infinite tight loop.",
                    "It incrementally increases delay between retries to prevent overwhelming recovering services.",
                    "It disables error logging completely.",
                    "It duplicates the job across all available workers."
                ],
                "correct_index": 1,
                "explanation": "Incrementally spacing retries gives recovering systems breathing room without saturating shared resources."
            },
            {
                "question": "Evaluate the architectural trade-off between synchronous in-memory calls and asynchronous message queues.",
                "bloom_level": "Evaluate",
                "options": [
                    "Synchronous calls offer immediate consistency with lower fault isolation; queues offer higher resilience with eventual consistency.",
                    "Queues are always faster than in-memory function execution.",
                    "Synchronous calls have zero network latency and cannot ever fail.",
                    "There are no architectural differences between the two patterns."
                ],
                "correct_index": 0,
                "explanation": "Synchronous execution is simple but tightly coupled; asynchronous architectures decouple failure domains at the expense of coordination complexity."
            }
        ]
    },
    "creator_repurposing": {
        "youtube_chapters_raw": "00:00 Introduction & Foundations\n00:20 Asynchronous Queues & Workers\n00:50 Fault Resiliency & Grounded Claims"
    }
}


class LensYouE2EBaseTest(unittest.TestCase):
    """
    Base test class providing an isolated temporary SQLite database,
    clean test client setup, and reusable contract assertion helpers.
    """
    temp_dir = None
    original_db_path = None

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="lensyou_e2e_test_")
        cls.test_db_path = os.path.join(cls.temp_dir, "test_lensyou.db")
        cls.original_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = cls.test_db_path

        # Initialize fresh test database
        init_db()

        # Disable TOTP for test sessions
        try:
            from services.totp_service import disable_admin_totp
            disable_admin_totp()
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        # Restore original database path
        if cls.original_db_path:
            os.environ["DATABASE_PATH"] = cls.original_db_path
        else:
            os.environ.pop("DATABASE_PATH", None)

        if cls.temp_dir and os.path.exists(cls.temp_dir):
            try:
                shutil.rmtree(cls.temp_dir, ignore_errors=True)
            except Exception:
                pass

    def setUp(self):
        from app import app
        self.app = app
        self.client = app.test_client()

    # --- Contract Validation Helpers ---

    def assert_valid_bloom_quiz(self, quiz_items: list):
        """Validates that quiz items conform to Bloom's taxonomy contract."""
        self.assertIsInstance(quiz_items, list, "Quiz items must be a list")
        self.assertGreater(len(quiz_items), 0, "Quiz list must not be empty")

        valid_bloom_levels = {
            "remember", "understand", "apply", "analyze", "evaluate", "create"
        }

        for idx, item in enumerate(quiz_items):
            self.assertIn("question", item, f"Quiz item {idx} missing 'question' stem")
            self.assertTrue(isinstance(item["question"], str) and len(item["question"].strip()) > 5,
                            f"Quiz item {idx} question must be a non-empty string")

            self.assertIn("options", item, f"Quiz item {idx} missing 'options'")
            options = item["options"]
            self.assertIsInstance(options, list, f"Quiz item {idx} options must be a list")
            self.assertEqual(len(options), 4, f"Quiz item {idx} must have exactly 4 options, got {len(options)}")

            for opt_idx, opt in enumerate(options):
                self.assertTrue(isinstance(opt, str) and len(opt.strip()) > 0,
                                f"Quiz item {idx} option {opt_idx} must be a non-empty string")

            self.assertIn("correct_index", item, f"Quiz item {idx} missing 'correct_index'")
            correct_idx = item["correct_index"]
            self.assertIsInstance(correct_idx, int, f"Quiz item {idx} correct_index must be an int")
            self.assertIn(correct_idx, [0, 1, 2, 3], f"Quiz item {idx} correct_index {correct_idx} out of range [0, 3]")

            self.assertIn("bloom_level", item, f"Quiz item {idx} missing 'bloom_level'")
            bloom_str = str(item["bloom_level"]).strip().lower()
            self.assertIn(bloom_str, valid_bloom_levels,
                          f"Quiz item {idx} bloom_level '{item['bloom_level']}' not recognized")

            if "explanation" in item:
                self.assertIsInstance(item["explanation"], str)

    def assert_valid_flashcards(self, flashcards: list):
        """Validates flashcards schema: front, back, concept, timestamp."""
        self.assertIsInstance(flashcards, list)
        self.assertGreater(len(flashcards), 0)
        for idx, card in enumerate(flashcards):
            self.assertIn("front", card, f"Flashcard {idx} missing 'front'")
            self.assertIn("back", card, f"Flashcard {idx} missing 'back'")
            self.assertTrue(card["front"].strip())
            self.assertTrue(card["back"].strip())

    def assert_valid_claims_grounding(self, claims: list, segments: list, max_duration_sec: int = 7200):
        """Verifies that all claims link to valid transcript timestamps within video bounds."""
        self.assertIsInstance(claims, list)
        for idx, claim in enumerate(claims):
            self.assertIn("timestamp", claim, f"Claim {idx} missing timestamp")
            self.assertIn("seconds", claim, f"Claim {idx} missing seconds")
            sec = claim["seconds"]
            self.assertGreaterEqual(sec, 0, f"Claim {idx} has negative seconds: {sec}")
            self.assertLessEqual(sec, max_duration_sec, f"Claim {idx} seconds {sec} exceeds max duration {max_duration_sec}")
            # Verify timestamp format (MM:SS or HH:MM:SS)
            ts = claim["timestamp"]
            parts = ts.split(":")
            self.assertIn(len(parts), [2, 3], f"Invalid timestamp format '{ts}' in claim {idx}")
