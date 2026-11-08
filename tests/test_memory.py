import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ultron.blueprints.chat as chat_blueprint
from ultron import create_app
from ultron.db import get_db
from ultron.services.memory import memory_context, save_memory
from ultron.services.memory_extraction import extract_explicit_memories, extract_explicit_memory
from ultron.services.workspace_tools import execute_tool


class MemoryCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary.name) / "memory.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.database})

    def tearDown(self):
        self.temporary.cleanup()

    def test_short_preference_becomes_an_active_durable_note(self):
        with self.app.app_context():
            db = get_db()
            item_id = extract_explicit_memory(db, "I like pizza.", auto_approve=True)
            db.commit()
            row = db.execute("SELECT content, category, active, approved FROM memories WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual(dict(row), {
            "content": "The user likes pizza.",
            "category": "preference",
            "active": 1,
            "approved": 1,
        })

    def test_identity_facts_projects_and_explicit_instructions(self):
        with self.app.app_context():
            db = get_db()
            extract_explicit_memories(
                db,
                "My name is Ada. I'm allergic to peanuts. I'm working on a Flask app. "
                "Please remember that I prefer dark mode.",
                auto_approve=True,
            )
            db.commit()
            contents = {
                row["content"]
                for row in db.execute("SELECT content FROM memories").fetchall()
            }
        self.assertIn("The user's name is Ada.", contents)
        self.assertIn("The user is allergic to peanuts.", contents)
        self.assertIn("The user is working on a Flask app.", contents)
        self.assertIn("The user prefers dark mode.", contents)

    def test_transient_questions_and_assistant_directed_statements_are_ignored(self):
        with self.app.app_context():
            db = get_db()
            for text in (
                "I would like a pizza.",
                "I like it.",
                "I like how you answer.",
                "Do I like pizza?",
                "Call me at five.",
                "Please remember to call mom.",
            ):
                extract_explicit_memories(db, text, auto_approve=True)
            db.commit()
            count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        self.assertEqual(count, 0)

    def test_secrets_are_never_stored(self):
        with self.app.app_context():
            db = get_db()
            ids = extract_explicit_memories(
                db, "My password is example-secret-123; please remember it.", auto_approve=True
            )
            result = save_memory(db, "My API key is example-token", "general", approved=True)
            count = db.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        self.assertEqual(ids, [])
        self.assertFalse(result["saved"])
        self.assertEqual(result["reason"], "sensitive")
        self.assertEqual(count, 0)

    def test_duplicates_merge_and_simple_contradictions_replace(self):
        with self.app.app_context():
            db = get_db()
            extract_explicit_memories(db, "I like pizza.", auto_approve=True)
            extract_explicit_memories(db, "I really like pizza a lot.", auto_approve=True)
            extract_explicit_memories(db, "I don't like pizza.", auto_approve=True)
            extract_explicit_memories(db, "I like pasta.", auto_approve=True)
            db.commit()
            rows = db.execute("SELECT content FROM memories ORDER BY id").fetchall()
        contents = [row["content"] for row in rows]
        self.assertEqual(len(contents), 2)
        self.assertIn("The user does not like pizza.", contents)
        self.assertIn("The user likes pasta.", contents)

    def test_memory_context_includes_notes_even_without_keyword_overlap(self):
        with self.app.app_context():
            db = get_db()
            extract_explicit_memories(db, "I like pizza. My name is Ada.", auto_approve=True)
            db.commit()
            context = memory_context(db, "What should I eat for dinner?")
        contents = {item["content"] for item in context}
        self.assertIn("The user likes pizza.", contents)
        self.assertIn("The user's name is Ada.", contents)

    def test_inactive_or_unapproved_notes_are_not_injected(self):
        with self.app.app_context():
            db = get_db()
            paused = extract_explicit_memory(db, "I like pizza.", auto_approve=True)
            pending = extract_explicit_memory(db, "I like pasta.", auto_approve=False)
            db.execute("UPDATE memories SET active = 0 WHERE id = ?", (paused,))
            db.commit()
            context = memory_context(db, "food")
        contents = {item["content"] for item in context}
        self.assertNotIn("The user likes pizza.", contents)
        self.assertNotIn("The user likes pasta.", contents)

    def test_save_memory_tool_is_deduplicated(self):
        first = execute_tool(
            self.database,
            "save_memory",
            {"content": "The user likes pizza.", "category": "preference"},
        )
        second = execute_tool(
            self.database,
            "save_memory",
            {"content": "The user likes pizza.", "category": "preference"},
        )
        self.assertTrue(first["saved"])
        self.assertFalse(second["saved"])
        self.assertEqual(second["reason"], "already_saved")
        self.assertIn("note", second)


class MemoryChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary.name) / "memory-chat.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.database})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_memory_is_captured_and_reused_in_a_later_conversation(self):
        first = self.client.post(
            "/api/conversations", json={"first_message": "I like pizza."}
        ).get_json()

        def first_reply(**kwargs):
            yield "Noted."

        with patch.object(chat_blueprint.ollama, "stream_chat", first_reply):
            response = self.client.post(
                f"/api/conversations/{first['id']}/stream", json={}, buffered=True
            )
        self.assertEqual(response.status_code, 200)
        memories = self.client.get("/api/memories").get_json()["memories"]
        self.assertEqual([(item["content"], item["active"], item["approved"]) for item in memories], [
            ("The user likes pizza.", 1, 1)
        ])

        second = self.client.post(
            "/api/conversations", json={"first_message": "What should I eat for dinner?"}
        ).get_json()
        captured = []

        def second_reply(**kwargs):
            captured.extend(kwargs["messages"])
            yield "Try something you enjoy."

        with patch.object(chat_blueprint.ollama, "stream_chat", second_reply):
            response = self.client.post(
                f"/api/conversations/{second['id']}/stream", json={}, buffered=True
            )
        self.assertEqual(response.status_code, 200)
        system_prompt = next(
            message["content"] for message in captured if message["role"] == "system"
        )
        self.assertIn("The user likes pizza.", system_prompt)


if __name__ == "__main__":
    unittest.main()
