"""Unit tests for notifier.py: channel selection and the requests each channel sends
(httpx is mocked, nothing leaves the machine)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import notifier

ALL = {
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "TELEGRAM_CHAT_ID": "42",
    "NTFY_URL": "https://ntfy.example/topic",
    "NTFY_TOKEN": "tk",
    "WEBHOOK_URL": "http://relay.example/notify",
}


class Recorder:
    """Stands in for httpx.Client and records every request."""

    calls: list = []
    status = 200

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _record(self, method, url, **kwargs):
        Recorder.calls.append((method, url, kwargs))
        return httpx.Response(Recorder.status)

    def post(self, url, **kwargs):
        return self._record("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._record("PUT", url, **kwargs)


class NotifierTest(unittest.TestCase):
    def setUp(self):
        Recorder.calls = []
        Recorder.status = 200
        patcher = mock.patch.object(notifier.httpx, "Client", Recorder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def env(self, **values):
        return mock.patch.dict(os.environ, values, clear=True)

    def test_enabled_channels(self):
        with self.env():
            self.assertEqual(notifier.enabled_channels(), [])
        with self.env(TELEGRAM_BOT_TOKEN="x"):  # chat id missing
            self.assertEqual(notifier.enabled_channels(), [])
        with self.env(**ALL):
            self.assertEqual(notifier.enabled_channels(), ["telegram", "ntfy", "webhook"])

    def test_text_to_every_channel(self):
        with self.env(**ALL):
            result = notifier.notify_sync("Motion detected: garden")
        self.assertEqual(result, {"telegram": True, "ntfy": True, "webhook": True})
        tg, ntfy, hook = Recorder.calls
        self.assertEqual(tg[1], "https://api.telegram.org/bot123:abc/sendMessage")
        self.assertEqual(tg[2]["data"], {"chat_id": "42", "text": "Motion detected: garden"})
        self.assertEqual(ntfy[:2], ("POST", "https://ntfy.example/topic"))
        self.assertEqual(ntfy[2]["headers"]["Authorization"], "Bearer tk")
        self.assertEqual(ntfy[2]["content"], b"Motion detected: garden")
        self.assertEqual(hook[2]["data"], {"message": "Motion detected: garden"})
        self.assertIsNone(hook[2]["files"])

    def test_snapshot_attached(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"jpeg")
        self.addCleanup(os.unlink, f.name)
        name = os.path.basename(f.name)
        with self.env(**ALL):
            notifier.notify_sync("Motion", file_path=f.name)
        tg, ntfy, hook = Recorder.calls
        self.assertTrue(tg[1].endswith("/sendPhoto"))
        self.assertEqual(tg[2]["files"], {"photo": (name, b"jpeg")})
        self.assertEqual(tg[2]["data"]["caption"], "Motion")
        self.assertEqual(ntfy[0], "PUT")
        self.assertEqual(ntfy[2]["params"], {"message": "Motion", "filename": name})
        self.assertEqual(ntfy[2]["content"], b"jpeg")
        self.assertEqual(hook[2]["files"], {"file": (name, b"jpeg")})

    def test_failure_is_reported_not_raised(self):
        Recorder.status = 500
        with self.env(**ALL):
            self.assertFalse(notifier.send("telegram", "x"))
        with self.env(**ALL), mock.patch.object(Recorder, "post", side_effect=httpx.ConnectError("down")):
            self.assertFalse(notifier.send("webhook", "x"))

    def test_disabled_or_unknown_channel(self):
        with self.env(NTFY_URL="https://ntfy.example/t"):
            self.assertFalse(notifier.send("telegram", "x"))
            self.assertFalse(notifier.send("email", "x"))
        self.assertEqual(Recorder.calls, [])


if __name__ == "__main__":
    unittest.main()
