"""Shared template helpers, formatting, and navigation context."""

from datetime import datetime, timedelta

from flask import current_app, g, request, url_for

from .db import get_db

DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def get_settings():
    """Request-scoped settings dictionary with fallbacks."""
    if "settings" not in g:
        from .constants import DEFAULT_SETTINGS
        data = dict(DEFAULT_SETTINGS)
        rows = get_db().execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            data[row["key"]] = row["value"]
        g.settings = data
    return g.settings


def clear_settings_cache():
    g.pop("settings", None)


def nav_items():
    candidates = (
        ("Home", "home.index", "home", "home"),
        ("Chat", "chat.index", "chat", "chat"),
        ("Knowledge Base", "knowledge.index", "knowledge", "knowledge"),
        ("Search", "search.index", "search", "search"),
        ("Calendar", "calendar.index", "calendar", "calendar"),
        ("Memory", "memory.index", "memory", "memory"),
        ("Automations", "automations.index", "automations", "automation"),
        ("Evolution", "evolution.index", "evolution", "memory"),
        ("Settings", "settings.index", "settings", "settings"),
    )
    items = []
    for label, endpoint, blueprint, icon_name in candidates:
        items.append(
            {
                "label": label,
                "href": url_for(endpoint),
                "icon": icon_name,
                "active": request.blueprint == blueprint,
            }
        )
    return items


def format_date(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%d %b %Y")


def format_datetime(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%d %b %Y · %H:%M")


def format_time(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    return parsed.strftime("%H:%M")


def format_month_day(value):
    parsed = parse_datetime(value)
    if not parsed:
        return {"day": "--", "month": "---"}
    return {"day": parsed.strftime("%d"), "month": parsed.strftime("%b").upper()}


def humanize(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value or ""
    delta = datetime.now() - parsed
    seconds = int(delta.total_seconds())
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{max(1, seconds // 60)}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    if seconds < 86400 * 7:
        return f"{seconds // 86400}d ago"
    return parsed.strftime("%d %b %Y")


def word_count(value):
    return len((value or "").split())


def initials(value):
    parts = [part for part in (value or "").strip().split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def register_helpers(app):
    app.jinja_env.filters["date"] = format_date
    app.jinja_env.filters["datetime"] = format_datetime
    app.jinja_env.filters["time"] = format_time
    app.jinja_env.filters["humanize"] = humanize
    app.jinja_env.filters["month_day"] = format_month_day
    app.jinja_env.filters["wordcount"] = word_count
    app.jinja_env.filters["initials"] = initials

    @app.context_processor
    def inject_globals():
        return {
            "settings": get_settings(),
            "nav_items": nav_items(),
            "app_version": current_app.config.get("APP_VERSION", "0.1.0"),
            "today_label": datetime.now().strftime("%a %d %b %Y").upper(),
            "greeting": greeting(),
            "current_year": datetime.now().year,
            "now": datetime.now(),
        }
