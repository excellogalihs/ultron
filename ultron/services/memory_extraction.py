"""Conservative, local rule-based capture of durable user memory.

The assistant should remember stable preferences, facts, ongoing projects, and
explicit reusable instructions. It should not turn one-off requests, questions,
hypotheticals, or secrets into long-term memory.
"""

import re

from .memory import (
    _GRAMMATICAL_WORDS,
    _STOP_WORDS,
    _VAGUE_OBJECTS,
    is_sensitive,
    save_memory,
)

_EXPLICIT_REMEMBER = re.compile(
    r"^\s*(?:(?:please|hey|okay|ok)\s+)?(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:remember|note|keep\s+in\s+mind|don'?t\s+forget)\b"
    r"(?:\s+that)?\s*[:,]?\s*",
    re.IGNORECASE,
)

_TASK_START = re.compile(
    r"^(?:to\b|call\b|buy\b|send\b|book\b|schedule\b|remind\b|do\b|finish\b|"
    r"complete\b|check\b|email\b|text\b|pay\b|order\b|pick\b|drop\b|clean\b|"
    r"wash\b|go\b|visit\b|make\b|get\b|take\b|submit\b|prepare\b|plan\b|look\b|"
    r"find\b|fix\b|update\b|review\b)\s",
    re.IGNORECASE,
)

_QUESTION_START = re.compile(
    r"^(?:do|does|did|am|are|is|was|were|can|could|would|should|will|have|has|"
    r"what|why|how|where|when|who|which)\b",
    re.IGNORECASE,
)

_ASSISTANT_DIRECTED = re.compile(
    r"\bI\s+(?:really\s+)?(?:like|love|prefer|enjoy|hate|dislike)\s+"
    r"(?:how|that|the\s+way|when)\s+you\b",
    re.IGNORECASE,
)

_PROJECT = re.compile(
    r"\bI(?:'m| am)\s+(?:currently\s+|still\s+|also\s+)?"
    r"(?:working\s+on|building|developing|creating|writing|learning|studying|researching)\b",
    re.IGNORECASE,
)

_PREFERENCE = re.compile(
    r"\bI\s+(?:really\s+|kind\s+of\s+|kinda\s+|quite\s+|also\s+|still\s+|just\s+)?"
    r"(?:like|love|prefer|enjoy|adore|hate|dislike|can't\s+stand|cannot\s+stand|"
    r"don't\s+like|do\s+not\s+like|don't\s+eat|do\s+not\s+eat|don't\s+drink|"
    r"do\s+not\s+drink|can't\s+eat|cannot\s+eat)\b"
    r"|\bmy\s+favou?rite\b",
    re.IGNORECASE,
)

_HABIT = re.compile(
    r"\bI\s+(?:always|usually|generally|never|often|sometimes|rarely|normally|typically)\s+\w+",
    re.IGNORECASE,
)

_SELF_CONTAINED_FACT = re.compile(
    r"\bI(?:'m|\s+am)\s+(?:a\s+|an\s+)?(?:[\w-]+\s+){0,2}"
    r"(?:vegetarian|vegan|student|teacher|"
    r"developer|engineer|designer|doctor|nurse|writer|artist|musician|freelancer|"
    r"manager|researcher|scientist|lawyer|accountant)\b"
    r"|\bI(?:'m|\s+am)\s+\d{1,3}\s+years?\s+old\b"
    r"|\bI\s+have\s+(?:a\s+|an\s+|\d+\s+)?"
    r"(?:dog|cat|pet|child|kid|son|daughter|brother|sister|wife|husband|partner)\b",
    re.IGNORECASE,
)

_FACT = re.compile(
    r"(?:\bmy\s+(?:name|birthday|timezone|email|phone|address|job|role|"
    r"favou?rite|preferred|native\s+language|language|age)\b"
    r"|\bcall\s+me\s+(?!at\b|on\b|in\b|before\b|after\b|tomorrow\b|today\b|"
    r"tonight\b|please\b|when\b)"
    r"|\bI\s+(?:live|reside|work|study|speak|use|own|was\s+born)\b"
    r"|\bI(?:'m|\s+am)\s+(?:from|based|allergic)\b)",
    re.IGNORECASE,
)

_INSTRUCTION = re.compile(
    r"^\s*(?:please\s+)?(?:always|never|from\s+now\s+on|going\s+forward|"
    r"next\s+time|in\s+the\s+future|in\s+future)\b",
    re.IGNORECASE,
)

_VERB_FORMS = {
    "am": "is",
    "are": "are",
    "is": "is",
    "was": "was",
    "were": "were",
    "be": "is",
    "have": "has",
    "has": "has",
    "do": "does",
    "go": "goes",
    "can": "can",
    "could": "could",
    "will": "will",
    "would": "would",
    "should": "should",
    "might": "might",
    "must": "must",
    "like": "likes",
    "love": "loves",
    "prefer": "prefers",
    "enjoy": "enjoys",
    "adore": "adores",
    "hate": "hates",
    "dislike": "dislikes",
    "live": "lives",
    "reside": "resides",
    "work": "works",
    "study": "studies",
    "speak": "speaks",
    "use": "uses",
    "need": "needs",
    "want": "wants",
    "eat": "eats",
    "drink": "drinks",
    "play": "plays",
    "read": "reads",
    "write": "writes",
    "make": "makes",
    "build": "builds",
    "create": "creates",
    "develop": "develops",
    "learn": "learns",
    "own": "owns",
    "keep": "keeps",
    "run": "runs",
    "cook": "cooks",
    "watch": "watches",
    "listen": "listens",
    "travel": "travels",
    "drive": "drives",
}

_SPLIT_SENTENCES = re.compile(r"(?<=[.!?;])\s+|\n+")

_ADVERB = (
    r"(?:really|also|still|just|quite|usually|generally|always|never|sometimes|"
    r"rarely|often|actually|definitely|currently|kinda|kind\s+of)"
)


def _third_person(verb):
    if verb in _VERB_FORMS:
        return _VERB_FORMS[verb]
    if verb.endswith(("s", "x", "z", "ch", "sh", "o")):
        return verb + "es"
    if len(verb) > 1 and verb.endswith("y") and verb[-2] not in "aeiou":
        return verb[:-1] + "ies"
    return verb + "s"


def _has_meaningful_object(text, match):
    if match is None:
        return False
    tail = text[match.end():]
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’+]*", tail):
        normalized = word.casefold()
        if normalized in _VAGUE_OBJECTS:
            continue
        if normalized in _GRAMMATICAL_WORDS:
            continue
        if normalized in _STOP_WORDS:
            continue
        if len(normalized) < 2:
            continue
        return True
    return False


def normalize_statement(text):
    """Rewrite a first-person note as a short, readable third-person fact."""
    text = re.sub(r"\s+", " ", (text or "")).strip(" ,;:-\"'“”")
    text = text.rstrip(".!?")
    if not text:
        return ""

    call_me = re.match(r"^call\s+me\s+(.+)$", text, re.IGNORECASE)
    if call_me:
        return f"The user is called {call_me.group(1).strip()}."

    changed = False
    contractions = (
        (r"^I'm\b", "The user is"),
        (r"^I am\b", "The user is"),
        (r"^I've\b", "The user has"),
        (r"^I have\b", "The user has"),
        (r"^I'll\b", "The user will"),
        (r"^I'd\b", "The user would"),
        (r"^I (?:don't|do not)\b", "The user does not"),
        (r"^I (?:can't|cannot)\b", "The user cannot"),
        (r"^I (?:won't|will not)\b", "The user will not"),
    )
    for pattern, replacement in contractions:
        updated = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        if updated != text:
            text = updated
            changed = True
            break

    if not changed:
        match = re.match(rf"^I\s+({_ADVERB})\s+([A-Za-z']+)(.*)$", text, re.IGNORECASE | re.DOTALL)
        if match:
            adverb, verb, rest = match.groups()
            text = f"The user {adverb.casefold()} {_third_person(verb.casefold())}{rest}"
            changed = True
        else:
            match = re.match(r"^I\s+([A-Za-z']+)(.*)$", text, re.IGNORECASE | re.DOTALL)
            if match:
                verb, rest = match.groups()
                text = f"The user {_third_person(verb.casefold())}{rest}"
                changed = True

    text = re.sub(r"\bmy\b", "the user's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmine\b", "the user's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bme\b", "the user", text, flags=re.IGNORECASE)
    text = re.sub(r"\bI\b", "the user", text)

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    return text[0].upper() + text[1:] + "."


def _classify(sentence):
    if _ASSISTANT_DIRECTED.search(sentence):
        return None
    if _PROJECT.search(sentence):
        return "project"
    if _HABIT.search(sentence) or _PREFERENCE.search(sentence):
        return "preference"
    if _FACT.search(sentence) or _SELF_CONTAINED_FACT.search(sentence):
        return "fact"
    if _INSTRUCTION.search(sentence):
        return "instruction"
    return None


def _candidate(sentence):
    """Return (rewritten_note, category) for one sentence, or None."""
    sentence = sentence.strip().strip("\"'“”")
    if not sentence:
        return None

    explicit = False
    match = _EXPLICIT_REMEMBER.match(sentence)
    if match:
        explicit = True
        sentence = sentence[match.end():].strip(" ,:;-")
        if sentence.casefold().startswith("to "):
            remainder = sentence[3:].strip()
            if _INSTRUCTION.match(remainder):
                sentence = remainder
            else:
                return None
        if not sentence:
            return None

    if sentence.endswith("?"):
        if not explicit:
            return None
        sentence = sentence[:-1].strip()
    elif not explicit and _QUESTION_START.match(sentence):
        return None

    if not explicit and _TASK_START.match(sentence) and not _FACT.search(sentence):
        return None
    if len(sentence) < 8 or len(sentence) > 800:
        return None
    if is_sensitive(sentence):
        return None

    category = _classify(sentence)
    if category is None:
        if not explicit:
            return None
        if _TASK_START.match(sentence):
            return None
        # Only save an explicit "remember ..." phrase when it carries a durable
        # first-person statement. This avoids turning "remember the meeting at 3"
        # into a permanent fact.
        if re.search(r"\b(?:I|I'm|I've|my)\b", sentence, re.IGNORECASE):
            category = "general"
        else:
            return None

    match = (
        _PROJECT.search(sentence)
        or _HABIT.search(sentence)
        or _PREFERENCE.search(sentence)
        or _FACT.search(sentence)
    )
    if category in ("preference", "project") and not _has_meaningful_object(sentence, match):
        return None
    if category == "fact" and not _SELF_CONTAINED_FACT.search(sentence):
        fact_match = _FACT.search(sentence)
        if fact_match is None or not _has_meaningful_object(sentence, fact_match):
            return None

    normalized = normalize_statement(sentence)
    if not normalized or len(normalized) < 10:
        return None
    return normalized, category


def extract_explicit_memories(db, text, auto_approve=False, max_items=5):
    """Capture up to ``max_items`` durable notes from one user message."""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) < 8 or len(text) > 800:
        return []
    if is_sensitive(text):
        return []

    stored = []
    for sentence in _SPLIT_SENTENCES.split(text):
        candidate = _candidate(sentence)
        if candidate is None:
            continue
        content, category = candidate
        result = save_memory(db, content, category, approved=auto_approve, source="conversation")
        memory = result.get("memory") or {}
        if result.get("saved") or (result.get("reason") == "already_saved" and memory.get("id")):
            memory_id = memory.get("id")
            if memory_id and memory_id not in stored:
                stored.append(memory_id)
        if len(stored) >= max_items:
            break
    return stored


def extract_explicit_memory(db, text, auto_approve=False):
    """Backward-compatible single-result helper."""
    ids = extract_explicit_memories(db, text, auto_approve=auto_approve, max_items=1)
    return ids[0] if ids else None
