"""Validated, application-scoped tools exposed to the local assistant."""

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from ..constants import EVENT_CATEGORIES, MEMORY_CATEGORIES, TASK_CATEGORIES, TASK_PRIORITIES
from ..helpers import now_str
from . import web_search

MAX_TOOL_CALLS = 8
MAX_TOOL_RESULT_LENGTH = 12000
MAX_WORKSPACE_FILES_SCANNED = 120
MAX_WORKSPACE_FILE_BYTES = 256 * 1024
WORKSPACE_TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".py", ".html", ".css", ".js", ".json", ".sql", ".toml", ".yaml", ".yml", ".csv"}
)
WORKSPACE_IGNORED_DIRECTORIES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "instance", "build", "dist"}
)
DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]

_STOP_WORDS = frozenset(
    "a an and are as at be by can do for from how i in is it me my of on or our please the this to we what when where which who with you your".split()
)


class ToolError(ValueError):
    """A safe, user-presentable tool validation error."""


def _arguments(value, allowed, required=()):
    if not isinstance(value, dict):
        raise ToolError("Tool arguments must be a JSON object.")
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown:
        raise ToolError(f"Unsupported argument: {sorted(unknown)[0]}.")
    if missing:
        raise ToolError(f"Missing argument: {sorted(missing)[0]}.")
    return value


def _text(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise ToolError(f"{label} must be text.")
    value = value.strip()
    if required and not value:
        raise ToolError(f"{label} is required.")
    if len(value) > maximum:
        raise ToolError(f"{label} is too long.")
    return value


def _content(value, maximum):
    if not isinstance(value, str):
        raise ToolError("Document content must be text.")
    if len(value) > maximum:
        raise ToolError("Document content is too long.")
    return value


def _date(value, label, optional=False):
    if optional and value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ToolError(f"{label} could not be interpreted.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as error:
        raise ToolError(f"{label} could not be interpreted.") from error


def _time(value, label, fallback=None):
    if value in (None, ""):
        return fallback
    if not isinstance(value, str):
        raise ToolError(f"{label} must use HH:MM.")
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError as error:
        raise ToolError(f"{label} must use HH:MM.") from error


def _row_dict(row):
    return dict(row) if row is not None else None


def _keywords(text):
    return {
        word
        for word in re.findall(r"[a-z0-9]{2,}", (text or "").casefold())
        if word not in _STOP_WORDS
    }


def relevant_memories(db, query, limit=5, max_characters=2800):
    """Return a small keyword-ranked subset, never the full memory table."""
    terms = _keywords(query)
    if not terms:
        return []

    rows = db.execute(
        "SELECT content, category, updated_at FROM memories "
        "WHERE active = 1 ORDER BY updated_at DESC, id DESC LIMIT 150"
    ).fetchall()
    ranked = []
    for row in rows:
        content_terms = _keywords(row["content"])
        overlap = terms & content_terms
        if overlap:
            ranked.append((len(overlap), row["updated_at"], row))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []
    used = 0
    for _, _, row in ranked:
        entry = {"content": row["content"], "category": row["category"]}
        cost = len(entry["content"]) + len(entry["category"]) + 8
        if used + cost > max_characters:
            continue
        selected.append(entry)
        used += cost
        if len(selected) >= limit:
            break
    return selected


def _search_workspace(db, arguments, workspace_root):
    args = _arguments(arguments, {"query"}, {"query"})
    query = _text(args["query"], "Query", 200, required=True)
    if len(query) < 2:
        raise ToolError("Search query must contain at least two characters.")
    rows = db.execute(
        """SELECT id, title, content, updated_at FROM documents
           WHERE title LIKE ? OR content LIKE ?
           ORDER BY updated_at DESC, id DESC LIMIT 6""",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    results = {
        "documents": [
            {
                "id": row["id"],
                "title": row["title"],
                "excerpt": row["content"][:1200],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }

    root = Path(workspace_root or DEFAULT_WORKSPACE_ROOT).resolve()
    needle = query.casefold()
    files = []
    scanned = 0
    try:
        for directory, child_dirs, file_names in os.walk(root, topdown=True, followlinks=False):
            current = Path(directory)
            child_dirs[:] = [
                name
                for name in child_dirs
                if name not in WORKSPACE_IGNORED_DIRECTORIES
                and not name.startswith(".")
                and not (current / name).is_symlink()
            ]
            for name in file_names:
                path = current / name
                if (
                    name.startswith(".")
                    or path.is_symlink()
                    or path.suffix.lower() not in WORKSPACE_TEXT_EXTENSIONS
                ):
                    continue
                scanned += 1
                if scanned > MAX_WORKSPACE_FILES_SCANNED:
                    break
                try:
                    if path.stat().st_size > MAX_WORKSPACE_FILE_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                position = text.casefold().find(needle)
                if position < 0:
                    continue
                start = max(0, position - 180)
                end = min(len(text), position + len(query) + 360)
                files.append({
                    "path": path.relative_to(root).as_posix(),
                    "excerpt": text[start:end],
                })
                if len(files) >= 5:
                    break
            if scanned > MAX_WORKSPACE_FILES_SCANNED or len(files) >= 5:
                break
    except OSError:
        pass
    results["files"] = files
    return results


def _read_document(db, arguments):
    args = _arguments(arguments, {"id", "title"})
    if ("id" in args) == ("title" in args):
        raise ToolError("Provide exactly one of id or title.")
    if "id" in args:
        if isinstance(args["id"], bool) or not isinstance(args["id"], int):
            raise ToolError("Document id must be an integer.")
        row = db.execute("SELECT * FROM documents WHERE id = ?", (args["id"],)).fetchone()
    else:
        title = _text(args["title"], "Title", 200, required=True)
        row = db.execute(
            "SELECT * FROM documents WHERE title = ? COLLATE NOCASE ORDER BY id DESC LIMIT 1",
            (title,),
        ).fetchone()
    if row is None:
        raise ToolError("Document not found.")
    return {"document": _row_dict(row)}


def _create_document(db, arguments):
    args = _arguments(arguments, {"title", "content"}, {"content"})
    title = _text(args.get("title", "Untitled document"), "Title", 200) or "Untitled document"
    content = _content(args["content"], 500000)
    timestamp = now_str()
    cursor = db.execute(
        "INSERT INTO documents (title, content, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title, content, timestamp, timestamp),
    )
    return {"document": _row_dict(db.execute("SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)).fetchone())}


def _edit_document(db, arguments):
    args = _arguments(arguments, {"id", "title", "content"}, {"id"})
    document_id = args["id"]
    if isinstance(document_id, bool) or not isinstance(document_id, int):
        raise ToolError("Document id must be an integer.")
    row = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ToolError("Document not found.")
    if "title" not in args and "content" not in args:
        raise ToolError("Provide a title or content to change.")
    title = _text(args.get("title", row["title"]), "Title", 200) or "Untitled document"
    content = _content(args.get("content", row["content"]), 500000)
    return {
        "proposal": {"id": document_id, "title": title, "content": content},
        "requires_user_approval": True,
        "message": (
            "This is only a proposal. Review and accept it in the document editor; "
            "the stored document was not changed."
        ),
    }


def _create_task(db, arguments):
    args = _arguments(
        arguments,
        {"title", "notes", "priority", "category", "due_date", "due_time", "project_id"},
        {"title"},
    )
    title = _text(args["title"], "Task title", 300, required=True)
    notes = _text(args.get("notes", ""), "Task notes", 4000)
    priority = args.get("priority", "normal")
    if priority not in TASK_PRIORITIES:
        raise ToolError("Priority must be low, normal, or high.")
    category = args.get("category", "general")
    if category not in TASK_CATEGORIES:
        raise ToolError("Invalid task category.")
    due_date = _date(args.get("due_date"), "Due date", optional=True)
    due_time = _time(args.get("due_time"), "Due time")
    if due_time and not due_date:
        raise ToolError("A due date is required when setting a reminder time.")
    project_id = args.get("project_id")
    if project_id is not None:
        if isinstance(project_id, bool) or not isinstance(project_id, int) or not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ToolError("Project id must identify an existing project.")
    cursor = db.execute(
          """INSERT INTO tasks (title, notes, status, priority, category, due_date, due_time, project_id, created_at)
              VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
          (title, notes, priority, category, due_date, due_time, project_id, now_str()),
    )
    return {"task": _row_dict(db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())}


def _read_tasks(db, arguments):
    args = _arguments(arguments, {"status", "category", "project_id"})
    status = args.get("status", "pending")
    if status not in ("pending", "completed", "all"):
        raise ToolError("Task status must be pending, completed, or all.")
    category = args.get("category")
    if category is not None and category not in TASK_CATEGORIES:
        raise ToolError("Invalid task category.")
    conditions = []
    params = []
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if "project_id" in args:
        project_id = args["project_id"]
        if isinstance(project_id, bool) or not isinstance(project_id, int) or not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ToolError("Project id must identify an existing project.")
        conditions.append("project_id = ?")
        params.append(project_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"""SELECT id, title, notes, status, priority, category, due_date, due_time, project_id, created_at
            FROM tasks {where}
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC, id DESC
            LIMIT 100""",
        params,
    ).fetchall()
    return {"tasks": [_row_dict(row) for row in rows]}


def _update_task(db, arguments):
    allowed = {"id", "title", "notes", "priority", "category", "due_date", "due_time", "status", "project_id"}
    args = _arguments(arguments, allowed, {"id"})
    task_id = args["id"]
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ToolError("Task id must be an integer.")
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ToolError("Task not found.")
    fields, values = [], []
    if "title" in args:
        fields.append("title = ?")
        values.append(_text(args["title"], "Task title", 300, required=True))
    if "notes" in args:
        fields.append("notes = ?")
        values.append(_text(args["notes"], "Task notes", 4000))
    if "priority" in args:
        if args["priority"] not in TASK_PRIORITIES:
            raise ToolError("Priority must be low, normal, or high.")
        fields.append("priority = ?")
        values.append(args["priority"])
    if "category" in args:
        if args["category"] not in TASK_CATEGORIES:
            raise ToolError("Invalid task category.")
        fields.append("category = ?")
        values.append(args["category"])
    if "due_date" in args:
        due_date = _date(args["due_date"], "Due date", optional=True)
        fields.append("due_date = ?")
        values.append(due_date)
        if due_date is None and "due_time" not in args:
            fields.append("due_time = ?")
            values.append(None)
    if "due_time" in args:
        fields.append("due_time = ?")
        values.append(_time(args["due_time"], "Due time"))
    if "project_id" in args:
        project_id = args["project_id"]
        if project_id is not None and (isinstance(project_id, bool) or not isinstance(project_id, int) or not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone()):
            raise ToolError("Project id must identify an existing project.")
        fields.append("project_id = ?")
        values.append(project_id)
    if "status" in args:
        status = args["status"]
        if status not in ("pending", "completed"):
            raise ToolError("Task status must be pending or completed.")
        fields.extend(("status = ?", "completed_at = ?"))
        values.extend((status, now_str() if status == "completed" else None))
    if not fields:
        raise ToolError("Provide at least one task field to update.")
    values.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)
    return {"task": _row_dict(db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())}


def _delete_task(db, arguments):
    args = _arguments(arguments, {"id"}, {"id"})
    task_id = args["id"]
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise ToolError("Task id must be an integer.")
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ToolError("Task not found.")
    db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return {"deleted_task": _row_dict(row)}


def _read_calendar_events(db, arguments):
    args = _arguments(arguments, {"date_from", "date_to"})
    date_from = _date(args.get("date_from"), "Start date", optional=True)
    date_to = _date(args.get("date_to"), "End date", optional=True)
    conditions = []
    params = []
    conditions.append("start_at >= ?")
    params.append(f"{date_from or now_str()[:10]} 00:00:00")
    if date_to:
        day_after = datetime.strptime(date_to, "%Y-%m-%d").date() + timedelta(days=1)
        conditions.append("start_at < ?")
        params.append(f"{day_after.isoformat()} 00:00:00")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(
        f"SELECT * FROM events {where} ORDER BY start_at ASC LIMIT 100", params
    ).fetchall()
    return {"events": [_row_dict(row) for row in rows]}


def _create_calendar_event(db, arguments):
    allowed = {"title", "date", "start_time", "end_time", "description", "category"}
    args = _arguments(arguments, allowed, {"title", "date", "start_time"})
    title = _text(args["title"], "Event title", 200, required=True)
    day = _date(args["date"], "Event date")
    start = _time(args.get("start_time"), "Start time")
    end = _time(args.get("end_time"), "End time")
    description = _text(args.get("description", ""), "Event description", 2000)
    category = args.get("category", "general")
    if category not in EVENT_CATEGORIES:
        raise ToolError("Invalid event category.")
    cursor = db.execute(
        """INSERT INTO events (title, description, start_at, end_at, category, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            title,
            description,
            f"{day} {start}:00",
            f"{day} {end}:00" if end else None,
            category,
            now_str(),
        ),
    )
    return {"event": _row_dict(db.execute("SELECT * FROM events WHERE id = ?", (cursor.lastrowid,)).fetchone())}


def _update_calendar_event(db, arguments):
    allowed = {"id", "title", "date", "start_time", "end_time", "description", "category"}
    args = _arguments(arguments, allowed, {"id"})
    event_id = args["id"]
    if isinstance(event_id, bool) or not isinstance(event_id, int):
        raise ToolError("Event id must be an integer.")
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ToolError("Calendar event not found.")
    day = _date(args.get("date", row["start_at"][:10]), "Event date")
    start_value = args.get("start_time", row["start_at"][11:16])
    start_time = _time(start_value, "Start time")
    if start_time is None:
        raise ToolError("Start time must use HH:MM.")
    if "end_time" in args:
        end_value = args["end_time"]
    else:
        end_value = row["end_at"][11:16] if row["end_at"] else None
    end_time = _time(end_value, "End time")
    if end_value not in (None, "") and end_time is None:
        raise ToolError("End time must use HH:MM.")
    title = _text(args.get("title", row["title"]), "Event title", 200, required=True)
    description = _text(args.get("description", row["description"]), "Event description", 2000)
    category = args.get("category", row["category"])
    if category not in EVENT_CATEGORIES:
        raise ToolError("Invalid event category.")
    db.execute(
        "UPDATE events SET title = ?, description = ?, start_at = ?, end_at = ?, category = ? WHERE id = ?",
        (title, description, f"{day} {start_time}:00", f"{day} {end_time}:00" if end_time else None, category, event_id),
    )
    return {"event": _row_dict(db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone())}


def _delete_calendar_event(db, arguments):
    args = _arguments(arguments, {"id"}, {"id"})
    event_id = args["id"]
    if isinstance(event_id, bool) or not isinstance(event_id, int):
        raise ToolError("Event id must be an integer.")
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ToolError("Calendar event not found.")
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    return {"deleted_event": _row_dict(row)}


def _read_memory(db, arguments):
    args = _arguments(arguments, {"query"}, {"query"})
    query = _text(args["query"], "Query", 500, required=True)
    return {"memories": relevant_memories(db, query, limit=5, max_characters=2800)}


def _save_memory(db, arguments):
    args = _arguments(arguments, {"content", "category"}, {"content"})
    content = _text(args["content"], "Memory", 2000, required=True)
    category = args.get("category", "general")
    if category not in MEMORY_CATEGORIES:
        raise ToolError("Memory category must be general, fact, preference, or project.")
    existing = db.execute(
        "SELECT * FROM memories WHERE content = ? COLLATE NOCASE AND category = ? LIMIT 1",
        (content, category),
    ).fetchone()
    if existing is not None:
        return {"saved": False, "memory": _row_dict(existing), "reason": "already_saved"}
    timestamp = now_str()
    cursor = db.execute(
        """INSERT INTO memories (content, category, active, created_at, updated_at)
           VALUES (?, ?, 1, ?, ?)""",
        (content, category, timestamp, timestamp),
    )
    return {"saved": True, "memory": _row_dict(db.execute("SELECT * FROM memories WHERE id = ?", (cursor.lastrowid,)).fetchone())}



def _web_search(db, arguments):
    args = _arguments(arguments, {"query", "max_results"}, {"query"})
    query = _text(args["query"], "Query", 200, required=True)
    if len(query) < 2:
        raise ToolError("Web search query must contain at least two characters.")
    max_results = 5
    if "max_results" in args:
        try:
            max_results = min(max(int(args["max_results"]), 1), 10)
        except (TypeError, ValueError):
            pass
    res = web_search.search(query, max_results=max_results)
    if not res["ok"]:
        return {
            "source": "web_search",
            "query": query,
            "results": [],
            "error": res.get("error") or "Web search unavailable.",
            "offline": res.get("offline", False),
        }
    return {
        "source": "web_search",
        "query": query,
        "results": res["results"],
        "count": len(res["results"]),
    }


def _fetch_webpage(db, arguments):
    args = _arguments(arguments, {"url"}, {"url"})
    url = _text(args["url"], "URL", 1000, required=True)
    res = web_search.fetch_page_text(url)
    if not res["ok"]:
        return {"source": "web_fetch", "url": url, "error": res.get("error")}
    return {"source": "web_fetch", "url": url, "text": res["text"], "content": res["text"]}


def _safe_file_target(rel_path, workspace_root):
    root = Path(workspace_root or DEFAULT_WORKSPACE_ROOT).resolve()
    clean_path = (rel_path or "").strip().lstrip("/" + chr(92))
    if not clean_path:
        raise ToolError("File path cannot be empty.")
    target = (root / clean_path).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise ToolError("Access denied: path is outside authorized workspace directory.")
    for part in relative.parts:
        if part.startswith(".") or part in WORKSPACE_IGNORED_DIRECTORIES:
            raise ToolError(f"Access denied: path segment '{part}' is protected.")
    return target, root


def _read_local_file(db, arguments, workspace_root):
    args = _arguments(arguments, {"path"}, {"path"})
    path_str = _text(args["path"], "Path", 500, required=True)
    target, root = _safe_file_target(path_str, workspace_root)
    if not target.is_file():
        raise ToolError(f"File not found: {target.relative_to(root).as_posix()}")
    if target.suffix.lower() not in WORKSPACE_TEXT_EXTENSIONS:
        raise ToolError(f"Unsupported file extension '{target.suffix}'.")
    if target.stat().st_size > MAX_WORKSPACE_FILE_BYTES:
        raise ToolError("File exceeds maximum allowed size (256 KB).")
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ToolError(f"Could not read file: {error}")
    return {
        "path": target.relative_to(root).as_posix(),
        "size_bytes": len(content.encode("utf-8")),
        "content": content,
    }


def _create_local_file(db, arguments, workspace_root):
    args = _arguments(arguments, {"path", "content"}, {"path", "content"})
    path_str = _text(args["path"], "Path", 500, required=True)
    content = _content(args.get("content", ""), 200000)
    target, root = _safe_file_target(path_str, workspace_root)
    if target.suffix.lower() not in WORKSPACE_TEXT_EXTENSIONS:
        raise ToolError(f"Unsupported file extension '{target.suffix}'.")
    if target.exists():
        return {
            "path": target.relative_to(root).as_posix(),
            "exists": True,
            "requires_user_approval": True,
            "proposal": {"path": target.relative_to(root).as_posix(), "content": content},
            "note": "File already exists. User confirmation required to overwrite.",
        }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as error:
        raise ToolError(f"Could not create file: {error}")
    return {
        "path": target.relative_to(root).as_posix(),
        "created": True,
        "bytes_written": len(content.encode("utf-8")),
    }

_TOOL_HANDLERS = {
    "web_search": _web_search,
    "fetch_webpage": _fetch_webpage,
    "read_local_file": _read_local_file,
    "create_local_file": _create_local_file,
    "search_workspace": _search_workspace,
    "read_document": _read_document,
    "create_document": _create_document,
    "edit_document": _edit_document,
    "create_task": _create_task,
    "read_tasks": _read_tasks,
    "update_task": _update_task,
    "delete_task": _delete_task,
    "read_calendar_events": _read_calendar_events,
    "create_calendar_event": _create_calendar_event,
    "update_calendar_event": _update_calendar_event,
    "delete_calendar_event": _delete_calendar_event,
    "read_memory": _read_memory,
    "save_memory": _save_memory,
}


def parse_tool_call(text, fallback_query=None):
    """Parse a structured tool call, including common small-model variants."""
    candidate = (text or "").strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in ("```", "```json") and lines[-1].strip() == "```":
            candidate = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(candidate)
    except (TypeError, ValueError):
        payload = None

    # Small local models often add a short explanation before or after the
    # JSON object, even when prompted to return JSON only. Recover the first
    # recognizable object while still validating the tool name below.
    if payload is None and candidate:
        decoder = json.JSONDecoder()
        for position, character in enumerate(candidate):
            if character != "{":
                continue
            try:
                item, _ = decoder.raw_decode(candidate, position)
            except ValueError:
                continue
            has_name = isinstance(item, dict) and any(
                key in item for key in ("ultron_tool", "ultrontool", "tool", "tool_name")
            )
            has_arguments = isinstance(item, dict) and any(
                key in item for key in ("arguments", "parameters", "args", "input", "function_call", "tool_call", "call")
            )
            if has_name and (has_arguments or len(item) > 1):
                payload = item
                break

    # Some models concatenate a tool label and its arguments as separate JSON
    # objects, sometimes with a misspelled envelope key. Accept only known
    # read-only search tools and query arguments in this compatibility path.
    if payload is None and candidate:
        decoder = json.JSONDecoder()
        objects = []
        position = 0
        while position < len(candidate):
            while position < len(candidate) and candidate[position].isspace():
                position += 1
            if position >= len(candidate):
                break
            try:
                item, end = decoder.raw_decode(candidate, position)
            except ValueError:
                objects = []
                break
            if not isinstance(item, dict):
                objects = []
                break
            objects.append(item)
            position = end

        if len(objects) >= 2:
            calls = []
            for index in range(len(objects) - 1):
                envelope = objects[index]
                raw_name = envelope.get("ultron_tool", envelope.get("ultrontool"))
                if not isinstance(raw_name, str):
                    continue
                normalized = raw_name.lower().replace("_", "")
                names = {
                    "searchworkspace": "search_workspace",
                    "searchweb": "web_search",
                    "websearch": "web_search",
                }
                name = names.get(normalized)
                arguments = objects[index + 1]
                if name is None and normalized in {item.replace("_", "") for item in _TOOL_HANDLERS}:
                    name = next(item for item in _TOOL_HANDLERS if item.replace("_", "") == normalized)
                    if isinstance(arguments, dict) and arguments:
                        return name, arguments
                if name and set(arguments) == {"query"} and isinstance(arguments["query"], str):
                    query = arguments["query"].strip()
                    if query:
                        calls.append((name, query))
            if calls:
                name = calls[0][0]
                queries = list(dict.fromkeys(query for call_name, query in calls if call_name == name))
                return name, {"query": "; ".join(queries)}

    # Small local models sometimes emit repeated one-field tool labels instead
    # of the documented envelope. Recover only that narrow, search-only shape.
    if payload is None and fallback_query and candidate:
        labels = []
        for line in candidate.splitlines():
            try:
                item = json.loads(line.strip())
            except (TypeError, ValueError):
                labels = []
                break
            if not isinstance(item, dict) or set(item) != {"ultron_tool"}:
                labels = []
                break
            labels.append(item.get("ultron_tool"))
        known_search_labels = {"web_search", "search_web", "search_workspace"}
        if labels and all(label in known_search_labels for label in labels):
            name = "web_search" if any(label in {"web_search", "search_web"} for label in labels) else "search_workspace"
            return name, {"query": fallback_query.strip()}

    if (
        isinstance(payload, dict)
        and set(payload) == {"ultron_tool"}
        and fallback_query
        and payload["ultron_tool"] in {"web_search", "search_web", "search_workspace"}
    ):
        name = "search_workspace" if payload["ultron_tool"] == "search_workspace" else "web_search"
        return name, {"query": fallback_query.strip()}

    if isinstance(payload, dict):
        for wrapper_key in ("function_call", "tool_call", "call"):
            if isinstance(payload.get(wrapper_key), dict):
                payload = payload[wrapper_key]
                break
    if not isinstance(payload, dict):
        return None
    raw_name = next(
        (payload[key] for key in ("ultron_tool", "ultrontool", "tool_name", "tool", "name") if key in payload),
        None,
    )
    if not isinstance(raw_name, str):
        return None
    normalized = re.sub(r"[\s-]+", "_", raw_name.strip().lower())
    name = {
        "search_web": "web_search",
        "list_tasks": "read_tasks",
        "get_tasks": "read_tasks",
        "task_list": "read_tasks",
        "list_events": "read_calendar_events",
        "get_events": "read_calendar_events",
        "list_calendar_events": "read_calendar_events",
        "get_calendar_events": "read_calendar_events",
        "create_event": "create_calendar_event",
        "add_event": "create_calendar_event",
        "add_calendar_event": "create_calendar_event",
        "update_event": "update_calendar_event",
        "delete_event": "delete_calendar_event",
        "add_task": "create_task",
        "edit_task": "update_task",
        "edit_event": "update_calendar_event",
        "edit_calendar_event": "update_calendar_event",
    }.get(normalized, normalized)
    argument_key = next((key for key in ("arguments", "parameters", "args", "input") if key in payload), None)
    if argument_key is not None:
        arguments = payload[argument_key]
    else:
        name_keys = {"ultron_tool", "ultrontool", "tool_name", "tool", "name"}
        arguments = {key: value for key, value in payload.items() if key not in name_keys}
    if name in {"web_search", "search_workspace"} and arguments == {} and fallback_query:
        return name, {"query": fallback_query.strip()}
    if not isinstance(name, str) or name not in _TOOL_HANDLERS:
        return None
    if not isinstance(arguments, dict):
        return None
    return name, arguments


def execute_tool(database_path, name, arguments, workspace_root=None):
    """Execute one allow-listed tool on a private SQLite connection."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise ToolError("Unknown workspace tool.")
    connection = sqlite3.connect(database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        if name in ("search_workspace", "read_local_file", "create_local_file"):
            result = handler(connection, arguments, workspace_root)
        else:
            result = handler(connection, arguments)
        connection.commit()
        return result
    except ToolError:
        connection.rollback()
        raise
    except sqlite3.Error as error:
        connection.rollback()
        raise ToolError("The workspace database could not complete that action.") from error
    finally:
        connection.close()


def compact_tool_result(result):
    """Keep tool output bounded before including it in a model prompt."""
    serialized = json.dumps(result, ensure_ascii=False)
    if len(serialized) <= MAX_TOOL_RESULT_LENGTH:
        return serialized
    return json.dumps(
        {"truncated": True, "preview": serialized[: MAX_TOOL_RESULT_LENGTH - 100]},
        ensure_ascii=False,
    )
