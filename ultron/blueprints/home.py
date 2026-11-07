"""Home dashboard."""

from datetime import date, timedelta

from flask import Blueprint, render_template

from ..constants import DEFAULT_MODEL
from ..db import get_db
from ..helpers import get_settings, now_str

bp = Blueprint("home", __name__)


@bp.get("/")
def index():
    db = get_db()
    settings = get_settings()
    model = settings.get("default_model", DEFAULT_MODEL)

    recent_documents = db.execute(
        "SELECT * FROM documents ORDER BY updated_at DESC, id DESC LIMIT 4"
    ).fetchall()

    today = date.today()
    tomorrow = today + timedelta(days=1)
    today_events = db.execute(
        "SELECT * FROM events WHERE start_at >= ? AND start_at < ? "
        "ORDER BY start_at ASC LIMIT 4",
        (f"{today.isoformat()} 00:00:00", f"{tomorrow.isoformat()} 00:00:00"),
    ).fetchall()

    upcoming_events = db.execute(
        "SELECT * FROM events WHERE start_at >= ? ORDER BY start_at ASC LIMIT 4",
        (f"{tomorrow.isoformat()} 00:00:00",),
    ).fetchall()

    pending_tasks = db.execute(
        """
        SELECT * FROM tasks
        WHERE status = 'pending'
        ORDER BY
            CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
            CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
            due_date ASC,
            id DESC
        LIMIT 5
        """
    ).fetchall()

    recent_conversations = db.execute(
        """
        SELECT c.*,
            (SELECT content FROM messages m
             WHERE m.conversation_id = c.id
             ORDER BY m.id DESC LIMIT 1) AS last_message
        FROM conversations c
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT 4
        """
    ).fetchall()

    stats = {
        "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "pending_tasks": db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'pending'"
        ).fetchone()[0],
        "conversations": db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
        "memories": db.execute(
            "SELECT COUNT(*) FROM memories WHERE active = 1"
        ).fetchone()[0],
    }

    return render_template(
        "home.html",
        page="home",
        page_title="Home",
        model=model,
        today_events=today_events,
        recent_documents=recent_documents,
        upcoming_events=upcoming_events,
        pending_tasks=pending_tasks,
        recent_conversations=recent_conversations,
        stats=stats,
        today_value=now_str()[:10],
    )
