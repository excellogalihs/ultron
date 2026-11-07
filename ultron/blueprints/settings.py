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
    APP_VERSION,
    DEFAULT_MODEL,
    DEFAULT_SETTINGS,
    SUPPORTED_MODELS,
)
from ..db import get_db
from ..helpers import clear_settings_cache, get_settings, now_str
from ..services import ollama

bp = Blueprint("settings", __name__)

TABLES = (
    "conversations",
    "messages",
    "document_folders",
    "documents",
    "events",
    "tasks",
    "memories",
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
        errors.append("Display name must be under 80 characters.")

    model = (form.get("default_model") or DEFAULT_MODEL).strip()
    if not ollama.valid_model_name(model):
        errors.append("Choose a valid locally installed model.")

    ollama_url = (form.get("ollama_url") or DEFAULT_SETTINGS["ollama_url"]).strip().rstrip("/")
    parsed_url = urlparse(ollama_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        errors.append("Ollama URL must be a valid http:// or https:// address.")

    try:
        temperature = float(form.get("temperature", "0.7"))
        if temperature < 0 or temperature > 2:
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Temperature must be a number between 0 and 2.")
        temperature = 0.7

    system_prompt = (form.get("system_prompt") or "").strip()
    if len(system_prompt) > 4000:
        errors.append("System prompt must be under 4000 characters.")

    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("settings.index"))

    db = get_db()
    _upsert(db, "operator_name", operator_name)
    _upsert(db, "default_model", model)
    _upsert(db, "ollama_url", ollama_url)
    _upsert(db, "temperature", temperature)
    _upsert(db, "system_prompt", system_prompt)
    _upsert(db, "use_memory", "1" if form.get("use_memory") == "1" else "0")
    db.commit()
    clear_settings_cache()

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
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()
        payload["data"][table] = [dict(row) for row in rows]

    body = json.dumps(payload, indent=2, ensure_ascii=False)
    filename = f"ultron-backup-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    response = Response(body, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
