"""HTTP helpers to control and query the cameras (yi-hack CGI endpoints:
on/off switch, status, uptime/WiFi/firmware)."""

import asyncio
import logging
from urllib.parse import urlsplit, urlunsplit

import httpx
from i18n import t

logger = logging.getLogger("camera-app.cameras")


# The Yi cameras' tiny web server often drops or stalls a request: a short
# connect timeout plus a few quick retries turns most of those into a success
# without making an offline camera hold the page for long.
_CAMERA_TIMEOUT = httpx.Timeout(4.0, connect=1.5)


async def _camera_get(url: str, attempts: int = 2) -> httpx.Response | None:
    """GET to a camera with retries. Returns the response, or None if every
    attempt failed (unreachable, timeout, or HTTP 5xx)."""
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=_CAMERA_TIMEOUT) as client:
                resp = await client.get(url)
            if resp.status_code < 500:
                return resp
        except Exception as e:
            logger.debug(f"camera GET {url} attempt {attempt + 1} failed: {type(e).__name__}")
        if attempt < attempts - 1:
            await asyncio.sleep(0.4)
    return None


async def camera_power(url: str) -> bool:
    resp = await _camera_get(url, attempts=3)
    return resp is not None and resp.status_code < 400


async def camera_status(status_url: str) -> bool | None:
    """Returns True (on) / False (off) / None if unreachable or the
    response doesn't contain a recognizable SWITCH_ON field."""
    resp = await _camera_get(status_url)
    if resp is None or resp.status_code >= 400:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if "SWITCH_ON" not in data:
        return None
    return str(data["SWITCH_ON"]).strip().lower() == "yes"


def info_url_for(cam: dict) -> str | None:
    """URL of the camera's status.json (yi-hack: uptime, WiFi signal, firmware).
    Explicit `info_url` in config.yml wins; otherwise it is derived from the
    host of `status_url`."""
    if cam.get("info_url"):
        return cam["info_url"]
    if not cam.get("status_url"):
        return None
    parts = urlsplit(cam["status_url"])
    return urlunsplit((parts.scheme, parts.netloc, "/cgi-bin/status.json", "", ""))


def format_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}{t('days_short')} {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def parse_camera_info(data: dict) -> dict:
    """Picks the fields shown in the Cameras page out of yi-hack's
    status.json; anything missing or malformed becomes None."""

    def number(key):
        try:
            return float(data[key])
        except (KeyError, TypeError, ValueError):
            return None

    wifi = number("wlan_strength")
    uptime = number("uptime")
    return {
        "wifi": int(wifi) if wifi is not None else None,
        "uptime": format_uptime(uptime) if uptime is not None else None,
        "fw": str(data["fw_version"]) if data.get("fw_version") else None,
    }


async def camera_info(info_url: str) -> dict | None:
    """WiFi signal / uptime / firmware of a camera, or None if it doesn't answer."""
    resp = await _camera_get(info_url)
    if resp is None or resp.status_code >= 400:
        return None
    try:
        return parse_camera_info(resp.json())
    except ValueError:
        return None
