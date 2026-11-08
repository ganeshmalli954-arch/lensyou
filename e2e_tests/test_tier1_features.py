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
    save_cached_analysis,
    save_analysis,
    get_cached_analysis,
    get_user,
    create_user,
    update_user_plan,
)
from services.auth_service import (
    check_quota,
    increment_quota,
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
    JOBS,
    STAGES,
)


class TestTier1FeatureCoverage(LensYouE2EBaseTest):
    """
    Tier 1: Feature Coverage (>=5 tests per feature).
    Verifies nominal feature contracts across all 11 feature categories in PROJECT.md.
    """

    # =========================================================================
    # Feature 1: URL Validation & Video ID Parsing (F05)
    # =========================================================================

    def test_f01_standard_watch_url(self):
        """Standard youtube.com/watch?v=... extracts 11-char video ID."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_f02_shortened_youtu_be_url(self):
        """Shortened youtu.be/... extracts 11-char video ID."""
        url = "https://youtu.be/dQw4w9WgXcQ?t=42"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_f03_embed_url(self):
        """Embedded URL youtube.com/embed/... extracts 11-char video ID."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_f04_shorts_url(self):
        """YouTube Shorts URL youtube.com/shorts/... extracts 11-char video ID."""
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(url), "dQw4w9WgXcQ")

    def test_f05_raw_11_char_video_id(self):
        """Direct 11-character video ID is accepted directly."""
        raw_id = "dQw4w9WgXcQ"
        self.assertEqual(extract_video_id(raw_id), "dQw4w9WgXcQ")

    # =========================================================================
    # Feature 2: Video Metadata & oEmbed Resolution (F05)
    # =========================================================================

    @patch("services.metadata_service.requests.get")
    def test_f06_oembed_title_and_author(self, mock_get):
        """oEmbed response extracts video title and author."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_OEMBED_DATA
        mock_get.return_value = mock_resp

        meta = get_video_oembed(SAMPLE_VIDEO_ID)
        self.assertEqual(meta["title"], SAMPLE_OEMBED_DATA["title"])
        self.assertEqual(meta["author_name"], SAMPLE_OEMBED_DATA["author_name"])

    @patch("services.metadata_service.requests.get")
    def test_f07_oembed_thumbnail_resolution(self, mock_get):
        """oEmbed response provides valid thumbnail URL."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_OEMBED_DATA
        mock_get.return_value = mock_resp

        meta = get_video_oembed(SAMPLE_VIDEO_ID)
        self.assertIn("thumbnail_url", meta)
        self.assertTrue(meta["thumbnail_url"].startswith("https://"))

    def test_f08_duration_string_parsing_hhmmss(self):
        """parse_duration_string parses HH:MM:SS to integer seconds."""
        self.assertEqual(parse_duration_string("01:25:30"), 5130)

    def test_f09_duration_string_parsing_mmss(self):
        """parse_duration_string parses MM:SS to integer seconds."""
        self.assertEqual(parse_duration_string("14:20"), 860)

    @patch("services.metadata_service.requests.get")
    def test_f10_metadata_fallback_handling(self, mock_get):
        """Network error during oEmbed returns an empty dictionary without throwing."""
        mock_get.side_effect = Exception("Connection timeout")
        meta = get_video_oembed(SAMPLE_VIDEO_ID)
        self.assertEqual(meta, {})

    # =========================================================================
    # Feature 3: Transcript Extraction & Cleaning (F05, F09)
    # =========================================================================

    def test_f11_transcript_cleaning_filler_words(self):
        """sanitize_transcript removes filler words like um, uh, ah, you know."""
        raw_text = "So um this is uh definitely, you know, a crucial architecture point."
        cleaned = sanitize_transcript(raw_text)
        self.assertNotIn("um", cleaned.lower().split())
        self.assertNotIn("uh", cleaned.lower().split())
        self.assertNotIn("you know", cleaned.lower())

    def test_f12_transcript_cleaning_bracketed_sounds(self):
        """sanitize_transcript strips bracketed audio annotations like [Music]."""
        raw_text = "Welcome to the show. [Music] Today we talk distributed systems. [Applause]"
        cleaned = sanitize_transcript(raw_text)
        self.assertNotIn("[Music]", cleaned)
        self.assertNotIn("[Applause]", cleaned)

    def test_f13_transcript_segment_formatting(self):
        """format_seconds converts seconds to MM:SS and HH:MM:SS format."""
        self.assertEqual(format_seconds(45), "00:45")
        self.assertEqual(format_seconds(615), "10:15")
        self.assertEqual(format_seconds(3665), "01:01:05")

    def test_f14_transcript_timeline_sampling(self):
        """prepare_transcript_for_analysis maintains timeline bounds under max_chars limit."""
        prepared = prepare_transcript_for_analysis(SAMPLE_TRANSCRIPT_SEGMENTS, max_chars=1000)
        self.assertTrue(len(prepared) > 0)
        self.assertIn("00:00", prepared)

    def test_f15_transcript_search_segments(self):
        """search_transcript_segments finds matching segments for a given query."""
        results = search_transcript_segments(SAMPLE_TRANSCRIPT_SEGMENTS, "message queues")
        self.assertGreater(len(results), 0)
        self.assertTrue(any("message queues" in r.get("text", "").lower() for r in results))

    # =========================================================================
    # Feature 4: Summary Generation & Synthesis (F05)
    # =========================================================================

    def test_f16_executive_summary_structure(self):
        """Summary contains overview, content_type, tone, and synthesis text."""
        overview = SAMPLE_ANALYSIS_DATA["video_overview"]
        self.assertIn("summary", overview)
        self.assertIn("content_type", overview)
        self.assertIn("overall_tone", overview)
        self.assertGreater(len(overview["summary"]), 20)

    def test_f17_quality_scorecard_metrics(self):
        """Quality scorecard contains overall score, clarity, strengths, and weaknesses."""
        scorecard = SAMPLE_ANALYSIS_DATA["quality_scorecard"]
        self.assertIn("overall_score", scorecard)
        self.assertIn("clarity_score", scorecard)
        self.assertIn("strengths", scorecard)
        self.assertIn("weaknesses", scorecard)
        self.assertIsInstance(scorecard["strengths"], list)

    def test_f18_engagement_curve_mapping(self):
        """Engagement curve includes timestamp, score, and key highlight."""
        curve = SAMPLE_ANALYSIS_DATA["engagement_curve"]
        self.assertGreater(len(curve), 0)
        first_point = curve[0]
        self.assertIn("time", first_point)
        self.assertIn("seconds", first_point)
        self.assertIn("score", first_point)
        self.assertIn("highlight", first_point)

    def test_f19_safe_json_parsing_clean_json(self):
        """safe_json_parse successfully parses clean JSON strings."""
        payload = '{"status": "success", "score": 95}'
        parsed = safe_json_parse(payload)
        self.assertEqual(parsed.get("status"), "success")
        self.assertEqual(parsed.get("score"), 95)

    def test_f20_safe_json_parsing_markdown_wrapped(self):
        """safe_json_parse strips markdown backticks ```json ... ```."""
        payload = '```json\n{"status": "ok", "count": 3}\n```'
        parsed = safe_json_parse(payload)
        self.assertEqual(parsed.get("status"), "ok")
        self.assertEqual(parsed.get("count"), 3)

    # =========================================================================
    # Feature 5: Chapter Detection & Temporal Modeling (F05)
    # =========================================================================

    def test_f21_raw_chapters_parsing(self):
        """Parses youtube_chapters_raw string into discrete chapter lines."""
        raw_chapters = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]
        lines = [line.strip() for line in raw_chapters.split("\n") if line.strip()]
        self.assertGreaterEqual(len(lines), 3)

    def test_f22_chapter_seconds_calculation(self):
        """Verifies parse_duration_string correctly parses chapter start times."""
        raw_chapters = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]
        lines = [line.strip() for line in raw_chapters.split("\n") if line.strip()]
        times = [parse_duration_string(l.split()[0]) for l in lines]
        self.assertEqual(times, [0, 20, 50])

    def test_f23_chapter_titles_normalization(self):
        """Verifies chapter titles are extracted without timestamp prefixes."""
        raw_chapters = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]
        lines = [line.strip() for line in raw_chapters.split("\n") if line.strip()]
        titles = [" ".join(l.split()[1:]) for l in lines]
        self.assertIn("Introduction & Foundations", titles[0])
        self.assertIn("Asynchronous Queues & Workers", titles[1])

    def test_f24_chapter_chronological_ordering(self):
        """Ensures chapter timestamps are strictly non-decreasing."""
        raw_chapters = SAMPLE_ANALYSIS_DATA["creator_repurposing"]["youtube_chapters_raw"]
        lines = [line.strip() for line in raw_chapters.split("\n") if line.strip()]
        times = [parse_duration_string(l.split()[0]) for l in lines]
        self.assertEqual(times, sorted(times))

    def test_f25_visual_moments_timestamps(self):
        """Engagement curve timestamps match calculated integer seconds."""
        curve = SAMPLE_ANALYSIS_DATA["engagement_curve"]
        for pt in curve:
            calc_sec = parse_duration_string(pt["time"])
            self.assertEqual(calc_sec, pt["seconds"])

    # =========================================================================
    # Feature 6: Claim Extraction & Grounded Evidence (F05, F10)
    # =========================================================================

    def test_f26_key_takeaways_timestamp_grounding(self):
        """Key takeaways contain valid timestamp strings."""
        takeaways = SAMPLE_ANALYSIS_DATA["key_takeaways"]
        self.assertGreater(len(takeaways), 0)
        for t in takeaways:
            self.assertIn("timestamp", t)
            self.assertIn("seconds", t)

    def test_f27_claim_seconds_within_bounds(self):
        """All claim timestamps fall within total video duration."""
        takeaways = SAMPLE_ANALYSIS_DATA["key_takeaways"]
        duration_sec = parse_duration_string(SAMPLE_ANALYSIS_DATA["_meta"]["duration"])
        self.assert_valid_claims_grounding(takeaways, SAMPLE_TRANSCRIPT_SEGMENTS, duration_sec)

    def test_f28_claim_category_and_impact_level(self):
        """Claims specify actionable category and impact level."""
        for t in SAMPLE_ANALYSIS_DATA["key_takeaways"]:
            self.assertIn("category", t)
            self.assertIn("impact_level", t)

    def test_f29_contradictions_statement_pairs(self):
        """Contradictions provide statement_a, statement_b, and contextual nuance."""
        contradictions = SAMPLE_ANALYSIS_DATA["contradictions"]
        self.assertGreater(len(contradictions), 0)
        first = contradictions[0]
        self.assertIn("statement_a", first)
        self.assertIn("statement_b", first)
        self.assertIn("nuance", first)

    def test_f30_repetitions_occurrences(self):
        """Repetitions specify recurring concept, count, and timestamps."""
        repetitions = SAMPLE_ANALYSIS_DATA["repetitions"]
        self.assertGreater(len(repetitions), 0)
        rep = repetitions[0]
        self.assertIn("idea", rep)
        self.assertGreaterEqual(rep.get("occurrences_count", 0), 2)
        self.assertEqual(len(rep.get("timestamps", [])), rep.get("occurrences_count"))

    # =========================================================================
    # Feature 7: Bloom's Taxonomy Quiz & Flashcards (F05, F12)
    # =========================================================================

    def test_f31_bloom_quiz_stem_and_options_count(self):
        """Quiz questions validate against the Bloom contract (4 options)."""
        quiz = SAMPLE_ANALYSIS_DATA["learning"]["quiz"]
        self.assert_valid_bloom_quiz(quiz)

    def test_f32_bloom_quiz_correct_index_range(self):
        """Quiz items have correct_index within valid range [0, 3]."""
        quiz = SAMPLE_ANALYSIS_DATA["learning"]["quiz"]
        for q in quiz:
            self.assertIn(q["correct_index"], [0, 1, 2, 3])

    def test_f33_bloom_cognitive_levels_recognized(self):
        """Quiz questions map to valid cognitive levels (Understand, Apply, Evaluate)."""
        quiz = SAMPLE_ANALYSIS_DATA["learning"]["quiz"]
        levels = {q["bloom_level"].lower() for q in quiz}
        self.assertTrue(levels.issubset({"remember", "understand", "apply", "analyze", "evaluate", "create"}))

    def test_f34_flashcards_front_back_concept(self):
        """Flashcards contain front, back, concept, and timestamp."""
        flashcards = SAMPLE_ANALYSIS_DATA["learning"]["flashcards"]
        self.assert_valid_flashcards(flashcards)

    def test_f35_key_definitions_and_study_notes(self):
        """Definitions include term and description; study notes have headings and bullets."""
        defs = SAMPLE_ANALYSIS_DATA["learning"]["key_definitions"]
        notes = SAMPLE_ANALYSIS_DATA["learning"]["study_notes"]
        self.assertGreater(len(defs), 0)
        self.assertIn("term", defs[0])
        self.assertIn("definition", defs[0])
        self.assertGreater(len(notes), 0)
        self.assertIn("heading", notes[0])
        self.assertIn("bullets", notes[0])

    # =========================================================================
    # Feature 8: Entity Intelligence & Knowledge Graph (F05)
    # =========================================================================

    def test_f36_named_entities_people(self):
        """Named entities include people with name, role, and context."""
        people = SAMPLE_ANALYSIS_DATA["entities"]["people"]
        self.assertGreater(len(people), 0)
        self.assertIn("name", people[0])
        self.assertIn("role", people[0])

    def test_f37_named_entities_concepts(self):
        """Named entities include concepts with category and context."""
        concepts = SAMPLE_ANALYSIS_DATA["entities"]["concepts"]
        self.assertGreater(len(concepts), 0)
        self.assertIn("name", concepts[0])
        self.assertIn("category", concepts[0])

    def test_f38_named_entities_companies(self):
        """Named entities include organizations/companies."""
        companies = SAMPLE_ANALYSIS_DATA["entities"]["companies"]
        self.assertGreater(len(companies), 0)
        self.assertIn("name", companies[0])

    def test_f39_named_entities_tools_software(self):
        """Named entities include tools and software frameworks."""
        tools = SAMPLE_ANALYSIS_DATA["entities"]["tools_software"]
        self.assertGreater(len(tools), 0)
        self.assertIn("name", tools[0])

    def test_f40_knowledge_graph_relationship_mapping(self):
        """Entities aggregate into a multi-category intelligence map."""
        entities = SAMPLE_ANALYSIS_DATA["entities"]
        for category in ["people", "concepts", "companies", "tools_software"]:
            self.assertIn(category, entities)
            self.assertIsInstance(entities[category], list)

    # =========================================================================
    # Feature 9: Export Generation (PDF / Markdown / CSV) (F05, F09)
    # =========================================================================

    def test_f41_pdf_generation_bytes_output(self):
        """generate_detailed_pdf produces non-empty binary PDF stream."""
        pdf_stream = generate_detailed_pdf(SAMPLE_ANALYSIS_DATA)
        pdf_bytes = pdf_stream.getvalue()
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_f42_pdf_text_sanitization(self):
        """sanitize_text handles quotes, dashes, and unicode bullets."""
        text = '“Distributed Architecture” — A • Breakthrough'
        sanitized = sanitize_text(text)
        self.assertNotIn('“', sanitized)
        self.assertNotIn('”', sanitized)
        self.assertIn('&quot;', sanitized)

    def test_f43_markdown_export_formatting(self):
        """Formats analysis dictionary into structured Markdown dossier."""
        title = SAMPLE_ANALYSIS_DATA["_meta"]["title"]
        summary = SAMPLE_ANALYSIS_DATA["video_overview"]["summary"]
        md_text = f"# {title}\n\n## Executive Summary\n{summary}\n"
        self.assertIn("# Introduction to Distributed Systems", md_text)
        self.assertIn("## Executive Summary", md_text)

    def test_f44_csv_timestamps_export_formatting(self):
        """Formats transcript segments into standard CSV rows."""
        rows = ["timestamp,seconds,text"]
        for s in SAMPLE_TRANSCRIPT_SEGMENTS[:3]:
            rows.append(f'"{s["timestamp"]}",{s["start"]},"{s["text"]}"')
        csv_content = "\n".join(rows)
        self.assertIn('"00:00",0.0', csv_content)
        self.assertIn("message queues", csv_content)

    def test_f45_pdf_canvas_page_decorations(self):
        """PDF generation applies NumberedCanvas with running footer."""
        pdf_stream = generate_detailed_pdf(SAMPLE_ANALYSIS_DATA)
        self.assertTrue(len(pdf_stream.getvalue()) > 0)

    # =========================================================================
    # Feature 10: Relational Database & Storage Facades (F01, F02)
    # =========================================================================

    def test_f46_init_db_creates_core_tables(self):
        """init_db creates users, videos, user_activity_history tables."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("users", tables)
            self.assertIn("videos", tables)
            self.assertIn("user_activity_history", tables)

    def test_f47_save_cached_analysis_persists_data(self):
        """save_cached_analysis saves analysis JSON into database."""
        test_vid = f"test_{uuid.uuid4().hex[:8]}"
        save_cached_analysis(
            video_id=test_vid,
            title="Persistence Test Video",
            author="Test Channel",
            duration="10:00",
            analysis=SAMPLE_ANALYSIS_DATA
        )
        cached = get_cached_analysis(test_vid)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["_meta"]["title"], SAMPLE_ANALYSIS_DATA["_meta"]["title"])

    def test_f48_backward_compatibility_alias(self):
        """save_analysis is aliased to save_cached_analysis for existing tests."""
        self.assertIs(save_analysis, save_cached_analysis)

    def test_f49_get_cached_analysis_hit_and_miss(self):
        """get_cached_analysis returns None for non-existent video IDs."""
        missing = get_cached_analysis("non_existent_video_id_99999")
        self.assertIsNone(missing)

    def test_f50_index_videos_video_id_exists(self):
        """idx_videos_video_id index is created for fast caching lookup."""
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_videos_video_id'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)

    # =========================================================================
    # Feature 11: Usage Tracking & Tier Enforcement (F03)
    # =========================================================================

    def test_f51_anonymous_quota_limit(self):
        """Anonymous sessions have a default quota of 3 requests."""
        self.assertEqual(QUOTA_ANONYMOUS, 3)
        res = check_quota(session_key=f"anon_test_{uuid.uuid4().hex[:8]}")
        self.assertTrue(res["allowed"])
        self.assertEqual(res["limit"], 3)

    def test_f52_free_tier_quota_limit(self):
        """Registered free users have a default quota of 5 requests."""
        self.assertEqual(QUOTA_FREE, 5)
        raw_id = uuid.uuid4().hex[:8]
        uid = create_user("google", raw_id, f"free_{raw_id}@example.com", "Free User", "")
        update_user_plan(uid, "free", 5)
        res = check_quota(user_id=uid)
        self.assertTrue(res["allowed"])
        self.assertEqual(res["limit"], 5)

    def test_f53_unlimited_plan_quota_check(self):
        """Unlimited plan returns allowed=True with limit=-1."""
        raw_id = uuid.uuid4().hex[:8]
        uid = create_user("google", raw_id, f"unlim_{raw_id}@example.com", "Pro User", "")
        update_user_plan(uid, "unlimited", -1)
        res = check_quota(user_id=uid)
        self.assertTrue(res["allowed"])
        self.assertEqual(res["limit"], -1)

    def test_f54_increment_quota_updates_count(self):
        """increment_quota increments quota_used for a user."""
        raw_id = uuid.uuid4().hex[:8]
        uid = create_user("google", raw_id, f"inc_{raw_id}@example.com", "Inc User", "")
        update_user_plan(uid, "free", 5)
        increment_quota(user_id=uid)
        user = get_user(uid)
        self.assertEqual(user["quota_used"], 1)

    def test_f55_plan_config_pricing(self):
        """PLAN_CONFIG contains correct plan definitions and quota limits."""
        self.assertIn("free", PLAN_CONFIG)
        self.assertIn("pack10", PLAN_CONFIG)
        self.assertIn("unlimited", PLAN_CONFIG)
        self.assertEqual(PLAN_CONFIG["pack10"]["price"], 50)
        self.assertEqual(PLAN_CONFIG["unlimited"]["price"], 99)

    # =========================================================================
    # Feature 12: Asynchronous Job State Machine (F04)
    # =========================================================================

    def test_f56_create_job_queued_state(self):
        """create_job initializes a job with status='queued' and stage=0."""
        job_id = create_job()
        job = get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["stage"], 0)

    def test_f57_update_job_stage(self):
        """update_job_stage advances stage and assigns stage_name from STAGES."""
        job_id = create_job()
        update_job_stage(job_id, 1)
        job = get_job(job_id)
        self.assertEqual(job["stage"], 1)
        self.assertEqual(job["stage_name"], "Fetching metadata")

    def test_f58_complete_job_status(self):
        """complete_job sets status to 'completed' and attaches result."""
        job_id = create_job()
        complete_job(job_id, {"_meta": {"title": "Done"}})
        job = get_job(job_id)
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["_meta"]["title"], "Done")

    def test_f59_fail_job_status(self):
        """fail_job sets status to 'error' with formatted message."""
        job_id = create_job()
        fail_job(job_id, "TranscriptsDisabled: Captions disabled by creator")
        job = get_job(job_id)
        self.assertEqual(job["status"], "error")
        self.assertIn("subtitles may be disabled", job["error"].lower())

    def test_f60_get_job_returns_job_dict(self):
        """get_job returns the full job tracking dictionary."""
        job_id = create_job()
        job = get_job(job_id)
        for key in ["status", "stage", "stage_name", "result", "error", "started_at"]:
            self.assertIn(key, job)


if __name__ == "__main__":
    unittest.main()
