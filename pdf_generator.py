import io
import re
import html
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

def sanitize_text(text):
    if text is None:
        return ""
    s = str(text)
    replacements = {
        '✦': '*', '•': '-', '—': '-', '–': '-', '“': '"', '”': '"',
        '‘': "'", '’': "'", '✔': '[v]', '✓': '[v]', '❌': '[x]',
        '🎬': '', '📊': '', '⏳': '', '📑': '', '📝': '', '🏷️': '',
        '🎙️': '', '💡': '', '🔍': '', '⭐': '*', '🎯': '*', '🔒': '',
        '▶': '>', '►': '>'
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    s = re.sub(r'[^\x00-\xFF]', ' ', s)
    return html.escape(s).replace('&amp;', '&')


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically add total page numbers and running footer."""
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
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(36, 32, 576, 32)

        # Footer text
        footer_left = "LensYou AI Intelligence Dossier - Personal & Local Analysis"
        footer_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(36, 20, footer_left)
        self.drawRightString(576, 20, footer_right)

        # Running header on page 2+
        if self._pageNumber > 1:
            self.line(36, 762, 576, 762)
            self.drawString(36, 768, "LensYou Video Intelligence Report")
            self.drawRightString(576, 768, datetime.now().strftime("%B %d, %Y"))

        self.restoreState()


def generate_detailed_pdf(data: dict) -> io.BytesIO:
    """Generate a publication-grade, detailed PDF dossier with headings, subheadings, tables, and metrics."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=44,
        bottomMargin=44
    )

    styles = getSampleStyleSheet()

    color_primary = colors.HexColor("#1e1b4b")   # Dark Navy/Indigo
    color_accent = colors.HexColor("#4f46e5")    # Indigo
    color_muted = colors.HexColor("#475569")     # Slate Muted
    color_dark = colors.HexColor("#0f172a")      # Dark Body Text

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=color_primary,
        spaceAfter=6
    )

    h1_style = ParagraphStyle(
        'H1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=color_primary,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=color_accent,
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=color_dark,
        spaceAfter=5
    )

    body_muted = ParagraphStyle(
        'BodyMuted',
        parent=body_style,
        fontName='Helvetica-Oblique',
        textColor=color_muted,
        fontSize=8.5,
        leading=12
    )

    table_header_style = ParagraphStyle(
        'TH',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.whitesmoke
    )

    table_cell_style = ParagraphStyle(
        'TD',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=11,
        textColor=color_dark
    )

    table_cell_bold = ParagraphStyle(
        'TDBold',
        parent=table_cell_style,
        fontName='Helvetica-Bold',
        textColor=color_primary
    )

    quote_style = ParagraphStyle(
        'Quote',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#1e293b"),
        leftIndent=15,
        spaceBefore=4,
        spaceAfter=4
    )

    story = []

    # Metadata extraction
    meta = data.get("_meta", {})
    ov = data.get("video_overview", {})
    metrics = data.get("metrics", {})

    video_title = sanitize_text(meta.get("title") or ov.get("title") or "YouTube Video Analysis")
    author = sanitize_text(meta.get("author") or ov.get("channel") or "Content Creator")
    duration = sanitize_text(meta.get("duration") or metrics.get("duration") or "N/A")
    category = sanitize_text(ov.get("category") or "General")
    content_type = sanitize_text(ov.get("content_type") or "Video")
    overall_tone = sanitize_text(ov.get("overall_tone") or "Informative")
    quality_score = metrics.get("quality_score", "8.5")

    # 1. TOP HEADER BANNER
    header_box = [
        [
            Paragraph(f"<b>LENSYOU INTELLIGENCE DOSSIER</b> &nbsp;|&nbsp; <i>Personal &amp; Local Analysis</i>", table_header_style),
            Paragraph(f"<b>Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}", ParagraphStyle('RightTH', parent=table_header_style, alignment=2))
        ]
    ]
    hb_table = Table(header_box, colWidths=[360, 180])
    hb_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), color_primary),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(hb_table)
    story.append(Spacer(1, 10))

    # Video Title
    story.append(Paragraph(video_title, title_style))

    # Metadata Summary Bar
    meta_data = [
        [
            Paragraph(f"<b>Channel:</b> {author}", body_style),
            Paragraph(f"<b>Duration:</b> {duration}", body_style),
            Paragraph(f"<b>Category:</b> {category}", body_style),
            Paragraph(f"<b>Type:</b> {content_type}", body_style)
        ],
        [
            Paragraph(f"<b>Tone:</b> {overall_tone}", body_style),
            Paragraph(f"<b>Quality Score:</b> {quality_score}/10", body_style),
            Paragraph(f"<b>Key Points:</b> {metrics.get('key_points_count', len(data.get('key_takeaways', [])))}", body_style),
            Paragraph(f"<b>Chapters:</b> {metrics.get('chapters_count', len(data.get('chapters', [])))}", body_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[135, 135, 135, 135])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 1: EXECUTIVE SUMMARY
    # -------------------------------------------------------------
    story.append(Paragraph("1. EXECUTIVE SUMMARY", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))
    
    summary_text = sanitize_text(ov.get("summary") or "No executive summary available.")
    for para in summary_text.split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), body_style))

    if ov.get("target_audience") or ov.get("visual_style"):
        extra_meta = []
        if ov.get("target_audience"):
            extra_meta.append(f"<b>Target Audience:</b> {sanitize_text(ov['target_audience'])}")
        if ov.get("visual_style"):
            extra_meta.append(f"<b>Visual Style:</b> {sanitize_text(ov['visual_style'])}")
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(extra_meta), body_muted))

    story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # HEADING 2: STRATEGIC KEY TAKEAWAYS
    # -------------------------------------------------------------
    takeaways = data.get("key_takeaways", [])
    if takeaways:
        story.append(Paragraph("2. STRATEGIC KEY TAKEAWAYS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        for idx, t in enumerate(takeaways, 1):
            t_id = sanitize_text(t.get("id") or f"{idx:02d}")
            t_title = sanitize_text(t.get("title") or "Key Takeaway")
            t_imp = sanitize_text(t.get("importance") or "HIGH").upper()
            t_ts = sanitize_text(t.get("timestamp") or "")
            t_conf = sanitize_text(t.get("confidence") or "Analyzed")
            t_desc = sanitize_text(t.get("description") or "")

            imp_color = "#dc2626" if "CRITICAL" in t_imp else "#d97706" if "HIGH" in t_imp else "#2563eb"
            subhead_text = f"<b>Sub-Heading 2.{idx}: [{t_ts}] {t_title}</b> &nbsp;<font color='{imp_color}'><b>[{t_imp}]</b></font>"

            item_content = [
                Paragraph(subhead_text, h2_style),
                Paragraph(t_desc, body_style),
                Paragraph(f"<i>Source Timestamp: {t_ts} &nbsp;|&nbsp; Confidence: {t_conf}</i>", body_muted),
                Spacer(1, 4)
            ]
            story.append(KeepTogether(item_content))

        story.append(Spacer(1, 6))

    # -------------------------------------------------------------
    # HEADING 3: CHAPTER-BY-CHAPTER BREAKDOWN
    # -------------------------------------------------------------
    chapters = data.get("chapters", [])
    if chapters:
        story.append(Paragraph("3. CHAPTER-BY-CHAPTER BREAKDOWN", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        for idx, ch in enumerate(chapters, 1):
            ch_num = sanitize_text(ch.get("number") or f"{idx:02d}")
            ch_title = sanitize_text(ch.get("title") or "Chapter")
            ch_start = sanitize_text(ch.get("start_time") or "")
            ch_end = sanitize_text(ch.get("end_time") or "")
            ch_sum = sanitize_text(ch.get("summary") or "")
            key_points = ch.get("key_points", [])

            subhead_text = f"<b>Sub-Heading 3.{idx}: Chapter {ch_num} - {ch_title} ({ch_start} - {ch_end})</b>"
            
            ch_items = [
                Paragraph(subhead_text, h2_style),
                Paragraph(ch_sum, body_style)
            ]
            if key_points:
                bullet_lines = "<br/>".join([f"&nbsp;&nbsp;* {sanitize_text(pt)}" for pt in key_points])
                ch_items.append(Paragraph(bullet_lines, body_style))
            ch_items.append(Spacer(1, 4))

            story.append(KeepTogether(ch_items))

        story.append(Spacer(1, 6))

    # -------------------------------------------------------------
    # HEADING 4: CHRONOLOGICAL TIMELINE & MILESTONES
    # -------------------------------------------------------------
    timeline = data.get("timeline", [])
    if timeline:
        story.append(Paragraph("4. CHRONOLOGICAL TIMELINE & MILESTONES", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        tl_rows = [
            [
                Paragraph("<b>Timestamp</b>", table_header_style),
                Paragraph("<b>Milestone / Event</b>", table_header_style),
                Paragraph("<b>Category</b>", table_header_style),
                Paragraph("<b>Significance & Notes</b>", table_header_style)
            ]
        ]
        for item in timeline:
            ts = sanitize_text(item.get("time") or "")
            title = sanitize_text(item.get("title") or "")
            mtype = sanitize_text(item.get("type") or "Moment").replace("_", " ").title()
            desc = sanitize_text(item.get("description") or "")

            tl_rows.append([
                Paragraph(f"<b>{ts}</b>", table_cell_bold),
                Paragraph(f"<b>{title}</b>", table_cell_style),
                Paragraph(mtype, table_cell_style),
                Paragraph(desc, table_cell_style)
            ])

        tl_table = Table(tl_rows, colWidths=[65, 145, 90, 240])
        tl_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), color_primary),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ]))
        story.append(tl_table)
        story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 5: TOPIC DISTRIBUTION & COVERAGE
    # -------------------------------------------------------------
    topics = data.get("topics", [])
    if topics:
        story.append(Paragraph("5. TOPIC DISTRIBUTION & COVERAGE", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        top_rows = [
            [
                Paragraph("<b>Topic Name</b>", table_header_style),
                Paragraph("<b>Coverage %</b>", table_header_style),
                Paragraph("<b>Subtopics & Concepts Explored</b>", table_header_style)
            ]
        ]
        for top in topics:
            tname = sanitize_text(top.get("name") or "")
            tpct = f"{top.get('percentage', 0)}%"
            subtopics = ", ".join([sanitize_text(s) for s in top.get("subtopics", [])])

            top_rows.append([
                Paragraph(f"<b>{tname}</b>", table_cell_bold),
                Paragraph(tpct, table_cell_style),
                Paragraph(subtopics or "General analysis", table_cell_style)
            ])

        top_table = Table(top_rows, colWidths=[160, 80, 300])
        top_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), color_primary),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ]))
        story.append(top_table)
        story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 6: SPEAKER ATTRIBUTION & DYNAMICS
    # -------------------------------------------------------------
    speakers = data.get("speakers", [])
    if speakers:
        story.append(Paragraph("6. SPEAKER ATTRIBUTION & DYNAMICS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        spk_rows = [
            [
                Paragraph("<b>Speaker Name</b>", table_header_style),
                Paragraph("<b>Role / Title</b>", table_header_style),
                Paragraph("<b>Speaking Share</b>", table_header_style),
                Paragraph("<b>Est. Words</b>", table_header_style),
                Paragraph("<b>Questions</b>", table_header_style)
            ]
        ]
        for sp in speakers:
            sname = sanitize_text(sp.get("speaker") or "Speaker")
            srole = sanitize_text(sp.get("role") or "Participant")
            spct = f"{sp.get('percentage', 0)}%"
            words = sanitize_text(sp.get("words_estimate") or "-")
            questions = str(sp.get("questions_count", 0))

            spk_rows.append([
                Paragraph(f"<b>{sname}</b>", table_cell_bold),
                Paragraph(srole, table_cell_style),
                Paragraph(spct, table_cell_style),
                Paragraph(words, table_cell_style),
                Paragraph(questions, table_cell_style)
            ])

        spk_table = Table(spk_rows, colWidths=[130, 150, 85, 90, 85])
        spk_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), color_primary),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ]))
        story.append(spk_table)
        story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 7: FACT-CHECKING & VERIFIED CLAIMS
    # -------------------------------------------------------------
    claims = data.get("claims", [])
    if claims:
        story.append(Paragraph("7. FACT-CHECKING & VERIFIED CLAIMS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        cl_rows = [
            [
                Paragraph("<b>Timestamp</b>", table_header_style),
                Paragraph("<b>Claim / Statement</b>", table_header_style),
                Paragraph("<b>Classification</b>", table_header_style)
            ]
        ]
        for cl in claims:
            cts = sanitize_text(cl.get("timestamp") or "")
            cstmt = sanitize_text(cl.get("claim") or cl.get("statement") or "")
            ctype = sanitize_text(cl.get("type") or "Fact")

            badge_color = "#059669" if "Fact" in ctype else "#d97706" if "Prediction" in ctype else "#6366f1"
            type_formatted = f"<font color='{badge_color}'><b>{ctype.upper()}</b></font>"

            cl_rows.append([
                Paragraph(f"<b>{cts}</b>", table_cell_bold),
                Paragraph(cstmt, table_cell_style),
                Paragraph(type_formatted, table_cell_style)
            ])

        cl_table = Table(cl_rows, colWidths=[75, 375, 90])
        cl_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), color_primary),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ]))
        story.append(cl_table)
        story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 8: ENTITY INTELLIGENCE (PEOPLE, COMPANIES, TOOLS)
    # -------------------------------------------------------------
    entities = data.get("entities", {})
    people = entities.get("people", [])
    companies = entities.get("companies", [])
    tools = entities.get("tools_software", [])

    if people or companies or tools:
        story.append(Paragraph("8. ENTITY INTELLIGENCE & CITATIONS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        if people:
            p_str = ", ".join([f"<b>{sanitize_text(p.get('name'))}</b> ({sanitize_text(p.get('role', 'Participant'))})" for p in people])
            story.append(Paragraph(f"<b>People Mentioned:</b> {p_str}", body_style))

        if companies:
            c_str = ", ".join([f"<b>{sanitize_text(c.get('name'))}</b>" for c in companies])
            story.append(Paragraph(f"<b>Organizations / Companies:</b> {c_str}", body_style))

        if tools:
            t_str = ", ".join([f"<b>{sanitize_text(t.get('name'))}</b> ({sanitize_text(t.get('category', 'Tool'))})" for t in tools])
            story.append(Paragraph(f"<b>Tools, Software & References:</b> {t_str}", body_style))

        story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # HEADING 9: LEARNING BRIEF & DEFINITIONS
    # -------------------------------------------------------------
    learning = data.get("learning", {})
    defs = learning.get("key_definitions", [])
    snotes = learning.get("study_notes", [])

    if defs or snotes:
        story.append(Paragraph("9. EDUCATIONAL STUDY BRIEF & DEFINITIONS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        for d in defs[:5]:
            term = sanitize_text(d.get("term") or "")
            dfn = sanitize_text(d.get("definition") or "")
            ts = sanitize_text(d.get("timestamp") or "")
            story.append(Paragraph(f"<b># {term}</b> [{ts}]: {dfn}", body_style))

        for n in snotes[:3]:
            h = sanitize_text(n.get("heading") or "")
            story.append(Paragraph(f"<b>Module: {h}</b>", h2_style))
            for b in n.get("bullets", [])[:3]:
                story.append(Paragraph(f"- {sanitize_text(b)}", body_style))

        story.append(Spacer(1, 8))

    # -------------------------------------------------------------
    # HEADING 10: VIRAL SHORTS & SOCIAL REPURPOSING BRIEFS
    # -------------------------------------------------------------
    cr = data.get("creator_repurposing", {})
    clips = cr.get("viral_clips", [])
    if clips:
        story.append(Paragraph("10. CREATOR REPURPOSING: VIRAL SHORTS BRIEFS", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        clip_rows = [
            [
                Paragraph("<b>Timestamps</b>", table_header_style),
                Paragraph("<b>Hook / Clip Title</b>", table_header_style),
                Paragraph("<b>Viral Score</b>", table_header_style)
            ]
        ]
        for c in clips[:4]:
            t_range = f"{sanitize_text(c.get('start_time'))} - {sanitize_text(c.get('end_time'))}"
            ctitle = f"<b>{sanitize_text(c.get('title'))}</b><br/><i>\"{sanitize_text(c.get('hook'))}\"</i>"
            vscore = f"<b>{c.get('viral_score', 90)}/100</b>"

            clip_rows.append([
                Paragraph(t_range, table_cell_bold),
                Paragraph(ctitle, table_cell_style),
                Paragraph(vscore, table_cell_style)
            ])

        clip_table = Table(clip_rows, colWidths=[95, 365, 80])
        clip_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), color_primary),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor("#ffffff"), colors.HexColor("#f8fafc")]),
        ]))
        story.append(clip_table)
        story.append(Spacer(1, 10))

    # -------------------------------------------------------------
    # HEADING 11: NOTABLE QUOTES LIBRARY
    # -------------------------------------------------------------
    quotes = data.get("quotes", [])
    if quotes:
        story.append(Paragraph("11. NOTABLE QUOTES DIRECTORY", h1_style))
        story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

        for idx, q in enumerate(quotes, 1):
            q_text = sanitize_text(q.get("quote") or "")
            q_spk = sanitize_text(q.get("speaker") or "Speaker")
            q_ts = sanitize_text(q.get("timestamp") or "")

            q_content = [
                Paragraph(f'"{q_text}"', quote_style),
                Paragraph(f"<b>-- {q_spk}</b> (at {q_ts})", ParagraphStyle('QA', parent=body_muted, leftIndent=25)),
                Spacer(1, 4)
            ]
            story.append(KeepTogether(q_content))

        story.append(Spacer(1, 6))

    # -------------------------------------------------------------
    # HEADING 12: QUALITY SCORECARD & EXECUTIVE VERDICT
    # -------------------------------------------------------------
    exec_rec = data.get("executive_assessment", {})
    qs = data.get("quality_scorecard", {})

    story.append(Paragraph("12. QUALITY SCORECARD & EXECUTIVE VERDICT", h1_style))
    story.append(HRFlowable(width="100%", thickness=1, color=color_accent, spaceBefore=1, spaceAfter=6))

    if qs:
        score_line = f"<b>Density:</b> {qs.get('density_score', 90)}/100 &nbsp;|&nbsp; <b>Clarity:</b> {qs.get('clarity_score', 92)}/100 &nbsp;|&nbsp; <b>Structure:</b> {qs.get('structure_score', 94)}/100 &nbsp;|&nbsp; <b>Engagement:</b> {qs.get('engagement_score', 87)}/100"
        story.append(Paragraph(score_line, body_style))

        if qs.get("strengths"):
            str_list = " - " + "<br/> - ".join([sanitize_text(s) for s in qs.get("strengths", [])])
            story.append(Paragraph(f"<b>Core Content Strengths:</b><br/>{str_list}", body_style))

    if exec_rec:
        best_for = exec_rec.get("best_for", [])
        if best_for:
            best_str = ", ".join([sanitize_text(b) for b in best_for])
            story.append(Paragraph(f"<b>Target Demographic & Fit:</b> {best_str}", body_style))

        verdict = sanitize_text(exec_rec.get("recommendation") or qs.get("verdict") or "")
        if verdict:
            verdict_box = [
                [
                    Paragraph(f"<b>Strategic Verdict:</b> {verdict}", body_style)
                ]
            ]
            vb_table = Table(verdict_box, colWidths=[540])
            vb_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#eff6ff")),
                ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#3b82f6")),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(vb_table)

    # Build the document with running header/footer
    doc.build(story, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return buf
