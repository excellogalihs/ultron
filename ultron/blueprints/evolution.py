"""Experience Library, learning history, and local memory review APIs."""

import json

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..helpers import now_str
from ..services.learning import CATEGORIES, retrieve_experiences

bp = Blueprint("evolution", __name__)


@bp.get("/evolution")
def index():
    db = get_db()
    stats = {
        "experiences": db.execute("SELECT COUNT(*) FROM experiences WHERE archived=0").fetchone()[0],
        "reuses": db.execute("SELECT COALESCE(SUM(successful_uses),0) FROM experiences WHERE archived=0").fetchone()[0],
        "memories": db.execute("SELECT COUNT(*) FROM memories WHERE active=1").fetchone()[0],
        "automations": db.execute("SELECT COUNT(*) FROM automations WHERE enabled=1").fetchone()[0],
    }
    experiences = db.execute("SELECT * FROM experiences ORDER BY last_used_at DESC, id DESC LIMIT 100").fetchall()
    history = db.execute("SELECT * FROM learning_history ORDER BY id DESC LIMIT 20").fetchall()
    return render_template("evolution.html", page="evolution", page_title="Evolution", stats=stats, experiences=experiences, history=history, categories=CATEGORIES)


@bp.get("/api/experiences")
def list_experiences():
    db = get_db()
    query = request.args.get("q", "")
    if query:
        rows = retrieve_experiences(db, query, 20)
    else:
        rows = [dict(row) for row in db.execute("SELECT * FROM experiences ORDER BY id DESC LIMIT 100").fetchall()]
        for row in rows:
            row["execution_steps"] = json.loads(row["execution_steps"] or "[]")
            row["tools_used"] = json.loads(row["tools_used"] or "[]")
    return jsonify(experiences=rows)


@bp.post("/api/experiences")
def create_experience():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    category = (data.get("category") or "general productivity").strip()
    request_text = (data.get("original_request") or "").strip()
    if not title or not request_text:
        return jsonify(error="Title and original request are required."), 400
    if category not in CATEGORIES:
        return jsonify(error="Invalid category."), 400
    now = now_str()
    cursor = get_db().execute(
        """INSERT INTO experiences(title,category,original_request,task_description,execution_steps,tools_used,successful_methods,parameters,confidence,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (title[:160], category, request_text[:2000], (data.get("task_description") or "")[:2000], json.dumps(data.get("execution_steps") or []), json.dumps(data.get("tools_used") or []), (data.get("successful_methods") or "")[:4000], json.dumps(data.get("parameters") or {}), 0.5, now, now),
    )
    db = get_db()
    db.execute("INSERT INTO learning_history(record_type,title,details,created_at) VALUES('experience_created',?,?,?)", (title[:160], "Manually added experience", now))
    db.commit()
    return jsonify(id=cursor.lastrowid), 201


@bp.patch("/api/experiences/<int:item_id>")
def update_experience(item_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT id FROM experiences WHERE id=?", (item_id,)).fetchone()
    if not row:
        return jsonify(error="Experience not found."), 404
    fields, values = [], []
    allowed = {"title": ("title", 160), "category": ("category", 80), "original_request": ("original_request", 2000), "task_description": ("task_description", 2000), "successful_methods": ("successful_methods", 4000), "mistakes_solutions": ("mistakes_solutions", 4000)}
    for key, (column, maximum) in allowed.items():
        if key in data:
            value = str(data[key]).strip()
            if key == "category" and value not in CATEGORIES:
                return jsonify(error="Invalid category."), 400
            fields.append(f"{column}=?")
            values.append(value[:maximum])
    if "archived" in data:
        fields.append("archived=?")
        values.append(1 if data["archived"] else 0)
    if not fields:
        return jsonify(error="No supported fields supplied."), 400
    fields.append("updated_at=?")
    values.extend([now_str(), item_id])
    db.execute(f"UPDATE experiences SET {','.join(fields)} WHERE id=?", values)
    db.execute("INSERT INTO learning_history(record_type,title,details,created_at) SELECT 'experience_updated',title,'Experience edited',? FROM experiences WHERE id=?", (now_str(), item_id))
    db.commit()
    return jsonify(ok=True)


@bp.delete("/api/experiences/<int:item_id>")
def delete_experience(item_id):
    db = get_db()
    cursor = db.execute("DELETE FROM experiences WHERE id=?", (item_id,))
    if not cursor.rowcount:
        return jsonify(error="Experience not found."), 404
    db.commit()
    return jsonify(ok=True)
