"""Unit tests for the stalled-recording check (decide() state machine and is_stalled())."""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HOUR = 3600
NOW = 1_800_000_000.0


class DecideTest(unittest.TestCase):
    def setUp(self):
        import stall_check

        self.s = stall_check

    def test_not_stalled_nothing_happens(self):
        self.assertEqual(self.s.decide({}, False, NOW - 60, "reboot", NOW), (None, {}))

    def test_stalled_reboot_mode_reboots(self):
        action, state = self.s.decide({}, True, NOW - 5 * HOUR, "reboot", NOW)
        self.assertEqual(action, "reboot")
        self.assertEqual(state, {"stalled_since": NOW, "last_reboot": NOW})

    def test_stalled_alert_mode_only_alerts(self):
        action, state = self.s.decide({}, True, None, "alert", NOW)
        self.assertEqual(action, "alert")
        self.assertNotIn("last_reboot", state)

    def test_recent_reboot_means_alert(self):
        action, _ = self.s.decide({"last_reboot": NOW - 2 * HOUR}, True, None, "reboot", NOW)
        self.assertEqual(action, "alert")

    def test_no_second_reboot_before_recovery(self):
        state = {"stalled_since": NOW - 10 * HOUR, "last_reboot": NOW - 10 * HOUR}
        action, state = self.s.decide(state, True, NOW - 20 * HOUR, "reboot", NOW)
        self.assertEqual(action, "still_stalled")
        action, state = self.s.decide(state, True, NOW - 20 * HOUR, "reboot", NOW + 600)
        self.assertIsNone(action)
        self.assertEqual(state["last_reboot"], NOW - 10 * HOUR)

    def test_recovered_when_a_clip_arrives(self):
        state = {"stalled_since": NOW - HOUR, "last_reboot": NOW - HOUR}
        action, state = self.s.decide(state, False, NOW - 60, "reboot", NOW)
        self.assertEqual(action, "recovered")
        self.assertEqual(state, {"last_reboot": NOW - HOUR})

    def test_reboot_url_from_status_url(self):
        cam = {"status_url": "http://192.168.1.50/cgi-bin/get_configs.sh?conf=camera"}
        self.assertEqual(self.s.reboot_url_for(cam), "http://192.168.1.50/cgi-bin/reboot.sh")
        self.assertEqual(self.s.reboot_url_for({"reboot_url": "http://x/r"}), "http://x/r")
        self.assertIsNone(self.s.reboot_url_for({}))


class IsStalledTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        import recordings

        self.r = importlib.reload(recordings)
        self.r.init_db()
        import stall_check

        self.s = importlib.reload(stall_check)

    def tearDown(self):
        self.tmp.cleanup()

    def _motion(self, n: int, start: float):
        for i in range(n):
            self.r.add_motion_event("cam1", start + i * 60)

    def _clip(self, mtime: float):
        with self.r._connect() as conn:
            conn.execute("INSERT INTO recordings (path, camera, mtime) VALUES (?, 'cam1', ?)", (f"/r/{mtime}", mtime))

    def test_motion_without_clips_is_stalled(self):
        self._motion(6, NOW - 90 * 60)
        self._clip(NOW - 5 * HOUR)
        self.assertTrue(self.s.is_stalled("cam1", NOW, NOW - 2 * HOUR))

    def test_clip_in_window_is_fine(self):
        self._motion(6, NOW - 90 * 60)
        self._clip(NOW - 80 * 60)
        self.assertFalse(self.s.is_stalled("cam1", NOW, NOW - 2 * HOUR))

    def test_little_motion_is_fine(self):
        self._motion(3, NOW - 90 * 60)
        self.assertFalse(self.s.is_stalled("cam1", NOW, NOW - 2 * HOUR))

    def test_recent_motion_may_still_be_uploading(self):
        self._motion(6, NOW - 10 * 60)
        self.assertFalse(self.s.is_stalled("cam1", NOW, NOW - 2 * HOUR))


if __name__ == "__main__":
    unittest.main()
