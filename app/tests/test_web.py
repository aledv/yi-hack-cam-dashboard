"""Smoke tests: every page renders in both languages and the EN/IT switch works
(FastAPI TestClient, no cameras or MQTT needed)."""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$" + "x" * 53)
os.chdir(Path(__file__).resolve().parent.parent)  # templates/ and static/ are relative

import auth
import config
import main
import recordings
from fastapi.testclient import TestClient

CAMERA = {"name": "garden", "rtsp_main": "rtsp://192.168.1.50/ch0_0.h264", "mqtt_topic": "yicam/motion"}


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # other test modules reload recordings with their own (deleted) DATA_DIR
        os.environ["DATA_DIR"] = tempfile.mkdtemp()
        importlib.reload(recordings)
        recordings.init_db()
        config._cameras = [dict(CAMERA, ip="192.168.1.50")]

    def client(self, lang=None):
        client = TestClient(main.app)
        client.cookies.set(auth.SESSION_COOKIE, auth.create_session_cookie())
        if lang:
            client.cookies.set(main.LANG_COOKIE, lang)
        return client

    def test_login_required(self):
        resp = TestClient(main.app).get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_pages_render_in_both_languages(self):
        expected = {"en": ("Recordings", "Cameras"), "it": ("Registrazioni", "Telecamere")}
        for lang, words in expected.items():
            client = self.client(lang)
            for path in ("/", "/recordings", "/cameras", "/stats", "/api/system/status"):
                resp = client.get(path)
                self.assertEqual(resp.status_code, 200, f"{path} {lang}")
            page = client.get("/cameras").text
            self.assertIn(f'<html lang="{lang}">', page)
            for word in words:
                self.assertIn(word, page)

    def test_motion_range(self):
        recordings.add_motion_event("garden", 1_000_000)
        recordings.add_motion_event("garden", 1_000_500)
        data = self.client().get("/api/motion/range", params={"start": 1_000_100, "end": 1_001_000}).json()
        self.assertEqual(data["cameras"], {"garden": [1_000_500]})
        self.assertEqual(data["oldest"], 1_000_000)

    def test_stats_page_lists_cameras(self):
        page = self.client("it").get("/stats").text
        self.assertIn('data-cam="garden"', page)
        self.assertIn("Statistiche", page)

    def test_schedule_saved_and_shown(self):
        client = self.client("en")
        resp = client.post(
            "/api/cameras/garden/schedule", data={"days": ["0", "1", "2", "3", "4"], "start": "22:00", "end": "07:00"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Mon–Fri · 22:00–07:00", resp.text)
        self.assertEqual(recordings.get_camera_settings("garden")["schedule"]["ranges"], [["22:00", "07:00"]])
        self.assertIn("Mon–Fri · 22:00–07:00", client.get("/cameras").text)
        self.assertEqual(client.post("/api/cameras/nope/schedule", data={}).status_code, 404)

    def test_camera_order_saved(self):
        config._cameras = [dict(CAMERA, ip="192.168.1.50"), dict(CAMERA, name="garage", mqtt_topic="yicam/g")]
        try:
            client = self.client()
            resp = client.post("/api/cameras/order", json={"order": ["garage", "unknown", "garden"]})
            self.assertEqual(resp.status_code, 204)
            self.assertEqual(recordings.get_setting("camera_order"), ["garage", "garden"])
            page = client.get("/").text
            self.assertLess(page.index('id="tile-garage"'), page.index('id="tile-garden"'))
        finally:
            recordings.set_setting("camera_order", [])
            config._cameras = [dict(CAMERA, ip="192.168.1.50")]

    def test_notify_rules(self):
        client = self.client("en")
        resp = client.post("/api/notify/settings", data={"cooldown_min": "30"})
        self.assertIn('value="30" selected', resp.text)
        self.assertEqual(main.notify_settings.get()["cooldown_min"], 30)
        self.assertFalse(main.notify_settings.get()["send_video"])
        self.assertIn("Paused until", client.post("/api/notify/pause", data={"mode": "1h"}).text)
        self.assertIsNotNone(main.notify_settings.paused_until())
        self.assertIn("Active", client.post("/api/notify/pause", data={"mode": "resume"}).text)
        self.assertIsNone(main.notify_settings.paused_until())
        client.post("/api/notify/settings", data={"cooldown_min": "10", "send_video": "on"})

    def test_stylesheet_is_versioned(self):
        self.assertRegex(self.client().get("/cameras").text, r'/static/style\.css\?v=[0-9a-f]{10}"')

    def test_login_page_has_switch(self):
        page = TestClient(main.app).get("/login").text
        self.assertIn('href="/lang/it"', page)

    def test_switch_sets_cookie_and_goes_back(self):
        client = self.client()
        resp = client.get(
            "/lang/it", headers={"referer": "http://cam.local/recordings?period=all"}, follow_redirects=False
        )
        self.assertEqual(resp.headers["location"], "/recordings?period=all")
        self.assertIn("lang=it", resp.headers["set-cookie"])

    def test_switch_never_redirects_elsewhere(self):
        resp = self.client().get("/lang/en", headers={"referer": "//evil.example/x"}, follow_redirects=False)
        self.assertTrue(resp.headers["location"].startswith("/"))
        self.assertFalse(resp.headers["location"].startswith("//"))

    def test_unknown_language_ignored(self):
        resp = self.client().get("/lang/xx", follow_redirects=False)
        self.assertNotIn("set-cookie", resp.headers)


if __name__ == "__main__":
    unittest.main()
