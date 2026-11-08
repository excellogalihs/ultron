"""Small, request-scoped retrieval across Ultron's local workspace."""

import re
from datetime import date, datetime, timedelta

SEARCH_TYPES = {
    "tasks": ("task", "Task"),
    "projects": ("project", "Project"),
    "documents": ("document", "Document"),
    "folders": ("folder", "Folder"),
    "conversations": ("conversation", "Conversation"),
    "calendar": ("event", "Calendar"),
    "memories": ("memory", "Memory"),
    "knowledge": ("knowledge", "Knowledge"),
}


_STOPWORDS = set("a an and are as at be been book by can current do for from have how i in is it me my of on or our please say the this to we what when where which who with you your find show tell summarize summary discuss discussed working about documents document calendar events event recent recently week tomorrow prioritize priority status textbook".split())


def _terms(query):
    return [term for term in re.findall(r"[\w-]{2,}", query.casefold()) if term not in _STOPWORDS][:12]


def _snippet(text, terms, limit=260):
    text = " ".join((text or "").split())
    lowered = text.casefold()
    positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
    start = max(0, min(positions) - 90) if positions else 0
    excerpt = text[start : start + limit]
    return ("…" if start else "") + excerpt + ("…" if start + limit < len(text) else "")


def search_workspace(db, query, types=None, limit=40):
    """Search indexed workspace rows, with a bounded LIKE fallback."""
    limit = min(max(int(limit), 1), 100)
    terms = _terms(query)
    if not terms:
        return {"results": [], "fts": _has_fts(db)}
    requested = set(types or SEARCH_TYPES)
    requested.intersection_update(SEARCH_TYPES)
    if not requested:
        return {"results": [], "fts": False}
    placeholders = ",".join("?" for _ in requested)
    results = []
    used_fts = False
    try:
        match = " AND ".join('"' + term.replace('"', '""') + '"*' for term in terms)
        rows = db.execute(
            f"SELECT source, item_id, title, snippet(workspace_fts,3,'','', '…',12) AS excerpt, bm25(workspace_fts) AS rank "
            f"FROM workspace_fts WHERE workspace_fts MATCH ? AND source IN ({placeholders}) "
            "ORDER BY rank LIMIT ?",
            [match, *[SEARCH_TYPES[k][0] for k in requested], limit],
        ).fetchall()
        used_fts = True
        for row in rows:
            item = _resolve(db, row["source"], row["item_id"], row["title"], "")
            if item:
                item["snippet"] = " ".join((row["excerpt"] or "").split()) or item["snippet"]
                results.append(item)
    except Exception:
        rows = []

    if not used_fts:
        like = " AND ".join("(lower(title) LIKE ? OR lower(content) LIKE ?)" for _ in terms)
        query_params = []
        for term in terms:
            query_params.extend((f"%{term}%", f"%{term}%"))
        sources = []
        if "tasks" in requested:
            sources.append(("task", "SELECT 'task',id,title,notes,created_at FROM tasks"))
        if "projects" in requested:
            sources.append(("project", "SELECT 'project',id,name,description || ' ' || notes,updated_at FROM projects"))
        if "documents" in requested:
            sources.append(("document", "SELECT 'document', id, title, substr(content,1,1200), updated_at FROM documents"))
        if "folders" in requested:
            sources.append(("folder", "SELECT 'folder', id, name, name, created_at FROM document_folders"))
        if "conversations" in requested:
            sources.append(("conversation", "SELECT 'conversation', c.id, c.title, substr(COALESCE((SELECT m.content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1),''),1,1200), c.updated_at FROM conversations c"))
            sources.append(("conversation", "SELECT 'conversation', m.conversation_id, c.title, substr(m.content,1,1200), m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id"))
        if "calendar" in requested:
            sources.append(("event", "SELECT 'event', id, title, description, start_at FROM events"))
        if "memories" in requested:
            sources.append(("memory", "SELECT 'memory', id, category, content, updated_at FROM memories"))
        if "knowledge" in requested:
            sources.append(("knowledge", "SELECT 'knowledge', id, title, substr(content,1,1200), imported_at FROM knowledge_files"))
        for source, sql in sources:
            rows = db.execute(f"{sql} WHERE {like} ORDER BY 5 DESC LIMIT ?", (*query_params, limit)).fetchall()
            for row in rows:
                item = _resolve(db, row[0], row[1], row[2], row[3])
                if item:
                    item["snippet"] = _snippet(row[3], terms) or item["snippet"]
                    results.append(item)

    # FTS can produce several matching messages in one conversation; keep the
    # best ranked hit and cap total context/results for low-memory models.
    unique = {}
    for item in results:
        if item:
            key = (item["type"], item["id"])
            unique.setdefault(key, item)
    return {"results": list(unique.values())[: min(max(limit, 1), 100)], "fts": used_fts}


def _resolve(db, source, item_id, title, content):
    try:
        item_id = int(item_id)
    except (TypeError, ValueError):
        return None
    metadata = {}
    if source == "conversation":
        row = db.execute("SELECT title, updated_at FROM conversations WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        href = f"/chat/{item_id}"
        title, updated = row["title"], row["updated_at"]
    elif source == "task":
        row = db.execute("SELECT due_date,due_time,status,priority,created_at FROM tasks WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = "/tasks", row["created_at"]
        metadata = {"due_date": row["due_date"], "due_time": row["due_time"], "status": row["status"], "priority": row["priority"]}
    elif source == "project":
        row = db.execute("SELECT status,deadline,updated_at FROM projects WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/projects?project={item_id}", row["updated_at"]
        metadata = {"status": row["status"], "deadline": row["deadline"]}
    elif source == "document":
        row = db.execute("SELECT updated_at FROM documents WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/documents?doc={item_id}", row["updated_at"]
    elif source == "folder":
        row = db.execute("SELECT created_at FROM document_folders WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/documents?folder={item_id}", row["created_at"]
    elif source == "event":
        row = db.execute("SELECT start_at AS updated_at,end_at,category FROM events WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/calendar?view=day&date={row['updated_at'][:10]}&event={item_id}", row["updated_at"]
        metadata = {"start_at": row["updated_at"], "end_at": row["end_at"], "category": row["category"]}
    elif source == "memory":
        row = db.execute("SELECT updated_at,active,approved FROM memories WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/memory#memory-{item_id}", row["updated_at"]
        metadata = {"active": bool(row["active"]), "approved": bool(row["approved"])}
    elif source == "knowledge":
        row = db.execute("SELECT updated_at,status,file_type FROM knowledge_files WHERE id=?", (item_id,)).fetchone()
        if not row: return None
        href, updated = f"/knowledge?file={item_id}", row["updated_at"]
        metadata = {"status": row["status"], "file_type": row["file_type"]}
    else:
        return None
    label = next((label for _, (kind, label) in SEARCH_TYPES.items() if kind == source), source.title())
    return {"type": source, "label": label, "id": item_id, "title": title or label,
            "snippet": " ".join((content or title or "").split())[:260], "href": href,
            "updated_at": updated, "metadata": metadata}


def retrieve_context(db, query, max_items=6, max_characters=5000, include_memories=True):
    """Return a bounded set of relevant snippets for an assistant turn."""
    types = None if include_memories else [kind for kind in SEARCH_TYPES if kind != "memories"]
    result = search_workspace(db, query, types=types, limit=max_items)
    selected, total = [], 0
    seen = set()
    for item in result["results"]:
        if item["type"] == "memory" and (
            not item["metadata"].get("active") or not item["metadata"].get("approved")
        ):
            continue
        if item["type"] == "knowledge" and item["metadata"].get("status") != "indexed":
            continue
        content = item["snippet"]
        if total + len(content) > max_characters:
            content = content[: max(0, max_characters - total)]
        if content:
            selected.append({**item, "snippet": content})
            total += len(content)
            seen.add((item["type"], item["id"]))
        if total >= max_characters:
            break
    terms = _terms(query)
    lower_query = query.casefold()
    if any(word in lower_query for word in ("recent", "recently", "working on", "worked on")):
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        recent_rows = db.execute(
            "SELECT 'document' AS source,id,title,substr(content,1,1200),updated_at FROM documents WHERE updated_at>=? "
            "UNION ALL SELECT 'conversation',c.id,c.title,substr(COALESCE((SELECT m.content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1),''),1,1200),c.updated_at FROM conversations c WHERE c.updated_at>=? "
            "UNION ALL SELECT 'event',id,title,substr(description,1,1200),created_at FROM events WHERE created_at>=? "
            "UNION ALL SELECT 'knowledge',id,title,substr(content,1,1200),imported_at FROM knowledge_files WHERE imported_at>=? "
            "ORDER BY 5 DESC LIMIT 16", (cutoff, cutoff, cutoff, cutoff)
        ).fetchall()
        for row in recent_rows:
            item = _resolve(db, row["source"], row["id"], row["title"], row["content"])
            key = (item["type"], item["id"]) if item else None
            if item and not (item["type"] == "knowledge" and item["metadata"].get("status") != "indexed") and key not in seen and total < max_characters:
                selected.append(item)
                seen.add(key)
                total += len(item["snippet"])

    if "tomorrow" in lower_query or "this week" in lower_query or "next week" in lower_query:
        today = date.today()
        start = today + timedelta(days=1) if "tomorrow" in lower_query else today
        span = 1 if "tomorrow" in lower_query else (14 if "next week" in lower_query else 7)
        end = start + timedelta(days=span)
        date_from, date_to = start.isoformat(), end.isoformat()
        rows = db.execute(
            "SELECT 'event' AS source,id,title,description AS content,start_at AS updated_at FROM events WHERE start_at>=? AND start_at<? "
            "ORDER BY updated_at LIMIT 30", (date_from, date_to)
        ).fetchall()
        for row in rows:
            item = _resolve(db, row["source"], row["id"], row["title"], row["content"])
            key = (item["type"], item["id"]) if item else None
            if item and key not in seen and total < max_characters:
                selected.append(item)
                seen.add(key)
                total += len(item["snippet"])
        task_rows = db.execute("SELECT id,title,notes,created_at FROM tasks WHERE status='pending' AND due_date>=? AND due_date<? ORDER BY due_date,due_time LIMIT 30", (date_from, date_to)).fetchall()
        for row in task_rows:
            item = _resolve(db, "task", row["id"], row["title"], row["notes"])
            key = ("task", item["id"])
            if key not in seen and total < max_characters:
                selected.append(item); seen.add(key); total += len(item["snippet"])

    if "unfinished" in lower_query or "incomplete document" in lower_query:
        rows = db.execute(
            "SELECT id,title,substr(content,1,1200),updated_at FROM documents WHERE lower(title || ' ' || content) LIKE '%unfinished%' "
            "OR lower(title || ' ' || content) LIKE '%incomplete%' OR lower(content) LIKE '%todo%' "
            "OR lower(content) LIKE '%draft%' ORDER BY updated_at DESC LIMIT 8"
        ).fetchall()
        for row in rows:
            item = _resolve(db, "document", row["id"], row["title"], row["content"])
            key = ("document", item["id"])
            if key not in seen and total < max_characters:
                selected.append(item)
                seen.add(key)
                total += len(item["snippet"])
    bounded, remaining = [], max_characters
    for item in selected:
        if remaining <= 0 or len(bounded) >= max_items:
            break
        snippet = item["snippet"][:remaining]
        if snippet:
            bounded.append({**item, "snippet": snippet})
            remaining -= len(snippet)
    return bounded


def _has_fts(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_fts'").fetchone())
