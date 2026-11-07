"""Memory: user-curated facts injected into the local AI context."""

from flask import Blueprint, jsonify, render_template, request

from ..constants import MEMORY_CATEGORIES
from ..db import get_db
from ..helpers import now_str

bp = Blueprint("memory", __name__)

MAX_MEMORY_LENGTH = 2000


def _serialize(row):
    return dict(row) if row is not None else None


@bp.get("/memory")
def index():
    db = get_db()
    memories = db.execute(
        """
        SELECT * FROM memories
        ORDER BY active DESC, updated_at DESC, id DESC
        """
    ).fetchall()
    counts = {
        "total": len(memories),
        "active": sum(1 for memory in memories if memory["active"]),
    }
    return render_template(
        "memory.html",
        page="memory",
        page_title="Memory",
        memories=memories,
        counts=counts,
        categories=MEMORY_CATEGORIES,
    )


@bp.get("/api/memories")
def api_list():
    rows = get_db().execute("SELECT * FROM memories ORDER BY id DESC").fetchall()
    return jsonify(memories=[dict(row) for row in rows])


@bp.post("/api/memories")
def api_create():
    data = request.get_json(silent=True) or request.form
    content = (data.get("content") or "").strip()
    category = (data.get("category") or "general").strip()

    if not content:
        return jsonify(error="Memory content is required."), 400
    if len(content) > MAX_MEMORY_LENGTH:
        return jsonify(error="Memory content is too long."), 400
    if category not in MEMORY_CATEGORIES:
        return jsonify(error="Invalid memory category."), 400

    timestamp = now_str()
    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO memories (content, category, active, created_at, updated_at)
        VALUES (?, ?, 1, ?, ?)
        """,
        (content, category, timestamp, timestamp),
    )
    db.commit()
    row = db.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(memory=_serialize(row)), 201


@bp.patch("/api/memories/<int:memory_id>")
def api_update(memory_id):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        return jsonify(error="Memory not found."), 404

    fields = []
    params = []

    if "content" in data:
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify(error="Memory content cannot be empty."), 400
        if len(content) > MAX_MEMORY_LENGTH:
            return jsonify(error="Memory content is too long."), 400
        fields.append("content = ?")
        params.append(content)

    if "category" in data:
        category = (data.get("category") or "").strip()
        if category not in MEMORY_CATEGORIES:
            return jsonify(error="Invalid memory category."), 400
        fields.append("category = ?")
        params.append(category)

    if "active" in data:
        fields.append("active = ?")
        params.append(1 if data.get("active") else 0)

    if not fields:
        return jsonify(error="Nothing to update."), 400

    fields.append("updated_at = ?")
    params.append(now_str())
    params.append(memory_id)
    db.execute(f"UPDATE memories SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()
    updated = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return jsonify(memory=_serialize(updated))


@bp.delete("/api/memories/<int:memory_id>")
def api_delete(memory_id):
    db = get_db()
    row = db.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row is None:
        return jsonify(error="Memory not found."), 404
    db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    db.commit()
    return jsonify(ok=True)
