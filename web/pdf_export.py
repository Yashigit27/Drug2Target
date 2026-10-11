"""PDF export for analysis reports."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from web.report import build_report


def _p(text: str, style) -> Paragraph:
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return Paragraph(safe, style)


def build_report_pdf(run_id: str) -> bytes:
    report = build_report(run_id)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    story: list[Any] = []

    story.append(_p(f"D2T Analysis Report — {run_id}", styles["Title"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(_p(f"Disease: {report.get('disease')} ({report.get('ontology_id')})", styles["Normal"]))
    story.append(_p(f"Known genes collected: {report.get('known_gene_count')}", styles["Normal"]))
    story.append(Spacer(1, 0.15 * inch))

    for sec in report.get("sections", []):
        story.append(_p(sec.get("title", ""), styles["Heading2"]))
        if sec.get("subtitle"):
            story.append(_p(sec["subtitle"], styles["Italic"]))
        if sec.get("body"):
            story.append(_p(sec["body"], styles["Normal"]))
        for t in sec.get("targets", []):
            story.append(Spacer(1, 0.08 * inch))
            story.append(_p(f"#{t.get('rank')} {t.get('gene')} — score {t.get('score')}", styles["Heading3"]))
            story.append(_p(t.get("explain", ""), styles["BodyText"]))
        story.append(Spacer(1, 0.12 * inch))

    if report.get("llm_narrative"):
        story.append(_p("LLM narrative (literature-grounded)", styles["Heading2"]))
        for block in report["llm_narrative"].get("sections", []):
            story.append(_p(f"{block.get('gene_symbol')}: {block.get('narrative')}", styles["BodyText"]))
            story.append(Spacer(1, 0.08 * inch))

    doc.build(story)
    return buf.getvalue()
