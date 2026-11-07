"""Local, keyword-indexed knowledge base imports."""

import hashlib
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from ..db import get_db
from ..helpers import now_str
from ..services.document_files import read_knowledge_file

bp = Blueprint("knowledge", __name__)
ALLOWED = {".pdf", ".txt", ".md", ".markdown", ".docx"}
MAX_TEXT_LENGTH = 3_000_000


@bp.get("/knowledge")
def index():
    db = get_db()
    files = db.execute("SELECT k.*,c.name AS collection_name FROM knowledge_files k LEFT JOIN knowledge_collections c ON c.id=k.collection_id ORDER BY k.imported_at DESC").fetchall()
    collections = db.execute("SELECT * FROM knowledge_collections ORDER BY name COLLATE NOCASE").fetchall()
    selected_id = request.args.get("file", type=int)
    selected = db.execute("SELECT * FROM knowledge_files WHERE id=?", (selected_id,)).fetchone() if selected_id else None
    return render_template("knowledge.html", page="knowledge", page_title="Knowledge Base",
                           files=files, collections=collections, selected=selected)


@bp.get("/api/knowledge")
def api_list():
    rows = get_db().execute("SELECT id,collection_id,filename,title,file_type,status,imported_at,updated_at,length(content) AS character_count FROM knowledge_files ORDER BY imported_at DESC").fetchall()
    return jsonify(files=[dict(row) for row in rows])


@bp.post("/api/knowledge/collections")
def api_create_collection():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()[:80]
    if not name:
        return jsonify(error="Collection name is required."), 400
    db = get_db()
    try:
        cursor = db.execute("INSERT INTO knowledge_collections(name,created_at) VALUES (?,?)", (name, now_str()))
        db.commit()
    except Exception:
        db.rollback()
        return jsonify(error="A collection with that name already exists."), 409
    return jsonify(collection={"id": cursor.lastrowid, "name": name}), 201


@bp.delete("/api/knowledge/collections/<int:collection_id>")
def api_delete_collection(collection_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM knowledge_collections WHERE id=?", (collection_id,)).fetchone():
        return jsonify(error="Collection not found."), 404
    db.execute("DELETE FROM knowledge_collections WHERE id=?", (collection_id,))
    db.commit()
    return jsonify(ok=True)


@bp.post("/api/knowledge/import")
def api_import():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify(error="Choose a file to import."), 400
    filename = Path(uploaded.filename).name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED:
        return jsonify(error="Import a PDF, TXT, Markdown, or DOCX file."), 400
    payload = uploaded.read()
    if not payload or len(payload) > 15 * 1024 * 1024:
        return jsonify(error="File must be non-empty and under 15 MB."), 400
    digest = hashlib.sha256(payload).hexdigest()
    db = get_db()
    existing = db.execute("SELECT id,title FROM knowledge_files WHERE content_hash=?", (digest,)).fetchone()
    if existing:
        return jsonify(error="This file is already imported.", duplicate=True, file=dict(existing)), 409
    collection = request.form.get("collection_id") or None
    if collection:
        try:
            collection = int(collection)
        except ValueError:
            return jsonify(error="Choose a valid collection."), 400
        if not db.execute("SELECT 1 FROM knowledge_collections WHERE id=?", (collection,)).fetchone():
            return jsonify(error="Collection not found."), 404
    try:
        content = read_knowledge_file(filename, payload)
    except ValueError as error:
        timestamp = now_str()
        db.execute(
            "INSERT OR IGNORE INTO knowledge_files(collection_id,filename,title,file_type,content,content_hash,status,imported_at,updated_at) VALUES (?,?,?,?,?,?, 'error',?,?)",
            (collection, filename, Path(filename).stem, extension.lstrip("."), "", digest, timestamp, timestamp),
        )
        db.commit()
        return jsonify(error=str(error)), 400
    content = content.strip()
    if not content:
        timestamp = now_str()
        db.execute(
            "INSERT OR IGNORE INTO knowledge_files(collection_id,filename,title,file_type,content,content_hash,status,imported_at,updated_at) VALUES (?,?,?,?,?,?, 'error',?,?)",
            (collection, filename, Path(filename).stem, extension.lstrip("."), "", digest, timestamp, timestamp),
        )
        db.commit()
        return jsonify(error="No readable text was extracted from this file."), 400
    if len(content) > MAX_TEXT_LENGTH:
        return jsonify(error="Extracted text is over the 3 million character limit."), 400
    timestamp = now_str()
    cursor = db.execute(
        "INSERT INTO knowledge_files(collection_id,filename,title,file_type,content,content_hash,status,imported_at,updated_at) VALUES (?,?,?,?,?,?,'indexed',?,?)",
        (collection, filename, Path(filename).stem, extension.lstrip("."), content, digest, timestamp, timestamp),
    )
    db.commit()
    row = db.execute("SELECT id,collection_id,filename,title,file_type,status,imported_at,updated_at FROM knowledge_files WHERE id=?", (cursor.lastrowid,)).fetchone()
    return jsonify(file=dict(row)), 201


@bp.get("/api/knowledge/<int:file_id>")
def api_get(file_id):
    row = get_db().execute("SELECT * FROM knowledge_files WHERE id=?", (file_id,)).fetchone()
    if not row:
        return jsonify(error="Knowledge file not found."), 404
    return jsonify(file=dict(row))


@bp.patch("/api/knowledge/<int:file_id>")
def api_update(file_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM knowledge_files WHERE id=?", (file_id,)).fetchone():
        return jsonify(error="Knowledge file not found."), 404
    data = request.get_json(silent=True) or {}
    if not data or not set(data).issubset({"title", "collection_id"}):
        return jsonify(error="Provide a title or collection."), 400
    fields, values = [], []
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title or len(title) > 200:
            return jsonify(error="Title must be 1 to 200 characters."), 400
        fields.append("title=?"); values.append(title)
    if "collection_id" in data:
        collection = data["collection_id"] or None
        if collection is not None and (not isinstance(collection, int) or not db.execute("SELECT 1 FROM knowledge_collections WHERE id=?", (collection,)).fetchone()):
            return jsonify(error="Choose a valid collection."), 400
        fields.append("collection_id=?"); values.append(collection)
    fields.append("updated_at=?"); values.append(now_str()); values.append(file_id)
    db.execute(f"UPDATE knowledge_files SET {','.join(fields)} WHERE id=?", values)
    db.commit()
    row = db.execute("SELECT id,collection_id,filename,title,file_type,status,imported_at,updated_at FROM knowledge_files WHERE id=?", (file_id,)).fetchone()
    return jsonify(file=dict(row))


@bp.delete("/api/knowledge/<int:file_id>")
def api_delete(file_id):
    db = get_db()
    if not db.execute("SELECT 1 FROM knowledge_files WHERE id=?", (file_id,)).fetchone():
        return jsonify(error="Knowledge file not found."), 404
    db.execute("DELETE FROM knowledge_files WHERE id=?", (file_id,))
    db.commit()
    return jsonify(ok=True)
