"""Calendar: month grid and event CRUD."""

import calendar as pycalendar
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from ..constants import EVENT_CATEGORIES
from ..db import get_db
from ..helpers import now_str

bp = Blueprint("calendar", __name__)


def _parse_month(value):
    if value:
        try:
            parsed = datetime.strptime(value, "%Y-%m")
            return parsed.year, parsed.month
        except ValueError:
            pass
    today = date.today()
    return today.year, today.month


def _parse_date(value):
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return date.today()


def _shift_month(year, month, delta):
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


def _time_value(value, fallback=None):
    value = (value or "").strip()
    if not value:
        return fallback
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def _serialize(row):
    return dict(row) if row is not None else None


@bp.get("/calendar")
def index():
    view = request.args.get("view", "month")
    if view not in ("month", "week", "day"):
        view = "month"
    today = date.today()
    selected_date = _parse_date(request.args.get("date"))
    if view == "month":
        year, month = _parse_month(request.args.get("month"))
        selected_date = date(year, month, 1)
        range_start = selected_date
        if month == 12:
            range_end = date(year + 1, 1, 1)
        else:
            range_end = date(year, month + 1, 1)
        label = selected_date.strftime("%B %Y").upper()
        prev_year, prev_month = _shift_month(year, month, -1)
        next_year, next_month = _shift_month(year, month, 1)
        previous_href = f"?view=month&month={prev_year:04d}-{prev_month:02d}"
        next_href = f"?view=month&month={next_year:04d}-{next_month:02d}"
        today_href = f"?view=month&month={today:%Y-%m}"
        display_weeks = pycalendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    elif view == "week":
        range_start = selected_date - timedelta(days=selected_date.weekday())
        range_end = range_start + timedelta(days=7)
        week_end = range_end - timedelta(days=1)
        label = f"{range_start:%d %b} – {week_end:%d %b %Y}".upper()
        previous_href = f"?view=week&date={range_start - timedelta(days=7):%Y-%m-%d}"
        next_href = f"?view=week&date={range_end:%Y-%m-%d}"
        today_href = f"?view=week&date={today:%Y-%m-%d}"
        display_weeks = [
            [range_start + timedelta(days=offset) for offset in range(7)]
        ]
    else:
        range_start = selected_date
        range_end = selected_date + timedelta(days=1)
        label = selected_date.strftime("%A %d %B %Y").upper()
        previous_href = f"?view=day&date={selected_date - timedelta(days=1):%Y-%m-%d}"
        next_href = f"?view=day&date={range_end:%Y-%m-%d}"
        today_href = f"?view=day&date={today:%Y-%m-%d}"
        display_weeks = [[selected_date]]

    db = get_db()
    events = db.execute(
        """
        SELECT * FROM events
        WHERE start_at >= ? AND start_at < ?
        ORDER BY start_at ASC, id ASC
        """,
        (f"{range_start.isoformat()} 00:00:00", f"{range_end.isoformat()} 00:00:00"),
    ).fetchall()

    events_by_day = {}
    for event in events:
        day_key = event["start_at"][:10]
        events_by_day.setdefault(day_key, []).append(event)

    weeks = []
    for week_dates in display_weeks:
        week = []
        for day in week_dates:
            key = day.isoformat()
            week.append(
                {
                    "date": day,
                    "key": key,
                    "in_month": view != "month" or day.month == selected_date.month,
                    "is_today": day == today,
                    "events": events_by_day.get(key, []),
                }
            )
        weeks.append(week)

    return render_template(
        "calendar.html",
        page="calendar",
        page_title="Calendar",
        view=view,
        weeks=weeks,
        selected_date=selected_date,
        month_value=f"{selected_date.year:04d}-{selected_date.month:02d}",
        month_label=label,
        previous_href=previous_href,
        next_href=next_href,
        today_href=today_href,
        today_value=today.isoformat(),
        event_categories=EVENT_CATEGORIES,
        open_event_id=request.args.get("event", type=int),
    )


@bp.get("/api/events")
def api_list():
    rows = get_db().execute(
        "SELECT * FROM events ORDER BY start_at ASC, id ASC"
    ).fetchall()
    return jsonify(events=[dict(row) for row in rows])


@bp.get("/api/events/<int:event_id>")
def api_get(event_id):
    row = get_db().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return jsonify(error="Event not found."), 404
    return jsonify(event=_serialize(row))


def _validated_payload(default_category="general"):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Event title is required.")
    if len(title) > 200:
        raise ValueError("Event title is too long.")

    day = (data.get("date") or "").strip()
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("A valid event date is required.") from error

    start_time = _time_value(data.get("start_time"), "09:00")
    if start_time is None:
        raise ValueError("Start time must use HH:MM.")
    end_time = _time_value(data.get("end_time"), None)
    if (data.get("end_time") or "").strip() and end_time is None:
        raise ValueError("End time must use HH:MM.")

    description = (data.get("description") or "").strip()
    if len(description) > 2000:
        raise ValueError("Event description is too long.")
    category = (data.get("category") or default_category).strip()
    if category not in EVENT_CATEGORIES:
        raise ValueError("Choose a valid event category.")

    return {
        "title": title,
        "date": day,
        "start_at": f"{day} {start_time}:00",
        "end_at": f"{day} {end_time}:00" if end_time else None,
        "description": description,
        "category": category,
    }


@bp.post("/api/events")
def api_create():
    try:
        payload = _validated_payload()
    except ValueError as error:
        return jsonify(error=str(error)), 400

    db = get_db()
    cursor = db.execute(
        """
        INSERT INTO events (title, description, start_at, end_at, category, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            payload["title"],
            payload["description"],
            payload["start_at"],
            payload["end_at"],
            payload["category"],
            now_str(),
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM events WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return jsonify(event=_serialize(row)), 201


@bp.patch("/api/events/<int:event_id>")
def api_update(event_id):
    db = get_db()
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return jsonify(error="Event not found."), 404

    try:
        payload = _validated_payload(row["category"])
    except ValueError as error:
        return jsonify(error=str(error)), 400

    db.execute(
        """
        UPDATE events
        SET title = ?, description = ?, start_at = ?, end_at = ?, category = ?
        WHERE id = ?
        """,
        (
            payload["title"],
            payload["description"],
            payload["start_at"],
            payload["end_at"],
            payload["category"],
            event_id,
        ),
    )
    db.commit()
    updated = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return jsonify(event=_serialize(updated))


@bp.delete("/api/events/<int:event_id>")
def api_delete(event_id):
    db = get_db()
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return jsonify(error="Event not found."), 404
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    return jsonify(ok=True)
