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
            for path in ("/", "/recordings", "/cameras", "/api/system/status"):
                resp = client.get(path)
                self.assertEqual(resp.status_code, 200, f"{path} {lang}")
            page = client.get("/cameras").text
            self.assertIn(f'<html lang="{lang}">', page)
            for word in words:
                self.assertIn(word, page)

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
