import tempfile
import unittest
from pathlib import Path

from ultron import create_app
from ultron.blueprints.automations import run_due_jobs
from ultron.db import get_db
from ultron.helpers import now_str
from ultron.services.learning import record_success, retrieve_experiences
from ultron.services.memory_extraction import extract_explicit_memory


class EvolutionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temporary.name) / "evolution.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.database})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_recurring_automation_runs_once_and_notifies(self):
        response = self.client.post("/api/automations", json={
            "name": "Task check", "instruction": "Show unfinished tasks every evening",
            "schedule_type": "daily", "schedule_value": {"time": "19:00"}, "timezone": "Asia/Jakarta",
        })
        self.assertEqual(response.status_code, 201)
        automation_id = response.json["id"]
        with self.app.app_context():
            db = get_db()
            db.execute("INSERT INTO tasks(title,created_at) VALUES('Review plan',?)", (now_str(),))
            db.execute("UPDATE automations SET next_run_at='2000-01-01 00:00:00' WHERE id=?", (automation_id,))
            db.commit()
        run_due_jobs(self.app)
        run_due_jobs(self.app)
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM automation_runs WHERE automation_id=? AND status='completed'", (automation_id,)).fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM local_notifications WHERE category='automation'").fetchone()[0], 1)
            self.assertIsNotNone(db.execute("SELECT next_run_at FROM automations WHERE id=?", (automation_id,)).fetchone()[0])

    def test_experience_retrieval_and_confirmed_reuse(self):
        with self.app.app_context():
            db = get_db()
            item_id = record_success(db, "Create a weekly productivity report from completed tasks", "Weekly productivity report", "general productivity", ["Read completed tasks", "Group results by project"], ["read_tasks"], "Backend confirmed report created.")
            db.commit()
            found = retrieve_experiences(db, "Create another weekly productivity report", limit=1)
            self.assertEqual(found[0]["id"], item_id)
            record_success(db, "Create another weekly productivity report", "Weekly productivity report", "general productivity", ["Reuse confirmed grouping"], ["read_tasks"], "Backend confirmed report created.")
            db.commit()
            self.assertEqual(db.execute("SELECT successful_uses FROM experiences WHERE id=?", (item_id,)).fetchone()[0], 2)

    def test_schedule_validation_and_manual_run_history(self):
        bad = self.client.post("/api/automations", json={"name": "Bad", "instruction": "show tasks", "schedule_type": "daily", "schedule_value": {"time": "99:00"}, "timezone": "Asia/Jakarta"})
        self.assertEqual(bad.status_code, 400)
        created = self.client.post("/api/automations", json={"name": "Plan", "instruction": "Show today's schedule and unfinished tasks", "schedule_type": "once", "schedule_value": {"at": "2099-04-05 07:00"}, "timezone": "Asia/Jakarta"})
        self.assertEqual(created.status_code, 201)
        ran = self.client.post(f"/api/automations/{created.json['id']}/run", json={})
        self.assertEqual(ran.status_code, 200)
        self.assertIn("Today's events", ran.json["result"])

    def test_memory_extraction_is_conservative_and_requires_approval(self):
        with self.app.app_context():
            db = get_db()
            item_id = extract_explicit_memory(db, "I prefer simple document formatting without excessive decoration.")
            self.assertIsNotNone(item_id)
            row = db.execute("SELECT active,approved,category FROM memories WHERE id=?", (item_id,)).fetchone()
            self.assertEqual((row["active"], row["approved"], row["category"]), (0, 0, "preference"))
            self.assertIsNone(extract_explicit_memory(db, "My password is example-secret-123; please remember it."))


if __name__ == "__main__":
    unittest.main()
