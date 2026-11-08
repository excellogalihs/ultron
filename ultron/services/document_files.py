"""Small, local helpers for importing and exporting text-oriented documents."""

from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl",
    ".xml", ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx",
    ".jsx", ".mdx", ".vue", ".svelte", ".php", ".py", ".pyw", ".sql", ".sh", ".bash", ".zsh", ".bat", ".cmd",
    ".ps1", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".hpp",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".tex",
    ".ipynb", ".properties", ".gradle", ".mk", ".rb", ".swift", ".dart", ".pl", ".r",
}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".docx"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def read_document(filename, payload):
    """Decode an allowed text file or extract paragraphs from a DOCX package."""
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type. Supported extensions: {allowed}.")
    if extension != ".docx":
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("This file is not valid UTF-8 text.") from error

    try:
        with ZipFile(BytesIO(payload)) as archive:
            main_part = archive.getinfo("word/document.xml")
            if main_part.file_size > 8_000_000:
                raise ValueError("The Word document contains too much text to import.")
        from docx import Document
        from docx.oxml.text.paragraph import CT_P
        from docx.oxml.table import CT_Tbl
        from docx.text.paragraph import Paragraph
        from docx.table import Table
        source = Document(BytesIO(payload))
        content = []
        for child in source.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, source)
                run_parts = []
                for run in paragraph.runs:
                    value = run.text
                    if not value:
                        continue
                    if run.bold:
                        value = f"**{value}**"
                    if run.italic:
                        value = f"*{value}*"
                    if run.underline:
                        value = f"++{value}++"
                    run_parts.append(value)
                text = "".join(run_parts)
                style = paragraph.style.name if paragraph.style else ""
                if style == "Title":
                    text = f"# {text}"
                elif style == "Subtitle":
                    text = f"*{text}*"
                elif style.startswith("Heading "):
                    try:
                        level = min(max(int(style.split()[-1]), 1), 6)
                    except ValueError:
                        level = 2
                    text = f"{'#' * level} {text}"
                elif style.startswith("List Bullet"):
                    text = f"- {text}"
                elif style.startswith("List Number"):
                    text = f"1. {text}"
                content.append(text)
            elif isinstance(child, CT_Tbl):
                table = Table(child, source)
                rows = [[cell.text.replace("\n", " / ") for cell in row.cells] for row in table.rows]
                if rows:
                    content.append("| " + " | ".join(rows[0]) + " |")
                    content.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                    content.extend("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n\n".join(content)
    except ImportError:
        pass
    except Exception as error:
        raise ValueError("This Word document could not be read. Some advanced Word features may not be supported.") from error

    try:
        with ZipFile(BytesIO(payload)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 8_000_000:
                raise ValueError("The Word document contains too much text to import.")
            root = ET.fromstring(archive.read(info))
    except (BadZipFile, KeyError, ET.ParseError, RuntimeError, EOFError) as error:
        raise ValueError("This is not a readable .docx document.") from error

    paragraphs = []
    for paragraph in root.iter(f"{{{_W}}}p"):
        pieces = []
        for node in paragraph.iter():
            if node.tag == f"{{{_W}}}t":
                pieces.append(node.text or "")
            elif node.tag == f"{{{_W}}}tab":
                pieces.append("\t")
            elif node.tag == f"{{{_W}}}br":
                pieces.append("\n")
        paragraphs.append("".join(pieces))
    return "\n".join(paragraphs)


def make_docx(content):
    """Create a real, A4 Word document with common Markdown structure and styles."""
    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches, Pt
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from re import finditer, fullmatch

        document = Document()
        section = document.sections[0]
        section.page_width, section.page_height = Inches(8.27), Inches(11.69)
        section.top_margin = section.bottom_margin = Inches(0.85)
        section.left_margin = section.right_margin = Inches(0.9)
        normal = document.styles["Normal"]
        normal.font.name = "Aptos"
        normal.font.size = Pt(11)
        normal.paragraph_format.space_after = Pt(8)
        normal.paragraph_format.line_spacing = 1.15
        for name, size in (("Title", 22), ("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
            style = document.styles[name]
            style.font.name = "Aptos Display"
            style.font.size = Pt(size)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.add_run("ultron · local document").font.size = Pt(8)
        footer.add_run("  ·  ").font.size = Pt(8)
        page_field = OxmlElement("w:fldSimple")
        page_field.set(qn("w:instr"), "PAGE")
        page_run = OxmlElement("w:r")
        page_text = OxmlElement("w:t")
        page_text.text = "1"
        page_run.append(page_text)
        page_field.append(page_run)
        footer._p.append(page_field)

        def add_inline(paragraph, value):
            pattern = r"(\*\*.+?\*\*|__.+?__|~~.+?~~|\+\+.+?\+\+|(?<!\*)\*[^*\n]+\*|(?<!_)_[^_\n]+_)"
            position = 0
            for match in finditer(pattern, value):
                if match.start() > position:
                    paragraph.add_run(value[position:match.start()])
                token = match.group(0)
                run = paragraph.add_run(token[2:-2] if token.startswith(("**", "__", "~~", "++")) else token[1:-1])
                if token.startswith(("**", "__")):
                    run.bold = True
                elif token.startswith("~~"):
                    run.font.strike = True
                elif token.startswith("++"):
                    run.underline = True
                else:
                    run.italic = True
                position = match.end()
            if position < len(value):
                paragraph.add_run(value[position:])

        lines = (content or "").splitlines()
        index = 0
        current_alignment = None
        while index < len(lines):
            line = lines[index].strip()
            if not line:
                index += 1
                continue
            alignment_marker = fullmatch(r":::(left|center|right)", line)
            if alignment_marker:
                current_alignment = alignment_marker.group(1)
                index += 1
                continue
            if line == ":::":
                current_alignment = None
                index += 1
                continue
            if line in ("---", "<pagebreak>", "\\pagebreak"):
                document.add_page_break()
                index += 1
                continue
            if line.startswith("|") and index + 1 < len(lines) and fullmatch(r"\|?[\s:|\-]+\|?", lines[index + 1].strip()):
                table_lines = []
                while index < len(lines) and lines[index].strip().startswith("|"):
                    row = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                    if not all(set(cell) <= set("-: ") for cell in row):
                        table_lines.append(row)
                    index += 1
                if table_lines:
                    columns = max(map(len, table_lines))
                    table = document.add_table(rows=len(table_lines), cols=columns)
                    table.style = "Table Grid"
                    for r, cells in enumerate(table_lines):
                        for c in range(columns):
                            cell = table.cell(r, c)
                            cell.text = ""
                            add_inline(cell.paragraphs[0], cells[c] if c < len(cells) else "")
                            if r == 0:
                                for run in cell.paragraphs[0].runs:
                                    run.bold = True
                continue
            heading = fullmatch(r"(#{1,6})\s+(.+)", line)
            bullet = fullmatch(r"[-*+]\s+(.+)", line)
            numbered = fullmatch(r"\d+[.)]\s+(.+)", line)
            if heading:
                level, text = len(heading.group(1)), heading.group(2)
                paragraph = document.add_paragraph(style="Title" if level == 1 and len(document.paragraphs) == 0 else f"Heading {min(level, 3)}")
                add_inline(paragraph, text)
            elif bullet or numbered:
                paragraph = document.add_paragraph(style="List Bullet" if bullet else "List Number")
                add_inline(paragraph, (bullet or numbered).group(1))
            else:
                paragraph = document.add_paragraph()
                if line.startswith("> "):
                    paragraph.paragraph_format.left_indent = Inches(0.35)
                    paragraph.paragraph_format.space_before = Pt(4)
                    line = line[2:]
                add_inline(paragraph, line)
            if current_alignment:
                paragraph.alignment = {
                    "left": WD_ALIGN_PARAGRAPH.LEFT,
                    "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                }[current_alignment]
            index += 1

        output = BytesIO()
        document.save(output)
        return output.getvalue()
    except ImportError:
        # Keep legacy installations functional; the declared python-docx dependency
        # enables full styles and structure in normal installs.
        pass

    ET.register_namespace("w", _W)
    document = ET.Element(f"{{{_W}}}document")
    body = ET.SubElement(document, f"{{{_W}}}body")
    lines = content.split("\n") or [""]
    for line in lines:
        paragraph = ET.SubElement(body, f"{{{_W}}}p")
        run = ET.SubElement(paragraph, f"{{{_W}}}r")
        text = ET.SubElement(run, f"{{{_W}}}t")
        text.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text.text = line
    section = ET.SubElement(body, f"{{{_W}}}sectPr")
    ET.SubElement(section, f"{{{_W}}}pgSz", {f"{{{_W}}}w": "11906", f"{{{_W}}}h": "16838"})
    ET.SubElement(section, f"{{{_W}}}pgMar", {f"{{{_W}}}top": "1224", f"{{{_W}}}bottom": "1224", f"{{{_W}}}left": "1296", f"{{{_W}}}right": "1296", f"{{{_W}}}header": "708", f"{{{_W}}}footer": "708", f"{{{_W}}}gutter": "0"})

    content_types = ET.Element(f"{{{_CT}}}Types")
    ET.SubElement(content_types, f"{{{_CT}}}Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(content_types, f"{{{_CT}}}Default", {"Extension": "xml", "ContentType": "application/xml"})
    ET.SubElement(content_types, f"{{{_CT}}}Override", {"PartName": "/word/document.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"})

    relationships = ET.Element(f"{{{_R}}}Relationships")
    ET.SubElement(relationships, f"{{{_R}}}Relationship", {
        "Id": "rId1",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": "word/document.xml",
    })

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ET.tostring(content_types, encoding="utf-8", xml_declaration=True))
        archive.writestr("_rels/.rels", ET.tostring(relationships, encoding="utf-8", xml_declaration=True))
        archive.writestr("word/document.xml", ET.tostring(document, encoding="utf-8", xml_declaration=True))
    return output.getvalue()
