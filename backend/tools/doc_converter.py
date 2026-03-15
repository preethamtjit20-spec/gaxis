"""Markdown to DOCX converter with proper formatting.

Converts research markdown into a well-formatted .docx file with:
- Heading hierarchy (H1, H2, H3)
- Tables with bold headers and borders
- Bullet lists
- Checklists (☐ items)
- Callout blocks (TIP/WARNING/NOTE) with colored bold prefix
- Proper paragraph spacing
- Title as H1
- Sources as a numbered list (not headings)
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


def markdown_to_docx(content: str, title: str = "Research Document") -> str:
    """Convert markdown content to a .docx file. Returns the file path."""
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    # Set narrow margins
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    lines = content.split("\n")
    i = 0
    first_heading_done = False
    in_sources_section = False

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # Detect sources section — everything after "Sources" heading is a list
        if in_sources_section:
            # Source lines: numbered, markdown links, or plain URLs
            clean = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 — \2", line)
            clean = re.sub(r"^\d+\.\s*", "", clean)  # Strip leading numbers
            if clean:
                doc.add_paragraph(clean, style="List Number")
            i += 1
            continue

        # Check if entering sources section
        if re.match(r"^(#+\s*)?SOURCES\s*$", line, re.IGNORECASE) or line.strip().lower() == "sources":
            doc.add_heading("Sources", level=2)
            in_sources_section = True
            i += 1
            continue

        # === HEADINGS ===

        # Markdown H3
        if line.startswith("### "):
            doc.add_heading(line[4:], level=3)
            i += 1

        # Markdown H2
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
            first_heading_done = True
            i += 1

        # Markdown H1
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
            first_heading_done = True
            i += 1

        # First non-empty line → Title (H1)
        elif not first_heading_done and not line.startswith(("- ", "• ", "* ", "|", "☐", "[")):
            doc.add_heading(line, level=1)
            first_heading_done = True
            i += 1

        # "TABLE OF CONTENTS" — skip the heading and its items (Google Docs auto-generates)
        elif re.match(r"^(TABLE OF CONTENTS|CONTENTS)\s*$", line, re.IGNORECASE):
            i += 1
            # Skip numbered items that follow
            while i < len(lines) and re.match(r"^\d+\.", lines[i].strip()):
                i += 1
            continue

        # Numbered sections (e.g., "1. SECTION NAME" or "1. Section Name")
        elif re.match(r"^\d+\.\s+[A-Z]", line) and len(line) < 80 and "|" not in line:
            section = re.sub(r"^\d+\.\s+", "", line)
            doc.add_heading(section.title(), level=2)
            i += 1

        # ALL CAPS heading (but not table rows, not short words)
        elif line.isupper() and 5 < len(line) < 80 and "|" not in line:
            doc.add_heading(line.title(), level=2)
            i += 1

        # === TABLES ===
        elif "|" in line and line.count("|") >= 2:
            rows = []
            while i < len(lines) and "|" in lines[i].strip() and lines[i].strip().count("|") >= 2:
                cells = [c.strip() for c in lines[i].strip().split("|") if c.strip()]
                if cells:
                    rows.append(cells)
                i += 1

            if rows:
                num_cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=num_cols)
                table.style = "Light Grid Accent 1"

                for r_idx, row in enumerate(rows):
                    for c_idx, cell_text in enumerate(row):
                        if c_idx < num_cols:
                            cell = table.cell(r_idx, c_idx)
                            cell.text = cell_text
                            # Bold header row
                            if r_idx == 0:
                                for paragraph in cell.paragraphs:
                                    for run in paragraph.runs:
                                        run.bold = True
                            # Set cell font size
                            for paragraph in cell.paragraphs:
                                for run in paragraph.runs:
                                    run.font.size = Pt(10)

                doc.add_paragraph()  # Spacing after table

        # === CHECKLISTS ===
        elif line.startswith("☐ ") or line.startswith("[ ] "):
            while i < len(lines) and (lines[i].strip().startswith("☐ ") or lines[i].strip().startswith("[ ] ")):
                item = lines[i].strip().replace("☐ ", "").replace("[ ] ", "")
                p = doc.add_paragraph()
                # No bullet style — just the checkbox character
                run = p.add_run("☐  " + item)
                run.font.size = Pt(11)
                p.paragraph_format.left_indent = Inches(0.3)
                i += 1

        # === CALLOUTS ===
        elif line.startswith(("TIP:", "WARNING:", "NOTE:")):
            prefix = line.split(":")[0]
            text = line[len(prefix) + 1:].strip()
            p = doc.add_paragraph()
            # Bold colored prefix
            run_prefix = p.add_run(prefix + ": ")
            run_prefix.bold = True
            if prefix == "WARNING":
                run_prefix.font.color.rgb = RGBColor(0xE0, 0x33, 0x33)
            elif prefix == "NOTE":
                run_prefix.font.color.rgb = RGBColor(0x33, 0x66, 0xCC)
            else:
                run_prefix.font.color.rgb = RGBColor(0x1A, 0x99, 0x4D)
            p.add_run(text)
            i += 1

        # === BULLETS ===
        elif line.startswith(("- ", "• ", "* ")):
            while i < len(lines) and lines[i].strip() and lines[i].strip()[:2] in ("- ", "• ", "* "):
                item = lines[i].strip()[2:]
                item = re.sub(r"\*\*(.+?)\*\*", r"\1", item)
                doc.add_paragraph(item, style="List Bullet")
                i += 1

        # === SUBHEADING (short line ending with colon) ===
        elif len(line) < 60 and line.endswith(":") and not line.startswith(("TIP", "WAR", "NOT", "http")):
            doc.add_heading(line.rstrip(":"), level=3)
            i += 1

        # === REGULAR PARAGRAPH ===
        else:
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i].strip()):
                para_lines.append(lines[i].strip())
                i += 1

            text = " ".join(para_lines)
            # Strip markdown formatting
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
            text = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", text)
            doc.add_paragraph(text)

    # Save to temp file
    output_dir = Path("research-docs")
    output_dir.mkdir(exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}_{_slugify(title)}.docx"
    filepath = output_dir / filename
    doc.save(str(filepath))

    return str(filepath)


def _is_block_start(line: str) -> bool:
    """Check if a line starts a new block (heading, table, list, etc.)."""
    if not line:
        return False
    return any([
        line.startswith(("#", "- ", "• ", "* ", "☐", "[ ]", "TIP:", "WARNING:", "NOTE:")),
        "|" in line and line.count("|") >= 2,
        line.isupper() and len(line) > 5 and "|" not in line,
        re.match(r"^\d+\.\s+[A-Z]", line) and len(line) < 80,
        re.match(r"^(TABLE OF CONTENTS|CONTENTS|SOURCES)\s*$", line, re.IGNORECASE),
    ])


def _slugify(text: str) -> str:
    """Convert text to a safe filename."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "_", text)
    return text[:50]
