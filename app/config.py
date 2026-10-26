"""Loads config.yml and keeps it hot-reloaded (no container restart needed
when you add/edit a camera)."""

import os
import threading
from pathlib import Path
from urllib.parse import urlparse

import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Defaults to the container path; override with CONFIG_PATH for local runs
# outside Docker (e.g. CONFIG_PATH=../config.yml).
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.yml"))

_lock = threading.Lock()
_cameras: list[dict] = []


def _load():
    global _cameras
    with open(CONFIG_PATH) as f:
        data = yaml.safe_load(f) or {}
    cams = data.get("cameras", [])
    for cam in cams:
        cam.setdefault("ip", camera_ip(cam))
    with _lock:
        _cameras = cams


def camera_ip(cam: dict) -> str | None:
    """Host of the camera, taken from the first configured URL (ip in config.yml wins)."""
    for key in ("status_url", "rtsp_main", "rtsp_sub", "on_url"):
        host = urlparse(cam.get(key) or "").hostname
        if host:
            return host
    return None


def get_cameras() -> list[dict]:
    with _lock:
        return list(_cameras)


def get_camera(name: str) -> dict | None:
    for cam in get_cameras():
        if cam["name"] == name:
            return cam
    return None


class _ReloadHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if Path(event.src_path).name == CONFIG_PATH.name:
            _load()


def start_config_watcher():
    _load()
    observer = Observer()
    observer.schedule(_ReloadHandler(), str(CONFIG_PATH.parent), recursive=False)
    observer.daemon = True
    observer.start()
    return observer
