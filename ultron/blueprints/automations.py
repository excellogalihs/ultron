"""Local, SQLite-backed routine scheduler and automation history."""

import json
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..helpers import now_str

bp = Blueprint("automations", __name__)
_run_lock = threading.Lock()


def _timezone(value):
    try:
        return ZoneInfo(value or "Asia/Jakarta")
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose a valid IANA timezone, such as Asia/Jakarta.")


def _next_run(kind, value, timezone, after=None):
    local_now = after.astimezone(timezone) if after else datetime.now(timezone)
    hour, minute = map(int, value.get("time", "09:00").split(":"))
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if kind == "once":
        candidate = datetime.fromisoformat(value["at"]).replace(tzinfo=timezone)
        if candidate <= local_now:
            return None
    elif kind == "daily":
        if candidate <= local_now:
            candidate += timedelta(days=1)
    elif kind == "weekly":
        weekday = int(value.get("weekday", 0))
        candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
        if candidate <= local_now:
            candidate += timedelta(days=7)
    elif kind == "monthly":
        day = min(max(int(value.get("day", 1)), 1), 28)
        candidate = candidate.replace(day=day)
        if candidate <= local_now:
            month = candidate.month % 12 + 1
            year = candidate.year + (candidate.month == 12)
            candidate = candidate.replace(year=year, month=month, day=day)
    elif kind == "custom":
        interval = min(max(int(value.get("interval_minutes", 60)), 15), 525600)
        candidate = local_now + timedelta(minutes=interval)
    else:
        raise ValueError("Unsupported schedule type.")
    return candidate.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")


def _validate_schedule(kind, data, timezone):
    if kind not in ("once", "daily", "weekly", "monthly", "custom"):
        raise ValueError("Unsupported schedule type.")
    value = data.get("schedule_value") or {}
    _timezone(timezone)
    if kind == "once":
        value = {"at": value.get("at", "")}
        datetime.fromisoformat(value["at"])
    else:
        hour, minute = map(int, value.get("time", "09:00").split(":"))
        if hour not in range(24) or minute not in range(60):
            raise ValueError("Time must use 24-hour HH:MM format.")
        value["time"] = f"{hour:02d}:{minute:02d}"
        if kind == "weekly":
            value["weekday"] = int(value.get("weekday", 0))
            if value["weekday"] not in range(7):
                raise ValueError("Weekday must be from 0 to 6.")
        if kind == "monthly":
            value["day"] = int(value.get("day", 1))
            if value["day"] not in range(1, 29):
                raise ValueError("Monthly day must be from 1 to 28.")
        if kind == "custom":
            value["interval_minutes"] = int(value.get("interval_minutes", 60))
            if value["interval_minutes"] < 15:
                raise ValueError("Custom intervals must be at least 15 minutes.")
    return value, _next_run(kind, value, _timezone(timezone))


def _execute(db, automation, trigger="schedule"):
    """Run supported deterministic read-only summaries. Unsupported intents fail visibly."""
    instruction = automation["instruction"].casefold()
    parts, actions = [], []
    if any(word in instruction for word in ("schedule", "calendar", "event", "planning")):
        today = datetime.now(_timezone(automation["timezone"])).date()
        rows = db.execute("SELECT title,start_at FROM events WHERE start_at>=? AND start_at<? ORDER BY start_at", (f"{today} 00:00:00", f"{today + timedelta(days=1)} 00:00:00")).fetchall()
        parts.append("Today's events: " + ("; ".join(f"{row['start_at'][11:16]} {row['title']}" for row in rows) if rows else "none scheduled"))
        actions.append({"step": "Read today's calendar events", "count": len(rows)})
    if "task" in instruction:
        rows = db.execute("SELECT title,due_date FROM tasks WHERE status='pending' ORDER BY due_date,due_time,id LIMIT 100").fetchall()
        parts.append("Unfinished tasks: " + ("; ".join(row["title"] + (f" (due {row['due_date']})" if row["due_date"] else "") for row in rows) if rows else "none"))
        actions.append({"step": "Read unfinished tasks", "count": len(rows)})
    if not actions:
        raise ValueError("This routine does not match a supported local summary yet. Use instructions about calendar events or schedules.")
    result = "\n".join(parts)
    now = now_str()
    db.execute("INSERT INTO local_notifications(category,title,message,created_at) VALUES('automation',?,?,?)", ("Automation: " + automation["name"], result[:4000], now))
    db.execute("INSERT INTO automation_runs(automation_id,automation_name,trigger_type,status,actions,result,scheduled_for,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)", (automation["id"], automation["name"], trigger, "completed", json.dumps(actions), result, automation.get("next_run_at"), now, now))
    return result


def run_due_jobs(app):
    """A single daemon thread per app process checks due rows; writes are idempotent."""
    if not _run_lock.acquire(blocking=False):
        return
    try:
        with app.app_context():
            db = get_db()
            utc_now = datetime.now(ZoneInfo("UTC"))
            now = utc_now.strftime("%Y-%m-%d %H:%M:%S")
            lease = (utc_now + timedelta(seconds=90)).strftime("%Y-%m-%d %H:%M:%S")
            db.execute("UPDATE scheduler_lease SET lease_until=? WHERE id=1 AND lease_until<?", (lease, now))
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                db.rollback()
                return
            db.commit()
            due = db.execute("SELECT * FROM automations WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at<=? ORDER BY next_run_at LIMIT 10", (now,)).fetchall()
            for original in due:
                item = dict(original)
                db.execute("UPDATE automations SET next_run_at=NULL WHERE id=? AND enabled=1 AND next_run_at=?", (item["id"], item["next_run_at"]))
                if db.execute("SELECT changes()").fetchone()[0] != 1:
                    continue
                try:
                    _execute(db, item)
                    schedule = json.loads(item["schedule_value"])
                    if item["schedule_type"] != "once":
                        following = _next_run(item["schedule_type"], schedule, _timezone(item["timezone"]))
                        db.execute("UPDATE automations SET next_run_at=?,updated_at=? WHERE id=?", (following, now_str(), item["id"]))
                    else:
                        db.execute("UPDATE automations SET enabled=0,updated_at=? WHERE id=?", (now_str(), item["id"]))
                except Exception as error:
                    db.execute("INSERT INTO automation_runs(automation_id,automation_name,trigger_type,status,error,scheduled_for,started_at,finished_at) VALUES(?,?,?,?,?,?,?,?)", (item["id"], item["name"], "schedule", "failed", str(error)[:2000], item["next_run_at"], now, now_str()))
                    if item["schedule_type"] == "once":
                        db.execute("UPDATE automations SET enabled=0 WHERE id=?", (item["id"],))
                    else:
                        following = _next_run(item["schedule_type"], json.loads(item["schedule_value"]), _timezone(item["timezone"]))
                        db.execute("UPDATE automations SET next_run_at=?,updated_at=? WHERE id=?", (following, now_str(), item["id"]))
                db.commit()
            db.execute("UPDATE scheduler_lease SET lease_until='' WHERE id=1 AND lease_until=?", (lease,))
            db.commit()
    finally:
        _run_lock.release()


@bp.get("/automations")
def index():
    db = get_db()
    rows = db.execute("SELECT * FROM automations ORDER BY enabled DESC,next_run_at,id DESC").fetchall()
    runs = db.execute("SELECT * FROM automation_runs ORDER BY started_at DESC,id DESC LIMIT 30").fetchall()
    return render_template("automations.html", page="automations", page_title="Automations", automations=rows, runs=runs)


@bp.get("/api/automations")
def list_automations():
    db = get_db()
    return jsonify(automations=[dict(row) for row in db.execute("SELECT * FROM automations ORDER BY id DESC").fetchall()], runs=[dict(row) for row in db.execute("SELECT * FROM automation_runs ORDER BY id DESC LIMIT 50").fetchall()])


@bp.post("/api/automations")
def create_automation():
    data = request.get_json(silent=True) or {}
    name, instruction = (data.get("name") or "").strip(), (data.get("instruction") or "").strip()
    if not name or not instruction:
        return jsonify(error="Name and instruction are required."), 400
    if len(name) > 120 or len(instruction) > 2000:
        return jsonify(error="Name or instruction is too long."), 400
    timezone = (data.get("timezone") or "Asia/Jakarta").strip()
    try:
        kind = data.get("schedule_type", "daily")
        value, next_run = _validate_schedule(kind, data, timezone)
    except (ValueError, TypeError, KeyError):
        return jsonify(error="Invalid schedule. Check its time, date, and timezone."), 400
    now = now_str()
    db = get_db()
    cursor = db.execute("INSERT INTO automations(name,instruction,schedule_type,schedule_value,timezone,next_run_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (name, instruction, kind, json.dumps(value), timezone, next_run, now, now))
    db.commit()
    return jsonify(id=cursor.lastrowid, next_run_at=next_run), 201


@bp.patch("/api/automations/<int:item_id>")
def update_automation(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM automations WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify(error="Automation not found."), 404
    if "enabled" in data:
        enabled = 1 if data["enabled"] else 0
        db.execute("UPDATE automations SET enabled=?,updated_at=? WHERE id=?", (enabled, now_str(), item_id))
    if "name" in data or "instruction" in data:
        db.execute("UPDATE automations SET name=?,instruction=?,updated_at=? WHERE id=?", (str(data.get("name", row["name"]))[:120], str(data.get("instruction", row["instruction"]))[:2000], now_str(), item_id))
    if "schedule_type" in data or "schedule_value" in data or "timezone" in data:
        try:
            kind = data.get("schedule_type", row["schedule_type"])
            timezone = data.get("timezone", row["timezone"])
            schedule_data = {"schedule_value": data.get("schedule_value", json.loads(row["schedule_value"]))}
            value, next_run = _validate_schedule(kind, schedule_data, timezone)
        except (ValueError, TypeError, KeyError):
            return jsonify(error="Invalid schedule. Check its time, date, and timezone."), 400
        db.execute("UPDATE automations SET schedule_type=?,schedule_value=?,timezone=?,next_run_at=?,updated_at=? WHERE id=?", (kind, json.dumps(value), timezone, next_run, now_str(), item_id))
    db.commit()
    return jsonify(ok=True)


@bp.delete("/api/automations/<int:item_id>")
def delete_automation(item_id):
    db = get_db()
    cursor = db.execute("DELETE FROM automations WHERE id=?", (item_id,))
    if not cursor.rowcount:
        return jsonify(error="Automation not found."), 404
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/automations/<int:item_id>/run")
def run_automation(item_id):
    db = get_db()
    row = db.execute("SELECT * FROM automations WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify(error="Automation not found."), 404
    item = dict(row)
    try:
        result = _execute(db, item, "manual")
        db.commit()
        return jsonify(ok=True, result=result)
    except Exception as error:
        now = now_str()
        db.execute("INSERT INTO automation_runs(automation_id,automation_name,trigger_type,status,error,started_at,finished_at) VALUES(?,?,?,?,?,?,?)", (item_id, item["name"], "manual", "failed", str(error)[:2000], now, now))
        db.commit()
        return jsonify(error=str(error)), 400
