"""Unit tests for i18n.py: lookup, fallbacks and per-request language."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import i18n


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(None)

    def test_every_string_has_all_languages(self):
        for key, entry in i18n.STRINGS.items():
            for lang in i18n.LANGUAGES:
                self.assertTrue(entry.get(lang), f"{key} has no {lang} text")

    def test_switch_and_format(self):
        i18n.set_language("it")
        self.assertEqual(i18n.t("notify_motion", camera="garage"), "Movimento rilevato: garage")
        i18n.set_language("en")
        self.assertEqual(i18n.t("notify_motion", camera="garage"), "Motion detected: garage")
        self.assertEqual(i18n.table()["nav_cameras"], "Cameras")

    def test_invalid_language_falls_back_to_default(self):
        self.assertEqual(i18n.set_language("xx"), i18n.DEFAULT_LANGUAGE)
        self.assertEqual(i18n.set_language("IT-it"), "it")

    def test_unknown_key_is_returned_as_is(self):
        self.assertEqual(i18n.t("no_such_key"), "no_such_key")


if __name__ == "__main__":
    unittest.main()
