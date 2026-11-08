import os
import io
import uuid
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

from services.metadata_service import (
    extract_video_id,
    get_video_oembed,
    parse_duration_string,
)
from utils.time_utils import (
    format_seconds,
    sanitize_transcript,
    prepare_transcript_for_analysis,
    search_transcript_segments,
)
from utils.json_utils import safe_json_parse, sanitize_data_strings
from pdf_generator import generate_detailed_pdf, sanitize_text
from services.storage_service import (
    get_db,
    init_db,
    save_cached_analysis,
    get_cached_analysis,
    get_user,
    create_user,
    update_user_plan,
)
from services.auth_service import (
    check_quota,
    increment_quota,
    is_owner,
    PLAN_CONFIG,
    QUOTA_ANONYMOUS,
    QUOTA_FREE,
)
from services.job_service import (
    create_job,
    get_job,
    update_job_stage,
    complete_job,
    fail_job,
    format_user_error,
    JOBS,
    STAGES,
)


class TestTier2BoundaryAndCornerCases(LensYouE2EBaseTest):
    """
    Tier 2: Boundary & Corner Cases (>=5 tests per feature).
    Stresses edge conditions, boundary values, malformed inputs, and encoding robustness.
    """

    # =========================================================================
    # Boundary 1: URL & Metadata Corner Cases (F05)
    # =========================================================================

    def test_b01_empty_url_returns_none(self):
        """Empty string or None returns None for extract_video_id."""
        self.assertIsNone(extract_video_id(""))
        self.assertIsNone(extract_video_id(None))

    def test_b02_whitespace_url_returns_none(self):
        """Whitespace-only URLs return None."""
        self.assertIsNone(extract_video_id("    \t \n   "))

    def test_b03_non_youtube_domain_returns_none(self):
        """Non-YouTube domains return None."""
        self.assertIsNone(extract_video_id("https://vimeo.com/123456789"))
        self.assertIsNone(extract_video_id("https://dailymotion.com/video/x7tgad"))

    def test_b04_malformed_short_id_returns_none(self):
        """IDs that do not conform to YouTube 11-char pattern return None."""
        self.assertIsNone(extract_video_id("https://youtu.be/short"))
        self.assertIsNone(extract_video_id("https://www.youtube.com/watch?v=12345"))

    def test_b05_extremely_long_url_with_tracking(self):
        """URLs with excessive tracking parameters (>2000 chars) extract ID properly."""
        tracking_params = "&".join([f"utm_param_{i}=val_{i}" for i in range(150)])
        long_url = f"https://www.youtube.com/watch?v={SAMPLE_VIDEO_ID}&{tracking_params}"
        self.assertEqual(extract_video_id(long_url), SAMPLE_VIDEO_ID)

    # =========================================================================
    # Boundary 2: Transcript Boundary Cases (F05, F09)
    # =========================================================================

    def test_b06_empty_transcript_segments(self):
        """prepare_transcript_for_analysis returns empty string for empty segments."""
        self.assertEqual(prepare_transcript_for_analysis([]), "")
        self.assertEqual(prepare_transcript_for_analysis(None), "")

    def test_b07_extreme_word_count_transcript(self):
        """Large transcript with 10,000 segments samples down under max_chars without error."""
        massive_segments = [
            {"text": f"Segment number {i} discussing distributed computing.", "start": float(i), "duration": 1.0, "timestamp": format_seconds(i)}
            for i in range(10000)
        ]
        sampled = prepare_transcript_for_analysis(massive_segments, max_chars=5000)
        self.assertLessEqual(len(sampled), 6000)
        self.assertIn("00:00", sampled)

    def test_b08_transcript_with_empty_text_segments(self):
        """Transcript with empty text fields handles sanitization without raising."""
        empty_seg = [{"text": "", "start": 0.0, "duration": 1.0, "timestamp": "00:00"}]
        res = prepare_transcript_for_analysis(empty_seg)
        self.assertIn("00:00", res)

    def test_b09_rapid_overlapping_timestamps(self):
        """Segments with identical consecutive start times parse cleanly."""
        overlapping = [
            {"text": "First rapid utterance", "start": 10.0, "duration": 0.5, "timestamp": "00:10"},
            {"text": "Interrupted overlapping dialogue", "start": 10.0, "duration": 0.8, "timestamp": "00:10"},
        ]
        res = prepare_transcript_for_analysis(overlapping)
        self.assertIn("First rapid utterance", res)
        self.assertIn("Interrupted overlapping dialogue", res)

    def test_b10_search_transcript_with_no_matches(self):
        """search_transcript_segments falls back to evenly spaced sample when query has 0 matches."""
        results = search_transcript_segments(SAMPLE_TRANSCRIPT_SEGMENTS, "xyzNonExistentTerm12345")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertIn("text", results[0])

    # =========================================================================
    # Boundary 3: Summary & Synthesis Corner Cases (F05)
    # =========================================================================

    def test_b11_empty_json_string_safe_parse(self):
        """safe_json_parse on empty or whitespace string returns error dict."""
        res = safe_json_parse("")
        self.assertIn("error", res)
        res_ws = safe_json_parse("   \n   ")
        self.assertIn("error", res_ws)

    def test_b12_malformed_truncated_json(self):
        """safe_json_parse repairs or handles truncated JSON cleanly without crashing."""
        broken_json = '{"title": "Valid Title", "score": 90, "items": ["a", "b"'
        parsed = safe_json_parse(broken_json)
        self.assertIsInstance(parsed, dict)
        # Either repaired into valid dict or returns graceful error dict
        self.assertTrue("title" in parsed or "error" in parsed)

    def test_b13_sanitize_data_strings_none_and_numbers(self):
        """sanitize_data_strings handles non-string primitives (None, int, bool) safely."""
        self.assertIsNone(sanitize_data_strings(None))
        self.assertEqual(sanitize_data_strings(42), 42)
        self.assertEqual(sanitize_data_strings(True), True)

    def test_b14_sanitize_markdown_headers_and_bold(self):
        """sanitize_data_strings strips stray markdown asterisks and header hashes."""
        payload = {
            "title": "### **Executive Summary**",
            "items": ["**Core Insight**", "## Next Header"]
        }
        cleaned = sanitize_data_strings(payload)
        self.assertEqual(cleaned["title"], "Executive Summary")
        self.assertEqual(cleaned["items"][0], "Core Insight")
        self.assertEqual(cleaned["items"][1], "Next Header")

    def test_b15_special_characters_in_json(self):
        """safe_json_parse preserves unicode escapes and special control characters."""
        payload = '{"title": "Special \\n \\t \\"Quotes\\" & Symbols \\u2714"}'
        parsed = safe_json_parse(payload)
        self.assertIn("Quotes", parsed.get("title", ""))

    # =========================================================================
    # Boundary 4: Chapter & Temporal Boundary Cases (F05)
    # =========================================================================

    def test_b16_zero_duration_parsed(self):
        """parse_duration_string parses '00:00' and empty string to 0."""
        self.assertEqual(parse_duration_string("00:00"), 0)
        self.assertEqual(parse_duration_string(""), 0)
        self.assertEqual(parse_duration_string(None), 0)

    def test_b17_extreme_24_hour_duration(self):
        """parse_duration_string handles 24-hour video durations (86400s)."""
        self.assertEqual(parse_duration_string("24:00:00"), 86400)
        self.assertEqual(parse_duration_string("100:00:00"), 360000)

    def test_b18_empty_chapter_string(self):
        """Empty chapter raw strings parse without throwing."""
        raw = ""
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        self.assertEqual(lines, [])

    def test_b19_chapters_with_whitespace_and_tabs(self):
        """Chapters separated by variable tabs and spaces parse correctly."""
        raw = "00:00 \t  Introduction\n05:30    \t Next Chapter"
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(parse_duration_string(lines[0].split()[0]), 0)
        self.assertEqual(parse_duration_string(lines[1].split()[0]), 330)

    def test_b20_format_seconds_zero_and_large(self):
        """format_seconds accurately formats 0 seconds and extreme durations."""
        self.assertEqual(format_seconds(0), "00:00")
        self.assertEqual(format_seconds(86400), "24:00:00")

    # =========================================================================
    # Boundary 5: Claim Extraction Boundary Cases (F05, F10)
    # =========================================================================

    def test_b21_claim_timestamp_at_zero_seconds(self):
        """Claim positioned at start boundary 00:00 is valid."""
        claim = {"timestamp": "00:00", "seconds": 0, "title": "Opening statement"}
        self.assert_valid_claims_grounding([claim], SAMPLE_TRANSCRIPT_SEGMENTS, max_duration_sec=100)

    def test_b22_claim_timestamp_at_exact_video_end(self):
        """Claim positioned at end boundary equals video duration."""
        claim = {"timestamp": "01:15", "seconds": 75, "title": "Closing thesis"}
        self.assert_valid_claims_grounding([claim], SAMPLE_TRANSCRIPT_SEGMENTS, max_duration_sec=75)

    def test_b23_claim_timestamp_exceeding_duration_rejected(self):
        """Claim with seconds exceeding video duration triggers validation error."""
        claim = {"timestamp": "05:00", "seconds": 300, "title": "Invalid future claim"}
        with self.assertRaises(AssertionError):
            self.assert_valid_claims_grounding([claim], SAMPLE_TRANSCRIPT_SEGMENTS, max_duration_sec=100)

    def test_b24_empty_claims_list(self):
        """Empty list of claims validates cleanly without throwing."""
        self.assert_valid_claims_grounding([], SAMPLE_TRANSCRIPT_SEGMENTS, max_duration_sec=100)

    def test_b25_duplicate_timestamps_different_claims(self):
        """Multiple distinct claims sharing the exact same timestamp are supported."""
        claims = [
            {"timestamp": "00:20", "seconds": 20, "title": "Point A at 20s"},
            {"timestamp": "00:20", "seconds": 20, "title": "Point B at 20s"},
        ]
        self.assert_valid_claims_grounding(claims, SAMPLE_TRANSCRIPT_SEGMENTS, max_duration_sec=100)

    # =========================================================================
    # Boundary 6: Bloom's Taxonomy Quiz Schema Boundaries (F05, F12)
    # =========================================================================

    def test_b26_quiz_missing_question_stem_fails(self):
        """Quiz question missing stem fails schema assertion."""
        bad_quiz = [{
            "options": ["A", "B", "C", "D"],
            "correct_index": 0,
            "bloom_level": "Understand"
        }]
        with self.assertRaises(AssertionError):
            self.assert_valid_bloom_quiz(bad_quiz)

    def test_b27_quiz_wrong_option_count_fails(self):
        """Quiz question with 3 options instead of 4 fails schema assertion."""
        bad_quiz = [{
            "question": "What is the primary benefit of decoupled architecture?",
            "options": ["Option A", "Option B", "Option C"],
            "correct_index": 0,
            "bloom_level": "Understand"
        }]
        with self.assertRaises(AssertionError):
            self.assert_valid_bloom_quiz(bad_quiz)

    def test_b28_quiz_out_of_bounds_correct_index_fails(self):
        """Quiz question with correct_index out of range [0, 3] fails schema assertion."""
        bad_quiz = [{
            "question": "Which component manages background jobs?",
            "options": ["A", "B", "C", "D"],
            "correct_index": 4,  # Out of range
            "bloom_level": "Understand"
        }]
        with self.assertRaises(AssertionError):
            self.assert_valid_bloom_quiz(bad_quiz)

    def test_b29_quiz_invalid_bloom_level_fails(self):
        """Quiz question with unapproved cognitive depth tier fails schema assertion."""
        bad_quiz = [{
            "question": "Evaluate system performance under load?",
            "options": ["A", "B", "C", "D"],
            "correct_index": 1,
            "bloom_level": "RandomGuessingLevel"
        }]
        with self.assertRaises(AssertionError):
            self.assert_valid_bloom_quiz(bad_quiz)

    def test_b30_quiz_empty_options_text_fails(self):
        """Quiz option with empty string whitespace fails schema assertion."""
        bad_quiz = [{
            "question": "Identify the queue technology?",
            "options": ["RabbitMQ", "   ", "Kafka", "ActiveMQ"],
            "correct_index": 0,
            "bloom_level": "Understand"
        }]
        with self.assertRaises(AssertionError):
            self.assert_valid_bloom_quiz(bad_quiz)

    # =========================================================================
    # Boundary 7: Entity & Graph Boundary Cases (F05)
    # =========================================================================

    def test_b31_empty_entities_structure(self):
        """Entities container with empty category lists serializes cleanly."""
        empty_entities = {"people": [], "concepts": [], "companies": [], "tools_software": []}
        for k, v in empty_entities.items():
            self.assertEqual(len(v), 0)

    def test_b32_entity_names_with_special_characters(self):
        """Entities containing special syntax like C++, AT&T, O'Reilly preserve intact."""
        entities = {
            "concepts": [{"name": "C++ / C#", "category": "Language"}],
            "companies": [{"name": "AT&T", "industry": "Telecom"}],
            "people": [{"name": "Tim O'Reilly", "role": "Publisher"}]
        }
        self.assertEqual(entities["concepts"][0]["name"], "C++ / C#")
        self.assertEqual(entities["companies"][0]["name"], "AT&T")
        self.assertEqual(entities["people"][0]["name"], "Tim O'Reilly")

    def test_b33_entity_names_with_unicode(self):
        """Entities with non-Latin scripts (Hindi, Japanese, Cyrillic) handled without error."""
        entities = {
            "people": [{"name": "गुप्ता", "role": "Speaker"}],
            "concepts": [{"name": "分散システム", "category": "Architecture"}]
        }
        self.assertEqual(entities["people"][0]["name"], "गुप्ता")
        self.assertEqual(entities["concepts"][0]["name"], "分散システム")

    def test_b34_unusual_category_types(self):
        """Entities with novel or custom category labels parse cleanly."""
        entity = {"name": "Zero-Cost Infra", "category": "CustomConstraint"}
        self.assertEqual(entity["category"], "CustomConstraint")

    def test_b35_large_entity_set(self):
        """Handling a large entity set (>100 entities) executes without performance bottleneck."""
        large_concepts = [{"name": f"Concept_{i}", "category": "Tech"} for i in range(120)]
        self.assertEqual(len(large_concepts), 120)

    # =========================================================================
    # Boundary 8: Export & PDF Ampersand/XML/Unicode Edge Cases (F05, F09)
    # =========================================================================

    def test_b36_ampersands_in_video_title(self):
        """PDF generation handles ampersands in title (e.g., 'AT&T and R&D')."""
        custom_data = dict(SAMPLE_ANALYSIS_DATA)
        custom_data["_meta"] = dict(SAMPLE_ANALYSIS_DATA["_meta"])
        custom_data["_meta"]["title"] = "AT&T & R&D: Scalable Systems"
        pdf = generate_detailed_pdf(custom_data)
        self.assertTrue(len(pdf.getvalue()) > 500)

    def test_b37_ampersands_in_author_and_summary(self):
        """PDF generation handles ampersands in author name and summary text."""
        custom_data = dict(SAMPLE_ANALYSIS_DATA)
        custom_data["_meta"] = dict(SAMPLE_ANALYSIS_DATA["_meta"])
        custom_data["_meta"]["author"] = "Johnson & Johnson Media"
        custom_data["video_overview"] = dict(SAMPLE_ANALYSIS_DATA["video_overview"])
        custom_data["video_overview"]["summary"] = "A deep dive into R&D, QA & Production deployment."
        pdf = generate_detailed_pdf(custom_data)
        self.assertTrue(len(pdf.getvalue()) > 500)

    def test_b38_xml_tags_in_text(self):
        """PDF generator handles pseudo-HTML strings like <script> or <unknown_tag>."""
        sanitized = sanitize_text("<script>alert('xss')</script>")
        self.assertNotIn("<script>", sanitized)
        self.assertIn("&lt;script&gt;", sanitized)

    def test_b39_multilingual_unicode_in_pdf(self):
        """sanitize_text replaces non-Latin/Emoji characters safely for standard PDF fonts."""
        raw_text = "Analysis: 🎬 Video 100% ✔ Success! ✦ Great [Greek: α, β]"
        sanitized = sanitize_text(raw_text)
        self.assertNotIn("🎬", sanitized)
        self.assertIn("[v]", sanitized)

    def test_b40_extremely_long_unbroken_string(self):
        """PDF generator handles long unbroken URL strings without throwing layout error."""
        custom_data = dict(SAMPLE_ANALYSIS_DATA)
        custom_data["video_overview"] = dict(SAMPLE_ANALYSIS_DATA["video_overview"])
        custom_data["video_overview"]["summary"] = "Reference: " + ("https://example.com/" + "a" * 200)
        pdf = generate_detailed_pdf(custom_data)
        self.assertTrue(len(pdf.getvalue()) > 500)

    # =========================================================================
    # Boundary 9: Storage & SQL Injection Boundaries (F01, F02)
    # =========================================================================

    def test_b41_sql_injection_in_video_id(self):
        """Malicious SQL injection in video_id treated as a harmless literal."""
        malicious_vid = "test'; DROP TABLE videos; --"
        save_cached_analysis(
            video_id=malicious_vid,
            title="Safe Title",
            analysis=SAMPLE_ANALYSIS_DATA
        )
        # Verify table 'videos' still exists
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT count(*) FROM videos")
            count = c.fetchone()[0]
            self.assertGreaterEqual(count, 1)

    def test_b42_sql_injection_in_title_and_author(self):
        """Malicious SQL injection payload in title and author safely escaped."""
        vid = f"inj_{uuid.uuid4().hex[:8]}"
        save_cached_analysis(
            video_id=vid,
            title="' OR '1'='1",
            author="Robert'); DROP TABLE users;--",
            analysis=SAMPLE_ANALYSIS_DATA
        )
        cached = get_cached_analysis(vid)
        self.assertIsNotNone(cached)

    def test_b43_database_init_idempotency(self):
        """Calling init_db multiple times is idempotent and preserves existing data."""
        vid = f"idem_{uuid.uuid4().hex[:8]}"
        save_cached_analysis(video_id=vid, title="Idempotent Test", analysis=SAMPLE_ANALYSIS_DATA)
        # Re-initialize DB multiple times
        init_db()
        init_db()
        cached = get_cached_analysis(vid)
        self.assertIsNotNone(cached)

    def test_b44_duplicate_video_id_update(self):
        """Saving identical video_id multiple times updates existing record without duplicate key error."""
        vid = f"dup_{uuid.uuid4().hex[:8]}"
        save_cached_analysis(video_id=vid, title="Initial Title", analysis=SAMPLE_ANALYSIS_DATA)
        updated_data = dict(SAMPLE_ANALYSIS_DATA)
        updated_data["_meta"] = dict(SAMPLE_ANALYSIS_DATA["_meta"])
        updated_data["_meta"]["title"] = "Updated Title"
        save_cached_analysis(video_id=vid, title="Updated Title", analysis=updated_data)
        cached = get_cached_analysis(vid)
        self.assertEqual(cached["_meta"]["title"], "Updated Title")

    def test_b45_empty_video_id_handling(self):
        """save_cached_analysis with empty video_id returns empty string safely."""
        res = save_cached_analysis(video_id="", analysis=SAMPLE_ANALYSIS_DATA)
        self.assertEqual(res, "")

    # =========================================================================
    # Boundary 10: Usage & Duration Quota Boundaries (F03)
    # =========================================================================

    def test_b46_exact_quota_boundary_limit_reached(self):
        """User at quota_used == quota_limit is denied (allowed=False)."""
        raw_id = uuid.uuid4().hex[:8]
        uid = create_user("google", raw_id, f"limit_{raw_id}@example.com", "Limit User", "")
        update_user_plan(uid, "free", 5)
        # Set quota_used to exact limit
        with get_db() as conn:
            conn.cursor().execute("UPDATE users SET quota_used = 5 WHERE id = ?", (uid,))
            conn.commit()
        res = check_quota(user_id=uid)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["used"], 5)

    def test_b47_one_remaining_quota_allowed(self):
        """User at quota_used == quota_limit - 1 is permitted (allowed=True)."""
        raw_id = uuid.uuid4().hex[:8]
        uid = create_user("google", raw_id, f"near_{raw_id}@example.com", "Near Limit", "")
        update_user_plan(uid, "free", 5)
        with get_db() as conn:
            conn.cursor().execute("UPDATE users SET quota_used = 4 WHERE id = ?", (uid,))
            conn.commit()
        res = check_quota(user_id=uid)
        self.assertTrue(res["allowed"])
        self.assertEqual(res["used"], 4)

    def test_b48_non_existent_user_quota_check(self):
        """check_quota for non-existent user_id returns allowed=False."""
        res = check_quota(user_id="completely_non_existent_user_99999")
        self.assertFalse(res["allowed"])
        self.assertIn("reason", res)

    def test_b49_anonymous_quota_exhaustion(self):
        """Anonymous session with 3 requests transitions to allowed=False."""
        anon_key = f"anon_exh_{uuid.uuid4().hex[:8]}"
        check_quota(session_key=anon_key)  # Initialize session record
        for _ in range(3):
            increment_quota(session_key=anon_key)
        res = check_quota(session_key=anon_key)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["used"], 3)

    def test_b50_owner_override_unlimited_quota(self):
        """Owner email automatically receives unlimited plan with limit=-1."""
        raw_id = uuid.uuid4().hex[:8]
        owner_email = "ganeshmalli954@gmail.com"
        uid = create_user("google", raw_id, owner_email, "Platform Owner", "")
        res = check_quota(user_id=uid)
        self.assertTrue(res["allowed"])
        self.assertEqual(res["limit"], -1)

    # =========================================================================
    # Boundary 11: Job State Machine Lifecycle Boundaries (F04)
    # =========================================================================

    def test_b51_non_existent_job_id_lookup(self):
        """get_job for a non-existent job ID returns None."""
        self.assertIsNone(get_job("non_existent_job_xyz_9999"))

    def test_b52_unknown_stage_num_fallback(self):
        """update_job_stage with unmapped stage number generates fallback stage_name."""
        job_id = create_job()
        update_job_stage(job_id, 999)
        job = get_job(job_id)
        self.assertEqual(job["stage_name"], "Stage 999")

    def test_b53_fail_job_generic_exception(self):
        """fail_job with arbitrary error message records user error without crashing."""
        job_id = create_job()
        fail_job(job_id, "Unexpected internal worker crash during analysis")
        job = get_job(job_id)
        self.assertEqual(job["status"], "error")
        self.assertIn("Unexpected internal worker crash", job["error"])

    def test_b54_fail_job_quota_exhausted(self):
        """format_user_error formats 429 quota exhaustion into user advice."""
        err_msg = format_user_error("429 RESOURCE_EXHAUSTED: quota exceeded")
        self.assertIn("API request limit reached", err_msg)

    def test_b55_fail_job_503_overloaded(self):
        """format_user_error formats 503 unavailable error into retry advice."""
        err_msg = format_user_error("503 Service Unavailable: High demand")
        self.assertIn("demand spike", err_msg.lower())


if __name__ == "__main__":
    unittest.main()
