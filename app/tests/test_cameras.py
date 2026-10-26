"""Unit tests for the camera helpers in cameras.py (stdlib unittest, no network)."""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cameras
import httpx


class InfoUrlTest(unittest.TestCase):
    def test_derived_from_status_url(self):
        cam = {"status_url": "http://192.168.1.50/cgi-bin/get_configs.sh?conf=camera"}
        self.assertEqual(cameras.info_url_for(cam), "http://192.168.1.50/cgi-bin/status.json")

    def test_explicit_info_url_wins(self):
        cam = {"status_url": "http://a/x", "info_url": "http://b/status.json"}
        self.assertEqual(cameras.info_url_for(cam), "http://b/status.json")

    def test_none_without_status_url(self):
        self.assertIsNone(cameras.info_url_for({}))


class ParseInfoTest(unittest.TestCase):
    def test_uptime_format(self):
        self.assertEqual(cameras.format_uptime(328428.05), "3d 19h")
        self.assertEqual(cameras.format_uptime(3 * 3600 + 5 * 60), "3h 5m")
        self.assertEqual(cameras.format_uptime(59), "0m")

    def test_parse(self):
        info = cameras.parse_camera_info({"wlan_strength": "70", "uptime": "7300.5", "fw_version": "0.3.9"})
        self.assertEqual(info, {"wifi": 70, "uptime": "2h 1m", "fw": "0.3.9"})

    def test_parse_missing_or_malformed(self):
        info = cameras.parse_camera_info({"wlan_strength": "n/a"})
        self.assertEqual(info, {"wifi": None, "uptime": None, "fw": None})


class FakeClient:
    """Stands in for httpx.AsyncClient: pops one outcome per request."""

    outcomes: list = []
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        FakeClient.calls += 1
        outcome = FakeClient.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def run_with(outcomes, coro_factory):
    FakeClient.outcomes = list(outcomes)
    FakeClient.calls = 0
    with (
        mock.patch.object(cameras.httpx, "AsyncClient", FakeClient),
        mock.patch.object(cameras.asyncio, "sleep", mock.AsyncMock()),
    ):
        return asyncio.run(coro_factory())


class RetryTest(unittest.TestCase):
    def test_power_retries_then_succeeds(self):
        ok = run_with(
            [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.Response(200)],
            lambda: cameras.camera_power("http://cam/on"),
        )
        self.assertTrue(ok)
        self.assertEqual(FakeClient.calls, 3)

    def test_power_gives_up(self):
        ok = run_with([httpx.ConnectError("down")] * 3, lambda: cameras.camera_power("http://cam/on"))
        self.assertFalse(ok)
        self.assertEqual(FakeClient.calls, 3)

    def test_status_on_off_unknown(self):
        on = run_with([httpx.Response(200, json={"SWITCH_ON": "yes"})], lambda: cameras.camera_status("http://cam/s"))
        off = run_with([httpx.Response(200, json={"SWITCH_ON": "no"})], lambda: cameras.camera_status("http://cam/s"))
        odd = run_with([httpx.Response(200, json={"other": 1})], lambda: cameras.camera_status("http://cam/s"))
        down = run_with([httpx.ConnectError("x")] * 2, lambda: cameras.camera_status("http://cam/s"))
        self.assertEqual((on, off, odd, down), (True, False, None, None))

    def test_status_retries_after_server_error(self):
        on = run_with(
            [httpx.Response(502), httpx.Response(200, json={"SWITCH_ON": "yes"})],
            lambda: cameras.camera_status("http://cam/s"),
        )
        self.assertTrue(on)

    def test_info_offline_and_not_json(self):
        down = run_with([httpx.ConnectError("x")] * 2, lambda: cameras.camera_info("http://cam/status.json"))
        bad = run_with([httpx.Response(200, text="<html>")], lambda: cameras.camera_info("http://cam/status.json"))
        self.assertIsNone(down)
        self.assertIsNone(bad)


if __name__ == "__main__":
    unittest.main()
