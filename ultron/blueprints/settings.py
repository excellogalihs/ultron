"""Settings, local engine status, and data export."""

import json
import os
from datetime import datetime
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from ..constants import (
    ACCENTS,
    APP_VERSION,
    DEFAULT_MODEL,
    DEFAULT_SETTINGS,
    FONTS,
    SUPPORTED_MODELS,
    THEMES,
)
from ..db import get_db
from ..helpers import clear_settings_cache, get_settings, now_str
from ..services import ollama

bp = Blueprint("settings", __name__)

TABLES = (
    "conversations",
    "document_folders",
    "documents",
    "projects",
    "messages",
    "events",
    "tasks",
    "notifications",
    "memories",
    "knowledge_collections",
    "knowledge_files",
    "project_documents",
    "project_conversations",
    "project_knowledge_files",
)


def _pretty_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _upsert(db, key, value):
    db.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


@bp.get("/settings")
def index():
    db = get_db()
    settings = get_settings()
    counts = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in TABLES
    }
    database_path = current_app.config["DATABASE"]
    try:
        database_size = _pretty_size(os.path.getsize(database_path))
    except OSError:
        database_size = "unknown"

    return render_template(
        "settings.html",
        page="settings",
        page_title="Settings",
        models=ollama.model_options(
            settings.get("ollama_url"),
            current_model=settings.get("default_model", DEFAULT_MODEL),
        ),
        default_model=settings.get("default_model", DEFAULT_MODEL),
        counts=counts,
        database_path=database_path,
        database_size=database_size,
        app_version=APP_VERSION,
    )


@bp.post("/settings")
def save():
    form = request.form
    errors = []

    operator_name = (form.get("operator_name") or "").strip() or DEFAULT_SETTINGS["operator_name"]
    if len(operator_name) > 80:
        operator_name = operator_name[:80]

    model = (form.get("default_model") or DEFAULT_MODEL).strip()
    if not ollama.valid_model_name(model):
        model = DEFAULT_MODEL

    raw_url = (form.get("ollama_url") or DEFAULT_SETTINGS["ollama_url"]).strip().rstrip("/")
    if raw_url and "://" not in raw_url:
        raw_url = f"http://{raw_url}"
    parsed_url = urlparse(raw_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        errors.append("Ollama URL must be a valid http:// or https:// address.")
        ollama_url = DEFAULT_SETTINGS["ollama_url"]
    else:
        ollama_url = raw_url

    try:
        temperature = float(form.get("temperature", "0.7"))
        temperature = max(0.0, min(2.0, temperature))
    except (TypeError, ValueError):
        temperature = 0.7

    system_prompt = (form.get("system_prompt") or "").strip()
    if len(system_prompt) > 4000:
        system_prompt = system_prompt[:4000]

    use_memory = "1" if form.get("use_memory") == "1" else "0"

    theme = form.get("theme") or DEFAULT_SETTINGS["theme"]
    if theme not in THEMES:
        theme = DEFAULT_SETTINGS["theme"]

    accent = form.get("accent") or DEFAULT_SETTINGS["accent"]
    if accent not in ACCENTS:
        accent = DEFAULT_SETTINGS["accent"]

    font = form.get("font") or DEFAULT_SETTINGS["font"]
    if font not in FONTS:
        font = DEFAULT_SETTINGS["font"]

    chat_send_key = form.get("chat_send_key") or DEFAULT_SETTINGS["chat_send_key"]
    if chat_send_key not in ("enter", "ctrl_enter"):
        chat_send_key = DEFAULT_SETTINGS["chat_send_key"]

    web_search_enabled = "1" if form.get("web_search_enabled") == "1" else "0"
    try:
        task_reminder_time = datetime.strptime(
            form.get("task_reminder_time", get_settings().get("task_reminder_time", "09:00")), "%H:%M"
        ).strftime("%H:%M")
    except ValueError:
        task_reminder_time = "09:00"
    try:
        event_reminder_minutes = int(form.get("event_reminder_minutes", get_settings().get("event_reminder_minutes", "10")))
    except (TypeError, ValueError):
        event_reminder_minutes = 10
    if event_reminder_minutes not in (0, 5, 10, 15, 30, 60):
        event_reminder_minutes = 10

    wants_json = request.is_json or "application/json" in request.headers.get("Accept", "")

    if errors:
        if wants_json:
            return jsonify(ok=False, error="; ".join(errors)), 400
        for message in errors:
            flash(message, "error")
        return redirect(url_for("settings.index"))

    db = get_db()
    _upsert(db, "operator_name", operator_name)
    _upsert(db, "default_model", model)
    _upsert(db, "ollama_url", ollama_url)
    _upsert(db, "temperature", temperature)
    _upsert(db, "system_prompt", system_prompt)
    _upsert(db, "use_memory", use_memory)
    _upsert(db, "theme", theme)
    _upsert(db, "accent", accent)
    _upsert(db, "font", font)
    _upsert(db, "chat_send_key", chat_send_key)
    _upsert(db, "web_search_enabled", web_search_enabled)
    _upsert(db, "task_reminder_time", task_reminder_time)
    _upsert(db, "event_reminder_minutes", event_reminder_minutes)
    db.commit()
    clear_settings_cache()

    if wants_json:
        return jsonify(ok=True, message="Settings saved locally.")

    flash("Settings saved locally.", "success")
    return redirect(url_for("settings.index"))


@bp.get("/api/ollama/status")
def ollama_status():
    configured_url = get_settings().get("ollama_url", DEFAULT_SETTINGS["ollama_url"])
    requested_url = (request.args.get("url") or "").strip() or configured_url
    result = ollama.status(requested_url)
    installed = set(result["models"])
    result["supported"] = [
        {**model, "installed": model["id"] in installed} for model in SUPPORTED_MODELS
    ]
    result["options"] = ollama.model_options(
        requested_url,
        current_model=get_settings().get("default_model", DEFAULT_MODEL),
        installed_models=result["models"],
    )
    result["checked_at"] = datetime.now().strftime("%H:%M:%S")
    return jsonify(result)


@bp.get("/settings/export")
def export_data():
    db = get_db()
    payload = {
        "application": "ultron",
        "version": APP_VERSION,
        "exported_at": now_str(),
        "settings": {
            row["key"]: row["value"]
            for row in db.execute("SELECT key, value FROM settings").fetchall()
        },
        "data": {},
    }
    for table in TABLES:
        order = "" if table in ("project_documents", "project_conversations", "project_knowledge_files") else " ORDER BY id ASC"
        rows = db.execute(f"SELECT * FROM {table}{order}").fetchall()
        payload["data"][table] = [dict(row) for row in rows]

    body = json.dumps(payload, indent=2, ensure_ascii=False)
    filename = f"ultron-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    response = Response(body, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.post("/settings/restore")
def restore():
    uploaded = request.files.get("backup_file")
    if not uploaded or not uploaded.filename:
        flash("Please select a JSON backup file to restore.", "error")
        return redirect(url_for("settings.index"))

    try:
        payload = json.loads(uploaded.read().decode("utf-8", "replace"))
    except Exception as error:
        flash(f"Invalid backup file format: {error}", "error")
        return redirect(url_for("settings.index"))

    if payload.get("application") != "ultron" or not isinstance(payload.get("data"), dict):
        flash("File is not a valid Ultron workspace backup archive.", "error")
        return redirect(url_for("settings.index"))

    db = get_db()
    data = payload.get("data", {})
    try:
        # Atomic restore inside a transaction
        # Clear tables in reverse dependency order
        for table in reversed(TABLES):
            db.execute(f"DELETE FROM {table}")

        # Insert records for each table
        for table in TABLES:
            records = data.get(table, [])
            if not records:
                continue
            cols = list(records[0].keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(f'"{c}"' for c in cols)
            for rec in records:
                db.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                    [rec.get(c) for c in cols],
                )

        # Restore settings
        backup_settings = payload.get("settings", {})
        for k, v in backup_settings.items():
            _upsert(db, k, v)

        db.commit()
        clear_settings_cache()
        flash("Workspace data and settings restored successfully from backup.", "success")
    except Exception as error:
        db.rollback()
        flash(f"Restore failed: {error}", "error")

    return redirect(url_for("settings.index"))
