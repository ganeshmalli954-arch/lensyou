"""
test_m4_ux_progressive.py
LensYou Milestone 4 UX & Progressive Delivery Test Suite.

Validates:
1. Feature F14: Guided First-Time UX (Onboarding banner, hero input card, 1-click pills, tooltip).
2. Feature F15: View Segregation (Executive Core vs Full Research Tools, density toolbar, collapsible drawer).
3. Feature F16: Progressive Module Delivery (Live modular feed, in-memory stage status updates, 900ms polling cadence).
"""

import os
import re
import unittest
from flask import Flask
from services.orchestrator import (
    AsyncJobOrchestrator,
    JobStatus,
    STATUS_QUEUED,
    STATUS_EXTRACTING,
    STATUS_PROCESSING,
    STATUS_VALIDATING,
    STATUS_COMPLETED,
    STATUS_PARTIAL,
    STAGES,
)
import app as flask_app_module


class TestMilestone4UXProgressive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = flask_app_module.app
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

        # Read template, script, and style files directly for static checks
        base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, 'templates', 'index.html'), 'r', encoding='utf-8') as f:
            cls.index_html = f.read()
        with open(os.path.join(base_dir, 'static', 'script.js'), 'r', encoding='utf-8') as f:
            cls.script_js = f.read()
        with open(os.path.join(base_dir, 'static', 'style.css'), 'r', encoding='utf-8') as f:
            cls.style_css = f.read()

    # =========================================================================
    # FEATURE F14: GUIDED FIRST-TIME UX TESTS
    # =========================================================================

    def test_f14_onboarding_micro_guide_banner_present(self):
        """Verifies onboarding banner element, title, dismiss button, and storage key."""
        self.assertIn('id="firstTimeOnboardingBanner"', self.index_html)
        self.assertIn('dismissFirstTimeGuide()', self.index_html)
        self.assertIn('New to LensYou?', self.index_html)
        self.assertIn('lensyou_first_visit', self.script_js)
        self.assertIn('function dismissFirstTimeGuide()', self.script_js)
        self.assertIn('function initFirstTimeExperience()', self.script_js)

    def test_f14_hero_input_card_structure(self):
        """Verifies focused hero input card with name='urlInput', clear button, and submit action."""
        self.assertIn('id="analyzeForm"', self.index_html)
        self.assertIn('id="youtubeUrl"', self.index_html)
        self.assertIn('name="urlInput"', self.index_html)
        self.assertIn('id="clearHeroInputBtn"', self.index_html)
        self.assertIn('id="analyzeSubmitBtn"', self.index_html)
        self.assertIn('function clearHeroSearchInput()', self.script_js)

    def test_f14_floating_hint_tooltip(self):
        """Verifies contextual first-time input tooltip exists and is managed in script and css."""
        self.assertIn('id="firstTimeInputTooltip"', self.index_html)
        self.assertIn('hideFirstTimeTooltip()', self.script_js)
        self.assertIn('.first-time-floating-tooltip', self.style_css)

    def test_f14_one_click_quick_start_pills(self):
        """Verifies 1-click Quick-Start Pills (3B1B, Founder, Huberman) are prominently present."""
        self.assertIn('id="heroQuickStartZone"', self.index_html)
        # Verbatim strings required by project and regression tests
        self.assertIn('qmNCJxvs080', self.index_html)
        self.assertIn('aircAruvnKk', self.index_html)
        self.assertIn('LqY6hFLMEJw', self.index_html)
        self.assertIn('Analyze 3B1B Lecture (1-Click) →', self.index_html)
        self.assertIn('pasteQuickUrl(', self.index_html)
        self.assertIn('.quick-start-pill', self.style_css)

    # =========================================================================
    # FEATURE F15: VIEW SEGREGATION (EXECUTIVE CORE VS ADVANCED TOOLS) TESTS
    # =========================================================================

    def test_f15_density_toolbar_presence(self):
        """Verifies Executive View vs Full Research View density toolbar."""
        self.assertIn('id="dashboardDensityToolbar"', self.index_html)
        self.assertIn('id="btnViewCore"', self.index_html)
        self.assertIn('id="btnViewAdvanced"', self.index_html)
        self.assertIn('id="densityModeNotice"', self.index_html)
        self.assertIn('setDashboardViewMode(', self.index_html)
        self.assertIn('function setDashboardViewMode(mode)', self.script_js)
        self.assertIn('.density-toggle-btn', self.style_css)

    def test_f15_primary_core_view_elements(self):
        """Verifies Primary Core View contains summary, takeaways, chapters, transcript, flashcards, quiz."""
        self.assertIn('id="overviewSummaryText"', self.index_html)
        self.assertIn('id="takeawaysGrid"', self.index_html)
        self.assertIn('id="chaptersList"', self.index_html)
        self.assertIn('id="section-transcript"', self.index_html)
        self.assertIn('id="section-core-learning"', self.index_html)
        self.assertIn('id="activeFlashcard"', self.index_html)
        self.assertIn('id="quizContainer"', self.index_html)

    def test_f15_secondary_advanced_tools_collapsible_drawer(self):
        """Verifies Secondary Advanced Tools Collapsible Drawer and wrapper containers."""
        self.assertIn('id="advancedResearchSection"', self.index_html)
        self.assertIn('id="advancedToolsToggleCard"', self.index_html)
        self.assertIn('id="advancedToolsDrawerContent"', self.index_html)
        self.assertIn('toggleAdvancedResearchTools()', self.index_html)

        # Verify advanced tools are flagged with .advanced-analytical-tool and default collapsed
        self.assertIn('advanced-analytical-tool collapsed', self.index_html)
        self.assertIn('id="section-videomap"', self.index_html)
        self.assertIn('id="section-multitrack"', self.index_html)
        self.assertIn('id="section-scorecard"', self.index_html)
        self.assertIn('id="speakersGrid"', self.index_html)
        self.assertIn('id="contradictionsList"', self.index_html)
        self.assertIn('id="copilotMessages"', self.index_html)
        self.assertIn('id="section-exports"', self.index_html)

    def test_f15_advanced_subtool_navigation(self):
        """Verifies subtool navigation switching across graph, speakers, contradictions, copilot, exports."""
        self.assertIn('data-subtool="graph"', self.index_html)
        self.assertIn('data-subtool="speakers"', self.index_html)
        self.assertIn('data-subtool="contradictions"', self.index_html)
        self.assertIn('data-subtool="copilot"', self.index_html)
        self.assertIn('data-subtool="exports"', self.index_html)
        self.assertIn('function switchAdvancedSubtool(subtoolKey)', self.script_js)
        self.assertIn('function ensureAdvancedToolsExpanded(', self.script_js)

    def test_f15_export_handlers_implemented(self):
        """Verifies exportMarkdownDossier and exportTranscriptCSV functions are defined in script."""
        self.assertIn('function exportMarkdownDossier()', self.script_js)
        self.assertIn('function exportTranscriptCSV()', self.script_js)
        self.assertIn('function exportDetailedPDF()', self.script_js)

    # =========================================================================
    # FEATURE F16: PROGRESSIVE MODULE DELIVERY & LIVE STAGE POLLING TESTS
    # =========================================================================

    def test_f16_progressive_feed_cards_in_template(self):
        """Verifies HTML structure of progressive delivery feed and intermediate modular cards."""
        self.assertIn('id="progressiveDeliveryFeed"', self.index_html)
        self.assertIn('id="progCardMetadata"', self.index_html)
        self.assertIn('id="progMetaTitle"', self.index_html)
        self.assertIn('id="progMetaAuthor"', self.index_html)
        self.assertIn('id="progMetaDuration"', self.index_html)
        self.assertIn('id="progCardTranscript"', self.index_html)
        self.assertIn('id="progTranscriptCount"', self.index_html)
        self.assertIn('id="progCardSummary"', self.index_html)
        self.assertIn('id="progSummaryPreview"', self.index_html)
        self.assertIn('id="progCardChapters"', self.index_html)
        self.assertIn('id="progChaptersCount"', self.index_html)

    def test_f16_progressive_client_controller_and_cadence(self):
        """Verifies 900ms polling interval, progressive UI updater, and partial status handling."""
        self.assertIn('updateProgressiveModulesUI(', self.script_js)
        self.assertIn('resetProgressiveModules()', self.script_js)
        # Confirm 900ms polling cadence
        self.assertIn('setInterval(checkStatus, 900)', self.script_js)
        # Confirm partial status handling
        self.assertIn("jobData.status === 'partial'", self.script_js)

    def test_f16_backend_orchestrator_live_mem_status_assignment(self):
        """Verifies orchestrator.update_stage assigns live in-memory status across all stages."""
        orch = AsyncJobOrchestrator(max_job_workers=2)
        try:
            job_id = "test_m4_live_polling_job"

            with orch.lock:
                orch.jobs[job_id] = {
                    'job_id': job_id,
                    'url': 'https://www.youtube.com/watch?v=qmNCJxvs080',
                    'video_id': 'qmNCJxvs080',
                    'status': STATUS_QUEUED,
                    'stage': 0,
                    'stage_name': 'Queued',
                    'progress': 0,
                    'result': None,
                    'error': None,
                    'modules': {},
                    'is_partial': False,
                    'retry_count': 0,
                    'started_at': None,
                    'created_at': '2026-11-07T12:00:00'
                }

            # Stage 1: Extraction / Queue
            orch.update_stage(job_id, 1, "Submitting URL & allocating queue", progress=10)
            status1 = orch.get_job_status(job_id)
            self.assertEqual(status1['status'], STATUS_EXTRACTING)
            self.assertEqual(status1['stage'], 1)
            self.assertEqual(status1['progress'], 10)

            # Stage 2: Metadata Verified with module payload
            meta_data = {
                'title': 'Essence of Linear Algebra',
                'author': '3Blue1Brown',
                'duration': '14:22',
                'thumbnail_url': 'https://img.youtube.com/vi/qmNCJxvs080/hqdefault.jpg'
            }
            orch.update_stage(job_id, 2, "Metadata verified", progress=25, modules={'metadata': meta_data})
            status2 = orch.get_job_status(job_id)
            self.assertEqual(status2['status'], STATUS_EXTRACTING)
            self.assertIn('metadata', status2['modules'])
            self.assertEqual(status2['modules']['metadata']['title'], 'Essence of Linear Algebra')

            # Stage 3: Transcript Resolved with module payload
            transcript_data = [
                {'start': 0.0, 'duration': 4.0, 'text': 'Linear combinations are foundational.'},
                {'start': 4.0, 'duration': 5.0, 'text': 'Vectors can span entire multidimensional subspaces.'}
            ]
            orch.update_stage(job_id, 3, "Transcripts resolved", progress=35, modules={'transcript': transcript_data})
            status3 = orch.get_job_status(job_id)
            self.assertEqual(status3['status'], STATUS_EXTRACTING)
            self.assertIn('transcript', status3['modules'])
            self.assertEqual(len(status3['modules']['transcript']), 2)

            # Stage 4: Processing Overview & Summary
            overview_data = {
                'summary': 'A geometric visual intuition behind matrix operations and vector span.',
                'category': 'Education'
            }
            orch.update_stage(job_id, 4, "Executive intelligence synthesis", progress=50, modules={'overview': overview_data})
            status4 = orch.get_job_status(job_id)
            self.assertEqual(status4['status'], STATUS_PROCESSING)
            self.assertIn('overview', status4['modules'])

            # Stage 5: Chapters & Timeline
            chapters_data = [
                {'start_time': '00:00', 'title': 'Introduction to Vectors'},
                {'start_time': '04:15', 'title': 'Linear Span and Bases'}
            ]
            orch.update_stage(job_id, 5, "Timeline & chapters mapping", progress=65, modules={'chapters': chapters_data})
            status5 = orch.get_job_status(job_id)
            self.assertEqual(status5['status'], STATUS_PROCESSING)
            self.assertIn('chapters', status5['modules'])

            # Stage 8: Validating
            orch.update_stage(job_id, 8, "Verification audit", progress=90)
            status8 = orch.get_job_status(job_id)
            self.assertEqual(status8['status'], STATUS_VALIDATING)

            # Stage 9 / Complete (Partial delivery scenario)
            result_payload = {
                '_meta': meta_data,
                'video_overview': overview_data,
                'chapters': chapters_data,
                'learning': {'flashcards': []}
            }
            orch.complete_job(job_id, result=result_payload, is_partial=True)
            status_final = orch.get_job_status(job_id)
            self.assertEqual(status_final['status'], STATUS_PARTIAL)
            self.assertTrue(status_final['is_partial'])
            self.assertIsNotNone(status_final['result'])
        finally:
            orch.shutdown(wait=False)

    # =========================================================================
    # END-TO-END LANDING ROUTE TESTS
    # =========================================================================

    def test_landing_route_returns_200_and_all_features(self):
        """Verifies GET / returns 200 and includes all M4 landing and dashboard elements."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)

        # F14 assertions
        self.assertIn('firstTimeOnboardingBanner', body)
        self.assertIn('firstTimeInputTooltip', body)
        self.assertIn('heroQuickStartZone', body)
        self.assertIn('qmNCJxvs080', body)

        # F15 assertions
        self.assertIn('dashboardDensityToolbar', body)
        self.assertIn('btnViewCore', body)
        self.assertIn('btnViewAdvanced', body)
        self.assertIn('advancedResearchSection', body)

        # F16 assertions
        self.assertIn('progressiveDeliveryFeed', body)
        self.assertIn('progCardMetadata', body)
        self.assertIn('progCardTranscript', body)
        self.assertIn('progCardSummary', body)
        self.assertIn('progCardChapters', body)


if __name__ == '__main__':
    unittest.main()
