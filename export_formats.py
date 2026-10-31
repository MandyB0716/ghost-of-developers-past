"""Export the selected response and its reference list, without a source appendix."""

import html
import re
from io import BytesIO
from pathlib import Path

from review_page import source_snapshot
from revival_analysis import reference_fragments, resolve_reference


CITATION = re.compile(r"\[F\d+[^\]\n]*\]")


def references_for(text, messages):
    sources, _ = source_snapshot(messages)
    references, seen = [], set()
    for marker in CITATION.findall(text):
        for fragment in reference_fragments(marker):
            found, issue = resolve_reference(fragment, sources)
            if issue:
                label = f"{fragment}: source location unavailable"
                if label not in seen:
                    seen.add(label)
                    references.append(label)
                continue
            for reference in found:
                label = reference["label"] + " - " + reference["path"]
                if reference["scope"] == "file":
                    label += " (whole file; no line range cited)"
                else:
                    first, last = reference["first_line"], reference["last_line"]
                    label += f", line {first}" if first == last else f", lines {first}-{last}"
                if label not in seen:
                    seen.add(label)
                    references.append(label)
    return references


def filename(project, version, extension):
    slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-")[:70] or "project"
    return f"{slug}-restart-plan-v{version + 1}.{extension}"


def markdown_export(text, messages, project, version):
    # Keep the model's response unchanged; never append evidence text or messages.
    references = references_for(text, messages)
    reference_list = "\n".join("- " + label for label in references) or "No file-and-line references were cited."
    return (f"# {project.replace(chr(10), ' ').replace(chr(13), ' ')} - Restart plan\n\n"
            f"Version {version + 1}\n\n{text.rstrip()}\n\n"
            f"## File-and-line references\n\n{reference_list}\n").encode("utf-8")


def pdf_export(text, messages, project, version):
    # Import here so Markdown export remains independent of PDF rendering.
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    # ReportLab ships these openly licensed fonts on Windows and Linux alike.
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if "RevivalSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("RevivalSans", str(font_dir / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("RevivalSans-Bold", str(font_dir / "VeraBd.ttf")))
        pdfmetrics.registerFontFamily("RevivalSans", normal="RevivalSans", bold="RevivalSans-Bold")
    body = ParagraphStyle("Body", fontName="RevivalSans", fontSize=10, leading=16,
                          textColor=colors.HexColor("#172033"), spaceAfter=9,
                          splitLongWords=True)
    heading = ParagraphStyle("Section", parent=body, fontName="RevivalSans-Bold",
                             fontSize=12, leading=17, spaceBefore=14, spaceAfter=8,
                             keepWithNext=True)
    title = ParagraphStyle("Title", parent=heading, fontSize=21, leading=27, spaceBefore=0)
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=12,
                           spaceAfter=3, textColor=colors.HexColor("#48556a"))
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=15, firstLineIndent=-11)

    def safe_inline(value):
        # Never interpret model-provided HTML, images or external resources.
        value = html.escape(value)
        value = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", value)
        return re.sub(r"`([^`\n]+)`", r"<font color='#304b70'>\1</font>", value)

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=letter, rightMargin=48, leftMargin=48,
                                 topMargin=48, bottomMargin=48,
                                 title=f"{project} - Restart plan", author="Project Revival")
    story = [Paragraph(safe_inline(project), title),
             Paragraph(f"RESTART PLAN  /  VERSION {version + 1}", small), Spacer(1, 14)]
    paragraph = []

    def flush():
        if paragraph:
            story.append(Paragraph(safe_inline(" ".join(paragraph)), body))
            paragraph.clear()

    code_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            flush()
            code_fence = not code_fence
            continue
        match_heading = re.match(r"^#{1,6}\s+(.+)", line)
        match_bullet = re.match(r"^\s*([-*]|\d+\.)\s+(.+)", line)
        if code_fence:
            flush()
            story.append(Paragraph(html.escape(line).replace(" ", "&#160;") or "&#160;", small))
        elif match_heading:
            flush()
            story.append(Paragraph(safe_inline(match_heading[1]), heading))
        elif match_bullet:
            flush()
            prefix = "-" if match_bullet[1] in ("-", "*") else match_bullet[1]
            story.append(Paragraph(safe_inline(prefix + " " + match_bullet[2]), bullet))
        elif line.strip():
            paragraph.append(line.strip())
        else:
            flush()
    flush()
    story.append(Paragraph("File-and-line references", heading))
    for label in references_for(text, messages) or ["No file-and-line references were cited."]:
        story.append(Paragraph(safe_inline(label), small))

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d4dbe5"))
        canvas.line(48, 35, letter[0] - 48, 35)
        canvas.setFont("RevivalSans", 8)
        canvas.setFillColor(colors.HexColor("#48556a"))
        canvas.drawString(48, 22, "Project Revival | Restart plan")
        canvas.drawRightString(letter[0] - 48, 22, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return stream.getvalue()
