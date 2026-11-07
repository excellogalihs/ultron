import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from ultron import create_app
from ultron.blueprints import chat as chat_blueprint
from ultron.blueprints import documents as documents_blueprint
from ultron.services import ollama
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


class ChatBehaviorTests(unittest.TestCase):
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

    def test_chat_does_not_expose_or_execute_model_tool_calls(self):
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
        def fake_stream_chat(**kwargs):
            captured_messages.append(kwargs["messages"])
            yield json.dumps(
                {"ultron_tool": "create_task", "arguments": {"title": "Kite design"}}
            )

        with patch.object(chat_blueprint.ollama, "stream_chat", fake_stream_chat):
            response = client.post(
                "/api/conversations/%s/stream" % conversation["id"],
                json={},
                buffered=True,
            )

        body = response.get_data(as_text=True)
        self.assertNotIn("event: tool", body)
        self.assertIn("Tool calling is disabled", body)
        self.assertIn("event: done", body)
        self.assertNotIn("ultron_tool", captured_messages[0][0]["content"])
        tasks = client.get("/api/tasks").get_json()["tasks"]
        self.assertEqual(tasks, [])


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
