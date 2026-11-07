import json
import io
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ultron import create_app
from ultron.blueprints import chat as chat_blueprint
from ultron.blueprints import documents as documents_blueprint
from ultron.services import ollama
from ultron.services.document_files import make_docx, read_knowledge_file
from ultron.services.workspace_search import retrieve_context, search_workspace
from ultron.services.workspace_tools import (
    ToolError,
    execute_tool,
    parse_tool_call,
    relevant_memories,
)


class WorkspaceToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "workspace.db"
        connection = sqlite3.connect(self.database)
        schema = Path(__file__).resolve().parents[1] / "ultron" / "schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    def test_workspace_tools_validate_and_persist_local_actions(self):
        document = execute_tool(
            str(self.database),
            "create_document",
            {"title": "Planning", "content": "  first line\nsecond line  "},
        )["document"]
        self.assertEqual(document["content"], "  first line\nsecond line  ")
        self.assertEqual(
            execute_tool(str(self.database), "read_document", {"id": document["id"]})[
                "document"
            ]["title"],
            "Planning",
        )
        proposal = execute_tool(
            str(self.database),
            "edit_document",
            {"id": document["id"], "content": "Revised\ncontent"},
        )
        self.assertTrue(proposal["requires_user_approval"])
        self.assertEqual(proposal["proposal"]["content"], "Revised\ncontent")
        self.assertEqual(
            execute_tool(str(self.database), "read_document", {"id": document["id"]})[
                "document"
            ]["content"],
            "  first line\nsecond line  ",
        )
        self.assertEqual(
            execute_tool(str(self.database), "search_workspace", {"query": "first line"})[
                "documents"
            ][0]["id"],
            document["id"],
        )

        task = execute_tool(
            str(self.database),
            "create_task",
            {"title": "Review plan", "priority": "high", "due_date": "2026-11-12"},
        )["task"]
        self.assertEqual(task["status"], "pending")
        self.assertEqual(
            execute_tool(str(self.database), "read_tasks", {"status": "pending"})[
                "tasks"
            ][0]["title"],
            "Review plan",
        )
        event = execute_tool(
            str(self.database),
            "create_calendar_event",
            {"title": "Review", "date": "2026-11-12", "start_time": "10:30"},
        )["event"]
        events = execute_tool(
            str(self.database),
            "read_calendar_events",
            {"date_from": "2026-11-12", "date_to": "2026-11-12"},
        )["events"]
        self.assertEqual(events[0]["id"], event["id"])

        saved = execute_tool(
            str(self.database),
            "save_memory",
            {"content": "I prefer concise planning notes", "category": "preference"},
        )
        self.assertTrue(saved["saved"])
        self.assertEqual(
            execute_tool(str(self.database), "read_memory", {"query": "planning notes"})[
                "memories"
            ][0]["content"],
            "I prefer concise planning notes",
        )

    def test_workspace_file_search_is_bounded_and_skips_hidden_files(self):
        (self.root / "notes.md").write_text("Find the local roadmap", encoding="utf-8")
        (self.root / ".hidden.md").write_text("Find the local roadmap", encoding="utf-8")
        result = execute_tool(
            str(self.database),
            "search_workspace",
            {"query": "local roadmap"},
            workspace_root=str(self.root),
        )
        self.assertEqual([item["path"] for item in result["files"]], ["notes.md"])

    def test_tool_envelope_and_arguments_are_allow_listed(self):
        call = parse_tool_call(
            '{"ultron_tool":"create_task","arguments":{"title":"safe"}}'
        )
        self.assertEqual(call[0], "create_task")
        self.assertEqual(
            parse_tool_call(
                '{"ultrontool":"searchworkspace"} '
                '{"query":"gaming laptop specs"} '
                '{"ultrontool":"searchworkspace"} '
                '{"query":"gaming laptop price"}'
            ),
            (
                "search_workspace",
                {"query": "gaming laptop specs; gaming laptop price"},
            ),
        )
        self.assertEqual(
            parse_tool_call('{"ultron_tool":"search_web"}', fallback_query="local weather"),
            ("web_search", {"query": "local weather"}),
        )
        self.assertIsNone(
            parse_tool_call('{"ultron_tool":"run_shell","arguments":{"command":"id"}}')
        )
        with self.assertRaises(ToolError):
            execute_tool(
                str(self.database),
                "create_task",
                {"title": "unsafe", "command": "id"},
            )
        with self.assertRaises(ToolError):
            execute_tool(
                str(self.database),
                "search_workspace",
                {"query": "notes", "path": "/etc"},
            )

    def test_memory_retrieval_returns_only_relevant_notes(self):
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute(
            "INSERT INTO memories (content, category, active, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            ("Python answers should be concise", "preference", "2026-11-01", "2026-11-01"),
        )
        connection.execute(
            "INSERT INTO memories (content, category, active, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            ("Favorite music is ambient", "fact", "2026-11-02", "2026-11-02"),
        )
        connection.commit()
        memories = relevant_memories(connection, "Python concise", limit=5)
        connection.close()
        self.assertEqual(len(memories), 1)
        self.assertIn("Python", memories[0]["content"])


class GlobalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = create_app({"TESTING": True, "DATABASE": str(Path(self.temporary.name) / "global.db")})
        self.client = self.app.test_client()

    def test_universal_fts_search_spans_workspace_types(self):
        document = self.client.post("/api/documents", json={"title": "Python handbook", "content": "Python threading and networking reference"}).get_json()["document"]
        self.client.post("/api/conversations", json={"first_message": "We discussed Python networking in the project."})
        self.client.post("/api/tasks", json={"title": "Review Python networking", "due_date": date.today().isoformat()})
        self.client.post("/api/events", json={"title": "Python review", "date": date.today().isoformat(), "description": "Discuss Python networking"})
        self.client.post("/api/memories", json={"content": "Python networking is part of the systems course", "category": "fact"})
        imported = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(b"Python networking textbook excerpt"), "course.txt")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 201)
        project = self.client.post("/api/projects", json={"name": "Python lab", "description": "Networking exercises"}).get_json()["project"]
        self.client.post(f"/api/projects/{project['id']}/links", json={"type": "document", "id": document["id"]})
        result = self.client.get("/api/search?q=Python").get_json()
        self.assertTrue(result["fts"])
        self.assertTrue({"document", "conversation", "task", "event", "memory", "knowledge", "project"}.issubset({item["type"] for item in result["results"]}))
        self.assertTrue(all(item["href"].startswith("/") and item["snippet"] for item in result["results"]))
        filtered = self.client.get("/api/search?q=Python&type=knowledge").get_json()["results"]
        self.assertTrue(filtered)
        self.assertEqual({item["type"] for item in filtered}, {"knowledge"})

    def test_first_boot_indexes_existing_workspace_content(self):
        database = Path(self.temporary.name) / "existing.db"
        connection = sqlite3.connect(database)
        schema = Path(__file__).resolve().parents[1] / "ultron" / "schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO documents(title,content,created_at,updated_at) VALUES(?,?,?,?)", ("Legacy guide", "Imported Python notes", "2026-01-01", "2026-01-01"))
        connection.commit(); connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(database)})
        with app.app_context():
            from ultron.db import get_db
            result = search_workspace(get_db(), "Python", ["documents"])
        self.assertEqual(result["results"][0]["title"], "Legacy guide")

    def test_search_index_upgrade_rebuilds_existing_fts_rows(self):
        document = self.client.post("/api/documents", json={"title": "Upgrade notes", "content": "FTS upgradeable networking index"}).get_json()["document"]
        with self.app.app_context():
            from ultron.db import get_db
            get_db().execute("UPDATE settings SET value='2' WHERE key='workspace_fts_version'")
            get_db().commit()
        upgraded = create_app({"TESTING": True, "DATABASE": str(Path(self.temporary.name) / "global.db")})
        with upgraded.app_context():
            from ultron.db import get_db
            db = get_db()
            result = search_workspace(db, "networking", ["documents"])
            rows = db.execute("SELECT COUNT(*) FROM workspace_fts WHERE source='document' AND item_id=?", (document["id"],)).fetchone()[0]
        self.assertTrue(result["results"])
        self.assertEqual(rows, 1)

    def test_search_falls_back_to_sqlite_like_without_fts5(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        schema = Path(__file__).resolve().parents[1] / "ultron" / "schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.execute("INSERT INTO documents(title,content,created_at,updated_at) VALUES(?,?,?,?)", ("Field notes", "Python networking on a small router", "2026-01-01", "2026-01-01"))
        results = search_workspace(connection, "Python router", ["documents"])
        self.assertFalse(results["fts"])
        self.assertEqual(results["results"][0]["title"], "Field notes")
        connection.close()

    def test_knowledge_text_docx_duplicate_and_preview(self):
        collection = self.client.post("/api/knowledge/collections", json={"name": "Networking"}).get_json()["collection"]
        txt = self.client.post("/api/knowledge/import", data={"collection_id": str(collection["id"]), "file": (io.BytesIO(b"A concise networking guide"), "guide.txt")}, content_type="multipart/form-data")
        self.assertEqual(txt.status_code, 201)
        file_id = txt.get_json()["file"]["id"]
        self.assertIn("networking", self.client.get(f"/api/knowledge/{file_id}").get_json()["file"]["content"])
        self.assertEqual(self.client.get(f"/api/knowledge/{file_id}").get_json()["file"]["collection_id"], collection["id"])
        duplicate = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(b"A concise networking guide"), "copy.txt")}, content_type="multipart/form-data")
        self.assertEqual(duplicate.status_code, 409)
        docx = make_docx("DOCX networking notes")
        imported = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(docx), "notes.docx")}, content_type="multipart/form-data")
        self.assertEqual(imported.status_code, 201)
        self.assertIn("networking", self.client.get(f"/api/knowledge/{imported.get_json()['file']['id']}").get_json()["file"]["content"])
        self.assertIn("DOCX networking", read_knowledge_file("sample.docx", docx))

    def test_chat_receives_relevant_knowledge_with_a_source_link(self):
        imported = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(b"TCP handshakes synchronize the client and server before data transfer."), "networking-textbook.txt")}, content_type="multipart/form-data")
        file_id = imported.get_json()["file"]["id"]
        conversation = self.client.post("/api/conversations", json={"first_message": "Summarize my networking textbook about TCP handshakes"}).get_json()
        self.assertEqual(conversation["model"], "gemma3:1b")
        captured = []
        def fake_stream_chat(**kwargs):
            captured.extend(kwargs["messages"])
            yield "TCP handshakes synchronize both sides before data is sent."
        with patch("ultron.blueprints.chat.ollama.stream_chat", fake_stream_chat):
            response = self.client.post(f"/api/conversations/{conversation['id']}/stream", json={}, buffered=True)
        self.assertEqual(response.status_code, 200)
        user_prompt = next(message["content"] for message in captured if message["role"] == "user")
        self.assertIn("TCP handshakes synchronize", user_prompt)
        self.assertIn(f"/knowledge?file={file_id}", user_prompt)

    def test_pdf_text_extraction_when_a_lightweight_extractor_exists(self):
        import shutil
        if not shutil.which("pdftotext"):
            self.skipTest("pypdf or pdftotext must be installed for PDF extraction")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length 58 >>\nstream\nBT /F1 12 Tf 20 80 Td (PDF networking reference) Tj ET\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, 1):
            offsets.append(len(pdf)); pdf.extend(f"{index} 0 obj\n".encode()); pdf.extend(obj); pdf.extend(b"\nendobj\n")
        xref = len(pdf); pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]: pdf.extend(f"{offset:010d} 00000 n \n".encode())
        pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
        text = read_knowledge_file("reference.pdf", bytes(pdf))
        self.assertIn("networking", text.lower())

    def test_project_lifecycle_and_bounded_context_retrieval(self):
        created = self.client.post("/api/projects", json={"name": "Home network", "description": "Router setup", "notes": "Configure the lab network"})
        self.assertEqual(created.status_code, 201)
        project = created.get_json()["project"]
        task = self.client.post("/api/tasks", json={"title": "Update router", "project_id": project["id"]}).get_json()["task"]
        self.assertEqual(task["project_id"], project["id"])
        doc = self.client.post("/api/documents", json={"title": "Router notes", "content": "Configure the home network router safely."}).get_json()["document"]
        self.client.post(f"/api/projects/{project['id']}/links", json={"type": "document", "id": doc["id"]})
        conversation = self.client.post("/api/conversations", json={"first_message": "Home network router setup"}).get_json()
        knowledge = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(b"Home network configuration guide"), "network-guide.txt")}, content_type="multipart/form-data").get_json()["file"]
        self.client.post(f"/api/projects/{project['id']}/links", json={"type": "conversation", "id": conversation["id"]})
        self.client.post(f"/api/projects/{project['id']}/links", json={"type": "knowledge", "id": knowledge["id"]})
        details = self.client.get(f"/api/projects/{project['id']}").get_json()["project"]
        self.assertEqual(len(details["tasks"]), 1)
        self.assertEqual(len(details["documents"]), 1)
        self.assertEqual(len(details["knowledge_files"]), 1)
        self.assertEqual(len(details["conversations"]), 1)
        with self.app.app_context():
            from ultron.db import get_db
            context = retrieve_context(get_db(), "home network status", max_items=4, max_characters=500)
        self.assertTrue(context)
        self.assertLessEqual(sum(len(row["snippet"]) for row in context), 500)
        self.assertTrue(any("Router" in row["title"] for row in context))
        updated = self.client.patch(f"/api/projects/{project['id']}", json={"status": "archived"})
        self.assertEqual(updated.get_json()["project"]["status"], "archived")
        self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 200)

    def test_planning_context_includes_event_times_and_task_deadlines(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.client.post("/api/events", json={"title": "Design review", "date": tomorrow, "start_time": "14:30", "end_time": "15:15"})
        self.client.post("/api/tasks", json={"title": "Prepare review notes", "due_date": tomorrow, "priority": "high"})
        with self.app.app_context():
            from ultron.db import get_db
            context = retrieve_context(get_db(), "What should I prioritize tomorrow?", max_items=8, max_characters=3500)
        by_title = {item["title"]: item for item in context}
        self.assertEqual(by_title["Design review"]["metadata"]["start_at"], f"{tomorrow} 14:30:00")
        self.assertEqual(by_title["Prepare review notes"]["metadata"]["due_date"], tomorrow)
        self.assertEqual(by_title["Prepare review notes"]["metadata"]["priority"], "high")

    def test_chat_context_respects_the_memory_setting_and_active_state(self):
        active = self.client.post("/api/memories", json={"content": "Networking is my current study topic", "category": "fact"}).get_json()["memory"]
        inactive = self.client.post("/api/memories", json={"content": "Networking is an old study topic", "category": "fact"}).get_json()["memory"]
        self.client.patch(f"/api/memories/{inactive['id']}", json={"active": False})
        with self.app.app_context():
            from ultron.db import get_db
            db = get_db()
            enabled = retrieve_context(db, "networking", include_memories=True)
            disabled = retrieve_context(db, "networking", include_memories=False)
        self.assertIn(active["id"], {item["id"] for item in enabled if item["type"] == "memory"})
        self.assertNotIn(inactive["id"], {item["id"] for item in enabled if item["type"] == "memory"})
        self.assertFalse(any(item["type"] == "memory" for item in disabled))

    def test_workspace_navigation_pages_render(self):
        project = self.client.post("/api/projects", json={"name": "UI project"}).get_json()["project"]
        imported = self.client.post("/api/knowledge/import", data={"file": (io.BytesIO(b"Previewable networking text"), "preview.txt")}, content_type="multipart/form-data").get_json()["file"]
        for route in ("/search?q=networking", "/knowledge", f"/knowledge?file={imported['id']}", "/projects", f"/projects?project={project['id']}", "/tasks"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
        sidebar = self.client.get("/search").get_data(as_text=True)
        self.assertIn("Knowledge Base", sidebar)
        self.assertIn("Projects", sidebar)


class LiveOllamaIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("ULTRON_LIVE_OLLAMA_TESTS") == "1", "set ULTRON_LIVE_OLLAMA_TESTS=1 to run against local Ollama")
    def test_gemma3_4b_can_create_a_task_through_chat(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app({"TESTING": True, "DATABASE": str(Path(temporary.name) / "gemma4b.db")})
        client = app.test_client()
        conversation = client.post(
            "/api/conversations",
            json={
                "first_message": "I need this in my task list: review the 4B integration notes by December 12, 2026.",
                "model": "gemma3:4b",
            },
        ).get_json()
        response = client.post(f"/api/conversations/{conversation['id']}/stream", json={}, buffered=True)
        self.assertEqual(response.status_code, 200)
        tasks = client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(len(tasks), 1, response.get_data(as_text=True))
        self.assertIn("review", tasks[0]["title"].casefold())
        self.assertIn("integration notes", tasks[0]["title"].casefold())
        self.assertEqual(tasks[0]["due_date"], "2026-12-12")
class ChatBehaviorTests(unittest.TestCase):
    def test_plain_language_task_request_is_saved_without_model_tool_json(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app(
            {"TESTING": True, "DATABASE": str(Path(temporary.name) / "direct-task.db")}
        )
        client = app.test_client()
        conversation = client.post(
            "/api/conversations",
            json={"first_message": "Create a task as a reminder that at 20:00 I have to clean my room."},
        ).get_json()

        with patch.object(chat_blueprint.ollama, "stream_chat", side_effect=AssertionError("model should not be needed")):
            response = client.post(
                f"/api/conversations/{conversation['id']}/stream", json={}, buffered=True
            )

        body = response.get_data(as_text=True)
        tasks = client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Clean my room")
        self.assertEqual(tasks[0]["due_date"], date.today().isoformat())
        self.assertEqual(tasks[0]["due_time"], "20:00")
        self.assertIn("Added “Clean my room” to your tasks.", body)

    def test_task_list_phrasing_and_month_dates_are_understood(self):
        parsed = chat_blueprint._simple_task_request(
            "Could you add 'Call Sam' to my task list on December 12, 2026?"
        )
        self.assertEqual(parsed, {"title": "Call Sam", "due_date": "2026-12-12", "due_time": None})
        self.assertEqual(
            chat_blueprint._simple_task_request("I need to create a task to review the plan tomorrow."),
            {"title": "Review the plan", "due_date": (date.today() + timedelta(days=1)).isoformat(), "due_time": None},
        )

    def test_chat_wont_confirm_task_until_a_tool_saves_it(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app(
            {"TESTING": True, "DATABASE": str(Path(temporary.name) / "task-confirmation.db")}
        )
        client = app.test_client()
        conversation = client.post(
            "/api/conversations",
            json={"first_message": "Can you put a reminder in my project tasks to review my notes tomorrow?"},
        ).get_json()
        calls = []

        def fake_stream_chat(**kwargs):
            calls.append(kwargs["messages"])
            if len(calls) == 1:
                yield "Okay, added that to your tasks."
            elif len(calls) == 2:
                yield "I'll save that now: " + json.dumps({
                    "ultron_tool": "create_task",
                    "arguments": {"title": "Review my notes", "due_date": "2026-11-08"},
                })
            else:
                yield "Added the task to your list."

        with patch.object(chat_blueprint.ollama, "stream_chat", fake_stream_chat):
            response = client.post(
                f"/api/conversations/{conversation['id']}/stream", json={}, buffered=True
            )

        body = response.get_data(as_text=True)
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [task["title"] for task in client.get("/api/tasks").get_json()["tasks"]],
            ["Review my notes"],
        )
        self.assertIn("Added the task to your list.", body)
        self.assertNotIn("Okay, added that to your tasks.", body)
        self.assertTrue(any(
            "The user directly requested a calendar or task change" in message["content"]
            for message in calls[1]
        ))

    def test_offline_search_returns_browser_fallback(self):
        reply = chat_blueprint._format_web_search_result(
            "gaming laptop specs",
            {"error": "Internet connection is unavailable.", "offline": True},
        )
        self.assertIn("Open this search in your browser", reply)
        self.assertIn("https://duckduckgo.com/?q=gaming+laptop+specs", reply)

    def test_explicit_web_search_bypasses_model_tool_formatting(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(Path(temporary.name) / "search.db"),
                "ULTRON_WORKSPACE_ROOT": None,
            }
        )
        client = app.test_client()
        conversation = client.post(
            "/api/conversations",
            json={"first_message": "Can you search online for gaming laptop specs and price?"},
        ).get_json()
        search_results = {
            "source": "web_search",
            "query": "gaming laptop specs and price",
            "results": [{
                "title": "Laptop guide",
                "url": "https://example.com/laptops",
                "snippet": "Compare specifications and prices.",
            }],
            "count": 1,
        }
        with patch.object(chat_blueprint.web_search, "search", return_value=search_results) as search:
            with patch.object(chat_blueprint.ollama, "stream_chat", side_effect=AssertionError):
                response = client.post(
                    f"/api/conversations/{conversation['id']}/stream",
                    json={},
                    buffered=True,
                )
        body = response.get_data(as_text=True)
        search.assert_called_once_with("gaming laptop specs and price", max_results=5)
        self.assertIn("Laptop guide", body)
        self.assertIn("https://example.com/laptops", body)
        self.assertIn("event: done", body)

    def test_chat_allows_productivity_tools_and_blocks_other_tools(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        app = create_app(
            {"TESTING": True, "DATABASE": str(Path(temporary.name) / "chat.db")}
        )
        client = app.test_client()
        conversation = client.post(
            "/api/conversations",
            json={
                "first_message": "Create a kite design task",
                "model": "gemma3:1b",
            },
        ).get_json()
        captured_messages = []
        call_count = 0
        def fake_stream_chat(**kwargs):
            nonlocal call_count
            captured_messages.append(kwargs["messages"])
            if call_count == 0:
                yield json.dumps({"ultron_tool": "create_task", "arguments": {"title": "Kite design"}})
            else:
                yield "Added the Kite design task."
            call_count += 1

        with patch.object(chat_blueprint.ollama, "stream_chat", fake_stream_chat):
            response = client.post(
                "/api/conversations/%s/stream" % conversation["id"],
                json={},
                buffered=True,
            )

        body = response.get_data(as_text=True)
        self.assertNotIn("event: tool", body)
        self.assertIn("Adding the task", body)
        self.assertIn("Added the Kite design task", body)
        self.assertIn("event: done", body)
        self.assertNotIn('"ultron_tool"', body)
        system_prompt = next(message["content"] for message in captured_messages[0] if message["role"] == "system")
        self.assertIn("ordinary language", system_prompt)
        self.assertIn("do not ask the user to follow a template", system_prompt)
        self.assertIn("never show it to the user or ask them to repeat a date that way", system_prompt)
        self.assertIn("These tool instructions are internal", system_prompt)
        tasks = client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual([task["title"] for task in tasks], ["Kite design"])

        other_conversation = client.post(
            "/api/conversations",
            json={"first_message": "Create a document", "model": "gemma3:1b"},
        ).get_json()
        with patch.object(
            chat_blueprint.ollama,
            "stream_chat",
            lambda **kwargs: iter([json.dumps({"ultron_tool": "create_document", "arguments": {"title": "Nope", "content": "x"}})]),
        ):
            other_response = client.post(
                "/api/conversations/%s/stream" % other_conversation["id"],
                json={},
                buffered=True,
            )
        self.assertIn("couldn't complete", other_response.get_data(as_text=True))
        self.assertEqual(client.get("/api/documents").get_json()["documents"], [])


class ModelDiscoveryTests(unittest.TestCase):
    def test_custom_local_models_are_selectable(self):
        with patch.object(ollama, "list_models", return_value=["gemma3:1b", "hf.co/team/model:3b"]):
            options = ollama.model_options("http://localhost:11434")
        self.assertIn("hf.co/team/model:3b", [option["id"] for option in options])


class ProductivityWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(Path(self.temporary.name) / "workspace.db"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_task_time_triggers_reminder_at_its_due_time(self):
        due_time = (datetime.now() - timedelta(minutes=1)).strftime("%H:%M")
        created = self.client.post(
            "/api/tasks",
            json={"title": "Timed reminder", "due_date": date.today().isoformat(), "due_time": due_time},
        ).get_json()["task"]

        notifications = self.client.get("/api/notifications").get_json()["notifications"]
        reminder = next(item for item in notifications if item["source_type"] == "task")
        self.assertEqual(reminder["source_id"], created["id"])
        self.assertEqual(reminder["due_at"], f"{created['due_date']} {due_time}:00")

    def test_document_folder_search_and_ai_suggestion_do_not_overwrite(self):
        folder = self.client.post(
            "/api/document-folders", json={"name": "Research"}
        ).get_json()["folder"]
        document = self.client.post(
            "/api/documents",
            json={
                "title": "Draft",
                "content": "Original draft text",
                "folder_id": folder["id"],
                "format": "markdown",
            },
        ).get_json()["document"]
        result = self.client.get("/api/documents?q=Original&folder=%s" % folder["id"])
        self.assertEqual(result.get_json()["documents"][0]["id"], document["id"])

        def fake_suggestion(**kwargs):
            yield "A polished draft suggestion."

        with patch.object(documents_blueprint.ollama, "stream_chat", fake_suggestion):
            response = self.client.post(
                "/api/documents/%s/assist" % document["id"],
                json={"action": "improve"},
                buffered=True,
            )
        self.assertIn("A polished draft suggestion.", response.get_data(as_text=True))
        stored = self.client.get("/api/documents/%s" % document["id"]).get_json()[
            "document"
        ]
        self.assertEqual(stored["content"], "Original draft text")
        self.assertEqual(stored["folder_id"], folder["id"])

    def test_calendar_views_categories_and_task_categories(self):
        for view in ("month", "week", "day"):
            self.assertEqual(self.client.get("/calendar?view=" + view).status_code, 200)
        event = self.client.post(
            "/api/events",
            json={
                "title": "Study session",
                "date": "2026-11-08",
                "start_time": "16:00",
                "category": "study",
            },
        ).get_json()["event"]
        self.assertEqual(event["category"], "study")

        task = self.client.post(
            "/api/tasks", json={"title": "Practice", "category": "study"}
        ).get_json()["task"]
        self.assertEqual(task["category"], "study")
        updated = self.client.patch(
            "/api/tasks/%s" % task["id"], json={"category": "work"}
        ).get_json()["task"]
        self.assertEqual(updated["category"], "work")

        with self.assertRaises(ToolError):
            execute_tool(
                self.app.config["DATABASE"],
                "create_calendar_event",
                {"title": "Unclear", "date": "2026-11-08"},
            )

    def test_dashboard_separates_today_from_upcoming_events(self):
        today = date.today()
        tomorrow = today + timedelta(days=1)
        for title, event_day in (("Today item", today), ("Future item", tomorrow)):
            response = self.client.post(
                "/api/events",
                json={"title": title, "date": event_day.isoformat(), "start_time": "10:00"},
            )
            self.assertEqual(response.status_code, 201)
        page = self.client.get("/")
        self.assertIn(b"Today item", page.data)
        self.assertIn(b"Future item", page.data)
        self.assertNotIn(b"Nothing scheduled today", page.data)




class WebSearchAndFileToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "workspace.db"
        connection = sqlite3.connect(self.database)
        schema = Path(__file__).resolve().parents[1] / "ultron" / "schema.sql"
        connection.executescript(schema.read_text(encoding="utf-8"))
        connection.close()

    def tearDown(self):
        self.temporary.cleanup()

    def test_local_file_read_and_create_tools_restricted_to_workspace(self):
        # Create a file
        created = execute_tool(
            str(self.database),
            "create_local_file",
            {"path": "notes/project.txt", "content": "Ultron local project notes"},
            workspace_root=str(self.root),
        )
        self.assertTrue(created["created"])
        self.assertEqual(created["path"], "notes/project.txt")

        # Read the file
        read_res = execute_tool(
            str(self.database),
            "read_local_file",
            {"path": "notes/project.txt"},
            workspace_root=str(self.root),
        )
        self.assertEqual(read_res["content"], "Ultron local project notes")

        # Reject path traversal
        with self.assertRaises(ToolError):
            execute_tool(
                str(self.database),
                "read_local_file",
                {"path": "../../etc/passwd"},
                workspace_root=str(self.root),
            )

        # Reject forbidden extensions
        with self.assertRaises(ToolError):
            execute_tool(
                str(self.database),
                "create_local_file",
                {"path": "malicious.exe", "content": "bin"},
                workspace_root=str(self.root),
            )

    def test_web_search_and_fetch_tools(self):
        from ultron.services import web_search

        with patch.object(
            web_search,
            "search",
            return_value={"ok": True, "results": [{"title": "Ollama", "url": "https://ollama.com", "snippet": "Local LLMs"}]},
        ):
            res = execute_tool(str(self.database), "web_search", {"query": "ollama"})
            self.assertEqual(len(res["results"]), 1)
            self.assertEqual(res["results"][0]["title"], "Ollama")

        with patch.object(
            web_search,
            "fetch_page_text",
            return_value={"ok": True, "text": "Extracted content from page."},
        ):
            fetch_res = execute_tool(str(self.database), "fetch_webpage", {"url": "https://example.com"})
            self.assertEqual(fetch_res["content"], "Extracted content from page.")


class DocumentImportExportAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(Path(self.temporary.name) / "workspace.db"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_document_import_and_export(self):
        # Import JSON
        res = self.client.post(
            "/api/documents/import",
            json={"title": "Imported Specs", "content": "# Specifications\nLocal first."},
        )
        self.assertEqual(res.status_code, 201)
        doc_id = res.get_json()["document"]["id"]

        # Export single document
        export_res = self.client.get(f"/api/documents/{doc_id}/export")
        self.assertEqual(export_res.status_code, 200)
        self.assertIn("Specifications", export_res.get_data(as_text=True))
        self.assertEqual(export_res.headers["Content-Disposition"], 'attachment; filename="Imported Specs.md"')

        # Export all documents
        export_all = self.client.get("/api/documents/export-all")
        self.assertEqual(export_all.status_code, 200)
        payload = json.loads(export_all.get_data(as_text=True))
        self.assertEqual(payload["count"], 1)

    def test_settings_save_and_backup_restore(self):
        # Save custom theme and preferences
        save_res = self.client.post(
            "/settings",
            data={
                "operator_name": "Commander",
                "default_model": "gemma3:1b",
                "ollama_url": "http://localhost:11434",
                "temperature": "0.5",
                "system_prompt": "Custom prompt",
                "use_memory": "1",
                "theme": "nord",
                "accent": "emerald",
                "font": "sans",
                "web_search_enabled": "1",
                "voice_enabled": "1",
                "voice_auto_speak": "0",
                "chat_send_key": "ctrl_enter",
            },
            follow_redirects=True,
        )
        self.assertEqual(save_res.status_code, 200)

        # Verify settings persisted
        with self.app.app_context():
            from ultron.helpers import get_settings
            current = get_settings()
            self.assertEqual(current["theme"], "nord")
            self.assertEqual(current["accent"], "emerald")
            self.assertEqual(current["font"], "sans")
            self.assertEqual(current["chat_send_key"], "ctrl_enter")
            self.assertEqual(current["operator_name"], "Commander")

        # Verify AJAX save response
        ajax_res = self.client.post(
            "/settings",
            data={"operator_name": "Commander 2", "theme": "oled"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(ajax_res.status_code, 200)
        self.assertTrue(ajax_res.get_json()["ok"])

        # Export JSON backup
        export_res = self.client.get("/settings/export")
        self.assertEqual(export_res.status_code, 200)
        backup_data = export_res.get_data()

        # Add a new task
        self.client.post("/api/tasks", json={"title": "Temporary task before restore"})

        # Restore from backup
        import io
        restore_res = self.client.post(
            "/settings/restore",
            data={"backup_file": (io.BytesIO(backup_data), "backup.json")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(restore_res.status_code, 200)
        self.assertIn(b"Workspace data and settings restored successfully", restore_res.data)

        # Temporary task should be gone
        tasks = self.client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(len(tasks), 0)

if __name__ == "__main__":
    unittest.main()
