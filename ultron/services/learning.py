"""Small, local keyword retrieval and confirmed workflow experience storage."""

import json
import re

from ..helpers import now_str

STOP_WORDS = frozenset("a an and are as at be by can do for from how i in is it me my of on or please the this to we what when where which who with you your".split())
CATEGORIES = (
    "document management", "writing and editing", "research", "calendar management",
    "task management", "project management", "file management", "general productivity",
)


def _terms(text):
    return {word for word in re.findall(r"[a-z0-9]{2,}", (text or "").casefold()) if word not in STOP_WORDS}


def retrieve_experiences(db, query, limit=3):
    terms = _terms(query)
    if not terms:
        return []
    rows = db.execute("SELECT * FROM experiences WHERE archived=0 ORDER BY successful_uses DESC, last_used_at DESC LIMIT 200").fetchall()
    ranked = []
    for row in rows:
        haystack = " ".join((row["title"], row["category"], row["original_request"], row["task_description"], row["successful_methods"]))
        overlap = terms & _terms(haystack)
        if overlap:
            ranked.append((len(overlap), row["successful_uses"], row))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    output = []
    for _, _, row in ranked[:limit]:
        data = dict(row)
        data["execution_steps"] = json.loads(data["execution_steps"] or "[]")
        data["tools_used"] = json.loads(data["tools_used"] or "[]")
        output.append(data)
    return output


def retrieve_failures(db, query, limit=2):
    """Return relevant historical failures as cautions, never as confirmed fixes."""
    terms = _terms(query)
    if not terms:
        return []
    rows = db.execute("SELECT title,details,created_at FROM learning_history WHERE record_type='task_failure' ORDER BY id DESC LIMIT 100").fetchall()
    ranked = []
    for row in rows:
        overlap = terms & _terms(row["title"] + " " + row["details"])
        if overlap:
            ranked.append((len(overlap), row))
    ranked.sort(key=lambda item: (item[0], item[1]["created_at"]), reverse=True)
    return [dict(row) for _, row in ranked[:limit]]


def record_success(db, request, title, category, steps, tools, result, parameters=None):
    """Store only a confirmed successful operation; merge close keyword matches."""
    category = category if category in CATEGORIES else "general productivity"
    matches = retrieve_experiences(db, request, limit=1)
    now = now_str()
    encoded_steps = json.dumps(steps, ensure_ascii=False)
    encoded_tools = json.dumps(sorted(set(tools)), ensure_ascii=False)
    if matches and len(_terms(request) & _terms(matches[0]["original_request"])) >= max(2, len(_terms(request)) // 2):
        item = matches[0]
        db.execute(
            "UPDATE experiences SET successful_uses=successful_uses+1,last_used_at=?,updated_at=?,confidence=MIN(1.0,confidence+0.05),successful_methods=?,execution_steps=?,tools_used=?,parameters=? WHERE id=?",
            (now, now, result[:4000], encoded_steps, encoded_tools, json.dumps(parameters or {}, ensure_ascii=False), item["id"]),
        )
        db.execute("INSERT INTO learning_history(record_type,title,details,created_at) VALUES('experience_updated',?,?,?)", (item["title"], "Confirmed successful reuse", now))
        return item["id"]
    cursor = db.execute(
        """INSERT INTO experiences(title,category,original_request,task_description,execution_steps,tools_used,successful_methods,parameters,confidence,created_at,updated_at,last_used_at)
           VALUES(?,?,?,?,?,?,?,?,0.7,?,?,?)""",
        (title[:160], category, request[:2000], title[:500], encoded_steps, encoded_tools, result[:4000], json.dumps(parameters or {}, ensure_ascii=False), now, now, now),
    )
    db.execute("INSERT INTO learning_history(record_type,title,details,created_at) VALUES('experience_created',?,?,?)", (title[:160], result[:500], now))
    return cursor.lastrowid
