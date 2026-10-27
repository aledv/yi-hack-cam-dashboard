"""Motion notification rules in mqtt_listener: schedule, pause, cooldown and
the clip follow-up (no broker needed: _on_message is called directly)."""

import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CAMERA = {"name": "garden", "mqtt_topic": "yicam/motion", "mqtt_message": "motion_start", "recordings_path": "/x"}


class MqttRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        import config
        import mqtt_listener
        import notify_settings
        import recordings

        self.recordings = importlib.reload(recordings)
        self.recordings.init_db()
        self.settings = importlib.reload(notify_settings)
        self.mqtt = importlib.reload(mqtt_listener)
        config._cameras = [dict(CAMERA)]
        self.sent = []
        patches = [
            mock.patch.object(self.mqtt.notifier, "enabled_channels", return_value=["webhook"]),
            mock.patch.object(
                self.mqtt.notifier,
                "notify_sync",
                side_effect=lambda m, file_path=None: self.sent.append((m, file_path)),
            ),
            mock.patch.object(self.mqtt.events, "broadcast_threadsafe"),
            mock.patch.object(self.mqtt, "_latest_thumbnail", return_value=None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def record(self, message, file_path=None):
        self.sent.append((message, file_path))

    def tearDown(self):
        self.tmp.cleanup()

    def motion(self):
        self.mqtt._on_message(None, None, SimpleNamespace(topic="yicam/motion", payload=b"motion_start"))

    def test_cooldown(self):
        self.settings.save(10, False)
        self.motion()
        self.motion()
        self.assertEqual(len(self.sent), 1)
        self.settings.save(0, False)
        self.motion()
        self.assertEqual(len(self.sent), 2)

    def test_pause(self):
        self.settings.pause("1h")
        self.motion()
        self.assertEqual(self.sent, [])
        self.settings.pause("resume")
        self.motion()
        self.assertEqual(len(self.sent), 1)

    def test_outside_schedule(self):
        self.recordings.set_camera_schedule("garden", {"days": [], "ranges": []})
        self.motion()
        self.assertEqual(self.sent, [])

    def test_clip_follows_notified_motion(self):
        self.settings.save(10, True)
        self.motion()
        clip = Path(self.tmp.name) / "clip.mp4"
        clip.write_bytes(b"x" * 100)
        with (
            mock.patch.object(self.mqtt, "_wait_upload_complete", return_value=True),
            mock.patch.object(
                self.mqtt.threading,
                "Thread",
                side_effect=lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
            ),
        ):
            self.mqtt._on_new_clip("garden", clip)
            self.mqtt._on_new_clip("garden", clip)  # only the first clip
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1][1], str(clip))

    def test_wait_upload_complete(self):
        clip = Path(self.tmp.name) / "c.mp4"
        clip.write_bytes(b"abc")
        self.assertTrue(self.mqtt._wait_upload_complete(clip, interval=0.01, timeout=1))
        self.assertFalse(self.mqtt._wait_upload_complete(Path(self.tmp.name) / "missing.mp4", interval=0.01))

    def test_pause_until_tomorrow_morning(self):
        from datetime import datetime

        self.settings.pause("tomorrow", now=datetime(2026, 10, 27, 21, 30))
        until = self.recordings.get_setting("notify_paused_until")
        self.assertEqual(datetime.fromtimestamp(until), datetime(2026, 10, 28, 7, 0))
        self.assertLess(time.time(), until + 10**9)


if __name__ == "__main__":
    unittest.main()
