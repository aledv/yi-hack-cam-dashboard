"""Stalled-recording check: a camera that keeps sending motion events over MQTT
but no longer uploads clips is stuck (seen on yi-hack cams after days of uptime:
motion detection still works, the recorder does not). Per camera in config.yml:

    stall_check: alert    # notify only
    stall_check: reboot   # notify and reboot the camera (cgi-bin/reboot.sh)

Leave it out to skip the camera. Some cams do not come back from a software
reboot (they need a power cycle), so use `alert` for those.

Rules (env vars, defaults in brackets):
- stalled = at least STALL_MIN_MOTION [5] motion events in the last
  STALL_WINDOW_HOURS [2] hours (ignoring the last 15 min, whose clip may still be
  uploading) and no clip newer than the start of the window;
- at most one reboot every STALL_REBOOT_GAP_HOURS [6] hours per camera, and no
  second reboot while the camera has not recovered: then a notification only;
- cameras switched off on purpose (SWITCH_ON=no) or unreachable are skipped;
- a notification when the camera is stalled, rebooted and back to normal.

The state (stalled since, last reboot) lives in app_settings, so a container
restart does not trigger an extra reboot."""

import asyncio
import logging
import os
import time
from urllib.parse import urlsplit, urlunsplit

import cameras
import config
import notifier
import recordings
from i18n import t

logger = logging.getLogger("camera-app.stall_check")

INTERVAL_SECONDS = 600
UPLOAD_GRACE_SECONDS = 15 * 60
STATE_KEY = "stall_state"
MODES = ("alert", "reboot")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def reboot_url_for(cam: dict) -> str | None:
    """Explicit `reboot_url` wins; otherwise /cgi-bin/reboot.sh on the host of status_url."""
    if cam.get("reboot_url"):
        return cam["reboot_url"]
    if not cam.get("status_url"):
        return None
    parts = urlsplit(cam["status_url"])
    return urlunsplit((parts.scheme, parts.netloc, "/cgi-bin/reboot.sh", "", ""))


def is_stalled(camera: str, now: float, since: float) -> bool:
    """Enough motion since `since` (minus the upload grace) and no clip since then."""
    end = now - UPLOAD_GRACE_SECONDS
    if end <= since:
        return False
    motion = recordings.count_motion_between(camera, since, end)
    if motion < _env_float("STALL_MIN_MOTION", 5):
        return False
    latest = recordings.latest_recording_mtime(camera)
    return latest is None or latest < since


def decide(state: dict, stalled: bool, latest_clip: float | None, mode: str, now: float) -> tuple[str | None, dict]:
    """Pure state machine. Returns (action, new state); action is one of
    None, "reboot", "alert", "still_stalled", "recovered"."""
    state = dict(state)
    reboot_gap = _env_float("STALL_REBOOT_GAP_HOURS", 6) * 3600
    if state.get("stalled_since"):
        if latest_clip is not None and latest_clip >= state["stalled_since"]:
            return "recovered", {"last_reboot": state.get("last_reboot")}
        if stalled and not state.get("still_notified"):
            state["still_notified"] = True
            return "still_stalled", state
        return None, state
    if not stalled:
        return None, state
    state["stalled_since"] = now
    last_reboot = state.get("last_reboot") or 0
    if mode == "reboot" and now - last_reboot >= reboot_gap:
        state["last_reboot"] = now
        return "reboot", state
    return "alert", state


def _load_state() -> dict:
    state = recordings.get_setting(STATE_KEY, {})
    return state if isinstance(state, dict) else {}


async def check_camera(cam: dict, state: dict, now: float) -> dict:
    mode = cam.get("stall_check")
    name = cam["name"]
    if cam.get("status_url"):
        switched_on = await cameras.camera_status(cam["status_url"])
        if switched_on is not True:  # off on purpose, or unreachable
            return state
    window = _env_float("STALL_WINDOW_HOURS", 2) * 3600
    since = max(now - window, state.get("last_reboot") or 0)
    stalled = await asyncio.to_thread(is_stalled, name, now, since)
    latest = await asyncio.to_thread(recordings.latest_recording_mtime, name)
    action, new_state = decide(state, stalled, latest, mode, now)
    hours = f"{window / 3600:g}"
    if action == "reboot":
        url = reboot_url_for(cam)
        ok = bool(url) and await cameras.camera_power(url)
        logger.warning(f"{name}: motion without clips for {hours}h, reboot {'sent' if ok else 'FAILED'}")
        key = "stall_rebooted" if ok else "stall_reboot_failed"
        await notifier.notify(t(key, camera=name, hours=hours))
    elif action == "alert":
        logger.warning(f"{name}: motion without clips for {hours}h")
        await notifier.notify(t("stall_alert", camera=name, hours=hours))
    elif action == "still_stalled":
        logger.warning(f"{name}: still no clips after the reboot")
        await notifier.notify(t("stall_still", camera=name))
    elif action == "recovered":
        logger.info(f"{name}: clips are back")
        await notifier.notify(t("stall_recovered", camera=name))
    return new_state


async def run_once(now: float | None = None):
    now = now or time.time()
    states = _load_state()
    for cam in config.get_cameras():
        if cam.get("stall_check") not in MODES:
            continue
        try:
            states[cam["name"]] = await check_camera(cam, states.get(cam["name"], {}), now)
        except Exception as e:
            logger.warning(f"Stall check of {cam['name']} failed: {type(e).__name__}")
    recordings.set_setting(STATE_KEY, states)


async def loop():
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        await run_once()
