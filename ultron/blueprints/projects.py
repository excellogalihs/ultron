"""Projects and their workspace links."""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..helpers import now_str

bp = Blueprint("projects", __name__)


def _project(db, project_id):
    row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["tasks"] = [dict(item) for item in db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY status,due_date,id", (project_id,))]
    result["documents"] = [dict(item) for item in db.execute("SELECT d.id,d.title,d.file_type FROM project_documents p JOIN documents d ON d.id=p.document_id WHERE p.project_id=? ORDER BY d.updated_at DESC", (project_id,))]
    result["knowledge_files"] = [dict(item) for item in db.execute("SELECT k.id,k.title,k.filename FROM project_knowledge_files p JOIN knowledge_files k ON k.id=p.knowledge_file_id WHERE p.project_id=? ORDER BY k.imported_at DESC", (project_id,))]
    result["conversations"] = [dict(item) for item in db.execute("SELECT c.id,c.title,c.updated_at FROM project_conversations p JOIN conversations c ON c.id=p.conversation_id WHERE p.project_id=? ORDER BY c.updated_at DESC", (project_id,))]
    total = len(result["tasks"])
    result["progress"] = round(100 * sum(t["status"] == "completed" for t in result["tasks"]) / total) if total else 0
    return result


@bp.get("/projects")
def index():
    db = get_db()
    rows = db.execute("SELECT p.*,COUNT(t.id) AS task_count,SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) AS completed_count FROM projects p LEFT JOIN tasks t ON t.project_id=p.id GROUP BY p.id ORDER BY CASE p.status WHEN 'active' THEN 0 ELSE 1 END,p.updated_at DESC").fetchall()
    selected_id = request.args.get("project", type=int)
    selected = _project(db, selected_id) if selected_id else None
    return render_template("projects.html", page="projects", page_title="Projects", projects=rows, selected=selected,
                           available_documents=db.execute("SELECT id,title FROM documents ORDER BY updated_at DESC LIMIT 100").fetchall(),
                           available_knowledge=db.execute("SELECT id,title FROM knowledge_files ORDER BY imported_at DESC LIMIT 100").fetchall(),
                           available_conversations=db.execute("SELECT id,title FROM conversations ORDER BY updated_at DESC LIMIT 100").fetchall())


@bp.get("/api/projects")
def api_list():
    db = get_db()
    rows = db.execute("SELECT p.*,COUNT(t.id) AS task_count,SUM(CASE WHEN t.status='completed' THEN 1 ELSE 0 END) AS completed_count FROM projects p LEFT JOIN tasks t ON t.project_id=p.id GROUP BY p.id ORDER BY p.updated_at DESC").fetchall()
    return jsonify(projects=[dict(row) for row in rows])


@bp.post("/api/projects")
def api_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    notes = (data.get("notes") or "").strip()
    deadline = data.get("deadline") or None
    if not name or len(name) > 120:
        return jsonify(error="Project name must be 1 to 120 characters."), 400
    if len(description) > 3000 or len(notes) > 20000:
        return jsonify(error="Project description or notes are too long."), 400
    if deadline:
        try:
            deadline = datetime.strptime(deadline, "%Y-%m-%d").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return jsonify(error="Deadline must use YYYY-MM-DD."), 400
    timestamp = now_str()
    db = get_db()
    try:
        cursor = db.execute("INSERT INTO projects(name,description,notes,deadline,created_at,updated_at) VALUES (?,?,?,?,?,?)", (name,description,notes,deadline,timestamp,timestamp))
        db.commit()
    except Exception:
        return jsonify(error="A project with that name already exists."), 409
    return jsonify(project=_project(db, cursor.lastrowid)), 201


@bp.get("/api/projects/<int:project_id>")
def api_get(project_id):
    result = _project(get_db(), project_id)
    return (jsonify(project=result), 200) if result else (jsonify(error="Project not found."), 404)


@bp.patch("/api/projects/<int:project_id>")
def api_update(project_id):
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        return jsonify(error="Project not found."), 404
    data = request.get_json(silent=True) or {}
    allowed = {"name", "description", "notes", "deadline", "status"}
    if not set(data).issubset(allowed) or not data:
        return jsonify(error="Provide valid project fields to update."), 400
    values = {}
    for key in ("name", "description", "notes"):
        if key in data:
            values[key] = (data[key] or "").strip()
    if "name" in values and (not values["name"] or len(values["name"]) > 120):
        return jsonify(error="Project name must be 1 to 120 characters."), 400
    if "deadline" in data:
        try:
            values["deadline"] = datetime.strptime(data["deadline"], "%Y-%m-%d").strftime("%Y-%m-%d") if data["deadline"] else None
        except (TypeError, ValueError):
            return jsonify(error="Deadline must use YYYY-MM-DD."), 400
    if "status" in data:
        if data["status"] not in ("active", "archived"):
            return jsonify(error="Status must be active or archived."), 400
        values["status"] = data["status"]
    values["updated_at"] = now_str()
    try:
        db.execute("UPDATE projects SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?", [*values.values(), project_id])
        db.commit()
    except Exception:
        return jsonify(error="A project with that name already exists."), 409
    return jsonify(project=_project(db, project_id))


@bp.delete("/api/projects/<int:project_id>")
def api_delete(project_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        return jsonify(error="Project not found."), 404
    db.execute("DELETE FROM projects WHERE id=?", (project_id,))
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/projects/<int:project_id>/links")
def api_link(project_id):
    data = request.get_json(silent=True) or {}
    link_type, item_id = data.get("type"), data.get("id")
    configs = {
        "document": ("documents", "project_documents", "document_id"),
        "conversation": ("conversations", "project_conversations", "conversation_id"),
        "knowledge": ("knowledge_files", "project_knowledge_files", "knowledge_file_id"),
    }
    if link_type not in configs or not isinstance(item_id, int):
        return jsonify(error="Choose a valid related item."), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        return jsonify(error="Project not found."), 404
    target, relation, key = configs[link_type]
    if not db.execute(f"SELECT 1 FROM {target} WHERE id=?", (item_id,)).fetchone():
        return jsonify(error="Related item not found."), 404
    db.execute(f"INSERT OR IGNORE INTO {relation}(project_id,{key},created_at) VALUES (?,?,?)", (project_id,item_id,now_str()))
    db.commit()
    return jsonify(project=_project(db, project_id))


@bp.delete("/api/projects/<int:project_id>/links")
def api_unlink(project_id):
    data = request.get_json(silent=True) or {}
    configs = {"document": ("project_documents", "document_id"), "conversation": ("project_conversations", "conversation_id"), "knowledge": ("project_knowledge_files", "knowledge_file_id")}
    if data.get("type") not in configs or not isinstance(data.get("id"), int):
        return jsonify(error="Choose a valid related item."), 400
    relation, key = configs[data["type"]]
    db = get_db()
    db.execute(f"DELETE FROM {relation} WHERE project_id=? AND {key}=?", (project_id,data["id"]))
    db.commit()
    return jsonify(ok=True)
