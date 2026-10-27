"""Subscribes to each camera's MQTT motion topic (yi-hack publishes e.g.
`yicam/motion_detection` with `motion_start`) and triggers the motion popup,
the "motion today" counters and the notifications from there.

MQTT events are lighter than watching the recordings folder (no ffmpeg or DB
work on every new file) and are the same signal other automations (Home
Assistant, Homebridge) already use, so "motion happened" has a single source
of truth.
"""

import logging
import os
import threading
import time

import config
import events
import notifier
import notify_schedule
import notify_settings
import paho.mqtt.client as mqtt
import recordings
from i18n import t

logger = logging.getLogger("camera-app.mqtt")

MQTT_HOST = os.environ.get("MQTT_HOST")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER")
MQTT_PASS = os.environ.get("MQTT_PASS")

_client: mqtt.Client | None = None
_connected = False

# Last notification time per camera (cooldown) and motion events whose clip
# should follow as a second message once it is uploaded. In memory only.
_last_notified: dict[str, float] = {}
_pending_clip: dict[str, float] = {}
_state_lock = threading.Lock()


def is_connected() -> bool:
    return _connected


def _camera_for_topic(topic: str) -> dict | None:
    for cam in config.get_cameras():
        if cam.get("mqtt_topic") == topic:
            return cam
    return None


def _latest_thumbnail(camera_name: str) -> str | None:
    """Best-effort: attach a preview of the most recent recording to the
    notification. Returns None if there's nothing indexed yet (e.g. the
    file hasn't been written/picked up by the watcher when MQTT fires)."""
    recs = recordings.list_recordings(camera_name)
    if not recs:
        return None
    latest = recs[0]  # already ordered by mtime desc
    return latest["thumbnail"] or recordings.ensure_thumbnail(latest["path"])


def _on_message(client, userdata, msg):
    cam = _camera_for_topic(msg.topic)
    if not cam:
        return

    payload = msg.payload.decode("utf-8", errors="ignore").strip()
    expected = cam.get("mqtt_message")
    if expected is not None and payload != expected:
        return  # e.g. ignore "motion_stop" if only "motion_start" configured

    ts = time.time()
    try:
        recordings.add_motion_event(cam["name"], ts)
    except Exception as e:
        logger.warning(f"Motion event for {cam['name']} not saved: {e}")

    events.broadcast_threadsafe(
        {
            "camera": cam["name"],
            "ts": ts,
            "mqtt_topic": msg.topic,
        }
    )

    settings = recordings.get_camera_settings(cam["name"])
    if not settings["notify"] or not notifier.enabled_channels():
        return
    if not notify_schedule.is_active(settings["schedule"]):
        logger.info(f"Motion on {cam['name']} outside its notification schedule: not notified")
        return
    rules = notify_settings.get()
    if rules["paused_until"]:
        logger.info(f"Motion on {cam['name']}: notifications paused, not notified")
        return
    with _state_lock:
        last = _last_notified.get(cam["name"], 0)
        if ts - last < rules["cooldown_min"] * 60:
            logger.info(f"Motion on {cam['name']}: within the {rules['cooldown_min']} min gap, not notified")
            return
        _last_notified[cam["name"]] = ts
        if rules["send_video"]:
            _pending_clip[cam["name"]] = ts

    thumb = _latest_thumbnail(cam["name"])
    notifier.notify_sync(t("notify_motion", camera=cam["name"]), file_path=thumb)


def _on_new_clip(camera: str, path) -> None:
    """Watcher callback: the first clip of a camera uploaded within the
    CLIP_MATCH window of a notified motion event is sent as a follow-up."""
    now = time.time()
    with _state_lock:
        ts = _pending_clip.get(camera)
        if ts is None or not (ts - recordings.CLIP_MATCH_BEFORE <= now <= ts + recordings.CLIP_MATCH_AFTER):
            if ts is not None and now > ts + recordings.CLIP_MATCH_AFTER:
                _pending_clip.pop(camera, None)
            return
        _pending_clip.pop(camera, None)
    threading.Thread(target=_send_clip, args=(camera, ts, path), daemon=True).start()


def _send_clip(camera: str, ts: float, path) -> None:
    if not _wait_upload_complete(path):
        logger.info(f"Clip of {camera} not complete in time, not sent")
        return
    when = time.strftime("%H:%M", time.localtime(ts))
    notifier.notify_sync(t("notify_motion_clip", camera=camera, time=when), file_path=str(path))


def _wait_upload_complete(path, interval: float = 3, timeout: float = 180) -> bool:
    """The watcher sees the file as soon as the FTP upload starts: wait until
    its size stops changing."""
    deadline = time.time() + timeout
    last = -1
    while time.time() < deadline:
        try:
            size = os.path.getsize(path)
        except OSError:
            return False
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(interval)
    return False


def _on_connect(client, userdata, flags, rc):
    global _connected
    if rc == 0:
        _connected = True
        logger.info(f"MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
        for cam in config.get_cameras():
            topic = cam.get("mqtt_topic")
            if topic:
                client.subscribe(topic)
    else:
        _connected = False
        logger.warning(f"MQTT connection refused by the broker (rc={rc})")


def _on_disconnect(client, userdata, rc):
    global _connected
    _connected = False
    if rc != 0:
        logger.warning(f"MQTT disconnected unexpectedly (rc={rc}), will reconnect")


def start_mqtt_listener():
    """Returns None if MQTT_HOST isn't set -- MQTT notifications are
    opt-in, the app works fine without a broker configured. Logs the
    outcome either way, visible via `docker logs camera-app`."""
    global _client
    if not MQTT_HOST:
        logger.info("MQTT_HOST not set: motion events via MQTT disabled")
        return None

    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message = _on_message
    recordings.clip_listeners.append(_on_new_clip)

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as e:
        logger.warning(f"MQTT broker not reachable ({MQTT_HOST}:{MQTT_PORT}): {type(e).__name__}")
        return None

    thread = threading.Thread(target=client.loop_forever, daemon=True)
    thread.start()
    _client = client
    return client


def publish_test_event(cam: dict) -> bool:
    """Publishes the camera's own configured motion message to its own
    topic -- since this app is already subscribed to it, the broker
    echoes it straight back into _on_message exactly as if the real
    camera had sent it. Good end-to-end test of the whole pipeline
    (MQTT round-trip -> in-app popup -> notifier), not just a fake UI
    event. Returns False if MQTT isn't connected or the camera has no
    mqtt_topic configured."""
    topic = cam.get("mqtt_topic")
    message = cam.get("mqtt_message", "motion_start")
    if not topic or not _client or not _connected:
        return False
    result = _client.publish(topic, payload=message)
    return result.rc == mqtt.MQTT_ERR_SUCCESS
