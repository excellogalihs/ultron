"""Conservative, local rule-based suggestions from explicit user statements."""

import re

from ..helpers import now_str

SENSITIVE = re.compile(r"\b(password|passcode|secret|api[ _-]?key|token|credential|private key)\b", re.I)


def extract_explicit_memory(db, text):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 18 or len(text) > 800 or SENSITIVE.search(text):
        return None
    rules = (
        (r"\bI (?:prefer|like|want)\b", "preference"),
        (r"\b(?:next time|from now on|always|please remember)\b", "instruction"),
        (r"\bI(?:'m| am) (?:currently )?(?:working on|building|developing)\b", "project"),
    )
    category = next((name for pattern, name in rules if re.search(pattern, text, re.I)), None)
    if not category:
        return None
    content = text[:500]
    existing = db.execute("SELECT content FROM memories WHERE lower(content)=lower(?) LIMIT 1", (content,)).fetchone()
    if existing:
        return None
    now = now_str()
    cursor = db.execute("INSERT INTO memories(content,category,active,created_at,updated_at,approved) VALUES(?,?,0,?,?,0)", (content, category, now, now))
    db.execute("INSERT INTO learning_history(record_type,title,details,created_at) VALUES('memory_suggested',?,?,?)", (category.title() + " memory", content[:500], now))
    return cursor.lastrowid
