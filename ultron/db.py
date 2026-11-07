"""SQLite connection handling and schema setup."""

import sqlite3

from flask import current_app, g

from .constants import DEFAULT_SETTINGS


def get_db():
    """Return a request-scoped SQLite connection."""
    if "db" not in g:
        connection = sqlite3.connect(
            current_app.config["DATABASE"],
            timeout=15,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        g.db = connection
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    """Create tables and default settings when missing. Safe to run on every boot."""
    db = get_db()
    with current_app.open_resource("schema.sql") as schema_file:
        db.executescript(schema_file.read().decode("utf-8"))

    migrations = {
        "documents": {
            "folder_id": "INTEGER REFERENCES document_folders(id) ON DELETE SET NULL",
            "format": "TEXT NOT NULL DEFAULT 'markdown'",
        },
        "events": {"category": "TEXT NOT NULL DEFAULT 'general'"},
        "tasks": {"category": "TEXT NOT NULL DEFAULT 'general'"},
    }
    for table, columns in migrations.items():
        existing = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column, definition in columns.items():
            if column not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_folder "
        "ON documents (folder_id, updated_at DESC)"
    )

    for key, value in DEFAULT_SETTINGS.items():
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
            (key, value),
        )
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
