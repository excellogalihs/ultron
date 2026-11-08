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
            "file_type": "TEXT NOT NULL DEFAULT ''",
        },
        "messages": {"document_id": "INTEGER REFERENCES documents(id) ON DELETE SET NULL"},
        "events": {"category": "TEXT NOT NULL DEFAULT 'general'"},
        "tasks": {
            "category": "TEXT NOT NULL DEFAULT 'general'",
            "due_time": "TEXT",
            "project_id": "INTEGER REFERENCES projects(id) ON DELETE SET NULL",
        },
        "memories": {"approved": "INTEGER NOT NULL DEFAULT 1"},
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
    db.execute("DELETE FROM settings WHERE key IN ('voice_enabled', 'voice_auto_speak')")
    _setup_workspace_fts(db)
    db.commit()


def _setup_workspace_fts(db):
    """Install an optional FTS5 index and triggers; LIKE search remains fallback."""
    fts_exists = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_fts'").fetchone())
    version_row = db.execute("SELECT value FROM settings WHERE key='workspace_fts_version'").fetchone()
    rebuild = not fts_exists or not version_row or version_row["value"] != "3"
    try:
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS workspace_fts USING fts5("
            "source UNINDEXED, item_id UNINDEXED, title, content, tokenize='unicode61 remove_diacritics 2')"
        )
    except sqlite3.OperationalError:
        return

    trigger_names = [
        *(f"fts_{table}_{action}" for table in ("document_folders", "documents", "tasks", "events", "memories", "projects") for action in ("insert", "delete", "update")),
        *(f"fts_knowledge_files_{action}" for action in ("insert", "delete", "update")),
        "fts_messages_insert", "fts_messages_delete", "fts_messages_update", "fts_conversations_title",
    ]
    for trigger in trigger_names:
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    db.execute("DELETE FROM workspace_fts WHERE source='knowledge'")
    if rebuild and fts_exists:
        db.execute("DELETE FROM workspace_fts")

    sources = {
        "document_folders": ("folder", "id", "name", "name", 1_000_000_000),
        "documents": ("document", "id", "title", "content", 2_000_000_000),
        "tasks": ("task", "id", "title", "notes", 3_000_000_000),
        "events": ("event", "id", "title", "description", 4_000_000_000),
        "memories": ("memory", "id", "category", "content", 5_000_000_000),
        "projects": ("project", "id", "name", "description || ' ' || notes", 7_000_000_000),
    }
    for table, (source, id_column, title_expr, content_expr, rowid_offset) in sources.items():
        new_title_expr = f"new.{title_expr}"
        new_content_expr = "new.description || ' ' || new.notes" if table == "projects" else f"new.{content_expr}"
        db.executescript(f"""
            CREATE TRIGGER fts_{table}_insert AFTER INSERT ON {table} BEGIN
              INSERT INTO workspace_fts(rowid,source,item_id,title,content)
              VALUES ({rowid_offset} + new.{id_column},'{source}',new.{id_column},{new_title_expr},{new_content_expr});
            END;
            CREATE TRIGGER fts_{table}_delete AFTER DELETE ON {table} BEGIN
              DELETE FROM workspace_fts WHERE rowid={rowid_offset} + old.{id_column};
            END;
            CREATE TRIGGER fts_{table}_update AFTER UPDATE ON {table} BEGIN
              DELETE FROM workspace_fts WHERE rowid={rowid_offset} + old.{id_column};
              INSERT INTO workspace_fts(rowid,source,item_id,title,content)
              VALUES ({rowid_offset} + new.{id_column},'{source}',new.{id_column},{new_title_expr},{new_content_expr});
            END;
        """)

    db.executescript("""
        CREATE TRIGGER fts_messages_insert AFTER INSERT ON messages BEGIN
          INSERT INTO workspace_fts(rowid,source,item_id,title,content)
          SELECT 8000000000 + new.id,'conversation',new.conversation_id,title,new.content
          FROM conversations WHERE id=new.conversation_id;
        END;
        CREATE TRIGGER fts_messages_delete AFTER DELETE ON messages BEGIN
          DELETE FROM workspace_fts WHERE rowid=8000000000 + old.id;
        END;
        CREATE TRIGGER fts_messages_update AFTER UPDATE ON messages BEGIN
          DELETE FROM workspace_fts WHERE rowid=8000000000 + old.id;
          INSERT INTO workspace_fts(rowid,source,item_id,title,content)
          SELECT 8000000000 + new.id,'conversation',new.conversation_id,c.title,new.content
          FROM conversations c WHERE c.id=new.conversation_id;
        END;
        CREATE TRIGGER fts_conversations_title AFTER UPDATE OF title ON conversations BEGIN
          UPDATE workspace_fts SET title=new.title WHERE source='conversation' AND item_id=new.id;
        END;
    """)

    if rebuild:
        # One-time import for databases that predate the FTS index.
        for table, (source, id_column, title_expr, content_expr, rowid_offset) in sources.items():
            db.execute(
                "INSERT INTO workspace_fts(rowid,source,item_id,title,content) "
                f"SELECT {rowid_offset} + {id_column}, ?,{id_column},{title_expr},{content_expr} FROM {table}",
                (source,),
            )
        db.execute(
            "INSERT INTO workspace_fts(rowid,source,item_id,title,content) "
            "SELECT 8000000000 + m.id,'conversation',m.conversation_id,c.title,m.content FROM messages m "
            "JOIN conversations c ON c.id=m.conversation_id"
        )
    db.execute("INSERT INTO settings(key,value) VALUES ('workspace_fts_version','3') ON CONFLICT(key) DO UPDATE SET value=excluded.value")


def init_app(app):
    app.teardown_appcontext(close_db)
