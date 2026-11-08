"""
test_m3_fidelity_challenger.py
Empirical Adversarial Stress Test Suite for Milestone 3 (F12 Bloom's Taxonomy & Flashcards, F13 Contradiction Taxonomy).

Authored by: challenger_m3_2 (Milestone 3 Fidelity Challenger 2)

Covers exhaustive adversarial testing:
1. validate_bloom_quiz:
   - Malformed stems: <= 5 chars ("Why?"), pure whitespace, non-strings, exact boundary lengths 5 vs 6.
   - Option count variations: 0, 1, 2, 3, 5, 10 options, non-list options.
   - Duplicate options: exact duplicates, case-insensitive duplicates, duplicates after prefix stripping.
   - Empty/whitespace options: empty string, spaces, prefix-only strings ("A.", "(1)").
   - Prefix stripping: "A. ", "B) ", "(C) ", "1. ", "2) ", "(3) ", "D: ", "d- ".
   - Answer indices: letters "A"-"D" (upper & lower), digits "0"-"3" (int & str), text matching, invalid out-of-bounds (-1, 4, "Z", "4").
   - Cognitive depth tiers: all 6 canonical tiers + synonyms + case variations, invalid tiers ("RandomGuessing", empty, numeric).
2. validate_flashcards:
   - Empty front/back, whitespace front/back, length < 2, front == back (case-insensitive & whitespace-insensitive).
   - Polymorphic field names (front/back, question/answer, term/definition).
   - Concept tag defaulting: missing, whitespace, non-string -> "Core Concept".
   - Preserves timestamps and normalized bloom levels.
3. classify_contradictions:
   - DIRECT_CONTRADICTION: conflicting assertions, same context, zero conditions/nuance.
   - TEMPORAL_EVOLUTION: "formerly", "initially", "migrated", "later", historical shifts.
   - CONDITIONAL_QUALIFICATION: "trade-off", "depends", "at scale", "in memory", operational trade-offs.
   - PERSPECTIVE_DIVERGENCE: distinct speakers ("Dr. Alice" vs "Prof. Bob"), "perspective", "study", "viewpoint".
   - Precedence and boundary handling: empty input, polymorphic statements, missing fields.
"""

import unittest
from services.verification_service import (
    validate_bloom_quiz,
    validate_flashcards,
    classify_contradictions,
    clean_option_text,
    normalize_bloom_level,
    BLOOM_CANONICAL_LEVELS,
    OPTION_LETTER_MAP,
)


class TestAdversarialBloomQuiz(unittest.TestCase):
    """Exhaustive adversarial tests for validate_bloom_quiz (Feature F12)."""

    def test_malformed_question_stems(self):
        """Question stems with <= 5 characters, pure whitespace, or non-strings must be rejected."""
        valid_options = ["Option 1", "Option 2", "Option 3", "Option 4"]
        valid_tier = "Understand"

        adversarial_stems = [
            "",                       # 0 chars
            "   ",                    # pure whitespace
            "\t\n  \r",               # whitespace escape characters
            "Why?",                   # 4 chars
            "Where",                  # 5 chars
            "12345",                  # 5 chars
            "     12345     ",        # 5 chars after strip
            None,                     # non-string None
            12345678,                 # non-string int
            ["What is caching?"],     # non-string list
            {"stem": "What is it?"},  # non-string dict
            True                      # boolean
        ]

        for idx, stem in enumerate(adversarial_stems):
            quiz = [{
                "question": stem,
                "options": list(valid_options),
                "correct_index": 0,
                "bloom_level": valid_tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Stem candidate #{idx} '{stem}' should have failed validation")
            self.assertEqual(len(validated), 0, f"Stem candidate #{idx} '{stem}' should have been filtered out")

        # Boundary test: exact length 6 (> 5 chars) should be accepted
        boundary_quiz = [{
            "question": "Where?",  # exactly 6 chars
            "options": list(valid_options),
            "correct_index": 0,
            "bloom_level": valid_tier
        }]
        val_boundary, all_valid_boundary = validate_bloom_quiz(boundary_quiz)
        self.assertTrue(all_valid_boundary)
        self.assertEqual(len(val_boundary), 1)
        self.assertEqual(val_boundary[0]["question"], "Where?")

    def test_option_count_variations(self):
        """Quizzes with != 4 options or non-list options must be rejected."""
        stem = "What is the primary guarantee of ACID transactions?"
        tier = "Analyze"

        adversarial_options = [
            [],                                           # 0 options
            ["Atomicity"],                                # 1 option
            ["Atomicity", "Consistency"],                 # 2 options
            ["Atomicity", "Consistency", "Isolation"],    # 3 options
            ["A", "B", "C", "D", "E"],                   # 5 options
            ["A", "B", "C", "D", "E", "F", "G"],         # 7 options
            None,                                         # None
            "Atomicity, Consistency, Isolation, Durability", # String instead of list
            {"A": "Atomicity", "B": "Consistency"},      # Dict instead of list
            1234                                          # Int instead of list
        ]

        for idx, opts in enumerate(adversarial_options):
            quiz = [{
                "question": stem,
                "options": opts,
                "correct_index": 0,
                "bloom_level": tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Option candidate #{idx} should have failed validation")
            self.assertEqual(len(validated), 0)

    def test_duplicate_options_rejection(self):
        """Duplicate options (exact, case-insensitive, or post-prefix stripping) must be rejected."""
        stem = "Which consensus protocol is designed for asynchronous networks?"
        tier = "Remember"

        duplicate_sets = [
            # Exact duplicate
            ["Paxos", "Paxos", "Raft", "Zab"],
            # Case-insensitive duplicate
            ["Raft", "raft", "Paxos", "Zab"],
            # Whitespace variation duplicate
            ["Zab", "  Zab  ", "Paxos", "Raft"],
            # Prefix duplicate: after stripping "A. ", both become "Raft"
            ["A. Raft", "B. Raft", "C. Paxos", "D. Zab"],
            # Number prefix duplicate: after stripping "1) ", both become "Paxos"
            ["1) Paxos", "2) Paxos", "3) Raft", "4) Zab"],
            # All four identical
            ["Consensus", "Consensus", "Consensus", "Consensus"]
        ]

        for idx, opts in enumerate(duplicate_sets):
            quiz = [{
                "question": stem,
                "options": opts,
                "correct_index": 0,
                "bloom_level": tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Duplicate set #{idx} should have failed validation")
            self.assertEqual(len(validated), 0)

    def test_empty_and_whitespace_options(self):
        """Options that are empty, pure whitespace, or reduce to empty after prefix stripping must be rejected."""
        stem = "How does consistent hashing minimize remapping keys?"
        tier = "Apply"

        malformed_option_sets = [
            ["Ring topology", "", "Virtual nodes", "Modulo hashing"],               # Empty string
            ["Ring topology", "     ", "Virtual nodes", "Modulo hashing"],          # Whitespace
            ["Ring topology", "\t\n", "Virtual nodes", "Modulo hashing"],           # Tabs/newlines
            ["A. ", "B. Valid Option", "C. Valid Option 2", "D. Valid Option 3"],   # Prefix only ("A. ")
            ["(1)", "(2) Valid Option", "(3) Valid Option 2", "(4) Valid Option 3"] # Prefix only ("(1)")
        ]

        for idx, opts in enumerate(malformed_option_sets):
            quiz = [{
                "question": stem,
                "options": opts,
                "correct_index": 1,
                "bloom_level": tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Malformed option set #{idx} should have failed validation")
            self.assertEqual(len(validated), 0)

    def test_prefix_stripping_and_cleaning(self):
        """Prefix stripping cleans 'A. ', 'B) ', '(C) ', '1. ', '2) ', '3: ', 'd- ' correctly."""
        stem = "Identify the correct protocol characteristic."
        tier = "Understand"

        quiz = [
            {
                "question": stem,
                "options": ["A. Option Alpha", "B) Option Beta", "(C) Option Gamma", "4. Option Delta"],
                "correct_index": 0,
                "bloom_level": tier
            },
            {
                "question": stem,
                "options": ["1) First Item", "2: Second Item", "3- Third Item", "4. Fourth Item"],
                "correct_index": 2,
                "bloom_level": tier
            }
        ]
        validated, all_valid = validate_bloom_quiz(quiz)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["options"], ["Option Alpha", "Option Beta", "Option Gamma", "Option Delta"])
        self.assertEqual(validated[1]["options"], ["First Item", "Second Item", "Third Item", "Fourth Item"])

    def test_answer_indices_coercion_and_out_of_bounds(self):
        """Letter options and string digits coerce to 0..3; invalid or out-of-bounds indices are rejected."""
        stem = "Which data structure provides O(1) average lookup time?"
        opts = ["Linked List", "Hash Table", "Binary Search Tree", "Red-Black Tree"]
        tier = "Apply"

        # Valid coercions
        valid_coercions = [
            (0, 0),
            (1, 1),
            (2, 2),
            (3, 3),
            ("0", 0),
            ("1", 1),
            ("2", 2),
            ("3", 3),
            ("A", 0),
            ("B", 1),
            ("C", 2),
            ("D", 3),
            ("a", 0),
            ("b", 1),
            ("c", 2),
            ("d", 3),
            ("Hash Table", 1),         # text match via correct_index
            ("linked list", 0),        # case-insensitive text match
        ]

        for raw_corr, expected_idx in valid_coercions:
            quiz = [{
                "question": stem,
                "options": list(opts),
                "correct_index": raw_corr,
                "bloom_level": tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertTrue(all_valid, f"Failed coercion for raw_corr={raw_corr}")
            self.assertEqual(validated[0]["correct_index"], expected_idx)

        # Also test correct_answer field fallback
        quiz_answer = [{
            "question": stem,
            "options": list(opts),
            "correct_answer": "Red-Black Tree",
            "bloom_level": tier
        }]
        val_ans, all_ans = validate_bloom_quiz(quiz_answer)
        self.assertTrue(all_ans)
        self.assertEqual(val_ans[0]["correct_index"], 3)

        # Invalid / Out-of-bounds indices
        invalid_indices = [
            -1,
            -5,
            4,
            5,
            100,
            "-1",
            "4",
            "5",
            "Z",
            "E",
            "X",
            "Unknown Option",
            None,
            [],
            {}
        ]

        for idx, inv_corr in enumerate(invalid_indices):
            quiz = [{
                "question": stem,
                "options": list(opts),
                "correct_index": inv_corr,
                "bloom_level": tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Invalid index #{idx} '{inv_corr}' should have failed")
            self.assertEqual(len(validated), 0)

    def test_cognitive_depth_tiers_normalization_and_rejection(self):
        """All 6 Bloom tiers and synonyms normalize; non-conforming strings are rejected."""
        stem = "How does two-phase commit achieve atomic distributed state updates?"
        opts = ["Phase 1 Prepare", "Phase 2 Commit", "Coordinator Election", "Timeout Abort"]

        valid_tier_mappings = [
            ("remember", "Remember"),
            ("REMEMBER", "Remember"),
            ("remembering", "Remember"),
            ("knowledge", "Remember"),
            ("recall", "Remember"),
            ("understand", "Understand"),
            ("comprehension", "Understand"),
            ("understanding", "Understand"),
            ("apply", "Apply"),
            ("APPLY", "Apply"),
            ("applying", "Apply"),
            ("application", "Apply"),
            ("analyze", "Analyze"),
            ("analysis", "Analyze"),
            ("analyzing", "Analyze"),
            ("evaluate", "Evaluate"),
            ("evaluation", "Evaluate"),
            ("evaluating", "Evaluate"),
            ("create", "Create"),
            ("creation", None),       # "creation" is not in dict, "creating"/"synthesis"/"design" are
            ("creating", "Create"),
            ("synthesis", "Create"),
            ("design", "Create")
        ]

        for raw_tier, expected in valid_tier_mappings:
            quiz = [{
                "question": stem,
                "options": list(opts),
                "correct_index": 0,
                "bloom_level": raw_tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            if expected is not None:
                self.assertTrue(all_valid, f"Failed for valid tier '{raw_tier}'")
                self.assertEqual(validated[0]["bloom_level"], expected)
            else:
                self.assertFalse(all_valid, f"Should have rejected unrecognized tier '{raw_tier}'")
                self.assertEqual(len(validated), 0)

        # Invalid Bloom cognitive tiers
        invalid_tiers = [
            "RandomGuessing",
            "Intuition",
            "GutFeeling",
            "Level 1",
            "Tier 3",
            "High",
            "Low",
            "",
            "   ",
            None,
            123
        ]

        for idx, inv_tier in enumerate(invalid_tiers):
            quiz = [{
                "question": stem,
                "options": list(opts),
                "correct_index": 0,
                "bloom_level": inv_tier
            }]
            validated, all_valid = validate_bloom_quiz(quiz)
            self.assertFalse(all_valid, f"Invalid tier #{idx} '{inv_tier}' should have failed")
            self.assertEqual(len(validated), 0)

    def test_overall_quiz_batch_validity_flag(self):
        """all_valid is True only when all items conform; False if even one item is dropped."""
        opts = ["A1", "A2", "A3", "A4"]
        quiz = [
            {"question": "Valid Question One?", "options": list(opts), "correct_index": 0, "bloom_level": "Understand"},
            {"question": "Too?", "options": list(opts), "correct_index": 0, "bloom_level": "Understand"},  # Malformed
            {"question": "Valid Question Three?", "options": list(opts), "correct_index": 0, "bloom_level": "Apply"}
        ]
        validated, all_valid = validate_bloom_quiz(quiz)
        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 2)  # Middle item filtered out
        self.assertEqual(validated[0]["question"], "Valid Question One?")
        self.assertEqual(validated[1]["question"], "Valid Question Three?")


class TestAdversarialFlashcardGuardrails(unittest.TestCase):
    """Exhaustive adversarial tests for validate_flashcards (Feature F12)."""

    def test_empty_and_short_flashcard_fields(self):
        """Flashcards with empty, whitespace, or <2 character front/back must be rejected."""
        adversarial_cards = [
            {"front": "", "back": "Valid definition here"},
            {"front": "   ", "back": "Valid definition here"},
            {"front": "A", "back": "Valid definition here"},             # len < 2
            {"front": "Valid term here", "back": ""},
            {"front": "Valid term here", "back": "   "},
            {"front": "Valid term here", "back": "B"},                   # len < 2
            {"front": None, "back": "Valid definition here"},
            {"front": "Valid term here", "back": None},
            {"front": 12345, "back": "Valid definition here"},           # non-string
            {"front": "Valid term here", "back": 12345},                 # non-string
            "Not a dictionary item",                                     # non-dict
            None                                                         # non-dict None
        ]

        for idx, card in enumerate(adversarial_cards):
            validated, all_valid = validate_flashcards([card])
            self.assertFalse(all_valid, f"Card #{idx} should have failed validation")
            self.assertEqual(len(validated), 0)

    def test_front_equals_back_rejection(self):
        """Flashcards where front == back (including case and whitespace differences) must be rejected."""
        identical_pairs = [
            ("MapReduce", "MapReduce"),
            ("MapReduce", "mapreduce"),
            ("  MapReduce  ", "mapreduce"),
            ("EVENT DRIVEN", "event driven"),
        ]

        for front, back in identical_pairs:
            card = {"front": front, "back": back, "concept": "Architecture"}
            validated, all_valid = validate_flashcards([card])
            self.assertFalse(all_valid, f"Identical pair ({front}, {back}) should have been rejected")
            self.assertEqual(len(validated), 0)

    def test_polymorphic_field_support(self):
        """Supports front/back, question/answer, term/definition."""
        cards = [
            {"front": "CAP Theorem", "back": "Consistency, Availability, Partition tolerance trade-off."},
            {"question": "What is WAL?", "answer": "Write-Ahead Logging guarantees durability before mutations."},
            {"term": "Idempotence", "definition": "An operation yielding the same result when executed multiple times."}
        ]
        validated, all_valid = validate_flashcards(cards)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 3)
        self.assertEqual(validated[0]["front"], "CAP Theorem")
        self.assertEqual(validated[1]["front"], "What is WAL?")
        self.assertEqual(validated[2]["front"], "Idempotence")

    def test_concept_tag_defaulting(self):
        """Missing, whitespace, or non-string concept tag defaults to 'Core Concept'."""
        cards = [
            {"front": "Card 1 Term", "back": "Card 1 Definition"},                       # Missing concept
            {"front": "Card 2 Term", "back": "Card 2 Definition", "concept": ""},         # Empty concept
            {"front": "Card 3 Term", "back": "Card 3 Definition", "concept": "   "},      # Whitespace concept
            {"front": "Card 4 Term", "back": "Card 4 Definition", "concept": None},       # None concept
            {"front": "Card 5 Term", "back": "Card 5 Definition", "concept": 999},        # Non-string concept
            {"front": "Card 6 Term", "back": "Card 6 Definition", "topic": "Networking"}, # 'topic' fallback
            {"front": "Card 7 Term", "back": "Card 7 Definition", "concept": "Security"}  # Explicit concept
        ]
        validated, all_valid = validate_flashcards(cards)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 7)
        self.assertEqual(validated[0]["concept"], "Core Concept")
        self.assertEqual(validated[1]["concept"], "Core Concept")
        self.assertEqual(validated[2]["concept"], "Core Concept")
        self.assertEqual(validated[3]["concept"], "Core Concept")
        self.assertEqual(validated[4]["concept"], "Core Concept")
        self.assertEqual(validated[5]["concept"], "Networking")
        self.assertEqual(validated[6]["concept"], "Security")

    def test_flashcard_metadata_preservation(self):
        """Preserves timestamps, seconds, and normalizes bloom_level if provided."""
        card = {
            "front": "Eventual Consistency",
            "back": "Replicas converge given sufficient time without new updates.",
            "timestamp": "04:15",
            "seconds": "255",
            "bloom_level": "understand"
        }
        validated, all_valid = validate_flashcards([card])
        self.assertTrue(all_valid)
        self.assertEqual(validated[0]["timestamp"], "04:15")
        self.assertEqual(validated[0]["seconds"], 255)
        self.assertEqual(validated[0]["bloom_level"], "Understand")


class TestAdversarialContradictionClassifier(unittest.TestCase):
    """Exhaustive adversarial tests for classify_contradictions (Feature F13)."""

    def test_direct_contradiction_pure_conflict(self):
        """Raw contradictory claims with zero nuance markers and identical context are DIRECT_CONTRADICTION."""
        contradictions = [
            {
                "topic": "Thread Safety",
                "statement_a": {"text": "The shared counter is completely thread-safe without locks."},
                "statement_b": {"text": "The shared counter suffers from severe race conditions under multi-threading."},
                "nuance": "Direct conflict on thread safety guarantees."
            },
            {
                "topic": "Throughput benchmark",
                "statement_a": "Throughput was 100,000 requests per second.",
                "statement_b": "Throughput was only 500 requests per second.",
                "nuance": "Opposing quantitative measurements."
            }
        ]
        classified = classify_contradictions(contradictions)
        self.assertEqual(len(classified), 2)
        for c in classified:
            self.assertEqual(c["classification"], "DIRECT_CONTRADICTION")
            self.assertEqual(c["type"], "DIRECT_CONTRADICTION")
            self.assertTrue(c["is_logical_conflict"])
            self.assertIn("Direct incompatible assertions", c["rationale"])

    def test_temporal_evolution_markers(self):
        """Keywords such as 'formerly', 'initially', 'migrated', 'later' classify as TEMPORAL_EVOLUTION."""
        temporal_cases = [
            ("formerly", "The architecture formerly relied on XML-RPC endpoints."),
            ("initially", "The project initially began with a monolithic Python script."),
            ("migrated", "The team migrated from self-hosted MySQL to DynamoDB."),
            ("later", "Later benchmarks demonstrated that HTTP/2 multiplexing reduced latency."),
            ("over time", "Over time, disk throughput degraded due to fragmentation."),
            ("historically", "Historically, single-core CPUs dominated consumer computing."),
            ("outdated", "The original RFC is now outdated and superseded by RFC 9110.")
        ]

        for kw, sentence in temporal_cases:
            item = {
                "topic": f"Evolution testing ({kw})",
                "statement_a": {"text": sentence, "timestamp": "01:00"},
                "statement_b": {"text": "Current systems operate on distributed gRPC clusters.", "timestamp": "10:00"},
                "nuance": f"Temporal evolution marker: {kw} observed across system generations."
            }
            res = classify_contradictions([item])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["classification"], "TEMPORAL_EVOLUTION", f"Failed for temporal keyword '{kw}'")
            self.assertFalse(res[0]["is_logical_conflict"])

    def test_conditional_qualification_markers(self):
        """Keywords such as 'trade-off', 'depends', 'at scale', 'in memory' classify as CONDITIONAL_QUALIFICATION."""
        conditional_cases = [
            ("trade-off", "Trade-off between latency and durability."),
            ("depends", "Whether to shard depends on query access patterns."),
            ("at scale", "At scale, distributed caches become network-bound."),
            ("in memory", "In memory storage provides nanosecond reads but lacks durability."),
            ("small scale", "For small scale deployments, a single Postgres instance suffices."),
            ("high load", "Under high load, thread pools can become exhausted."),
            ("context-dependent", "Optimal garbage collection parameters are context-dependent.")
        ]

        for kw, sentence in conditional_cases:
            item = {
                "topic": f"Conditionality testing ({kw})",
                "statement_a": {"text": sentence, "timestamp": "02:00"},
                "statement_b": {"text": "Simpler architectures minimize operational complexity.", "timestamp": "05:00"},
                "nuance": f"Analysis involves a {kw} qualification."
            }
            res = classify_contradictions([item])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["classification"], "CONDITIONAL_QUALIFICATION", f"Failed for conditional keyword '{kw}'")
            self.assertFalse(res[0]["is_logical_conflict"])

    def test_perspective_divergence_speakers_and_markers(self):
        """Distinct named speakers or perspective keywords classify as PERSPECTIVE_DIVERGENCE."""
        # Test distinct speakers without nuance keywords -> triggers Rule 2 (speaker names in rationale)
        speaker_item = {
            "topic": "Microservices vs Monolith",
            "statement_a": {"speaker": "Dr. Alice Vance", "text": "Microservices introduce unmanageable network complexity."},
            "statement_b": {"speaker": "Prof. Bob Chen", "text": "Microservices are mandatory for multi-team organizational autonomy."},
            "nuance": "Opposing architectural philosophies."
        }
        res_spk = classify_contradictions([speaker_item])
        self.assertEqual(len(res_spk), 1)
        self.assertEqual(res_spk[0]["classification"], "PERSPECTIVE_DIVERGENCE")
        self.assertFalse(res_spk[0]["is_logical_conflict"])
        self.assertIn("Dr. Alice Vance", res_spk[0]["rationale"])
        self.assertIn("Prof. Bob Chen", res_spk[0]["rationale"])

        # Test perspective keywords in nuance (Rule 1)
        perspective_cases = ["perspective", "study", "viewpoint", "debate", "school of thought", "researchers"]
        for kw in perspective_cases:
            item = {
                "topic": f"Perspective marker ({kw})",
                "statement_a": {"text": "Clean Architecture strictly decouples entities from frameworks."},
                "statement_b": {"text": "Pragmatic developers favor vertical slice architecture."},
                "nuance": f"Represents a divergent {kw} among senior architects."
            }
            res = classify_contradictions([item])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["classification"], "PERSPECTIVE_DIVERGENCE", f"Failed for perspective keyword '{kw}'")
            self.assertFalse(res[0]["is_logical_conflict"])

    def test_generic_speakers_do_not_falsely_trigger_perspective_divergence(self):
        """Generic labels like 'Speaker' or 'Narrator' alone must not trigger PERSPECTIVE_DIVERGENCE."""
        item = {
            "topic": "Memory Allocation",
            "statement_a": {"speaker": "Speaker", "text": "Static allocation prevents fragmentation."},
            "statement_b": {"speaker": "Speaker", "text": "Dynamic heap allocation causes out-of-memory errors."},
            "nuance": "Direct opposing assertions."
        }
        res = classify_contradictions([item])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["classification"], "DIRECT_CONTRADICTION")
        self.assertTrue(res[0]["is_logical_conflict"])

    def test_transcript_context_triggers_syntactic_qualification(self):
        """When nuance is absent, surrounding transcript segments trigger syntax-based classification."""
        segments = [
            {"start": 10.0, "duration": 5.0, "text": "However, at scale this approach degrades."},
            {"start": 30.0, "duration": 5.0, "text": "In the past, engineers relied strictly on physical mainframes."}
        ]

        # Conditional syntax in transcript
        cond_item = {
            "topic": "Scaling behaviour",
            "statement_a": {"text": "Simple hashing is fine.", "seconds": 12.0},
            "statement_b": {"text": "Hashing collapses.", "seconds": 14.0},
            "nuance": ""
        }
        res_cond = classify_contradictions([cond_item], transcript_segments=segments)
        self.assertEqual(res_cond[0]["classification"], "CONDITIONAL_QUALIFICATION")

        # Temporal syntax in transcript
        temp_item = {
            "topic": "Mainframe evolution",
            "statement_a": {"text": "Mainframes were ubiquitous.", "seconds": 32.0},
            "statement_b": {"text": "Cloud computing is ubiquitous.", "seconds": 34.0},
            "nuance": ""
        }
        res_temp = classify_contradictions([temp_item], transcript_segments=segments)
        self.assertEqual(res_temp[0]["classification"], "TEMPORAL_EVOLUTION")

    def test_graceful_empty_and_malformed_contradictions(self):
        """Empty lists, non-dictionary items, or missing keys do not raise unhandled exceptions."""
        self.assertEqual(classify_contradictions([]), [])
        self.assertEqual(classify_contradictions(None), [])
        self.assertEqual(classify_contradictions(["invalid string", 1234, None]), [])

        sparse_item = {"topic": "Sparse contradiction"}
        res = classify_contradictions([sparse_item])
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["classification"], "DIRECT_CONTRADICTION")
        self.assertTrue(res[0]["is_logical_conflict"])


class TestAdversarialStressAndScale(unittest.TestCase):
    """Stress testing scale, throughput, and exotic unicode/emoji boundaries."""

    def test_high_volume_bloom_quiz_throughput(self):
        """Processes 2,000 quiz items with high throughput and accurate filtering."""
        import time

        items = []
        # 1,000 valid items
        for i in range(1000):
            items.append({
                "question": f"Question {i:04d}: What is the primary characteristic of distributed consensus protocol #{i}?",
                "options": [f"Option A {i}", f"Option B {i}", f"Option C {i}", f"Option D {i}"],
                "correct_index": i % 4,
                "bloom_level": ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"][i % 6]
            })
        # 1,000 malformed items (stems too short, <= 3 options, duplicate options, invalid tiers)
        for i in range(1000):
            items.append({
                "question": "Why?",  # malformed stem
                "options": [f"Option {i}", f"Option {i}"],  # malformed duplicate & length
                "correct_index": 0,
                "bloom_level": "RandomGuessing"
            })

        t0 = time.perf_counter()
        validated, all_valid = validate_bloom_quiz(items)
        elapsed = time.perf_counter() - t0

        self.assertFalse(all_valid)
        self.assertEqual(len(validated), 1000)
        self.assertLess(elapsed, 2.0, f"2,000 items took {elapsed:.3f}s, expected < 2.0s")

    def test_high_volume_contradictions_throughput(self):
        """Processes 2,000 contradiction items across all 4 categories in < 1.0 second."""
        import time

        items = []
        for i in range(500):
            # Direct contradiction
            items.append({
                "topic": f"Throughput {i}",
                "statement_a": f"Benchmark is {i} req/sec.",
                "statement_b": f"Benchmark is {i + 10000} req/sec.",
                "nuance": "Direct metric conflict."
            })
            # Temporal evolution
            items.append({
                "topic": f"Protocol evolution {i}",
                "statement_a": f"Formerly used protocol v{i}.",
                "statement_b": f"Now migrated to protocol v{i + 1}.",
                "nuance": "Historical timeline progression."
            })
            # Conditional qualification
            items.append({
                "topic": f"Caching scale {i}",
                "statement_a": f"Local memory cache {i}.",
                "statement_b": f"Distributed Redis cache {i}.",
                "nuance": "Trade-off depending on scale and memory footprint."
            })
            # Perspective divergence
            items.append({
                "topic": f"Design debate {i}",
                "statement_a": {"speaker": f"Architect Alpha {i}", "text": "Favors microservices."},
                "statement_b": {"speaker": f"Architect Beta {i}", "text": "Favors monoliths."},
                "nuance": "Architectural school of thought."
            })

        t0 = time.perf_counter()
        classified = classify_contradictions(items)
        elapsed = time.perf_counter() - t0

        self.assertEqual(len(classified), 2000)
        self.assertLess(elapsed, 1.0, f"2,000 contradictions took {elapsed:.3f}s, expected < 1.0s")

        counts = {}
        for c in classified:
            cls = c["classification"]
            counts[cls] = counts.get(cls, 0) + 1

        self.assertEqual(counts.get("DIRECT_CONTRADICTION", 0), 500)
        self.assertEqual(counts.get("TEMPORAL_EVOLUTION", 0), 500)
        self.assertEqual(counts.get("CONDITIONAL_QUALIFICATION", 0), 500)
        self.assertEqual(counts.get("PERSPECTIVE_DIVERGENCE", 0), 500)

    def test_unicode_emojis_and_multilingual_inputs(self):
        """Handles non-ASCII scripts (Greek, Japanese) and emojis gracefully."""
        quiz = [
            {
                "question": "Τι είναι το θεώρημα CAP στα κατανεμημένα συστήματα;",  # Greek
                "options": ["🚀 Συνέπεια και Διαθεσιμότητα", "🐢 Μόνο Διαθεσιμότητα", "💾 Αποθήκευση Μνήμης", "🔒 Κλειδώματα"],
                "correct_index": 0,
                "bloom_level": "understand"
            },
            {
                "question": "分散システムにおけるPaxosアルゴリズムの主な目的は何ですか？",  # Japanese
                "options": ["A. 合意形成", "B. データの圧縮", "C. ルーティング", "D. 暗号化"],
                "correct_index": "A",
                "bloom_level": "Apply"
            }
        ]
        validated, all_valid = validate_bloom_quiz(quiz)
        self.assertTrue(all_valid)
        self.assertEqual(len(validated), 2)
        self.assertEqual(validated[0]["options"][0], "🚀 Συνέπεια και Διαθεσιμότητα")
        self.assertEqual(validated[1]["options"][0], "合意形成")  # Stripped 'A. '
        self.assertEqual(validated[1]["correct_index"], 0)


class TestWorkerAndPipelineFidelity(unittest.TestCase):
    """Verifies integration of F12 and F13 into Workers and Orchestrator."""

    def test_learning_worker_robustness_with_adversarial_ai_data(self):
        """run_learning_worker filters out adversarial items and returns only conforming cards/quizzes."""
        from services.workers.learning_worker import run_learning_worker

        adversarial_payload = {
            "learning": {
                "key_definitions": [{"term": "T", "definition": "D"}],
                "flashcards": [
                    {"front": "Valid Term", "back": "Valid Definition"},
                    {"front": "Invalid", "back": "Invalid"},             # front == back
                    {"front": "", "back": "Empty front"},                 # empty front
                    {"front": "No Concept", "back": "Applies Default"}   # defaults to Core Concept
                ],
                "quiz": [
                    {
                        "question": "What is the primary trade-off of Paxos?",
                        "options": ["Latency", "Throughput", "Complexity", "Memory"],
                        "correct_index": "A",
                        "bloom_level": "Analyze"
                    },
                    {
                        "question": "Bad?",                               # stem <= 5 chars
                        "options": ["A", "B", "C", "D"],
                        "correct_index": 0,
                        "bloom_level": "Remember"
                    },
                    {
                        "question": "What about invalid Bloom level?",
                        "options": ["O1", "O2", "O3", "O4"],
                        "correct_index": 0,
                        "bloom_level": "FakeLevel123"                     # invalid tier
                    }
                ]
            }
        }

        res = run_learning_worker([], {}, raw_analysis=adversarial_payload)
        self.assertTrue(res["success"])
        data = res["data"]

        # Only 2 valid flashcards should survive
        self.assertEqual(len(data["flashcards"]), 2)
        self.assertEqual(data["flashcards"][0]["front"], "Valid Term")
        self.assertEqual(data["flashcards"][1]["concept"], "Core Concept")

        # Only 1 valid quiz item should survive
        self.assertEqual(len(data["quizzes"]), 1)
        self.assertEqual(data["quizzes"][0]["bloom_level"], "Analyze")
        self.assertEqual(data["quizzes"][0]["correct_index"], 0)

    def test_claim_worker_contradiction_enrichment(self):
        """run_claim_worker enriches contradictions with taxonomy classifications."""
        from services.workers.claim_worker import run_claim_worker

        segments = [{"start": 0.0, "duration": 30.0, "text": "Distributed systems scale horizontally."}]
        metadata = {"duration_seconds": 60, "author": "Tech Academy"}
        raw_analysis = {
            "claims": [{"statement": "Distributed systems scale horizontally.", "seconds": 0}],
            "contradictions": [
                {
                    "topic": "Scaling Limits",
                    "statement_a": {"text": "Horizontal scaling is infinite."},
                    "statement_b": {"text": "Network coordination limits horizontal scale."},
                    "nuance": "Trade-off depending on network latency and consensus overhead."
                }
            ]
        }

        res = run_claim_worker(segments, metadata, raw_analysis=raw_analysis)
        self.assertTrue(res["success"])
        data = res["data"]
        contras = data["contradictions"]
        self.assertEqual(len(contras), 1)
        self.assertEqual(contras[0]["classification"], "CONDITIONAL_QUALIFICATION")
        self.assertFalse(contras[0]["is_logical_conflict"])
        self.assertGreaterEqual(contras[0]["confidence"], 0.80)


if __name__ == "__main__":
    unittest.main()

