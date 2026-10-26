"""Indexes .mp4 recordings (recursively) into a small SQLite DB so listing
them stays fast even with thousands of files, instead of walking the
filesystem on every page load. A watchdog observer keeps the index in sync."""

import math
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

# Defaults to the container path; override with DATA_DIR for local runs
# outside Docker (e.g. DATA_DIR=../data).
DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "recordings.db"
THUMB_DIR = DATA_DIR / "thumbnails"
# Recordings on a network share (e.g. Samba/CIFS mounted from another host) don't
# raise inotify events for files written remotely: set RECORDINGS_POLL_SECONDS to
# use a polling watcher with that interval instead. Empty/0 = inotify (local disk).
POLL_SECONDS = float(os.environ.get("RECORDINGS_POLL_SECONDS") or 0)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()


def _connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with _lock, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recordings (
                path TEXT PRIMARY KEY,
                camera TEXT NOT NULL,
                mtime REAL NOT NULL,
                thumbnail TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS motion_events (
                camera TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS motion_events_camera_ts ON motion_events (camera, ts)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS camera_settings (
                camera TEXT PRIMARY KEY,
                notify INTEGER NOT NULL DEFAULT 1
            )
        """)


def get_camera_settings(camera: str) -> dict:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT notify FROM camera_settings WHERE camera = ?", (camera,)).fetchone()
    return {"notify": bool(row[0]) if row else True}  # default: notifications on


def set_camera_settings(camera: str, notify: bool):
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO camera_settings (camera, notify) VALUES (?, ?)
            ON CONFLICT(camera) DO UPDATE SET notify = excluded.notify
        """,
            (camera, int(notify)),
        )


MOTION_KEEP_DAYS = 30
# A clip lands on disk when the camera has finished recording and uploaded it,
# so it can be indexed up to a few minutes after the motion event.
CLIP_MATCH_BEFORE = 30
CLIP_MATCH_AFTER = 240


def add_motion_event(camera: str, ts: float):
    """Store one motion event (from MQTT) and drop the ones older than MOTION_KEEP_DAYS."""
    with _lock, _connect() as conn:
        conn.execute("INSERT INTO motion_events (camera, ts) VALUES (?, ?)", (camera, ts))
        conn.execute("DELETE FROM motion_events WHERE ts < ?", (ts - MOTION_KEEP_DAYS * 86400,))


def motion_events_since(since: float) -> dict[str, list[dict]]:
    """Motion events after `since`, newest first, per camera. Each event carries the
    path of the recording it most likely produced (first clip indexed in the
    CLIP_MATCH window), or None."""
    with _lock, _connect() as conn:
        events = conn.execute(
            "SELECT camera, ts FROM motion_events WHERE ts >= ? ORDER BY ts DESC", (since,)
        ).fetchall()
        clips = conn.execute(
            "SELECT camera, mtime, path FROM recordings WHERE mtime >= ? ORDER BY mtime ASC",
            (since - CLIP_MATCH_BEFORE,),
        ).fetchall()
    by_cam: dict[str, list[tuple[float, str]]] = {}
    for camera, mtime, path in clips:
        by_cam.setdefault(camera, []).append((mtime, path))
    result: dict[str, list[dict]] = {}
    for camera, ts in events:
        lo, hi = ts - CLIP_MATCH_BEFORE, ts + CLIP_MATCH_AFTER
        clip = next((path for mtime, path in by_cam.get(camera, []) if lo <= mtime <= hi), None)
        result.setdefault(camera, []).append({"ts": ts, "clip": clip})
    return result


def _make_thumbnail(video_path: Path) -> str | None:
    thumb_path = THUMB_DIR / f"{abs(hash(str(video_path)))}.jpg"
    if thumb_path.exists():
        return str(thumb_path)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=320:-1",
                str(thumb_path),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        return str(thumb_path)
    except Exception:
        return None


def index_file(video_path: Path, camera: str, generate_thumb: bool = True):
    thumb = _make_thumbnail(video_path) if generate_thumb else None
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO recordings (path, camera, mtime, thumbnail) VALUES (?, ?, ?, ?)",
            (str(video_path), camera, video_path.stat().st_mtime, thumb),
        )


def ensure_thumbnail(path: str) -> str | None:
    """Generate the thumbnail on demand (first time it's viewed) and cache
    it in the DB, instead of generating it for every file at startup."""
    thumb = _make_thumbnail(Path(path))
    if thumb:
        with _lock, _connect() as conn:
            conn.execute("UPDATE recordings SET thumbnail = ? WHERE path = ?", (thumb, path))
    return thumb


def remove_file(video_path: Path):
    with _lock, _connect() as conn:
        row = conn.execute("SELECT thumbnail FROM recordings WHERE path = ?", (str(video_path),)).fetchone()
        conn.execute("DELETE FROM recordings WHERE path = ?", (str(video_path),))
    if row and row[0]:
        Path(row[0]).unlink(missing_ok=True)


def list_recordings(camera: str | None = None) -> list[dict]:
    with _lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        if camera:
            rows = conn.execute(
                "SELECT * FROM recordings WHERE camera = ? ORDER BY mtime DESC",
                (camera,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM recordings ORDER BY mtime DESC").fetchall()
        return [dict(r) for r in rows]


RECENT_DAYS = 2
PAGE_SIZE = 30


def list_recordings_page(camera: str | None, page: int, only_recent: bool = True) -> dict:
    """Paginated listing for the Recordings page. only_recent limits to
    the last RECENT_DAYS days by default -- years of recordings otherwise
    make a single unpaginated query (and an infinite-scroll UI) slow."""
    page = max(1, page)
    conditions = []
    params: list = []
    if camera:
        conditions.append("camera = ?")
        params.append(camera)
    if only_recent:
        conditions.append("mtime >= ?")
        params.append(time.time() - RECENT_DAYS * 86400)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with _lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        total = conn.execute(f"SELECT COUNT(*) FROM recordings {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM recordings {where} ORDER BY mtime DESC LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages)
    return {"items": [dict(r) for r in rows], "page": page, "total_pages": total_pages, "total": total}


def neighbors(path: str) -> dict | None:
    """The recording at `path` plus the previous (older) and next (newer)
    recording of the same camera, for the prev/next arrows of the video
    viewer. Ties on mtime are broken by path so the order is stable."""
    with _lock, _connect() as conn:
        conn.row_factory = sqlite3.Row
        rec = conn.execute("SELECT * FROM recordings WHERE path = ?", (path,)).fetchone()
        if not rec:
            return None
        key = (rec["camera"], rec["mtime"], rec["mtime"], rec["path"])
        prev = conn.execute(
            "SELECT path FROM recordings WHERE camera = ? AND (mtime < ? OR (mtime = ? AND path < ?))"
            " ORDER BY mtime DESC, path DESC LIMIT 1",
            key,
        ).fetchone()
        nxt = conn.execute(
            "SELECT path FROM recordings WHERE camera = ? AND (mtime > ? OR (mtime = ? AND path > ?))"
            " ORDER BY mtime ASC, path ASC LIMIT 1",
            key,
        ).fetchone()
    return {"rec": dict(rec), "prev": prev[0] if prev else None, "next": nxt[0] if nxt else None}


def full_scan(cameras: list[dict]):
    """Walk every configured recordings_path recursively and index any .mp4
    not already in the DB. Run at startup -- deliberately does NOT generate
    thumbnails here (that would mean calling ffmpeg once per existing file
    and could block startup for minutes on a folder with many recordings).
    Thumbnails are generated lazily on first view instead.

    Also prunes rows (and cached thumbnails) of files that no longer exist,
    e.g. removed by the nightly retention cleanup while the app was down.
    A camera whose recordings_path is missing (share not mounted) is skipped
    entirely, so an unavailable mount never wipes its index."""
    with _lock, _connect() as conn:
        existing = {row[0] for row in conn.execute("SELECT path FROM recordings")}

    for cam in cameras:
        root = Path(cam["recordings_path"])
        if not root.exists():
            continue
        found = set()
        for mp4 in root.rglob("*.mp4"):
            found.add(str(mp4))
            if str(mp4) in existing:
                continue
            with _lock, _connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO recordings (path, camera, mtime, thumbnail) VALUES (?, ?, ?, NULL)",
                    (str(mp4), cam["name"], mp4.stat().st_mtime),
                )
        prefix = str(root).rstrip("/") + "/"
        stale = [p for p in existing if p.startswith(prefix) and p not in found]
        for path in stale:
            remove_file(Path(path))


class _RecordingHandler(FileSystemEventHandler):
    def __init__(self, camera_name: str):
        self.camera_name = camera_name

    def on_created(self, event):
        if not event.src_path.endswith(".mp4"):
            return
        # Indexing only, no thumbnail here -- notifications are triggered
        # by mqtt_listener.py from the camera's own motion-detection topic
        # instead, so this doesn't need to run ffmpeg on every new file.
        index_file(Path(event.src_path), self.camera_name, generate_thumb=False)

    def on_deleted(self, event):
        if event.src_path.endswith(".mp4"):
            remove_file(Path(event.src_path))


def start_recordings_watcher(cameras: list[dict]) -> Observer:
    observer = PollingObserver(timeout=POLL_SECONDS) if POLL_SECONDS > 0 else Observer()
    for cam in cameras:
        root = Path(cam["recordings_path"])
        if root.exists():
            observer.schedule(_RecordingHandler(cam["name"]), str(root), recursive=True)
    observer.daemon = True
    observer.start()
    return observer
