"""Unit tests for the per-camera notification schedule."""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import notify_schedule as ns

# 2026-10-26 is a Monday
MON = datetime(2026, 10, 26)


def at(day_offset: int, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return MON.replace(day=26 + day_offset, hour=h, minute=m)


class ScheduleTest(unittest.TestCase):
    def test_default_always_active(self):
        self.assertTrue(ns.is_active(ns.DEFAULT, at(3, "03:00")))
        self.assertTrue(ns.is_default(ns.DEFAULT))

    def test_days_only(self):
        weekdays = {"days": [0, 1, 2, 3, 4], "ranges": []}
        self.assertTrue(ns.is_active(weekdays, at(0, "12:00")))
        self.assertFalse(ns.is_active(weekdays, at(5, "12:00")))

    def test_daytime_range(self):
        s = {"days": ns.ALL_DAYS, "ranges": [["09:00", "18:00"]]}
        self.assertTrue(ns.is_active(s, at(0, "09:00")))
        self.assertFalse(ns.is_active(s, at(0, "18:00")))
        self.assertFalse(ns.is_active(s, at(0, "08:59")))

    def test_overnight_range_belongs_to_start_day(self):
        friday_night = {"days": [4], "ranges": [["22:00", "07:00"]]}
        self.assertTrue(ns.is_active(friday_night, at(4, "23:30")))  # Friday
        self.assertTrue(ns.is_active(friday_night, at(5, "06:59")))  # Saturday morning
        self.assertFalse(ns.is_active(friday_night, at(5, "23:30")))  # Saturday night
        self.assertFalse(ns.is_active(friday_night, at(4, "06:00")))  # Friday morning (Thursday's night)

    def test_until_midnight(self):
        s = {"days": [0], "ranges": [["20:00", "00:00"]]}
        self.assertTrue(ns.is_active(s, at(0, "23:59")))
        self.assertFalse(ns.is_active(s, at(1, "00:00")))

    def test_no_days_never(self):
        self.assertFalse(ns.is_active({"days": [], "ranges": []}, at(0, "12:00")))

    def test_normalize_drops_invalid(self):
        s = ns.normalize(["0", "6", "9", "x", "0"], ["22:00", "25:00", "", "08:00"], ["07:00", "01:00", "", "08:30"])
        self.assertEqual(s, {"days": [0, 6], "ranges": [["22:00", "07:00"], ["08:00", "08:30"]]})

    def test_summary(self):
        names = "Mon Tue Wed Thu Fri Sat Sun".split()
        labels = {"always": "Always", "never": "Never", "every_day": "Every day", "all_day": "all day"}
        self.assertEqual(ns.summary(ns.DEFAULT, names, labels), "Always")
        s = {"days": [0, 1, 2, 3, 4], "ranges": [["22:00", "07:00"]]}
        self.assertEqual(ns.summary(s, names, labels), "Mon–Fri · 22:00–07:00")
        self.assertEqual(ns.summary({"days": [5, 6], "ranges": []}, names, labels), "Sat–Sun · all day")


if __name__ == "__main__":
    unittest.main()
