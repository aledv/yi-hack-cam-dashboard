"""Per-camera notification schedule: the weekdays and time ranges in which a
motion event sends a notification. Popups, counters and the Stats page record
every event regardless.

A schedule is {"days": [0..6], "ranges": [["HH:MM", "HH:MM"], ...]} with
Monday = 0. No ranges means all day on the selected days. A range whose end is
earlier than its start runs past midnight and belongs to the day it starts on:
Friday 22:00-07:00 also covers Saturday until 07:00. Equal start and end means
the whole day. Times are the container's local time (set TZ, e.g. Europe/Rome).
"""

import re
from datetime import datetime

ALL_DAYS = list(range(7))
DEFAULT = {"days": ALL_DAYS, "ranges": []}
MAX_RANGES = 6

_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def normalize(days, starts, ends) -> dict:
    """Builds a schedule from form fields, dropping invalid or empty values."""
    clean_days = sorted({int(d) for d in days if str(d).isdigit() and 0 <= int(d) <= 6})
    ranges = []
    for start, end in zip(starts, ends, strict=False):
        start, end = (start or "").strip()[:5], (end or "").strip()[:5]
        if _TIME.match(start) and _TIME.match(end) and [start, end] not in ranges:
            ranges.append([start, end])
    return {"days": clean_days, "ranges": ranges[:MAX_RANGES]}


def is_default(schedule: dict) -> bool:
    return schedule["days"] == ALL_DAYS and not schedule["ranges"]


def is_active(schedule: dict, now: datetime | None = None) -> bool:
    """True if a notification sent at `now` (default: local time) falls in the schedule."""
    now = now or datetime.now()
    days = set(schedule.get("days", ALL_DAYS))
    ranges = schedule.get("ranges") or []
    today, yesterday = now.weekday(), (now.weekday() - 1) % 7
    if not ranges:
        return today in days
    minute = now.hour * 60 + now.minute
    for start, end in ranges:
        a, b = _minutes(start), _minutes(end)
        if a == b:
            if today in days:
                return True
        elif a < b:
            if today in days and a <= minute < b:
                return True
        elif (minute >= a and today in days) or (minute < b and yesterday in days):
            return True
    return False


def summary(schedule: dict, day_names: list[str], labels: dict[str, str]) -> str:
    """Short text for the Cameras page, e.g. "Mon–Fri · 22:00–07:00"."""
    if is_default(schedule):
        return labels["always"]
    days = schedule["days"]
    if not days:
        return labels["never"]
    if days == ALL_DAYS:
        days_text = labels["every_day"]
    elif days == [0, 1, 2, 3, 4]:
        days_text = f"{day_names[0]}–{day_names[4]}"
    elif days == [5, 6]:
        days_text = f"{day_names[5]}–{day_names[6]}"
    else:
        days_text = " ".join(day_names[d] for d in days)
    ranges = ", ".join(f"{a}–{b}" for a, b in schedule["ranges"]) or labels["all_day"]
    return f"{days_text} · {ranges}"
