"""Task and project workspace pages and APIs."""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..helpers import now_str

bp = Blueprint("tasks_projects", __name__)


@bp.get("/tasks")
def tasks_page():
    rows = get_db().execute("SELECT * FROM tasks ORDER BY status, due_date, id DESC").fetchall()
    return render_template("workspace_list.html", page="tasks", page_title="Tasks", items=rows)


@bp.get("/projects")
def projects_page():
    rows = get_db().execute("SELECT * FROM projects ORDER BY status, updated_at DESC").fetchall()
    return render_template("workspace_list.html", page="projects", page_title="Projects", items=rows)


@bp.get("/api/tasks")
def list_tasks():
    db = get_db()
    query, params = "SELECT * FROM tasks", []
    status = request.args.get("status")
    if status in ("pending", "completed"):
        query += " WHERE status=?"; params.append(status)
    query += " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, due_date, due_time, id DESC"
    return jsonify(tasks=[dict(row) for row in db.execute(query, params).fetchall()])


def _task_payload(data, current=None):
    current = dict(current or {})
    title = str(data.get("title", current.get("title", ""))).strip()
    if not title or len(title) > 240:
        raise ValueError("Task title is required and must be at most 240 characters.")
    due_date = data.get("due_date", current.get("due_date")) or None
    if due_date:
        datetime.strptime(due_date, "%Y-%m-%d")
    due_time = data.get("due_time", current.get("due_time")) or None
    if due_time:
        datetime.strptime(due_time, "%H:%M")
    priority = data.get("priority", current.get("priority", "normal"))
    if priority not in ("low", "normal", "high"):
        raise ValueError("Choose a valid priority.")
    category = str(data.get("category", current.get("category", "general"))).strip() or "general"
    notes = str(data.get("notes", current.get("notes", ""))).strip()
    project_id = data.get("project_id", current.get("project_id")) or None
    return title, notes, priority, category, due_date, due_time, project_id


@bp.post("/api/tasks")
def create_task():
    db = get_db(); data = request.get_json(silent=True) or {}
    try:
        title, notes, priority, category, due_date, due_time, project_id = _task_payload(data)
    except (ValueError, TypeError):
        return jsonify(error="Invalid task details."), 400
    if project_id and not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        return jsonify(error="Project not found."), 404
    cur = db.execute("INSERT INTO tasks(title,notes,priority,category,due_date,due_time,project_id,created_at) VALUES(?,?,?,?,?,?,?,?)", (title, notes, priority, category, due_date, due_time, project_id, now_str()))
    db.commit()
    return jsonify(task=dict(db.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone())), 201


@bp.patch("/api/tasks/<int:item_id>")
def update_task(item_id):
    db = get_db(); row = db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone()
    if row is None: return jsonify(error="Task not found."), 404
    data = request.get_json(silent=True) or {}
    if "status" in data and data["status"] not in ("pending", "completed"): return jsonify(error="Invalid status."), 400
    try: fields = _task_payload(data, row)
    except (ValueError, TypeError): return jsonify(error="Invalid task details."), 400
    title, notes, priority, category, due_date, due_time, project_id = fields
    status = data.get("status", row["status"])
    completed_at = now_str() if status == "completed" else None
    db.execute("UPDATE tasks SET title=?,notes=?,priority=?,category=?,due_date=?,due_time=?,project_id=?,status=?,completed_at=? WHERE id=?", (*fields, status, completed_at, item_id)); db.commit()
    return jsonify(task=dict(db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone()))


@bp.delete("/api/tasks/<int:item_id>")
def delete_task(item_id):
    db=get_db(); cur=db.execute("DELETE FROM tasks WHERE id=?", (item_id,)); db.commit()
    return (jsonify(ok=True), 200) if cur.rowcount else (jsonify(error="Task not found."), 404)


@bp.get("/api/projects")
def list_projects():
    return jsonify(projects=[dict(row) for row in get_db().execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()])


@bp.post("/api/projects")
def create_project():
    db=get_db(); data=request.get_json(silent=True) or {}; name=str(data.get("name", "")).strip()
    if not name or len(name)>160: return jsonify(error="Project name is required and must be at most 160 characters."),400
    deadline=data.get("deadline") or None
    try:
        if deadline: datetime.strptime(deadline,"%Y-%m-%d")
        cur=db.execute("INSERT INTO projects(name,description,notes,deadline,created_at,updated_at) VALUES(?,?,?,?,?,?)",(name,str(data.get("description", ""))[:2000],str(data.get("notes", ""))[:5000],deadline,now_str(),now_str()))
    except ValueError: return jsonify(error="Invalid project deadline."),400
    except Exception: return jsonify(error="A project with that name already exists."),409
    db.commit(); return jsonify(project=dict(db.execute("SELECT * FROM projects WHERE id=?",(cur.lastrowid,)).fetchone())),201


@bp.get("/api/projects/<int:item_id>")
def get_project(item_id):
    db=get_db(); row=db.execute("SELECT * FROM projects WHERE id=?",(item_id,)).fetchone()
    if not row:return jsonify(error="Project not found."),404
    item=dict(row); item["tasks"]=[dict(r) for r in db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY id DESC",(item_id,)).fetchall()]
    item["documents"]=[dict(r) for r in db.execute("SELECT d.id,d.title FROM project_documents p JOIN documents d ON d.id=p.document_id WHERE p.project_id=?",(item_id,)).fetchall()]
    item["conversations"]=[dict(r) for r in db.execute("SELECT c.id,c.title FROM project_conversations p JOIN conversations c ON c.id=p.conversation_id WHERE p.project_id=?",(item_id,)).fetchall()]
    return jsonify(project=item)


@bp.patch("/api/projects/<int:item_id>")
def update_project(item_id):
    db=get_db(); row=db.execute("SELECT * FROM projects WHERE id=?",(item_id,)).fetchone()
    if not row:return jsonify(error="Project not found."),404
    data=request.get_json(silent=True) or {}; allowed={"name","description","notes","status","deadline"}
    if not data or set(data)-allowed:return jsonify(error="Invalid project fields."),400
    values={key:data.get(key, row[key]) for key in allowed}
    if not str(values["name"]).strip() or values["status"] not in ("active","archived"):return jsonify(error="Invalid project details."),400
    try:
        if values["deadline"]:datetime.strptime(values["deadline"],"%Y-%m-%d")
        db.execute("UPDATE projects SET name=?,description=?,notes=?,status=?,deadline=?,updated_at=? WHERE id=?",(str(values["name"]).strip(),str(values["description"]),str(values["notes"]),values["status"],values["deadline"] or None,now_str(),item_id)); db.commit()
    except Exception:return jsonify(error="Invalid project details or duplicate name."),400
    return jsonify(project=dict(db.execute("SELECT * FROM projects WHERE id=?",(item_id,)).fetchone()))


@bp.delete("/api/projects/<int:item_id>")
def delete_project(item_id):
    db=get_db(); cur=db.execute("DELETE FROM projects WHERE id=?",(item_id,)); db.commit()
    return (jsonify(ok=True),200) if cur.rowcount else (jsonify(error="Project not found."),404)


@bp.post("/api/projects/<int:item_id>/links")
def link_project(item_id):
    db=get_db(); data=request.get_json(silent=True) or {}; kind=data.get("type"); linked_id=data.get("id")
    tables={"document":("project_documents","document_id","documents"),"conversation":("project_conversations","conversation_id","conversations")}
    if kind not in tables or not isinstance(linked_id,int):return jsonify(error="Invalid project link."),400
    table,column,target=tables[kind]
    if not db.execute("SELECT 1 FROM projects WHERE id=?",(item_id,)).fetchone():return jsonify(error="Project not found."),404
    if not db.execute(f"SELECT 1 FROM {target} WHERE id=?",(linked_id,)).fetchone():return jsonify(error="Linked item not found."),404
    db.execute(f"INSERT OR IGNORE INTO {table}(project_id,{column},created_at) VALUES(?,?,?)",(item_id,linked_id,now_str())); db.commit(); return jsonify(ok=True)


@bp.delete("/api/projects/<int:item_id>/links/<kind>/<int:linked_id>")
def unlink_project(item_id,kind,linked_id):
    tables={"document":("project_documents","document_id"),"conversation":("project_conversations","conversation_id")}
    if kind not in tables:return jsonify(error="Invalid project link."),400
    table,column=tables[kind]; db=get_db(); db.execute(f"DELETE FROM {table} WHERE project_id=? AND {column}=?",(item_id,linked_id)); db.commit(); return jsonify(ok=True)
