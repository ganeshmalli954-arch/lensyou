import os
import sys
import html
import re
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

def clean(text):
    if text is None:
        return ""
    s = str(text)
    replacements = {
        '✦': '*', '•': '-', '—': '-', '–': '-', '“': '"', '”': '"',
        '‘': "'", '’': "'", '✔': '[v]', '✓': '[v]', '❌': '[x]',
        '🎬': '', '📊': '', '⏳': '', '📑': '', '📝': '', '🏷️': '',
        '🎙️': '', '💡': '', '🔍': '', '⭐': '*', '🎯': '*', '🔒': '',
        '▶': '>', '►': '>', '🧠': '', '🎴': '', '🎓': '', '📄': '',
        '🩺': '', '💼': '', '⚡': '', '💬': '', '☕': '', '₹': 'Rs. ',
        '→': '->', '←': '<-', '≈': '~'
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    s = re.sub(r'[^\x00-\xFF]', ' ', s)
    return html.escape(html.unescape(s), quote=True)

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running footer line
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(36, 32, 576, 32)

        # Footer text
        footer_left = "LensYou Enterprise Project Dossier - Confidential & Comprehensive Architecture"
        footer_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 20, footer_left)
        self.drawRightString(576, 20, footer_right)

        # Running header on page 2+
        if self._pageNumber > 1:
            self.line(36, 762, 576, 762)
            self.drawString(36, 768, "LensYou - Executive Video Intelligence & Learning Engine")
            self.drawRightString(576, 768, datetime.now().strftime("%B %Y"))

        self.restoreState()

def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=44,
        bottomMargin=44
    )

    styles = getSampleStyleSheet()
    primary = colors.HexColor("#0f172a")     # Slate 900
    accent = colors.HexColor("#4338ca")      # Indigo 700
    accent_blue = colors.HexColor("#0284c7") # Sky 600
    muted = colors.HexColor("#475569")       # Slate 600
    dark = colors.HexColor("#1e293b")        # Slate 800
    bg_subtle = colors.HexColor("#f8fafc")   # Slate 50
    border_color = colors.HexColor("#e2e8f0")# Slate 200

    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=20, leading=24,
        textColor=primary, spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSub', parent=styles['Normal'],
        fontName='Helvetica', fontSize=10.5, leading=14,
        textColor=muted, spaceAfter=12
    )
    h1_style = ParagraphStyle(
        'H1', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=13, leading=17,
        textColor=primary, spaceBefore=14, spaceAfter=6, keepWithNext=True
    )
    h2_style = ParagraphStyle(
        'H2', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=10.5, leading=14,
        textColor=accent, spaceBefore=10, spaceAfter=4, keepWithNext=True
    )
    h3_style = ParagraphStyle(
        'H3', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=9.5, leading=13,
        textColor=accent_blue, spaceBefore=6, spaceAfter=2, keepWithNext=True
    )
    body = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=12.5,
        textColor=dark, spaceAfter=4
    )
    body_bold = ParagraphStyle(
        'BodyBold', parent=body,
        fontName='Helvetica-Bold'
    )
    bullet = ParagraphStyle(
        'Bullet', parent=body,
        leftIndent=12, firstLineIndent=-8, spaceAfter=3
    )
    callout_text = ParagraphStyle(
        'Callout', parent=body,
        fontSize=8.5, leading=12, textColor=colors.HexColor("#1e1b4b")
    )
    table_cell = ParagraphStyle(
        'Cell', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8, leading=11, textColor=dark
    )
    table_cell_bold = ParagraphStyle(
        'CellB', parent=table_cell, fontName='Helvetica-Bold', textColor=primary
    )
    table_cell_code = ParagraphStyle(
        'CellCode', parent=table_cell, fontName='Courier', fontSize=7.5, leading=10, textColor=accent
    )

    story = []

    # =========================================================================
    # COVER / HEADER BLOCK
    # =========================================================================
    story.append(Paragraph(clean("LENSYOU — EXECUTIVE VIDEO INTELLIGENCE & LEARNING ENGINE"), title_style))
    story.append(Paragraph(clean("Complete End-to-End Master Project Dossier: Architecture, Evolution, Technical Modules, and Production Reference"), subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=accent, spaceAfter=10))

    meta_table_data = [
        [
            Paragraph(clean("<b>Platform:</b> LensYou v2.5 Enterprise"), table_cell),
            Paragraph(clean("<b>Repository:</b> github.com/ganeshmalli954-arch/lensyou"), table_cell),
            Paragraph(clean("<b>Status:</b> Live Production"), table_cell)
        ],
        [
            Paragraph(clean("<b>Author:</b> Ganesh Malli & Team"), table_cell),
            Paragraph(clean("<b>Deployment:</b> Render PaaS + UptimeRobot Watchdog"), table_cell),
            Paragraph(clean("<b>Test Pass Rate:</b> 52 / 52 Automated Tests (100%)"), table_cell)
        ],
        [
            Paragraph(clean("<b>Live Domain:</b> lensyou.onrender.com"), table_cell),
            Paragraph(clean("<b>Core Architecture:</b> Event-Driven Modular Pipeline"), table_cell),
            Paragraph(clean(f"<b>Generated:</b> {datetime.now().strftime('%B %d, %Y')}"), table_cell)
        ]
    ]
    t_meta = Table(meta_table_data, colWidths=[180, 200, 160])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), bg_subtle),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 12))

    # =========================================================================
    # SECTION 1: EXECUTIVE SUMMARY & PLATFORM IDENTITY
    # =========================================================================
    story.append(Paragraph(clean("1. Executive Summary & Core Value Proposition"), h1_style))
    story.append(Paragraph(clean(
        "<b>LensYou</b> is an enterprise-grade AI video intelligence and active learning platform engineered to solve the "
        "lecture and podcast overload crisis for high-stakes, time-poor consumers. While generic LLM wrappers produce superficial "
        "walls of summary text, LensYou transforms 1- to 4+ hour video recordings into interactive, fully grounded, verifiable "
        "knowledge engines in ~50 milliseconds for cached media and under 2 minutes for raw multi-hour lectures."
    ), body))
    story.append(Paragraph(clean(
        "The fundamental design tenet of LensYou is: <i>'Never call it a summarizer.'</i> Summaries are commodity artifacts. "
        "LensYou is an <b>Executive Video Intelligence & Learning Engine</b> featuring four distinct capabilities that standard LLMs and ChatGPT cannot deliver:"
    ), body))

    diff_table_data = [
        [
            Paragraph(clean("<b>Capability</b>"), table_cell_bold),
            Paragraph(clean("<b>What LensYou Delivers</b>"), table_cell_bold),
            Paragraph(clean("<b>Why ChatGPT Cannot Compete</b>"), table_cell_bold)
        ],
        [
            Paragraph(clean("<b>1. Interactive 3D Flashcards</b>"), table_cell),
            Paragraph(clean("Active recall flashcard decks with realistic 3D card-flip physics and rapid desktop keyboard navigation ([Space] to flip, [<-] and [->] to cycle)."), table_cell),
            Paragraph(clean("ChatGPT outputs static bullet points without interactive state, spatial flipping, or keyboard study ergonomics."), table_cell)
        ],
        [
            Paragraph(clean("<b>2. Bloom's Taxonomy Quizzes</b>"), table_cell),
            Paragraph(clean("Diagnostic assessments categorized across cognitive tiers (Remember, Understand, Apply, Evaluate) with automated rationale explanations."), table_cell),
            Paragraph(clean("Generic models generate basic multiple-choice questions without hierarchical cognitive testing or explanation mapping."), table_cell)
        ],
        [
            Paragraph(clean("<b>3. Timeline Density Heatmaps</b>"), table_cell),
            Paragraph(clean("Visual multi-track timeline spanning 1-4+ hour videos with clickable, verifiable timestamps grounded in transcript segments."), table_cell),
            Paragraph(clean("LLMs have zero native temporal grounding and cannot verify or jump to exact playback points."), table_cell)
        ],
        [
            Paragraph(clean("<b>4. Publication PDF Dossiers</b>"), table_cell),
            Paragraph(clean("Publication-grade multi-page PDF dossiers with thesis extraction, concept hierarchies, quote evidence, and study outlines exported with 1 click."), table_cell),
            Paragraph(clean("ChatGPT provides raw unstructured text that requires manual formatting and loses layout structure."), table_cell)
        ]
    ]
    t_diff = Table(diff_table_data, colWidths=[120, 230, 190])
    t_diff.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#e0e7ff")),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_diff)
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 2: COMPLETE CHRONOLOGICAL EVOLUTION (FROM GENESIS TO COMPLETION)
    # =========================================================================
    story.append(Paragraph(clean("2. Chronological Project Evolution: Starting Point to Completion"), h1_style))
    story.append(Paragraph(clean(
        "The project underwent seven major evolutionary phases, transforming from a simple prototype into an enterprise-ready, "
        "fault-tolerant video intelligence platform:"
    ), body))

    phases = [
        ("Phase 1: Genesis & Prototype Architecture (VideoLens MVP)",
         "Created the initial prototype with Flask and Waitress server on Windows. Integrated basic youtube_transcript_api and "
         "Google Gemini 1.5 Flash API calls. Built the core 5-mode user interface (Understand, Research, Learn, Create, Compare) "
         "using a Bloomberg-density quiet luxury dark theme."),
        ("Phase 2: Part A Architectural Foundation & Security (SQLite, 2FA, Admin)",
         "Replaced in-memory states with a persistent SQLite relational database (videolens.db). Implemented isolated multi-account user records, "
         "Google OAuth 2.0 integration, anonymous session tracking, and quota management. Built the comprehensive Owner & Admin Portal "
         "featuring live system telemetry (CPU, RAM, Disk), search analytics, user audit logs, Buy Me a Coffee (BMC) dynamic settings, "
         "UPI intent links, promo code batch generation, and Google Authenticator Two-Factor Authentication (TOTP QR codes and secret keys)."),
        ("Phase 3: Brand Rebranding (VideoLens -> LensYou)",
         "Executed an end-to-end rebranding across the entire codebase to protect trademarks and establish unique intellectual property: "
         "updated all frontend templates, titles, meta tags, manifest.json, PDF dossiers, system prompts, Bat runners, and TOTP issuer strings "
         "(otpauth://totp/LensYou:Admin). Maintained 100% backward compatibility for database tables."),
        ("Phase 4: True Multi-Hour Lecture Duration Scaling (1–4+ Hours)",
         "Solved the video truncation bug where YouTube oEmbed omitted durations and sparse transcripts collapsed 3-hour lectures into "
         "1-minute timelines. Implemented ISO 8601 itemprop scraping (e.g. PT2H45M12S) combined with yt-dlp length checks, and built a dynamic "
         "timeline phase scaling algorithm generating 4 to 12 structured chronological milestones spanning multi-hour recordings."),
        ("Phase 5: The 4 Failure Chokepoints (Pre-Mortem Neutralization)",
         "Identified and permanently neutralized the 4 critical failure modes: (1) Cloud IP Wall & (2) API Throttling solved via 50ms instant SQLite "
         "caching in job_service.py and /api/analyze with idx_videos_video_id index, consuming 0 tokens on viral repeat videos; (3) Cold-Start Bug "
         "solved via public /api/health endpoint, an 8-minute background self-ping daemon, and UptimeRobot watchdog; (4) 'One-and-Done' Churn solved "
         "via public shareable dossiers (/v/<video_id>), dynamic OpenGraph and Twitter card link unfurling, and 1-click social share modals."),
        ("Phase 6: Anti-Commodity Repositioning & Dual-Region Monetization",
         "Repositioned the platform from 'summarizer' to 'Executive Video Intelligence & Learning Engine'. Added high-converting sticky top bars on shared "
         "dossiers, interactive 3D flashcards with focus-guarded keyboard listeners, Bloom's taxonomy quiz badges, and 3 high-stakes audience shortcuts "
         "(Medical/Engineering Students, Investors/Founders, Self-Improvement). Built dual-currency pricing toggle (India INR: Rs. 50/Rs. 70/Rs. 99 via UPI vs "
         "International USD: $2.99/$3.99/$4.99 via Stripe/BMC). Deployed automated weekly retention loops (retention_service.py) and cloud backups (backup_service.py)."),
        ("Phase 7: Teamwork Enterprise Reliability & Evidence Grounding Upgrade",
         "Executed a multi-agent architectural overhaul: (R1) Module-Level Partial Recovery preserving upstream outputs (metadata, transcript, chapters, summary) "
         "when downstream AI modules fail; (R2) Evidence Grounding Engine with transcript segment ID linking, timestamp duration boundary validation, and verbatim "
         "quote excerpts; (R3) Duration-Weighted Credit Model scaling resource consumption using 15-minute ceiling blocks with sub-second precision; (R4) Expanded "
         "canonical test suite to 52 automated tests passing with 100% verification and zero regressions.")
    ]

    for title, desc in phases:
        story.append(Paragraph(clean(f"<b>{title}</b>"), h2_style))
        story.append(Paragraph(clean(desc), body))

    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 3: TECHNICAL ARCHITECTURE & COMPONENT BLUEPRINT
    # =========================================================================
    story.append(Paragraph(clean("3. System Architecture & Technical Stack"), h1_style))
    story.append(Paragraph(clean(
        "LensYou operates on a decoupled, event-driven modular pipeline designed to balance microsecond response times for cached "
        "intelligence with deep analytical precision for raw multi-hour video ingestion."
    ), body))

    tech_stack_data = [
        [Paragraph(clean("<b>Layer</b>"), table_cell_bold), Paragraph(clean("<b>Technologies & Architecture</b>"), table_cell_bold)],
        [Paragraph(clean("<b>Backend Web Server</b>"), table_cell), Paragraph(clean("Python 3.11, Flask, Waitress multi-threaded WSGI server (8 worker threads), Werkzeug ProxyFix for reverse-proxy client IP and SSL resolution."), table_cell)],
        [Paragraph(clean("<b>Frontend Application</b>"), table_cell), Paragraph(clean("High-performance Vanilla JavaScript (zero heavy NPM dependencies), CSS3 3D transforms with perspective flipping, SVG iconography, dark-mode quiet luxury design system."), table_cell)],
        [Paragraph(clean("<b>Database & Caching</b>"), table_cell), Paragraph(clean("SQLite relational database with WAL (Write-Ahead Logging) mode, custom BoundedCache LRU in-memory buffer (20 items), indexed video lookups via idx_videos_video_id."), table_cell)],
        [Paragraph(clean("<b>AI / LLM Orchestration</b>"), table_cell), Paragraph(clean("Google Gemini 1.5 / 2.0 API with round-robin multi-key pool rotation (GEMINI_API_KEYS), temperature control, structured JSON schema parsing, and copilot grounded Q&A prompts."), table_cell)],
        [Paragraph(clean("<b>Transcript Ingestion</b>"), table_cell), Paragraph(clean("4-Tier resilient waterfall: Tier 1 (youtube_transcript_api), Tier 2 (yt-dlp auto-sub VTT), Tier 3 (Groq Whisper Large v3 turbo), Tier 4 (metadata & chapter synthesis)."), table_cell)],
        [Paragraph(clean("<b>Verification Engine</b>"), table_cell), Paragraph(clean("services/verification_service.py: Dual-mode citation validation, transcript segment ID matching, timestamp duration boundary verification, and verbatim source quote extraction."), table_cell)],
        [Paragraph(clean("<b>Retention Engine</b>"), table_cell), Paragraph(clean("services/retention_service.py: Automated spaced repetition notifications for saved flashcard decks, weekly trending podcast digests, and cron scheduler."), table_cell)],
        [Paragraph(clean("<b>DevOps & Hosting</b>"), table_cell), Paragraph(clean("Render PaaS Web Service, persistent disk mounts (/var/data), automated 8-minute keepalive self-ping daemon, UptimeRobot external 5-minute health watchdog."), table_cell)]
    ]
    t_stack = Table(tech_stack_data, colWidths=[130, 410])
    t_stack.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_stack)
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 4: COMPLETE FEATURE MATRIX
    # =========================================================================
    story.append(Paragraph(clean("4. Complete Feature Inventory & Functional Matrix"), h1_style))
    story.append(Paragraph(clean(
        "LensYou provides five core intelligence modes, three dedicated exploration tools, an AI Copilot, and an enterprise admin console:"
    ), body))

    features = [
        ("Core Mode 1: Understand Mode", [
            "Executive Notes: High-level thesis statement, primary mission, and distilled key takeaways.",
            "Automatic Chapters: Structured chronological breakdown with exact timestamps and descriptive sub-points.",
            "Multi-Track Timeline: Visual heatmap mapping the flow of topics and speaker narrative.",
            "Quality Scorecard & Engagement Curve: Numerical quality ratings (0-100) and audience attention curves."
        ]),
        ("Core Mode 2: Research Mode", [
            "Evidence Claims: Grounded propositions linked to transcript segment IDs and exact start/end seconds.",
            "Entity Extractor: Comprehensive registry of referenced individuals, technologies, companies, and academic papers.",
            "Contradiction Detector: Flags internal speaker inconsistencies or logical paradoxes within the presentation.",
            "Repetition Index & Speaker Dynamics: Quantifies rhetoric emphasis, topic frequency, and dialogue distribution."
        ]),
        ("Core Mode 3: Learn Mode", [
            "Interactive 3D Flashcards: 3D perspective flip cards with keyboard shortcuts ([Space], [<-], [->]) and focus protection.",
            "Bloom's Taxonomy Quiz: Multi-question assessments tagged with cognitive tiers (Remember, Understand, Apply, Evaluate).",
            "Study Notes: Comprehensive educational breakdown formatted for rapid exam review and knowledge retention."
        ]),
        ("Core Mode 4: Create / Act Mode", [
            "Viral Short Concepts: Actionable short-form video hooks with visual descriptions and timestamp cues.",
            "Executive Social Posts: Pre-formatted Twitter/X threads and LinkedIn thought-leadership essays.",
            "Newsletter Digests: Publication-ready markdown newsletter summaries with headline hooks."
        ]),
        ("Core Mode 5: Compare Mode", [
            "Cross-Video Comparative Matrix: Side-by-side thematic analysis across two different video analyses.",
            "Common Ground & Key Disagreements: Highlights shared principles and philosophical divergences.",
            "Synthesis Verdict: AI-generated holistic consensus on the subject matter."
        ]),
        ("Specialized Tools & Copilot", [
            "Grounded Video Copilot: Interactive chat grounded in video evidence, citing timestamps [MM:SS] with zero disclaimers.",
            "Video Map Concept Graph: Visual node-based relationship map connecting key concepts and sub-topics.",
            "Split Transcript Explorer: Side-by-side timestamped transcript with live search and snippet filtering.",
            "Publication-Grade PDF Export: 1-click download of styled, publication-ready multi-page intelligence reports."
        ]),
        ("Owner & Admin Portal (/admin/)", [
            "System Telemetry: Real-time hardware gauges for CPU usage, RAM allocation, and Disk utilization.",
            "User Management & Plan Overrides: View user accounts, login history, and override plans (Free, Rs. 50, Rs. 70, Rs. 99).",
            "Content & Search Analytics: Tracks total queries, unique searched media, processing success rates, and user interactions.",
            "Two-Factor Authentication (2FA): Google Authenticator TOTP protection with QR code provisioning and manual secret key.",
            "Payment Auditing: Verified transaction logs for UPI and Razorpay, revenue metrics, and promo voucher generation."
        ])
    ]

    for title, items in features:
        story.append(Paragraph(clean(f"<b>{title}</b>"), h2_style))
        for item in items:
            story.append(Paragraph(clean(f"- {item}"), bullet))

    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 5: DATABASE SCHEMA & DATA DICTIONARY
    # =========================================================================
    story.append(Paragraph(clean("5. Relational Database Schema & Architecture"), h1_style))
    story.append(Paragraph(clean(
        "LensYou persists all operational state in SQLite. Below is the complete relational schema specification:"
    ), body))

    db_tables = [
        ("users", "id (PK, TEXT), provider (TEXT), provider_id (TEXT), email (TEXT), name (TEXT), avatar_url (TEXT), plan (TEXT: free|pack10|pack50|unlimited), quota_used (INT), quota_limit (INT: -1 for unlimited), role (TEXT: user|admin), created_at (TEXT), last_active (TEXT), login_count (INT)"),
        ("anon_sessions", "session_key (PK, TEXT: SHA256 IP+UA hash), quota_used (INT), created_at (TEXT)"),
        ("videos", "id (PK, TEXT), video_id (TEXT, INDEXED via idx_videos_video_id), title (TEXT), author (TEXT), duration (TEXT), analysis_json (TEXT: complete JSON intelligence cache), user_id (TEXT), session_key (TEXT), created_at (TEXT)"),
        ("redemption_codes", "code (PK, TEXT), plan (TEXT), quota_grant (INT), used (BOOLEAN), used_by (TEXT), used_at (TEXT), created_at (TEXT)"),
        ("search_events", "id (PK, TEXT), user_id (TEXT), session_key (TEXT), query (TEXT), content_id (TEXT), content_title (TEXT), content_type (TEXT), plan (TEXT), created_at (TEXT)"),
        ("processing_events", "id (PK, TEXT), user_id (TEXT), session_key (TEXT), content_id (TEXT), content_title (TEXT), content_type (TEXT), status (TEXT: pending|success|failed), error_info (TEXT), duration (TEXT), model_used (TEXT), plan (TEXT), created_at (TEXT)"),
        ("payments", "id (PK, TEXT), user_id (TEXT), payment_id (TEXT), order_id (TEXT), amount (REAL), currency (TEXT: INR|USD), plan (TEXT), status (TEXT: verified), provider (TEXT: razorpay|stripe|bmc), created_at (TEXT)"),
        ("system_settings", "key (PK, TEXT), value (TEXT), updated_at (TEXT) - stores bmc_url and admin_2fa_enabled"),
        ("notifications", "id (PK, TEXT), user_id (TEXT), title (TEXT), message (TEXT), type (TEXT: spaced_repetition|trending_digest), is_read (INT), created_at (TEXT)")
    ]

    db_table_data = [
        [Paragraph(clean("<b>Table Name</b>"), table_cell_bold), Paragraph(clean("<b>Columns, Data Types & Constraints</b>"), table_cell_bold)]
    ]
    for tbl, cols in db_tables:
        db_table_data.append([
            Paragraph(clean(f"<b>{tbl}</b>"), table_cell_code),
            Paragraph(clean(cols), table_cell)
        ])

    t_db = Table(db_table_data, colWidths=[110, 430])
    t_db.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 3.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_db)
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 6: API ROUTE SPECIFICATION
    # =========================================================================
    story.append(Paragraph(clean("6. Complete API Route & Endpoint Reference"), h1_style))
    story.append(Paragraph(clean(
        "LensYou exposes a robust RESTful API surface handling public sharing, authentication, intelligence processing, and administration:"
    ), body))

    routes_data = [
        ("GET /", "Public landing page and main interactive intelligence canvas."),
        ("GET /history", "Personal analysis history and saved intelligence records page."),
        ("GET /v/<video_id>", "Public shareable dossier endpoint rendering pre-cached intelligence in 50ms with OpenGraph tags."),
        ("GET /api/dossier/<video_id>", "JSON API returning cached video intelligence without consuming Gemini tokens."),
        ("GET /api/health", "Lightweight JSON health check returning status: ok for keepalive and UptimeRobot."),
        ("GET /manifest.json, /robots.txt, /sitemap.xml", "PWA web app manifest, SEO search crawler directives, and daily XML sitemap."),
        ("GET /auth/google, /auth/google/callback", "Google OAuth 2.0 authorization redirect and profile token callback handler."),
        ("GET /auth/google/info", "Helper page providing exact Authorized Redirect URI for Google Cloud Console setup."),
        ("POST /auth/logout", "Terminates active session and clears permanent authentication cookies."),
        ("GET /api/me", "Returns user identity, active plan, quota allowance, and history limits."),
        ("GET /api/config", "Exposes active feature flags (Google login, Twitter login) and dynamic BMC link."),
        ("POST /api/search", "Unified search endpoint recording search event and scraping candidate YouTube videos."),
        ("POST /api/analyze", "Initiates asynchronous video intelligence analysis job, validating quota and cache."),
        ("GET /api/job/<job_id>", "Polls status of running job, reporting granular stage progress (1-9) or completion."),
        ("POST /api/chat", "Evidence-grounded Copilot chat endpoint synthesizing answer from transcript citations."),
        ("POST /api/compare", "Cross-video comparative synthesis matrix comparing two analyzed media items."),
        ("POST /api/export-pdf", "Generates and streams publication-grade PDF report with attachment header."),
        ("POST /api/redeem", "Redeems promotional access code to upgrade user plan and grant extra quotas."),
        ("GET /api/payment/plans", "Returns plan catalog with domestic INR and international USD pricing specifications."),
        ("POST /api/payment/verify", "Verifies Razorpay/Stripe transaction and updates user plan tier."),
        ("GET /api/notifications/retention", "Fetches active spaced repetition alerts and weekly trending podcast digests."),
        ("GET /admin/", "Owner & Admin Portal dashboard (protected by admin session and TOTP 2FA)."),
        ("GET, POST /admin/login", "Administrator authentication handler supporting password and Google Authenticator 6-digit TOTP."),
        ("GET, POST /admin/setup-2fa", "Provisions 2FA QR code and manual setup key for Google Authenticator app."),
        ("POST /admin/api/user/<user_id>/plan", "Overrides user subscription plan (free, pack10, pack50, unlimited) and quota limit."),
        ("GET /admin/api/stats, /health, /users, /videos", "Exposes executive statistics, hardware telemetry, registered accounts, and analyzed video caches.")
    ]

    r_table_data = [
        [Paragraph(clean("<b>Route & Method</b>"), table_cell_bold), Paragraph(clean("<b>Description & Functionality</b>"), table_cell_bold)]
    ]
    for rt, desc in routes_data:
        r_table_data.append([
            Paragraph(clean(f"<b>{rt}</b>"), table_cell_code),
            Paragraph(clean(desc), table_cell)
        ])

    t_routes = Table(r_table_data, colWidths=[170, 370])
    t_routes.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_routes)
    story.append(Spacer(1, 10))

    # =========================================================================
    # SECTION 7: TESTING, AUDIT & DEPLOYMENT VERIFICATION
    # =========================================================================
    story.append(Paragraph(clean("7. Testing Verification, Adversarial Audits & Production Status"), h1_style))
    story.append(Paragraph(clean(
        "LensYou has undergone rigorous multi-phase testing, culminating in an adversarial multi-agent verification wave "
        "and an independent Victory Audit confirming zero defects and zero regressions across all canonical suites:"
    ), body))

    test_suites_data = [
        [Paragraph(clean("<b>Test Suite File</b>"), table_cell_bold), Paragraph(clean("<b>Cases</b>"), table_cell_bold), Paragraph(clean("<b>Focus Area & Verification Scope</b>"), table_cell_bold), Paragraph(clean("<b>Status</b>"), table_cell_bold)],
        [Paragraph(clean("test_part_a_suite.py"), table_cell_code), Paragraph(clean("18"), table_cell), Paragraph(clean("Public routes, auth protection, account isolation, search analytics, TOTP 2FA, payments."), table_cell), Paragraph(clean("<b>18 / 18 PASS</b>"), table_cell)],
        [Paragraph(clean("test_boost_features.py"), table_cell_code), Paragraph(clean("14"), table_cell), Paragraph(clean("50ms SQLite cache hit, /api/health, public dossier routes, dual-region pricing, retention loops."), table_cell), Paragraph(clean("<b>14 / 14 PASS</b>"), table_cell)],
        [Paragraph(clean("test_reliability_suite.py"), table_cell_code), Paragraph(clean("20"), table_cell), Paragraph(clean("10-module fault isolation, partial recovery, citation grounding, timestamp bounds, duration credits."), table_cell), Paragraph(clean("<b>20 / 20 PASS</b>"), table_cell)],
        [Paragraph(clean("<b>TOTAL CANONICAL SUITE</b>"), table_cell_bold), Paragraph(clean("<b>52</b>"), table_cell_bold), Paragraph(clean("<b>End-to-End Enterprise Reliability & Production Readiness</b>"), table_cell_bold), Paragraph(clean("<b>52 / 52 PASS (100%)</b>"), table_cell_bold)]
    ]
    t_test = Table(test_suites_data, colWidths=[140, 45, 275, 80])
    t_test.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f1f5f9")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#dcfce7")),
        ('BOX', (0,0), (-1,-1), 0.5, border_color),
        ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(t_test)
    story.append(Spacer(1, 14))

    # Concluding Callout
    callout_data = [[
        Paragraph(clean(
            "<b>PROJECT COMPLETION VERDICT:</b> LensYou has successfully evolved from a baseline transcript viewer into an "
            "authoritative, fault-tolerant Executive Video Intelligence & Learning Engine. With 52 passing automated tests, persistent "
            "SQLite caching, sub-second evidence citations, duration-weighted resource controls, and multi-region payment monetization, "
            "the platform is production-ready, highly resilient, and completely deployed."
        ), callout_text)
    ]]
    t_callout = Table(callout_data, colWidths=[540])
    t_callout.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#e0e7ff")),
        ('BOX', (0,0), (-1,-1), 1, accent),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(t_callout)

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Master Dossier PDF successfully generated at: {output_path}")

if __name__ == '__main__':
    out = os.path.join(os.path.dirname(__file__), 'LensYou_Master_Project_Dossier.pdf')
    build_pdf(out)
