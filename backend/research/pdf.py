from __future__ import annotations

from io import BytesIO
import re


def render_markdown_pdf(title: str, markdown: str) -> bytes:
    """Render a conservative, Unicode-capable report PDF without filesystem state."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    try:
        pdfmetrics.getFont("STSong-Light")
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="知渊研究工作台",
    )
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "ResearchBody",
        parent=base["BodyText"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=17,
        textColor=HexColor("#273444"),
        spaceAfter=7,
    )
    heading = ParagraphStyle(
        "ResearchHeading",
        parent=body,
        fontSize=16,
        leading=22,
        textColor=HexColor("#12233F"),
        spaceBefore=12,
        spaceAfter=8,
    )
    cover = ParagraphStyle(
        "ResearchCover",
        parent=heading,
        fontSize=24,
        leading=34,
        alignment=TA_CENTER,
        spaceAfter=16,
    )
    story = [Spacer(1, 45 * mm), Paragraph(_rich_text(title), cover), PageBreak()]
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 3 * mm))
        elif line.startswith("#"):
            text = line.lstrip("#").strip()
            story.append(Paragraph(_rich_text(text), heading))
        elif line.startswith("- "):
            story.append(Paragraph("· " + _rich_text(line[2:]), body))
        else:
            story.append(Paragraph(_rich_text(line), body))
    document.build(story)
    return buffer.getvalue()


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_LATIN_RUN = re.compile(r"[\x20-\x7E]+")


def _rich_text(value: str) -> str:
    escaped = _escape(value)
    return _LATIN_RUN.sub(
        lambda match: f'<font name="Helvetica">{match.group(0)}</font>', escaped
    )
