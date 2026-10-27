"""App-wide motion notification settings, set on the Cameras page and stored
in the DB (app_settings): a minimum gap between two notifications of the same
camera, whether to follow up with the clip, and a global pause."""

import time
from datetime import datetime, timedelta

import recordings

DEFAULTS = {"cooldown_min": 10, "send_video": True}
COOLDOWN_CHOICES = (0, 1, 5, 10, 15, 30, 60)
RESUME_HOUR = 7  # "pause until tomorrow" ends at 07:00 local time


def get() -> dict:
    stored = recordings.get_setting("notify_settings", {}) or {}
    settings = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    settings["paused_until"] = paused_until()
    return settings


def save(cooldown_min: int, send_video: bool):
    if cooldown_min not in COOLDOWN_CHOICES:
        cooldown_min = DEFAULTS["cooldown_min"]
    recordings.set_setting("notify_settings", {"cooldown_min": cooldown_min, "send_video": send_video})


def paused_until() -> float | None:
    """End of the current pause (epoch seconds), or None if not paused."""
    until = recordings.get_setting("notify_paused_until", 0) or 0
    return until if until > time.time() else None


def pause(mode: str, now: datetime | None = None):
    """mode: "1h", "tomorrow" (until RESUME_HOUR tomorrow) or "resume"."""
    now = now or datetime.now()
    if mode == "1h":
        until = now + timedelta(hours=1)
    elif mode == "tomorrow":
        until = (now + timedelta(days=1)).replace(hour=RESUME_HOUR, minute=0, second=0, microsecond=0)
    else:
        recordings.set_setting("notify_paused_until", 0)
        return
    recordings.set_setting("notify_paused_until", until.timestamp())
