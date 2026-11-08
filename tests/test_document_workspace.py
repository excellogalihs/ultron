import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
import shutil
import subprocess

from ultron import create_app
from ultron.blueprints.chat import _system_prompt
from ultron.db import get_db
from ultron.services.document_files import make_docx, read_document


class DocumentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": str(Path(self.temporary.name) / "workspace.db")})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_document_links_open_chat_workspace_and_versions_restore(self):
        created = self.client.post("/api/documents", json={"title": "Report", "content": "# First\n\nOriginal body"}).get_json()["document"]
        edited = self.client.patch(f"/api/documents/{created['id']}", json={"title": "Report", "content": "# First\n\nUpdated body", "format": "markdown"})
        self.assertEqual(edited.status_code, 200)
        redirect = self.client.get(f"/documents?doc={created['id']}")
        self.assertEqual(redirect.status_code, 302)
        self.assertIn(f"/chat?doc={created['id']}", redirect.headers["Location"])
        page = self.client.get(redirect.headers["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"chat-workspace", page.data)
        versions = self.client.get(f"/api/documents/{created['id']}/versions").get_json()["versions"]
        self.assertEqual(len(versions), 1)
        restored = self.client.post(f"/api/documents/{created['id']}/versions/{versions[0]['id']}/restore", json={})
        self.assertEqual(restored.get_json()["document"]["content"], "# First\n\nOriginal body")
        self.assertEqual(self.client.get(f"/api/documents/{created['id']}/versions").get_json()["versions"][0]["character_count"], len("# First\n\nUpdated body"))

    def test_email_prompt_requires_grounded_body_only_reply(self):
        with self.app.test_request_context("/"):
            prompt = _system_prompt("From: Alex <alex@example.test>\nSubject: Meeting\n\nCould we meet next week?")
        self.assertIn("Never invent facts, commitments, dates, attachments, or promises", prompt)
        self.assertIn("Return only the reply body", prompt)

    def test_docx_export_is_a_readable_package_with_a4_page_layout(self):
        source = "# Report\n\n## Findings\n\nA **bold** point.\n\n- First\n- Second\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
        payload = make_docx(source)
        with ZipFile(BytesIO(payload)) as package:
            names = set(package.namelist())
            self.assertIn("word/document.xml", names)
            document_xml = package.read("word/document.xml").decode("utf-8")
            self.assertIn("Report", document_xml)
            self.assertIn("<w:pgSz", document_xml)
            self.assertTrue("11906" in document_xml or "11909" in document_xml)
        imported = read_document("roundtrip.docx", payload)
        self.assertIn("## Findings", imported)
        self.assertIn("**bold**", imported)
        self.assertIn("| 1 | 2 |", imported)
        libreoffice = shutil.which("libreoffice") or shutil.which("soffice")
        if libreoffice:
            with tempfile.TemporaryDirectory() as output_dir:
                docx_path = Path(output_dir) / "report.docx"
                docx_path.write_bytes(payload)
                converted = subprocess.run([libreoffice, "--headless", "--convert-to", "pdf", "--outdir", output_dir, str(docx_path)], capture_output=True, timeout=30, check=False)
                if converted.returncode and not converted.stdout and not converted.stderr:
                    self.skipTest("LibreOffice conversion is blocked in this execution context.")
                self.assertEqual(converted.returncode, 0, converted.stderr.decode("utf-8", "replace"))
                self.assertTrue((Path(output_dir) / "report.pdf").exists())


if __name__ == "__main__":
    unittest.main()
