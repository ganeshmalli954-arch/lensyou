"""
test_m4_ux_view_challenger.py
LensYou Milestone 4 Adversarial Stress Challenger Test Suite:
- Feature F14: Guided First-Time UX (Onboarding banner, hero input card, 1-click pills, tooltip)
- Feature F15: View Segregation (Executive Core vs Full Research Tools, density toolbar, collapsible drawer)
- Verbatim String Preservation across templates/index.html
- Client-Side Markdown and CSV Export Routines Robustness

Covers empirical assertions in both Python DOM/Static inspection and
live execution of the Node.js empirical test harness (test_m4_ux_view_stress.js).
"""

import os
import re
import subprocess
import unittest

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


class TestF14GuidedFirstTimeUXStaticAndDOM(unittest.TestCase):
    """Adversarially validates Feature F14 HTML DOM structure, JS controllers, and CSS styles."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PROJECT_ROOT, 'templates', 'index.html'), 'r', encoding='utf-8') as f:
            cls.html = f.read()
        with open(os.path.join(PROJECT_ROOT, 'static', 'script.js'), 'r', encoding='utf-8') as f:
            cls.js = f.read()
        with open(os.path.join(PROJECT_ROOT, 'static', 'style.css'), 'r', encoding='utf-8') as f:
            cls.css = f.read()

    def test_f14_onboarding_micro_guide_banner_dom(self):
        """Verify onboarding banner exists, has correct ID, title, sparkle badge, and dismiss callback."""
        self.assertIn('id="firstTimeOnboardingBanner"', self.html)
        self.assertIn('class="first-time-onboarding-card"', self.html)
        self.assertIn('New to LensYou? 30-Second Quick Start:', self.html)
        self.assertIn('onclick="dismissFirstTimeGuide()"', self.html)
        self.assertIn('✕ Got it', self.html)

        # Verify 3-step track
        self.assertIn('Paste YouTube Link', self.html)
        self.assertIn('AI Extraction', self.html)
        self.assertIn('Executive Mastery', self.html)

    def test_f14_hero_card_input_structure(self):
        """Verify prominent hero input card with name='urlInput', clear button, and submit action."""
        self.assertIn('id="analyzeForm"', self.html)
        self.assertIn('class="url-input-card focused-hero-input-card"', self.html)
        self.assertIn('id="youtubeUrl"', self.html)
        self.assertIn('name="urlInput"', self.html)
        self.assertIn('id="clearHeroInputBtn"', self.html)
        self.assertIn('onclick="clearHeroSearchInput()"', self.html)
        self.assertIn('id="analyzeSubmitBtn"', self.html)
        self.assertIn('id="analyzeBtnText"', self.html)

    def test_f14_contextual_floating_tooltip(self):
        """Verify floating hint tooltip with pulse dot directly beneath input."""
        self.assertIn('id="firstTimeInputTooltip"', self.html)
        self.assertIn('class="first-time-floating-tooltip"', self.html)
        self.assertIn('class="tooltip-pulse-dot"', self.html)
        self.assertIn('Paste any YouTube link here or click a 1-click sample below', self.html)

    def test_f14_one_click_quick_start_pills_in_hero_zone(self):
        """Verify prominent 1-click Quick-Start Pills zone directly beneath input card."""
        self.assertIn('id="heroQuickStartZone"', self.html)
        self.assertIn('class="hero-quick-start"', self.html)
        self.assertIn('1-Click Quick Samples:', self.html)

        # 3 target videos
        self.assertIn('pasteQuickUrl(\'https://www.youtube.com/watch?v=aircAruvnKk\')', self.html)
        self.assertIn('pasteQuickUrl(\'https://youtu.be/LqY6hFLMEJw\')', self.html)
        self.assertIn('pasteQuickUrl(\'https://www.youtube.com/watch?v=qmNCJxvs080\')', self.html)

        # Labels and icons
        self.assertIn('Neural Networks', self.html)
        self.assertIn('Founder Interview', self.html)
        self.assertIn('Neuroscience Protocols', self.html)

    def test_f14_css_classes_onboarding_and_pills(self):
        """Verify CSS styles for onboarding micro-guide card, pills, and tooltip."""
        self.assertIn('.first-time-onboarding-card', self.css)
        self.assertIn('.first-time-floating-tooltip', self.css)
        self.assertIn('.quick-start-pill', self.css)
        self.assertIn('.focused-hero-input-card', self.css)

    def test_f14_js_first_visit_key_and_functions_present(self):
        """Verify JS first-visit controller constants and function definitions."""
        self.assertIn("const FIRST_VISIT_KEY = 'lensyou_first_visit';", self.js)
        self.assertIn("function initFirstTimeExperience()", self.js)
        self.assertIn("function dismissFirstTimeGuide()", self.js)
        self.assertIn("function hideFirstTimeTooltip()", self.js)
        self.assertIn("function pasteQuickUrl(url)", self.js)


class TestF15ViewSegregationStaticAndDOM(unittest.TestCase):
    """Adversarially validates Feature F15 HTML DOM structure, View Segregation, and Secondary Tools."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PROJECT_ROOT, 'templates', 'index.html'), 'r', encoding='utf-8') as f:
            cls.html = f.read()
        with open(os.path.join(PROJECT_ROOT, 'static', 'script.js'), 'r', encoding='utf-8') as f:
            cls.js = f.read()
        with open(os.path.join(PROJECT_ROOT, 'static', 'style.css'), 'r', encoding='utf-8') as f:
            cls.css = f.read()

    def test_f15_density_toolbar_structure(self):
        """Verify Executive View vs Full Research View density toolbar."""
        self.assertIn('id="dashboardDensityToolbar"', self.html)
        self.assertIn('id="btnViewCore"', self.html)
        self.assertIn('id="btnViewAdvanced"', self.html)
        self.assertIn('id="densityModeNotice"', self.html)
        self.assertIn('Executive View', self.html)
        self.assertIn('Full Research View', self.html)
        self.assertIn("onclick=\"setDashboardViewMode('core')\"", self.html)
        self.assertIn("onclick=\"setDashboardViewMode('advanced')\"", self.html)

    def test_f15_primary_core_view_exposed(self):
        """Verify primary core tools are directly exposed in understand mode pane."""
        self.assertIn('id="pane-understand"', self.html)
        self.assertIn('id="overviewSummaryText"', self.html)
        self.assertIn('id="takeawaysGrid"', self.html)
        self.assertIn('id="section-chapters"', self.html)
        self.assertIn('id="chaptersList"', self.html)
        self.assertIn('id="section-transcript"', self.html)
        self.assertIn('id="section-core-learning"', self.html)
        self.assertIn('id="activeFlashcard"', self.html)
        self.assertIn('id="quizContainer"', self.html)

    def test_f15_secondary_advanced_tools_drawer_and_toggle_card(self):
        """Verify collapsible secondary research tools drawer and toggle header."""
        self.assertIn('id="advancedResearchSection"', self.html)
        self.assertIn('id="advancedToolsToggleCard"', self.html)
        self.assertIn('id="advancedToolsDrawerContent"', self.html)
        self.assertIn('onclick="toggleAdvancedResearchTools()"', self.html)
        self.assertIn('id="btnExpandAdvanced"', self.html)
        self.assertIn('id="advancedToggleBtnText"', self.html)
        self.assertIn('id="advancedToggleArrow"', self.html)

    def test_f15_all_secondary_analytical_containers_have_collapsed_class(self):
        """Verify all secondary analytical tools have .advanced-analytical-tool and .collapsed classes."""
        required_tools = [
            '#section-videomap',
            '#section-multitrack',
            '#section-scorecard',
            '#section-entities',
            '#section-visualmoments',
            '#section-speakers',
            '#section-quotes',
            '#section-repetitions',
            '#section-contradictions',
            '#section-claims',
            '#section-copilot',
            '#section-compare',
            '#section-exports',
            '#section-notes',
            '#section-clips'
        ]

        for tool_id in required_tools:
            raw_id = tool_id.replace('#', '')
            # Match element with this ID having advanced-analytical-tool and collapsed classes
            pattern = rf'id="{raw_id}"[^>]*class="[^"]*advanced-analytical-tool[^"]*collapsed[^"]*"'
            alt_pattern = rf'class="[^"]*advanced-analytical-tool[^"]*collapsed[^"]*"[^>]*id="{raw_id}"'
            self.assertTrue(
                bool(re.search(pattern, self.html) or re.search(alt_pattern, self.html)),
                f"Element {tool_id} must have both 'advanced-analytical-tool' and 'collapsed' classes"
            )

        # Verify inner element containers referenced in requirements exist
        self.assertIn('id="speakersGrid"', self.html)
        self.assertIn('id="contradictionsList"', self.html)
        self.assertIn('id="copilotMessages"', self.html)
        self.assertIn('id="compareMatrixTable"', self.html)

    def test_f15_advanced_subnav_tabs_and_panels(self):
        """Verify 5 subtool navigation tabs and panels."""
        subtools = ['graph', 'speakers', 'contradictions', 'copilot', 'exports']
        for sub in subtools:
            self.assertIn(f'data-subtool="{sub}"', self.html)
            self.assertIn(f'id="subtool-panel-{sub}"', self.html)

    def test_f15_css_classes_collapsed_and_toolbar(self):
        """Verify CSS styling for collapsed state and density toolbar."""
        self.assertIn('.advanced-analytical-tool.collapsed', self.css)
        self.assertIn('.dashboard-density-toolbar', self.css)
        self.assertIn('.density-toggle-btn', self.css)

    def test_f15_js_view_segregation_functions_present(self):
        """Verify JS view segregation functions and constants."""
        self.assertIn("const VIEW_MODE_KEY = 'lensyou_view_mode';", self.js)
        self.assertIn("function setDashboardViewMode(mode)", self.js)
        self.assertIn("function toggleAdvancedTool(elementId)", self.js)
        self.assertIn("function toggleAdvancedResearchTools(forceState = null)", self.js)
        self.assertIn("function ensureAdvancedToolsExpanded(targetElementId = null)", self.js)
        self.assertIn("function switchAdvancedSubtool(subtoolKey)", self.js)


class TestM4VerbatimStringsPreservation(unittest.TestCase):
    """Adversarially validates that 100% of required verbatim strings remain intact in index.html."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PROJECT_ROOT, 'templates', 'index.html'), 'r', encoding='utf-8') as f:
            cls.html = f.read()

    def test_verbatim_blooms_taxonomy_quiz(self):
        self.assertIn("Bloom's Taxonomy Video Mastery Quiz", self.html)

    def test_verbatim_3d_flashcards_shortcuts(self):
        self.assertIn("Space", self.html)
        self.assertIn("Flip", self.html)
        self.assertIn("Prev", self.html)
        self.assertIn("Next", self.html)
        self.assertIn("Interactive 3D Flashcards", self.html)

    def test_verbatim_multihour_timeline_heatmap(self):
        # Allow either raw '&' or HTML escaped '&amp;'
        found = ("Multi-Hour Timeline Heatmap & Evidence Explorer" in self.html or
                 "Multi-Hour Timeline Heatmap &amp; Evidence Explorer" in self.html)
        self.assertTrue(found, "Multi-Hour Timeline Heatmap & Evidence Explorer must be present")

    def test_verbatim_quick_start_pills_and_target_segments(self):
        self.assertIn("Analyze 3B1B Lecture (1-Click) →", self.html)
        self.assertIn("Analyze Founder Interview (1-Click) →", self.html)
        self.assertIn("Analyze Huberman Lab (1-Click) →", self.html)
        self.assertIn("qmNCJxvs080", self.html)
        self.assertIn("aircAruvnKk", self.html)
        self.assertIn("LqY6hFLMEJw", self.html)

    def test_verbatim_chatgpt_differentiation(self):
        self.assertIn("4 Things ChatGPT Cannot Do With Video", self.html)
        self.assertIn("Publication-Grade PDF Dossiers", self.html)

    def test_verbatim_executive_video_intelligence_brand(self):
        found = ("Executive Video Intelligence & Learning Engine" in self.html or
                 "Executive Video Intelligence &amp; Learning Engine" in self.html)
        self.assertTrue(found, "Executive Video Intelligence & Learning Engine must be present")

    def test_verbatim_target_personas(self):
        p1 = ("Medical & Engineering Students" in self.html or
              "Medical &amp; Engineering Students" in self.html)
        p2 = ("Investors & Founders" in self.html or
              "Investors &amp; Founders" in self.html)
        p3 = "Self-Improvement Junkies" in self.html
        self.assertTrue(p1, "Medical & Engineering Students persona must be present")
        self.assertTrue(p2, "Investors & Founders persona must be present")
        self.assertTrue(p3, "Self-Improvement Junkies persona must be present")


class TestM4ClientExportRoutines(unittest.TestCase):
    """Adversarially validates client-side export routines in static/script.js."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PROJECT_ROOT, 'static', 'script.js'), 'r', encoding='utf-8') as f:
            cls.js = f.read()

    def test_export_markdown_dossier_function_definition(self):
        self.assertIn("function exportMarkdownDossier()", self.js)
        self.assertIn("LensYou_${cleanTitle}_Dossier.md", self.js)
        self.assertIn("new Blob([md], { type: 'text/markdown;charset=utf-8;' })", self.js)

    def test_export_transcript_csv_function_definition(self):
        self.assertIn("function exportTranscriptCSV()", self.js)
        self.assertIn("LensYou_${cleanTitle}_Transcript.csv", self.js)
        self.assertIn("new Blob([csv], { type: 'text/csv;charset=utf-8;' })", self.js)

    def test_export_detailed_pdf_function_definition(self):
        self.assertIn("function exportDetailedPDF()", self.js)


class TestM4NodeJsEmpiricalStressExecution(unittest.TestCase):
    """Executes the Node.js empirical JavaScript test harness (19 stress test scenarios)."""

    def test_run_node_js_empirical_stress_harness(self):
        harness_path = os.path.join(PROJECT_ROOT, 'test_m4_ux_view_stress.js')
        self.assertTrue(os.path.exists(harness_path), "test_m4_ux_view_stress.js must exist")

        res = subprocess.run(['node', harness_path], capture_output=True, text=True, cwd=PROJECT_ROOT)
        self.assertEqual(
            res.returncode, 0,
            f"Node.js stress test failed with code {res.returncode}:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
        self.assertIn("=== JAVASCRIPT STRESS TEST RESULTS: 19/19 PASSED ===", res.stdout)


if __name__ == '__main__':
    unittest.main()
