"""Unit tests for the recordings index (stdlib unittest, run inside the app image):
docker compose run --rm --no-deps camera-app python -m unittest discover -s tests -v
"""

import importlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_recordings(data_dir: str, poll: str = ""):
    os.environ["DATA_DIR"] = data_dir
    os.environ["RECORDINGS_POLL_SECONDS"] = poll
    import recordings

    return importlib.reload(recordings)


class FullScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.rec_root = base / "rec" / "cam1"
        (self.rec_root / "2026Y10M01D10H").mkdir(parents=True)
        self.r = load_recordings(str(base / "data"))
        self.r.init_db()
        self.cams = [{"name": "cam1", "recordings_path": str(self.rec_root)}]

    def tearDown(self):
        self.tmp.cleanup()

    def paths(self):
        return {x["path"] for x in self.r.list_recordings("cam1")}

    def test_indexes_new_files(self):
        f = self.rec_root / "2026Y10M01D10H" / "00M00S60.mp4"
        f.write_bytes(b"x")
        self.r.full_scan(self.cams)
        self.assertEqual(self.paths(), {str(f)})

    def test_prunes_deleted_files_and_thumbnails(self):
        keep = self.rec_root / "2026Y10M01D10H" / "keep.mp4"
        gone = self.rec_root / "2026Y10M01D10H" / "gone.mp4"
        keep.write_bytes(b"x")
        gone.write_bytes(b"x")
        self.r.full_scan(self.cams)
        thumb = self.r.THUMB_DIR / "gone.jpg"
        thumb.write_bytes(b"jpg")
        with self.r._connect() as conn:
            conn.execute("UPDATE recordings SET thumbnail = ? WHERE path = ?", (str(thumb), str(gone)))
        gone.unlink()
        self.r.full_scan(self.cams)
        self.assertEqual(self.paths(), {str(keep)})
        self.assertFalse(thumb.exists())

    def test_missing_root_keeps_index(self):
        f = self.rec_root / "2026Y10M01D10H" / "a.mp4"
        f.write_bytes(b"x")
        self.r.full_scan(self.cams)
        self.r.full_scan([{"name": "cam1", "recordings_path": str(self.rec_root) + "-not-mounted"}])
        self.assertEqual(self.paths(), {str(f)})

    def test_neighbors_same_camera_in_time_order(self):
        with self.r._connect() as conn:
            for path, cam, mtime in [("a", "cam1", 100), ("b", "cam2", 150), ("c", "cam1", 200), ("d", "cam1", 300)]:
                conn.execute("INSERT INTO recordings (path, camera, mtime) VALUES (?, ?, ?)", (path, cam, mtime))
        nb = self.r.neighbors("c")
        self.assertEqual((nb["prev"], nb["next"]), ("a", "d"))  # "b" is another camera
        self.assertEqual((self.r.neighbors("a")["prev"], self.r.neighbors("d")["next"]), (None, None))
        self.assertIsNone(self.r.neighbors("missing"))


class WatcherTest(unittest.TestCase):
    def test_polling_watcher_sees_new_and_deleted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "rec"
            root.mkdir()
            r = load_recordings(str(Path(tmp) / "data"), poll="0.2")
            r.init_db()
            obs = r.start_recordings_watcher([{"name": "cam1", "recordings_path": str(root)}])
            self.assertEqual(type(obs).__name__, "PollingObserver")
            try:
                f = root / "new.mp4"
                f.write_bytes(b"x")
                deadline = time.time() + 5
                while time.time() < deadline and not r.list_recordings("cam1"):
                    time.sleep(0.1)
                self.assertEqual([x["path"] for x in r.list_recordings("cam1")], [str(f)])
                f.unlink()
                deadline = time.time() + 5
                while time.time() < deadline and r.list_recordings("cam1"):
                    time.sleep(0.1)
                self.assertEqual(r.list_recordings("cam1"), [])
            finally:
                obs.stop()

    def test_inotify_watcher_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = load_recordings(str(Path(tmp) / "data"))
            obs = r.start_recordings_watcher([])
            try:
                self.assertNotEqual(type(obs).__name__, "PollingObserver")
            finally:
                obs.stop()


if __name__ == "__main__":
    unittest.main()


class MotionEventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.rec_root = base / "rec" / "cam1"
        self.rec_root.mkdir(parents=True)
        self.r = load_recordings(str(base / "data"))
        self.r.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def clip(self, name: str, mtime: float) -> Path:
        f = self.rec_root / name
        f.write_bytes(b"x")
        os.utime(f, (mtime, mtime))
        self.r.index_file(f, "cam1", generate_thumb=False)
        return f

    def test_events_since_newest_first_with_clip(self):
        now = time.time()
        self.r.add_motion_event("cam1", now - 3600)
        self.r.add_motion_event("cam1", now - 600)
        self.r.add_motion_event("cam2", now - 300)
        self.r.add_motion_event("cam1", now - 2 * 86400)  # before `since`
        f = self.clip("a.mp4", now - 600 + 90)  # uploaded 90 s after the event
        got = self.r.motion_events_since(now - 86400)
        self.assertEqual([e["clip"] for e in got["cam1"]], [str(f), None])
        self.assertEqual(len(got["cam2"]), 1)

    def test_old_events_pruned(self):
        now = time.time()
        self.r.add_motion_event("cam1", now - 400 * 86400)
        self.r.add_motion_event("cam1", now)
        self.assertEqual(len(self.r.motion_events_since(0)["cam1"]), 1)
