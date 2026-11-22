"""
test_reliability_suite.py
Comprehensive automated test suite validating Milestone M1 Reliability Enhancements:
- R1: Module-Level Failure Reporting and Partial-Result Recovery
- R2: Evidence and Timestamp Validation
- R3: Duration-Weighted Credit and Resource Controls
"""

import unittest
import uuid
import os
import json
from unittest.mock import patch, MagicMock

from app import app
from services.orchestrator import (
    AsyncJobOrchestrator, STATUS_COMPLETED, STATUS_PARTIAL, STATUS_FAILED
)
from services.job_service import run_analysis_job, get_job, submit_or_attach, orchestrator
from services.storage_service import (
    create_user, get_user, update_user_quota, update_user_plan,
    get_anon_session, increment_anon_quota, save_analysis, get_modular_analysis,
    save_cached_analysis, get_cached_analysis
)
from services.usage_service import (
    calculate_credit_cost, parse_duration_seconds
)
from services.auth_service import (
    check_quota, increment_quota
)
from services.verification_service import (
    verify_grounded_claims, verify_grounded_insights,
    validate_evidence_citations, ground_copilot_response
)
from services.transcript_service import (
    normalize_transcript_segments
)
from services.workers import WorkerResult


def make_mock_metadata(video_id, duration_seconds=600, duration_str="10:00"):
    return WorkerResult(
        module="metadata",
        success=True,
        data={
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "title": f"Reliability Engineering Principles ({video_id})",
            "author": "Reliability Lead",
            "thumbnail_url": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
            "duration_seconds": duration_seconds,
            "duration": duration_str
        }
    )


def make_mock_transcript(video_id, duration_seconds=600, duration_str="10:00"):
    return WorkerResult(
        module="transcript",
        success=True,
        data={
            "segments": [
                {"id": f"seg_{video_id}_0", "segment_id": f"seg_{video_id}_0", "text": "Welcome to reliability engineering principles.", "start": 0.0, "duration": 30.0, "end": 30.0, "timestamp": "00:00"},
                {"id": f"seg_{video_id}_1", "segment_id": f"seg_{video_id}_1", "text": "Core concepts and system architecture.", "start": 30.0, "duration": 60.0, "end": 90.0, "timestamp": "00:30"}
            ],
            "duration_seconds": duration_seconds,
            "formatted_duration": duration_str,
            "is_synthesized": False,
            "ui_sample": []
        }
    )


def make_mock_raw_analysis(video_id, title="Test Lecture", author="Author", duration_str="10:00"):
    from services.analysis_service import _ensure_complete_schema
    res = _ensure_complete_schema({}, duration_str, title, author)
    res["video_overview"] = {"summary": f"Comprehensive summary for {title}"}
    res["chapters"] = [
        {"number": "01", "title": "Introduction", "start_time": "00:00", "end_time": "05:00", "start_seconds": 0, "end_seconds": 300, "summary": "Intro"}
    ]
    res["timeline"] = [
        {"time": "00:00", "seconds": 0, "title": "Introduction", "type": "intro"}
    ]
    res["claims"] = [
        {"claim": "Reliability engineering ensures fault isolation and resilience", "seconds": 10}
    ]
    res["insights"] = [
        {"insight": "System architecture separates concerns across modular boundaries", "timestamp": "00:30"}
    ]
    res["learning"] = {
        "quiz": [{"question": "What is fault isolation?", "options": ["A", "B", "C", "D"], "answer": "A", "bloom_level": "Understand"}],
        "flashcards": [{"front": "Fault Isolation", "back": "Preventing failure cascade"}]
    }
    res["entities"] = [{"name": "Fault Isolation", "type": "concept"}]
    res["knowledge_graph"] = {"nodes": [{"id": "1", "label": "Fault Isolation"}], "edges": []}
    return res


class TestRequirementR1FailureReportingAndPartialRecovery(unittest.TestCase):
    """Tests for R1: Module-Level Failure Reporting and Partial-Result Recovery."""

    def setUp(self):
        self.client = app.test_client()

    def test_01_transcript_failure_preserves_metadata_and_completes_partial(self):
        """
        When transcript extraction encounters an error in Stage 2,
        the pipeline must preserve completed Stage 1 metadata in raw_analysis and modules,
        record exact failure details in _module_status and failed_modules,
        set is_partial=True, and transition the job to STATUS_PARTIAL.
        """
        test_vid = f"t1_{uuid.uuid4().hex[:8]}"
        user_id = create_user('google', f'sub_r1_{uuid.uuid4().hex[:6]}', 'r1_user@test.com', 'R1 User', '')
        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        # Execute job with simulated transcript failure and mock metadata worker
        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid)):
            run_analysis_job(
                job_id,
                test_vid,
                user_id=user_id,
                simulate_failures={"transcript": True}
            )

        job = get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], STATUS_PARTIAL)
        self.assertTrue(job['is_partial'])

        res = job['result']
        self.assertIsNotNone(res)
        self.assertTrue(res.get('is_partial'))
        self.assertTrue(res.get('_partial'))

        # Upstream metadata MUST be preserved
        self.assertIn('metadata', res.get('modules', {}))
        self.assertEqual(res['modules']['metadata'].get('video_id'), test_vid)
        self.assertEqual(res.get('_meta', {}).get('video_id'), test_vid)

        # Module status tracking
        mod_status = res.get('_module_status', {})
        self.assertEqual(mod_status.get('metadata'), 'COMPLETED')
        self.assertEqual(mod_status.get('transcript'), 'FAILED')
        self.assertEqual(mod_status.get('summary'), 'FAILED')
        self.assertEqual(mod_status.get('timeline'), 'FAILED')
        self.assertEqual(mod_status.get('chapters'), 'FAILED')

        # Error details must identify exact failing module
        failed_mods = res.get('failed_modules', {})
        self.assertIn('transcript', failed_mods)
        self.assertIn('Simulated transcript', failed_mods['transcript'])

    def test_02_summary_failure_preserves_metadata_transcripts_and_chapters(self):
        """
        When Stage 5 AI summary fails, metadata, transcripts, chapters, and timeline
        must be preserved, summary marked FAILED, and job completed as STATUS_PARTIAL.
        """
        test_vid = f"t2_{uuid.uuid4().hex[:8]}"
        user_id = create_user('google', f'sub_r1_sum_{uuid.uuid4().hex[:6]}', 'r1_sum@test.com', 'R1 Sum User', '')
        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        # Execute job with simulated summary failure and mock metadata/transcript
        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid)), \
             patch('services.orchestrator.run_transcript_worker', return_value=make_mock_transcript(test_vid)):
            run_analysis_job(
                job_id,
                test_vid,
                user_id=user_id,
                simulate_failures={"summary": True}
            )

        job = get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job['status'], STATUS_PARTIAL)
        self.assertTrue(job['is_partial'])

        res = job['result']
        self.assertIsNotNone(res)

        # Both metadata and transcripts are preserved
        self.assertIn('metadata', res.get('modules', {}))
        self.assertIn('transcript', res.get('modules', {}))
        self.assertGreater(len(res['modules']['transcript']), 0)

        # Downstream chapters and timeline fallbacks succeed
        self.assertIn('chapters', res.get('modules', {}))
        self.assertIn('timeline', res.get('modules', {}))
        self.assertGreater(len(res['modules']['chapters']), 0)
        self.assertGreater(len(res['modules']['timeline']), 0)

        # Module status verification
        mod_status = res.get('_module_status', {})
        self.assertEqual(mod_status.get('metadata'), 'COMPLETED')
        self.assertEqual(mod_status.get('transcript'), 'COMPLETED')
        self.assertEqual(mod_status.get('summary'), 'FAILED')
        self.assertEqual(mod_status.get('chapters'), 'COMPLETED')
        self.assertEqual(mod_status.get('timeline'), 'COMPLETED')

        # Failed modules must identify summary
        failed_mods = res.get('failed_modules', {})
        self.assertIn('summary', failed_mods)

    def test_03_full_module_status_tracking_and_timeline_registration(self):
        """
        Verify that modules_status tracks all 10+ core modules including 'timeline',
        'entities', 'knowledge_graph', 'verification', and 'export_pdf'.
        """
        test_vid = f"t3_{uuid.uuid4().hex[:8]}"
        user_id = create_user('google', f'sub_r1_track_{uuid.uuid4().hex[:6]}', 'r1_track@test.com', 'R1 Track', '')
        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        # Run with export_pdf simulated failure
        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid)), \
             patch('services.orchestrator.run_transcript_worker', return_value=make_mock_transcript(test_vid)), \
             patch('services.orchestrator.run_videolens_analysis', return_value=make_mock_raw_analysis(test_vid)):
            run_analysis_job(
                job_id,
                test_vid,
                user_id=user_id,
                simulate_failures={"export_pdf": True}
            )

        job = get_job(job_id)
        res = job['result']
        mod_status = res.get('_module_status', {})

        required_modules = {
            "metadata", "transcript", "summary", "timeline", "chapters",
            "claims", "learning", "entities", "knowledge_graph", "verification", "export_pdf"
        }
        for mod in required_modules:
            self.assertIn(mod, mod_status, f"Missing {mod} in _module_status")

        # Verify timeline is registered
        self.assertEqual(mod_status['timeline'], 'COMPLETED')
        self.assertIn('timeline', res.get('modules', {}))
        self.assertEqual(mod_status['export_pdf'], 'FAILED')

    def test_04_simulate_failures_across_auxiliary_modules(self):
        """
        Test simulate_failures for timeline, claims, learning, entities, and verification.
        """
        test_vid = f"t4_{uuid.uuid4().hex[:8]}"
        user_id = create_user('google', f'sub_r1_sim_{uuid.uuid4().hex[:6]}', 'r1_sim@test.com', 'R1 Sim', '')
        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        # Simulate failures for timeline, claims, and verification
        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid)), \
             patch('services.orchestrator.run_transcript_worker', return_value=make_mock_transcript(test_vid)), \
             patch('services.orchestrator.run_videolens_analysis', return_value=make_mock_raw_analysis(test_vid)):
            run_analysis_job(
                job_id,
                test_vid,
                user_id=user_id,
                simulate_failures={"timeline": True, "claims": True, "verification": True}
            )

        job = get_job(job_id)
        self.assertEqual(job['status'], STATUS_PARTIAL)
        res = job['result']
        mod_status = res.get('_module_status', {})

        self.assertEqual(mod_status['timeline'], 'FAILED')
        self.assertEqual(mod_status['claims'], 'FAILED')
        self.assertEqual(mod_status['verification'], 'FAILED')
        self.assertEqual(mod_status['chapters'], 'COMPLETED')
        self.assertEqual(mod_status['metadata'], 'COMPLETED')

        failed_mods = res.get('failed_modules', {})
        self.assertIn('timeline', failed_mods)
        self.assertIn('claims', failed_mods)
        self.assertIn('verification', failed_mods)

    def test_05_job_hydration_restores_modules_from_sqlite(self):
        """
        Verify that get_job() properly restores 'modules' from result_summary
        when hydrating a job from SQLite analysis_jobs table.
        """
        test_vid = f"t5_{uuid.uuid4().hex[:8]}"
        user_id = create_user('google', f'sub_r1_hyd_{uuid.uuid4().hex[:6]}', 'r1_hyd@test.com', 'R1 Hyd', '')
        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid)), \
             patch('services.orchestrator.run_transcript_worker', return_value=make_mock_transcript(test_vid)), \
             patch('services.orchestrator.run_videolens_analysis', return_value=make_mock_raw_analysis(test_vid)):
            run_analysis_job(job_id, test_vid, user_id=user_id)

        # Evict from in-memory orchestrator dictionary to force SQLite hydration
        with orchestrator.lock:
            orchestrator.jobs.pop(job_id, None)

        hydrated = get_job(job_id)
        self.assertIsNotNone(hydrated)
        self.assertIn('modules', hydrated)
        self.assertIsInstance(hydrated['modules'], dict)
        self.assertIn('metadata', hydrated['modules'])
        self.assertIn('chapters', hydrated['modules'])
        self.assertIn('timeline', hydrated['modules'])


class TestRequirementR2EvidenceAndTimestampValidation(unittest.TestCase):
    """Tests for R2: Evidence and Timestamp Validation."""

    def test_01_transcript_segments_contain_id_and_end(self):
        """
        Verify that in-memory segments include id, segment_id, start, duration,
        and end with end == start + duration.
        """
        raw_segments = [
            {"text": "Introduction", "start": 0.0, "duration": 15.0},
            {"text": "Key Concept", "start": 15.0, "duration": 30.0}
        ]
        norm = normalize_transcript_segments(raw_segments, video_id="test_vid_123")
        self.assertEqual(len(norm), 2)

        for idx, s in enumerate(norm):
            self.assertIn('id', s)
            self.assertIn('segment_id', s)
            self.assertIn('start', s)
            self.assertIn('duration', s)
            self.assertIn('end', s)
            self.assertIn('timestamp', s)
            self.assertEqual(s['id'], f"seg_test_vid_123_{idx}")
            self.assertEqual(s['segment_id'], s['id'])
            self.assertAlmostEqual(s['end'], s['start'] + s['duration'], places=2)

    def test_02_storage_deserializes_segment_ids(self):
        """
        Verify that get_modular_analysis() deserializes segment id and segment_id from SQLite.
        """
        test_vid = f"mod_seg_{uuid.uuid4().hex[:8]}"
        analysis_data = {
            "_meta": {"video_id": test_vid, "title": "Segment Storage Test", "duration": "05:00"},
            "transcript_segments": [
                {"text": "Opening discussion", "start": 0.0, "duration": 60.0},
                {"text": "Main protocol", "start": 60.0, "duration": 120.0}
            ],
            "video_overview": {"summary": "Storage test overview"}
        }
        save_analysis(test_vid, "Segment Storage Test", "Author", "05:00", analysis_data)

        retrieved = get_modular_analysis(test_vid)
        self.assertIsNotNone(retrieved)
        segs = retrieved.get('transcript_segments', [])
        self.assertGreater(len(segs), 0)
        for s in segs:
            self.assertIn('id', s)
            self.assertIn('segment_id', s)
            self.assertIn('end', s)
            self.assertAlmostEqual(s['end'], s['start'] + s['duration'], places=2)

    def test_03_claims_grounding_enriches_start_end_segment_id_and_excerpts(self):
        """
        Verify that verify_grounded_claims populates seconds, start_seconds, end_seconds,
        start_timestamp, end_timestamp, transcript_segment_id, matched_segment_id,
        transcript_excerpt, source_excerpt, confidence_score, verified, flagged, and grounding_status.
        """
        segments = [
            {"id": "seg_0", "segment_id": "seg_0", "text": "Sunlight exposure early morning resets circadian biology", "start": 12.0, "duration": 18.0, "end": 30.0},
            {"id": "seg_1", "segment_id": "seg_1", "text": "Cold immersion increases dopamine for several hours", "start": 45.0, "duration": 25.0, "end": 70.0}
        ]
        raw_claims = [
            {"claim": "Morning sunlight resets circadian rhythm", "seconds": 15},
            {"claim": "Cold exposure releases dopamine for hours", "seconds": 50}
        ]

        verified_claims, stats = verify_grounded_claims(raw_claims, segments, max_duration=120)
        self.assertEqual(len(verified_claims), 2)
        self.assertEqual(stats['verified_count'], 2)

        c1 = verified_claims[0]
        self.assertEqual(c1['transcript_segment_id'], 'seg_0')
        self.assertEqual(c1['matched_segment_id'], 'seg_0')
        self.assertEqual(c1['start_seconds'], 12.0)
        self.assertEqual(c1['end_seconds'], 30.0)
        self.assertEqual(c1['start_timestamp'], '00:12')
        self.assertEqual(c1['end_timestamp'], '00:30')
        self.assertEqual(c1['transcript_excerpt'], segments[0]['text'])
        self.assertEqual(c1['source_excerpt'], segments[0]['text'])
        self.assertTrue(c1['verified'])
        self.assertFalse(c1['flagged'])
        self.assertEqual(c1['grounding_status'], 'VERIFIED')
        self.assertGreaterEqual(c1['confidence_score'], 0.5)

    def test_04_insights_grounding_functionality(self):
        """
        Verify that verify_grounded_insights grounds high-leverage insights against transcript segments.
        """
        segments = [
            {"id": "seg_10", "segment_id": "seg_10", "text": "Metabolic flexibility allows the heart to oxidize ketones and fatty acids", "start": 120.0, "duration": 40.0, "end": 160.0}
        ]
        raw_insights = [
            {"insight": "The heart utilizes ketones for energy under metabolic flexibility", "timestamp": "02:10"}
        ]

        grounded_insights, stats = verify_grounded_insights(raw_insights, segments, max_duration=300)
        self.assertEqual(len(grounded_insights), 1)
        ins = grounded_insights[0]

        self.assertEqual(ins['transcript_segment_id'], 'seg_10')
        self.assertEqual(ins['start_seconds'], 120.0)
        self.assertEqual(ins['end_seconds'], 160.0)
        self.assertEqual(ins['start_timestamp'], '02:00')
        self.assertEqual(ins['end_timestamp'], '02:40')
        self.assertEqual(ins['grounding_status'], 'VERIFIED')
        self.assertTrue(ins['verified'])

    def test_05_dual_mode_flagging_vs_rejection_of_ungrounded_statements(self):
        """
        Test dual-mode validation:
        - reject_ungrounded=False (default): flags ungrounded statements (flagged=True, verified=False, grounding_status="UNGROUNDED")
        - reject_ungrounded=True: excludes ungrounded statements from output
        """
        segments = [
            {"id": "seg_0", "segment_id": "seg_0", "text": "Quantum computing uses superposition and entanglement", "start": 10.0, "duration": 20.0, "end": 30.0}
        ]
        mixed_statements = [
            {"statement": "Quantum computers rely on superposition", "seconds": 10},
            {"statement": "Baking sourdough bread requires organic whole wheat flour and wild yeast", "seconds": 800} # ungrounded & out of bounds
        ]

        # Mode A: Flagging (reject_ungrounded=False)
        flagged_list, f_stats = validate_evidence_citations(
            mixed_statements, segments, max_duration=60, reject_ungrounded=False
        )
        self.assertEqual(len(flagged_list), 2)
        self.assertEqual(f_stats['verified_count'], 1)
        self.assertEqual(f_stats['rejected_count'], 0)

        # Valid statement
        self.assertTrue(flagged_list[0]['verified'])
        self.assertFalse(flagged_list[0]['flagged'])
        self.assertEqual(flagged_list[0]['grounding_status'], 'VERIFIED')

        # Ungrounded statement is retained but flagged
        self.assertFalse(flagged_list[1]['verified'])
        self.assertTrue(flagged_list[1]['flagged'])
        self.assertEqual(flagged_list[1]['grounding_status'], 'UNGROUNDED')

        # Mode B: Rejection (reject_ungrounded=True)
        rejected_list, r_stats = validate_evidence_citations(
            mixed_statements, segments, max_duration=60, reject_ungrounded=True
        )
        self.assertEqual(len(rejected_list), 1)
        self.assertEqual(r_stats['verified_count'], 1)
        self.assertEqual(r_stats['rejected_count'], 1)
        self.assertEqual(rejected_list[0]['statement'], mixed_statements[0]['statement'])

    def test_06_copilot_citation_parsing_validation_and_out_of_bounds_detection(self):
        """
        Verify ground_copilot_response parses [MM:SS] timestamps, matches transcript segments,
        and flags out-of-bounds citations.
        """
        segments = [
            {"id": "seg_0", "segment_id": "seg_0", "text": "Cardiovascular exercise promotes mitochondrial biogenesis", "start": 30.0, "duration": 20.0, "end": 50.0},
            {"id": "seg_1", "segment_id": "seg_1", "text": "Zone 2 training should be performed for 150 to 180 minutes per week", "start": 90.0, "duration": 30.0, "end": 120.0}
        ]
        # Video is 180 seconds long
        answer_text = (
            "According to the speaker at [00:40], cardio exercise triggers mitochondrial biogenesis. "
            "Furthermore, Zone 2 protocols are detailed at [01:45]. "
            "However, an ungrounded claim was made at [99:30] which does not exist."
        )

        grounded_text, citations, summary = ground_copilot_response(
            answer_text, segments, max_duration=180.0
        )
        self.assertEqual(len(citations), 3)
        self.assertEqual(summary['total_citations'], 3)
        self.assertEqual(summary['valid_citations'], 2)
        self.assertEqual(summary['invalid_citations'], 1)

        # First citation [00:40] -> valid (matches seg_0)
        c0 = citations[0]
        self.assertTrue(c0['valid'])
        self.assertFalse(c0['flagged'])
        self.assertEqual(c0['timestamp'], '00:40')
        self.assertEqual(c0['transcript_segment_id'], 'seg_0')
        self.assertIn("mitochondrial biogenesis", c0['transcript_excerpt'])

        # Second citation [01:45] (105s) -> valid (matches seg_1)
        c1 = citations[1]
        self.assertTrue(c1['valid'])
        self.assertEqual(c1['timestamp'], '01:45')
        self.assertEqual(c1['transcript_segment_id'], 'seg_1')

        # Third citation [99:30] -> invalid (5970s > 180s)
        c2 = citations[2]
        self.assertFalse(c2['valid'])
        self.assertTrue(c2['flagged'])
        self.assertEqual(c2['grounding_status'], 'INVALID_TIMESTAMP')
        self.assertIn('exceeds video duration', c2.get('error', ''))

    def test_07_post_api_chat_e2e_citations_and_grounding(self):
        """
        Verify POST /api/chat end-to-end execution succeeds with HTTP 200,
        normalizes markdown headers via re.sub, and returns citations and grounding_summary.
        """
        test_client = app.test_client()
        mock_response = MagicMock()
        mock_response.text = "#### Phase 1: Key Insights\nDetailed breakdown at [00:15]."

        snippets = [
            {"id": "seg_0", "segment_id": "seg_0", "start": 0.0, "duration": 30.0, "end": 30.0, "text": "Detailed breakdown of the architecture."}
        ]

        with patch('app.call_gemini_with_fallback', return_value=mock_response), \
             patch('app.check_quota', return_value={'allowed': True}):
            res = test_client.post('/api/chat', json={
                'question': 'Explain Phase 1 architecture',
                'duration': '02:00',
                'snippets': snippets,
                'video_id': 'test_chat_vid',
                'title': 'Test Lecture'
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("answer", data)
            self.assertIn("### Phase 1: Key Insights", data["answer"])
            self.assertIn("citations", data)
            self.assertEqual(len(data["citations"]), 1)
            self.assertTrue(data["citations"][0]["valid"])
            self.assertEqual(data["citations"][0]["transcript_segment_id"], "seg_0")
            self.assertIn("grounding_summary", data)
            self.assertEqual(data["grounding_summary"]["valid_citations"], 1)

    def test_08_hallucinated_claim_with_valid_timestamp_flagged_ungrounded(self):
        """
        Verify hallucinated claim with valid in-bounds timestamp but no transcript keyword overlap
        is strictly flagged verified=False, flagged=True, grounding_status='UNGROUNDED'.
        """
        segments = [
            {'id': 'seg_0', 'segment_id': 'seg_0', 'start': 0.0, 'duration': 30.0, 'end': 30.0, 'text': 'Raft consensus algorithm for distributed systems.'}
        ]
        hallucinated_claims = [
            {'claim': 'Eating uranium helps with immortality', 'seconds': 15.0}
        ]
        res, stats = validate_evidence_citations(hallucinated_claims, segments, max_duration=60.0)
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0]['verified'])
        self.assertTrue(res[0]['flagged'])
        self.assertEqual(res[0]['grounding_status'], 'UNGROUNDED')
        self.assertEqual(res[0]['confidence_score'], 0.30)
        self.assertEqual(stats['verified_count'], 0)

    def test_09_claim_with_out_of_bounds_timestamp_flagged_ungrounded(self):
        """
        Verify claim with timestamp > video duration is strictly flagged ungrounded
        even if text happens to overlap keywords with earlier segments.
        """
        segments = [
            {'id': 'seg_0', 'segment_id': 'seg_0', 'start': 10.0, 'duration': 25.0, 'end': 35.0, 'text': 'Database replication and consistency.'}
        ]
        out_of_bounds_claim = [
            {'claim': 'Database replication is explained at high speed', 'seconds': 9999.0}
        ]
        res, stats = validate_evidence_citations(out_of_bounds_claim, segments, max_duration=120.0)
        self.assertEqual(len(res), 1)
        self.assertFalse(res[0]['verified'])
        self.assertTrue(res[0]['flagged'])
        self.assertEqual(res[0]['grounding_status'], 'UNGROUNDED')
        self.assertEqual(res[0]['confidence_score'], 0.10)
        self.assertEqual(stats['verified_count'], 0)

    def test_10_boundary_timestamp_matches_subsequent_segment(self):
        """
        Verify boundary citation matching in ground_copilot_response:
        when citation timestamp matches exact segment start, it matches the segment
        starting at that timestamp rather than the preceding ending segment.
        """
        segments = [
            {'id': 'seg_1', 'segment_id': 'seg_1', 'start': 30.0, 'duration': 45.0, 'end': 75.0, 'text': 'Introductory remarks and context.'},
            {'id': 'seg_2', 'segment_id': 'seg_2', 'start': 75.0, 'duration': 45.0, 'end': 120.0, 'text': 'Deep dive into core mechanism.'}
        ]
        _, citations, _ = ground_copilot_response('The deep dive begins at [01:15].', segments, max_duration=120.0)
        self.assertEqual(len(citations), 1)
        self.assertTrue(citations[0]['valid'])
        self.assertEqual(citations[0]['transcript_segment_id'], 'seg_2')
        self.assertIn('Deep dive into core mechanism', citations[0]['transcript_excerpt'])


class TestRequirementR3DurationWeightedCreditControls(unittest.TestCase):
    """Tests for R3: Duration-Weighted Credit and Resource Controls."""

    def test_01_calculate_credit_cost_scaling(self):
        """
        Verify calculate_credit_cost scales with 15-minute blocks (900 seconds) and tier multipliers:
        - <= 15 min (900s, e.g. 14:20) = 1 credit (backward compatible)
        - 30 min (1800s) = 2 credits
        - 60 min (3600s) = 4 credits
        - 60 min at deep tier (1.5x) = 6 credits
        - 60 min at premium tier (2.0x) = 8 credits
        - zero/empty duration = 1 credit
        """
        # Standard short videos <= 15m
        self.assertEqual(calculate_credit_cost("14:20"), 1)
        self.assertEqual(calculate_credit_cost("15:00"), 1)
        self.assertEqual(calculate_credit_cost(900), 1)
        self.assertEqual(calculate_credit_cost(300), 1)
        self.assertEqual(calculate_credit_cost(0), 1)
        self.assertEqual(calculate_credit_cost(None), 1)

        # Multi-block scaling
        self.assertEqual(calculate_credit_cost(901), 2)
        self.assertEqual(calculate_credit_cost("30:00"), 2)
        self.assertEqual(calculate_credit_cost(1800), 2)
        self.assertEqual(calculate_credit_cost("01:00:00"), 4)
        self.assertEqual(calculate_credit_cost(3600), 4)

        # Tier multipliers
        self.assertEqual(calculate_credit_cost(3600, tier="deep"), 6)
        self.assertEqual(calculate_credit_cost(3600, tier="research"), 6)
        self.assertEqual(calculate_credit_cost(3600, tier="premium"), 8)
        self.assertEqual(calculate_credit_cost("14:20", tier="deep"), 2)

    def test_02_check_quota_and_increment_quota_with_variable_credits(self):
        """
        Verify check_quota compares remaining against required_credits,
        and increment_quota deducts the exact credit amount.
        """
        # Registered user with limit 5
        user_id = create_user('google', f'sub_credit_{uuid.uuid4().hex[:6]}', 'credit@test.com', 'Credit User', '')
        user = get_user(user_id)
        self.assertEqual(user['quota_used'], 0)
        self.assertEqual(user['quota_limit'], 5)

        # Check required credits 4 -> allowed
        q1 = check_quota(user_id=user_id, required_credits=4)
        self.assertTrue(q1['allowed'])
        self.assertEqual(q1['remaining'], 5)
        self.assertEqual(q1['required_credits'], 4)

        # Deduct 4 credits
        increment_quota(user_id=user_id, amount=4)
        u_after = get_user(user_id)
        self.assertEqual(u_after['quota_used'], 4)

        # Check required credits 2 -> remaining 1 < 2 -> NOT allowed
        q2 = check_quota(user_id=user_id, required_credits=2)
        self.assertFalse(q2['allowed'])
        self.assertEqual(q2['remaining'], 1)
        self.assertEqual(q2['required_credits'], 2)

        # Check required credits 1 -> remaining 1 >= 1 -> allowed
        q3 = check_quota(user_id=user_id, required_credits=1)
        self.assertTrue(q3['allowed'])

    def test_03_pre_dispatch_quota_check_rejection(self):
        """
        Verify /api/analyze rejects dispatch with HTTP 402 if cached video duration
        requires more credits than the user possesses.
        """
        test_client = app.test_client()
        test_vid = f"cp_{uuid.uuid4().hex[:8]}"

        # Save a 60-minute video to cache (requires 4 credits)
        save_cached_analysis(
            test_vid, "Hour Long Lecture", "Professor", "01:00:00",
            {"_meta": {"video_id": test_vid, "duration": "01:00:00", "duration_seconds": 3600}}
        )

        # Create user with limit 5, already used 4 (remaining = 1)
        user_id = create_user('google', f'sub_predisp_{uuid.uuid4().hex[:6]}', 'predisp@test.com', 'Predisp', '')
        update_user_quota(user_id, increment=4)

        with test_client.session_transaction() as sess:
            sess['user_id'] = user_id

        # Dispatch should fail with 402 because 4 credits required but only 1 remaining
        res = test_client.post('/api/analyze', json={'url': f"https://www.youtube.com/watch?v={test_vid}"})
        self.assertEqual(res.status_code, 402)
        data = res.get_json()
        self.assertEqual(data.get('error'), 'Quota exceeded')
        self.assertEqual(data.get('required_credits'), 4)

    def test_04_mid_pipeline_quota_enforcement_aborts_excessive_duration(self):
        """
        Verify mid-pipeline quota check in orchestrator.run_pipeline aborts
        with STATUS_FAILED before LLM execution if video duration exceeds quota.
        """
        test_vid = f"mq_{uuid.uuid4().hex[:8]}"
        # User has limit 5, used 4 (remaining = 1)
        user_id = create_user('google', f'sub_midq_{uuid.uuid4().hex[:6]}', 'midq@test.com', 'Midq', '')
        update_user_quota(user_id, increment=4)

        job_id, _ = submit_or_attach(test_vid, user_id=user_id)

        # Mock metadata & transcript workers to return a 2-hour lecture (7200s -> 8 credits required)
        with patch('services.orchestrator.run_metadata_worker', return_value=make_mock_metadata(test_vid, duration_seconds=7200, duration_str="02:00:00")), \
             patch('services.orchestrator.run_transcript_worker', return_value=make_mock_transcript(test_vid, duration_seconds=7200, duration_str="02:00:00")):
            run_analysis_job(job_id, test_vid, user_id=user_id)

        job = get_job(job_id)
        self.assertEqual(job['status'], STATUS_FAILED)
        self.assertIn('Insufficient credits', job.get('error', ''))

    def test_05_floating_point_seconds_credit_cost(self):
        """
        Verify calculate_credit_cost preserves floating-point seconds:
        - 900.1 float -> 2 credits (crosses into 2nd 15-min block)
        - "900.1" string -> 2 credits
        - 900.0 float -> 1 credit (exactly 1 block)
        - "900.0" string -> 1 credit
        - 0.5 float -> 1 credit (minimum cost)
        """
        self.assertEqual(calculate_credit_cost(900.1), 2)
        self.assertEqual(calculate_credit_cost("900.1"), 2)
        self.assertEqual(calculate_credit_cost(900.0), 1)
        self.assertEqual(calculate_credit_cost("900.0"), 1)
        self.assertEqual(calculate_credit_cost(0.5), 1)


if __name__ == '__main__':
    unittest.main()
