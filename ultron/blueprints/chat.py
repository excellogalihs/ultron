"""Chat UI and API, including streaming responses from Ollama."""

import json
import re
import sqlite3
from urllib.parse import quote_plus

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

from ..constants import DEFAULT_MODEL
from ..db import get_db
from ..helpers import get_settings, now_str
from ..services import ollama, web_search
from ..services.workspace_tools import relevant_memories

bp = Blueprint("chat", __name__)

MAX_MESSAGE_LENGTH = 20000
MAX_TITLE_LENGTH = 90


def _explicit_web_search_query(text):
    """Return a query for clear, direct web-search requests."""
    match = re.match(
        r"^.*?\bsearch(?:\s+(?:the\s+web|online|the\s+internet))?"
        r"\s+(?:for\s+)?(.+?)\s*[?.!]*\s*$",
        text or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    query = re.sub(r"^(?:please\s+)?(?:for\s+)?", "", match.group(1).strip(), flags=re.IGNORECASE)
    return query or None


def _format_web_search_result(query, result):
    """Render search results directly so a local model cannot block the search."""
    if result.get("error"):
        if result.get("offline"):
            url = "https://duckduckgo.com/?q=" + quote_plus(query)
            return (
                "Ultron cannot reach the internet from its server. "
                f"[Open this search in your browser]({url})."
            )
        return f"Web search for **{query}** failed: {result['error']}"
    items = result.get("results") or []
    if not items:
        return f"No web results found for **{query}**."
    lines = [f"Web search results for **{query}**:"]
    for item in items:
        title = item.get("title") or item.get("url") or "Untitled result"
        url = item.get("url", "")
        snippet = item.get("snippet", "").strip()
        lines.append(f"- [{title}]({url})" + (f" — {snippet}" if snippet else ""))
    return "\n\n".join(lines)


def _conversation_list(db):
    return db.execute(
        """
        SELECT c.*,
            (SELECT content FROM messages m
             WHERE m.conversation_id = c.id
             ORDER BY m.id DESC LIMIT 1) AS last_message,
            (SELECT COUNT(*) FROM messages m
             WHERE m.conversation_id = c.id) AS message_count
        FROM conversations c
        ORDER BY c.updated_at DESC, c.id DESC
        """
    ).fetchall()


def _get_conversation(db, conversation_id):
    return db.execute(
        "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
    ).fetchone()


def _make_title(text):
    compact = " ".join((text or "").split())
    if len(compact) > MAX_TITLE_LENGTH:
        compact = compact[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return compact or "New conversation"


def _render_page(conversation_id=None):
    db = get_db()
    conversations = _conversation_list(db)
    conversation = None
    messages = []

    if conversation_id is not None:
        conversation = _get_conversation(db, conversation_id)
        if conversation is None:
            abort(404)
    elif conversations:
        conversation = _get_conversation(db, conversations[0]["id"])

    if conversation is not None:
        messages = db.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation["id"],),
        ).fetchall()

    settings = get_settings()
    current_model = (
        conversation["model"] if conversation else settings.get("default_model", DEFAULT_MODEL)
    )
    return render_template(
        "chat.html",
        page="chat",
        page_title="Chat",
        conversations=conversations,
        conversation=conversation,
        messages=messages,
        supported_models=ollama.model_options(
            settings.get("ollama_url"), current_model=current_model
        ),
        default_model=DEFAULT_MODEL,
    )


@bp.get("/chat")
def index():
    return _render_page()


@bp.get("/chat/<int:conversation_id>")
def conversation(conversation_id):
    return _render_page(conversation_id)


def _create_conversation(first_message="", title="", model=None):
    model = (model or get_settings().get("default_model", DEFAULT_MODEL)).strip()
    if not ollama.valid_model_name(model):
        model = DEFAULT_MODEL
    if title:
        title = _make_title(title)
    elif first_message:
        title = _make_title(first_message)

    timestamp = now_str()
    db = get_db()
    cursor = db.execute(
        "INSERT INTO conversations (title, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title or "New conversation", model, timestamp, timestamp),
    )
    conversation_id = cursor.lastrowid

    if first_message:
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, first_message, timestamp),
        )
    db.commit()

    return {
        "id": conversation_id,
        "title": title or "New conversation",
        "model": model,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


@bp.post("/chat/new")
def new_from_form():
    first_message = (request.form.get("first_message") or "").strip()
    model = request.form.get("model")
    created = _create_conversation(first_message=first_message, model=model)
    query = "?autosend=1" if first_message else ""
    return redirect(
        url_for("chat.conversation", conversation_id=created["id"]) + query
    )


@bp.get("/api/conversations")
def api_list_conversations():
    conversations = _conversation_list(get_db())
    return jsonify(conversations=[dict(row) for row in conversations])


@bp.post("/api/conversations")
def api_create_conversation():
    data = request.get_json(silent=True) or request.form
    first_message = (data.get("first_message") or "").strip()
    created = _create_conversation(
        first_message=first_message,
        title=(data.get("title") or "").strip(),
        model=(data.get("model") or "").strip() or None,
    )
    return jsonify(created), 201


@bp.patch("/api/conversations/<int:conversation_id>")
def api_update_conversation(conversation_id):
    data = request.get_json(silent=True) or request.form
    db = get_db()
    conversation = _get_conversation(db, conversation_id)
    if conversation is None:
        return jsonify(error="Conversation not found."), 404

    fields = []
    params = []

    if "title" in data:
        title = _make_title(data.get("title") or "")
        fields.append("title = ?")
        params.append(title)

    if "model" in data:
        model = (data.get("model") or "").strip()
        if not ollama.valid_model_name(model):
            return jsonify(error="Model name is invalid."), 400
        fields.append("model = ?")
        params.append(model)

    if not fields:
        return jsonify(error="Nothing to update."), 400

    params.append(conversation_id)
    db.execute(f"UPDATE conversations SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()
    updated = _get_conversation(db, conversation_id)
    return jsonify(conversation=dict(updated))


@bp.delete("/api/conversations/<int:conversation_id>")
def api_delete_conversation(conversation_id):
    db = get_db()
    conversation = _get_conversation(db, conversation_id)
    if conversation is None:
        return jsonify(error="Conversation not found."), 404
    db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    db.commit()
    return jsonify(ok=True)


def _system_prompt(query):
    settings = get_settings()
    prompt = (settings.get("system_prompt") or "").strip()
    if not prompt:
        prompt = "You are ultron, a concise and practical local AI assistant."
    prompt += (
        "\n\nYou are the user's personal productivity assistant. Be helpful and concise, "
        "use workspace context when relevant, and help with planning and organizing."
    )
    prompt += (
        f"\nMachine-local date and time: {now_str()}. Interpret relative calendar dates "
        "using this local clock. If a date or start time is uncertain, ask before scheduling."
    )

    prompt += (
        "\nWhen the user explicitly asks to search the web, the application provides search results "
        "in the conversation. Respond to those results in plain language."
    )

    if settings.get("use_memory", "1") == "1":
        memories = relevant_memories(get_db(), query)
        if memories:
            lines = [f"- [{row['category']}] {row['content']}" for row in memories]
            prompt += (
                "\n\nRelevant saved memory notes (use only when applicable):\n"
                + "\n".join(lines)
            )
    return prompt


def _temperature():
    settings = get_settings()
    try:
        value = float(settings.get("temperature", "0.7"))
    except (TypeError, ValueError):
        value = 0.7
    return min(max(value, 0.0), 2.0)


def _sse(event, data):
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _persist_reply(database_path, conversation_id, reply, finished_at):
    """Save a completed streamed reply on a connection independent of the request.

    Flask tears down the request-scoped SQLite connection before a streaming
    response finishes, so the generator must own its connection.
    """
    connection = sqlite3.connect(database_path, timeout=15)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        cursor = connection.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
            (conversation_id, reply, finished_at),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (finished_at, conversation_id),
        )
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


@bp.post("/api/conversations/<int:conversation_id>/stream")
def api_stream_reply(conversation_id):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    db = get_db()
    conversation = _get_conversation(db, conversation_id)
    if conversation is None:
        return jsonify(error="Conversation not found."), 404

    if content and len(content) > MAX_MESSAGE_LENGTH:
        return jsonify(error="Message is too long."), 400

    timestamp = now_str()
    title = conversation["title"]

    if content:
        message_count = db.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
            (conversation_id, content, timestamp),
        )
        if message_count == 0:
            title = _make_title(content)
        db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, timestamp, conversation_id),
        )
        db.commit()
    else:
        latest = db.execute(
            "SELECT role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if latest is None or latest["role"] != "user":
            return jsonify(error="There is no pending user message to answer."), 400

    history = db.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 30",
        (conversation_id,),
    ).fetchall()
    latest_user_message = next(
        (row["content"] for row in history if row["role"] == "user"), ""
    )
    chat_messages = [{
        "role": "system",
        "content": _system_prompt(content or latest_user_message),
    }]
    for row in reversed(history):
        if row["role"] in ("user", "assistant"):
            if row["role"] == "assistant" and any(
                marker in row["content"].lower()
                for marker in ('"ultron_tool"', '"ultrontool"')
            ):
                continue
            chat_messages.append({"role": row["role"], "content": row["content"]})

    settings = get_settings()
    base_url = settings.get("ollama_url", "http://localhost:11434")
    model = conversation["model"] or settings.get("default_model", DEFAULT_MODEL)
    temperature = _temperature()
    database_path = current_app.config["DATABASE"]

    def generate():
        yield _sse("meta", {"conversation_id": conversation_id, "model": model, "title": title})
        direct_query = _explicit_web_search_query(latest_user_message)
        if direct_query:
            if settings.get("web_search_enabled", "1") == "1":
                try:
                    search_result = web_search.search(direct_query, max_results=5)
                    reply = _format_web_search_result(direct_query, search_result)
                except Exception:
                    reply = "Web search could not be completed. Check your internet connection and try again."
            else:
                reply = "Web search is disabled. Enable it in Settings and try again."

            yield _sse("token", {"token": reply})
            finished_at = now_str()
            message_id = _persist_reply(database_path, conversation_id, reply, finished_at)
            yield _sse(
                "done",
                {"id": message_id, "content": reply, "created_at": finished_at, "title": title},
            )
            return

        try:
            round_chunks = []
            decided = False
            structured_candidate = False
            for token in ollama.stream_chat(
                base_url=base_url,
                model=model,
                messages=chat_messages,
                temperature=temperature,
            ):
                round_chunks.append(token)
                if not decided:
                    candidate = "".join(round_chunks).lstrip()
                    if not candidate:
                        continue
                    decided = True
                    structured_candidate = candidate.startswith(("{", "```"))
                    if not structured_candidate:
                        yield _sse("token", {"token": "".join(round_chunks)})
                elif not structured_candidate:
                    yield _sse("token", {"token": token})

            round_text = "".join(round_chunks)
            if structured_candidate and "tool" in round_text.lower():
                reply = "Tool calling is disabled. Ask me to answer directly instead."
                yield _sse("token", {"token": reply})
            else:
                reply = round_text.strip()
                if structured_candidate and reply:
                    yield _sse("token", {"token": reply})
        except ollama.OllamaError as error:
            yield _sse("error", {"error": str(error)})
            return
        except Exception:
            yield _sse(
                "error",
                {"error": "The local model stopped unexpectedly. Check the server log."},
            )
            return

        if not reply:
            yield _sse("error", {"error": "The model returned an empty response. Try again."})
            return

        finished_at = now_str()
        message_id = _persist_reply(database_path, conversation_id, reply, finished_at)
        yield _sse(
            "done",
            {
                "id": message_id,
                "content": reply,
                "created_at": finished_at,
                "title": title,
            },
        )

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@bp.post("/api/conversations/<int:conversation_id>/regenerate")
def api_regenerate_reply(conversation_id):
    db = get_db()
    if _get_conversation(db, conversation_id) is None:
        return jsonify(error="Conversation not found."), 404
    latest = db.execute(
        "SELECT id, role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if latest is None or latest["role"] not in ("assistant", "user"):
        return jsonify(error="There is no response to regenerate."), 400
    if latest["role"] == "assistant":
        db.execute("DELETE FROM messages WHERE id = ?", (latest["id"],))
        db.commit()
    return jsonify(ok=True)


@bp.post("/api/conversations/<int:conversation_id>/partial")
def api_save_partial_reply(conversation_id):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify(ok=True, saved=False)
    if len(content) > 50000:
        return jsonify(error="Partial response is too long."), 400

    db = get_db()
    if _get_conversation(db, conversation_id) is None:
        return jsonify(error="Conversation not found."), 404
    latest = db.execute(
        "SELECT role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if latest and latest["role"] == "assistant":
        return jsonify(ok=True, saved=False)
    if latest is None or latest["role"] != "user":
        return jsonify(error="There is no pending user message."), 400

    timestamp = now_str()
    _persist_reply(current_app.config["DATABASE"], conversation_id, content, timestamp)
    return jsonify(ok=True, saved=True)
