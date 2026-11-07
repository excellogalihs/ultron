"""In-app and optional desktop reminders for tasks and calendar events."""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from ..db import get_db
from ..helpers import get_settings, now_str

bp = Blueprint("notifications", __name__)


def _reminder_settings():
    settings = get_settings()
    try:
        task_time = datetime.strptime(settings.get("task_reminder_time", "09:00"), "%H:%M").strftime("%H:%M")
    except ValueError:
        task_time = "09:00"
    try:
        event_minutes = int(settings.get("event_reminder_minutes", "10"))
    except (TypeError, ValueError):
        event_minutes = 10
    return task_time, min(max(event_minutes, 0), 120)


def _schedule_due_reminders(db, now):
    task_time, event_minutes = _reminder_settings()
    current = now.strftime("%Y-%m-%d %H:%M:%S")
    new_ids = []

    due_tasks = db.execute(
        "SELECT id, title, due_date, due_time FROM tasks WHERE status = 'pending' AND due_date = ?",
        (now.date().isoformat(),),
    ).fetchall()
    for task in due_tasks:
        reminder_time = task["due_time"] or task_time
        due_at = f"{task['due_date']} {reminder_time}:00"
        if due_at > current:
            continue
        cursor = db.execute(
            """INSERT OR IGNORE INTO notifications
               (source_type, source_id, schedule_key, title, message, due_at, created_at)
               VALUES ('task', ?, ?, ?, ?, ?, ?)""",
            (task["id"], f"{task['due_date']} {reminder_time}", "Task due today", task["title"], due_at, current),
        )
        if cursor.rowcount:
            new_ids.append(cursor.lastrowid)

    event_floor = (now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    event_ceiling = (now + timedelta(minutes=event_minutes + 15)).strftime("%Y-%m-%d %H:%M:%S")
    events = db.execute(
        "SELECT id, title, description, start_at FROM events WHERE start_at >= ? AND start_at <= ? ORDER BY start_at",
        (event_floor, event_ceiling),
    ).fetchall()
    for event in events:
        start = datetime.strptime(event["start_at"], "%Y-%m-%d %H:%M:%S")
        reminder_at = start - timedelta(minutes=event_minutes)
        due_at = reminder_at.strftime("%Y-%m-%d %H:%M:%S")
        if due_at > current:
            continue
        cursor = db.execute(
            """INSERT OR IGNORE INTO notifications
               (source_type, source_id, schedule_key, title, message, due_at, created_at)
               VALUES ('event', ?, ?, ?, ?, ?, ?)""",
            (
                event["id"], event["start_at"], "Upcoming calendar event",
                event["title"] + (f" · {event['description']}" if event["description"] else ""),
                due_at, current,
            ),
        )
        if cursor.rowcount:
            new_ids.append(cursor.lastrowid)

    db.commit()
    return new_ids


def _notification_dict(row):
    item = dict(row)
    item["href"] = "/tasks?view=pending" if item["source_type"] == "task" else "/calendar?view=day&date=" + item["schedule_key"][:10]
    return item


@bp.get("/api/notifications")
def api_list():
    db = get_db()
    new_ids = _schedule_due_reminders(db, datetime.now().replace(microsecond=0))
    rows = db.execute(
        "SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT 40"
    ).fetchall()
    by_id = {row["id"]: row for row in rows}
    new_notifications = [_notification_dict(by_id[item_id]) for item_id in new_ids if item_id in by_id]
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
    return jsonify(
        notifications=[_notification_dict(row) for row in rows],
        new=new_notifications,
        unread=unread,
    )


@bp.post("/api/notifications/<int:notification_id>/read")
def api_read(notification_id):
    db = get_db()
    row = db.execute("SELECT id FROM notifications WHERE id = ?", (notification_id,)).fetchone()
    if row is None:
        return jsonify(error="Notification not found."), 404
    db.execute("UPDATE notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?", (now_str(), notification_id))
    db.commit()
    unread = db.execute("SELECT COUNT(*) FROM notifications WHERE read_at IS NULL").fetchone()[0]
    return jsonify(ok=True, unread=unread)


@bp.post("/api/notifications/read-all")
def api_read_all():
    db = get_db()
    db.execute("UPDATE notifications SET read_at = COALESCE(read_at, ?)", (now_str(),))
    db.commit()
    return jsonify(ok=True, unread=0)
