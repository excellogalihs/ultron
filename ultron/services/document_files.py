"""Small, local helpers for importing and exporting text-oriented documents."""

from io import BytesIO
import subprocess
import shutil
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


def read_knowledge_file(filename, payload):
    """Extract plain text from a supported knowledge file without model use."""
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(payload), strict=False)
            if len(reader.pages) > 500:
                raise ValueError("PDF imports are limited to 500 pages.")
            return "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except ImportError:
            extractor = shutil.which("pdftotext")
            if not extractor:
                raise ValueError("PDF extraction needs pypdf installed or pdftotext available.")
            try:
                result = subprocess.run(
                    [extractor, "-f", "1", "-l", "500", "-", "-"], input=payload, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, timeout=20, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError("PDF text extraction failed or timed out.") from error
            if result.returncode:
                raise ValueError("This PDF could not be read.")
            return result.stdout.decode("utf-8", "replace")
        except Exception as error:
            raise ValueError("This PDF could not be read or contains no extractable text.") from error
    return read_document(filename, payload)


def make_docx(content):
    """Create a minimal, valid DOCX containing the edited paragraph text."""
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
    ET.SubElement(section, f"{{{_W}}}pgSz", {f"{{{_W}}}w": "12240", f"{{{_W}}}h": "15840"})

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
