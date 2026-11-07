"""Tasks: local to-do list with priorities and due dates."""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from ..constants import TASK_CATEGORIES, TASK_PRIORITIES
from ..db import get_db
from ..helpers import now_str

bp = Blueprint("tasks", __name__)

VIEWS = ("all", "pending", "completed")


def _due_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as error:
        raise ValueError("Due date must use YYYY-MM-DD.") from error


def _serialize(row):
    return dict(row) if row is not None else None


@bp.get("/tasks")
def index():
    view = request.args.get("view", "all")
    if view not in VIEWS:
        view = "all"

    db = get_db()
    where = ""
    if view == "pending":
        where = "WHERE tasks.status = 'pending'"
    elif view == "completed":
        where = "WHERE tasks.status = 'completed'"

    tasks = db.execute(
        f"""
        SELECT tasks.*,projects.name AS project_name FROM tasks LEFT JOIN projects ON projects.id=tasks.project_id
        {where}
        ORDER BY
            CASE tasks.status WHEN 'pending' THEN 0 ELSE 1 END,
            CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
            CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
            tasks.due_date ASC,
            tasks.id DESC
        """
    ).fetchall()

    counts = {
        "all": db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "pending": db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ).fetchone()[0],
        "completed": db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'completed'"
        ).fetchone()[0],
    }

    return render_template(
        "tasks.html",
        page="tasks",
        page_title="Tasks",
        tasks=tasks,
        view=view,
        counts=counts,
        priorities=TASK_PRIORITIES,
        categories=TASK_CATEGORIES,
        today_value=now_str()[:10],
        projects=db.execute("SELECT id,name,status FROM projects ORDER BY name COLLATE NOCASE").fetchall(),
    )


@bp.get("/api/tasks")
def api_list():
    rows = get_db().execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    return jsonify(tasks=[dict(row) for row in rows])


@bp.get("/api/tasks/<int:task_id>")
def api_get(task_id):
    row = get_db().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return jsonify(error="Task not found."), 404
    return jsonify(task=dict(row))


@bp.post("/api/tasks")
def api_create():
    data = request.get_json(silent=True) or request.form
    title = (data.get("title") or "").strip()
    notes = (data.get("notes") or "").strip()
    priority = (data.get("priority") or "normal").strip()
    category = (data.get("category") or "general").strip()

    if not title:
        return jsonify(error="Task title is required."), 400
    if len(title) > 300:
        return jsonify(error="Task title is too long."), 400
    if len(notes) > 4000:
        return jsonify(error="Task notes are too long."), 400
    if priority not in TASK_PRIORITIES:
        return jsonify(error="Invalid priority."), 400
    if category not in TASK_CATEGORIES:
        return jsonify(error="Invalid task category."), 400
    try:
        due_date = _due_date(data.get("due_date"))
    except ValueError as error:
        return jsonify(error=str(error)), 400

    db = get_db()
    project_id = data.get("project_id")
    if project_id in ("", None):
        project_id = None
    elif not isinstance(project_id, int) or not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        return jsonify(error="Choose a valid project."), 400
    cursor = db.execute(
        """
        INSERT INTO tasks (title, notes, status, priority, category, due_date, project_id, created_at)
        VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
        """,
        (title, notes, priority, category, due_date, project_id, now_str()),
    )
    db.commit()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(task=_serialize(row)), 201


@bp.patch("/api/tasks/<int:task_id>")
def api_update(task_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return jsonify(error="Task not found."), 404

    fields = []
    params = []

    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify(error="Task title cannot be empty."), 400
        if len(title) > 300:
            return jsonify(error="Task title is too long."), 400
        fields.append("title = ?")
        params.append(title)

    if "notes" in data:
        notes = (data.get("notes") or "").strip()
        if len(notes) > 4000:
            return jsonify(error="Task notes are too long."), 400
        fields.append("notes = ?")
        params.append(notes)

    if "priority" in data:
        priority = (data.get("priority") or "").strip()
        if priority not in TASK_PRIORITIES:
            return jsonify(error="Invalid priority."), 400
        fields.append("priority = ?")
        params.append(priority)

    if "category" in data:
        category = (data.get("category") or "").strip()
        if category not in TASK_CATEGORIES:
            return jsonify(error="Invalid task category."), 400
        fields.append("category = ?")
        params.append(category)

    if "due_date" in data:
        try:
            due_date = _due_date(data.get("due_date"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        fields.append("due_date = ?")
        params.append(due_date)

    if "project_id" in data:
        project_id = data.get("project_id") or None
        if project_id is not None and (not isinstance(project_id, int) or not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()):
            return jsonify(error="Choose a valid project."), 400
        fields.append("project_id = ?")
        params.append(project_id)

    if "status" in data:
        status = (data.get("status") or "").strip()
        if status not in ("pending", "completed"):
            return jsonify(error="Invalid task status."), 400
        fields.append("status = ?")
        params.append(status)
        fields.append("completed_at = ?")
        params.append(now_str() if status == "completed" else None)

    if not fields:
        return jsonify(error="Nothing to update."), 400

    params.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()
    updated = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return jsonify(task=_serialize(updated))


@bp.delete("/api/tasks/<int:task_id>")
def api_delete(task_id):
    db = get_db()
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return jsonify(error="Task not found."), 404
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    return jsonify(ok=True)
