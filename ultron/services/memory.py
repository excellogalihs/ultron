"""Durable local memory storage, deduplication, and bounded retrieval."""

import re
import sqlite3

from ..constants import MEMORY_CATEGORIES
from ..helpers import now_str

MAX_MEMORY_LENGTH = 2000

_SENSITIVE = re.compile(
    r"\b(?:password|passcode|passphrase|secret|api[ _-]?key|access[ _-]?token|"
    r"auth[ _-]?token|credential|private[ _-]?key|seed[ _-]?phrase|"
    r"recovery[ _-]?code|social[ _-]?security|ssn|credit[ _-]?card|"
    r"card[ _-]?number|cvv|pin)\b",
    re.IGNORECASE,
)

_STOP_WORDS = frozenset(
    "a an and are as at be been being but by can could did do does doing for "
    "from had has have having he her here hers him his how i if in into is it "
    "its just me more most my no nor not of on once only or other our out over "
    "own same she should so some such than that the their them then there these "
    "they this those to too under until up user very was we were what when where "
    "which while who whom why will with would you your yours saved memory "
    "remember".split()
)

_GRAMMATICAL_WORDS = frozenset(
    "i you he she it we they me him her us them my your his its our their "
    "this that these those".split()
)

_VAGUE_OBJECTS = frozenset(
    "it this that these those them one ones something anything nothing "
    "everything lot lots bit more less idea response answer reply message "
    "conversation chat question thing things document file draft text "
    "format formatting".split()
)

_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|never|without|cannot|(?:don|doesn|didn|isn|aren|wasn|weren|"
    r"can|won|wouldn|shouldn|couldn)'?t)\b",
    re.IGNORECASE,
)

_CORE_FACT = re.compile(
    r"\b(?:name|birthday|born|live|lives|allerg|timezone|language|job|work|"
    r"role|favou?rite|prefer|like|love|hate|dislike|vegetarian|vegan|pet|dog|"
    r"cat|child|kid|family|partner|wife|husband|goal|project|study|student)\b",
    re.IGNORECASE,
)

_CATEGORY_WEIGHT = {
    "preference": 6,
    "fact": 5,
    "instruction": 5,
    "project": 4,
    "general": 2,
}

MEMORY_CONTEXT_LIMIT = 18
MEMORY_CONTEXT_CHARACTERS = 3200


def is_sensitive(text):
    """Return True when text looks like it contains a credential or secret."""
    return bool(_SENSITIVE.search(text or ""))


def normalize_term(word):
    """Small, conservative stemmer for keyword overlap."""
    word = (word or "").casefold().replace("’", "'")
    if word.endswith("'s"):
        word = word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        stem = word[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(word) > 4 and word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def keywords(text):
    """Return normalized search terms, ignoring common filler words."""
    terms = set()
    for raw in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", (text or "").casefold().replace("’", "'")):
        if len(raw) < 2 or raw in _STOP_WORDS:
            continue
        term = normalize_term(raw)
        if len(term) >= 2 and term not in _STOP_WORDS:
            terms.add(term)
    return terms


def memory_key(content):
    """Normalize memory text for exact and near-duplicate detection."""
    text = (content or "").casefold().replace("’", "'")
    text = re.sub(r"^(?:the\s+)?user(?:'s)?\s+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _row_value(row, key, index):
    if isinstance(row, sqlite3.Row):
        return row[key]
    if isinstance(row, dict):
        return row[key]
    return row[index]


def _memory_dict(row):
    return {
        "id": _row_value(row, "id", 0),
        "content": _row_value(row, "content", 1),
        "category": _row_value(row, "category", 2),
        "active": _row_value(row, "active", 3),
        "approved": _row_value(row, "approved", 4),
        "created_at": _row_value(row, "created_at", 5),
        "updated_at": _row_value(row, "updated_at", 6),
    }


def _duplicate_of(rows, content):
    """Find an existing note that already captures the same statement."""
    key = memory_key(content)
    terms = keywords(content)
    new_is_negated = bool(_NEGATION_PATTERN.search(content or ""))
    for row in rows:
        existing_content = _row_value(row, "content", 1)
        existing_key = memory_key(existing_content)
        if key and key == existing_key:
            return row, "exact"
        if key and existing_key and (key in existing_key or existing_key in key):
            shorter, longer = sorted((len(key), len(existing_key)))
            if shorter / max(1, longer) >= 0.72:
                if new_is_negated != bool(_NEGATION_PATTERN.search(existing_content or "")):
                    return row, "contradiction"
                return row, "near"
        existing_terms = keywords(existing_content)
        if terms and existing_terms:
            overlap = terms & existing_terms
            if len(overlap) / min(len(terms), len(existing_terms)) >= 0.9:
                if new_is_negated != bool(_NEGATION_PATTERN.search(existing_content or "")):
                    return row, "contradiction"
                return row, "near"
    return None, None


def save_memory(db, content, category="general", approved=True, source="assistant"):
    """Store one durable note, merging duplicates and simple contradictions.

    Returns a JSON-safe result dict. When ``approved`` is false the note is
    stored as an inactive suggestion, matching the review workflow.
    """
    content = re.sub(r"\s+", " ", (content or "")).strip()
    if not content:
        return {"saved": False, "reason": "empty"}
    if len(content) > MAX_MEMORY_LENGTH:
        return {"saved": False, "reason": "too_long"}
    if category not in MEMORY_CATEGORIES:
        return {"saved": False, "reason": "invalid_category"}
    if is_sensitive(content):
        return {"saved": False, "reason": "sensitive"}

    rows = db.execute(
        "SELECT id, content, category, active, approved, created_at, updated_at "
        "FROM memories ORDER BY id DESC LIMIT 500"
    ).fetchall()
    existing, relation = _duplicate_of(rows, content)
    now = now_str()

    if existing is not None:
        existing_id = _row_value(existing, "id", 0)
        existing_content = _row_value(existing, "content", 1)
        if not approved:
            row = db.execute(
                "SELECT id, content, category, active, approved, created_at, updated_at FROM memories WHERE id = ?",
                (existing_id,),
            ).fetchone()
            return {
                "saved": False,
                "updated": False,
                "reason": "already_saved",
                "memory": _memory_dict(row),
            }
        updated = False
        if relation == "contradiction" or (
            relation == "near" and len(memory_key(content)) > len(memory_key(existing_content))
        ):
            db.execute(
                "UPDATE memories SET content = ?, category = ?, active = 1, approved = 1, updated_at = ? WHERE id = ?",
                (content, category, now, existing_id),
            )
            updated = True
        elif approved:
            db.execute(
                "UPDATE memories SET active = 1, approved = 1, updated_at = ? WHERE id = ?",
                (now, existing_id),
            )
        row = db.execute(
            "SELECT id, content, category, active, approved, created_at, updated_at FROM memories WHERE id = ?",
            (existing_id,),
        ).fetchone()
        return {
            "saved": updated,
            "updated": updated,
            "reason": "replaced" if updated else "already_saved",
            "memory": _memory_dict(row),
        }

    cursor = db.execute(
        "INSERT INTO memories (content, category, active, approved, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (content, category, 1 if approved else 0, 1 if approved else 0, now, now),
    )
    db.execute(
        "INSERT INTO learning_history (record_type, title, details, created_at) VALUES (?, ?, ?, ?)",
        (
            "memory_saved" if approved else "memory_suggested",
            category.title() + " memory",
            content[:500],
            now,
        ),
    )
    row = db.execute(
        "SELECT id, content, category, active, approved, created_at, updated_at FROM memories WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    return {"saved": True, "updated": False, "reason": "created", "memory": _memory_dict(row)}


def relevant_memories(db, query, limit=5, max_characters=2800):
    """Return a small keyword-ranked subset, never the full memory table."""
    terms = keywords(query)
    if not terms:
        return []

    rows = db.execute(
        "SELECT id, content, category, updated_at FROM memories "
        "WHERE active = 1 AND approved = 1 ORDER BY updated_at DESC, id DESC LIMIT 200"
    ).fetchall()
    ranked = []
    for row in rows:
        content = _row_value(row, "content", 1)
        overlap = terms & keywords(content)
        if overlap:
            ranked.append((len(overlap), _row_value(row, "updated_at", 3), row))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []
    used = 0
    for _, _, row in ranked:
        content = _row_value(row, "content", 1)
        category = _row_value(row, "category", 2)
        cost = len(content) + len(category) + 8
        if used + cost > max_characters:
            continue
        selected.append({"content": content, "category": category})
        used += cost
        if len(selected) >= limit:
            break
    return selected


def memory_context(db, query, limit=MEMORY_CONTEXT_LIMIT, max_characters=MEMORY_CONTEXT_CHARACTERS):
    """Return durable memories for the assistant's system prompt.

    Keyword matches rank first, but a bounded profile of important and recent
    notes is always included. This is what lets a preference stated in one
    conversation still be available in a later, unrelated conversation.
    """
    rows = db.execute(
        "SELECT id, content, category, updated_at FROM memories "
        "WHERE active = 1 AND approved = 1 ORDER BY updated_at DESC, id DESC LIMIT 300"
    ).fetchall()
    if not rows:
        return []

    terms = keywords(query)
    scored = []
    for index, row in enumerate(rows):
        content = _row_value(row, "content", 1)
        category = _row_value(row, "category", 2)
        overlap = terms & keywords(content)
        importance = 4 if _CORE_FACT.search(content) else 0
        recency = max(0.0, 2.0 - (index / 100.0))
        score = (len(overlap) * 10) + _CATEGORY_WEIGHT.get(category, 1) + importance + recency
        scored.append((score, -index, bool(overlap), row))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected, used, seen = [], 0, set()
    for score, index, relevant, row in scored:
        content = _row_value(row, "content", 1)
        category = _row_value(row, "category", 2)
        key = memory_key(content)
        if key in seen:
            continue
        cost = len(content) + len(category) + 8
        if used + cost > max_characters:
            continue
        selected.append({
            "id": _row_value(row, "id", 0),
            "content": content,
            "category": category,
            "relevant": relevant,
        })
        used += cost
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected
