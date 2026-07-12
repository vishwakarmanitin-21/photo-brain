import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings

from app.util.app_settings import AppSettings, _to_bool, _to_int, _to_float


class CoercionTests(unittest.TestCase):
    """QSettings can hand back strings; coercion must be robust (UX-13)."""

    def test_to_bool_handles_strings(self):
        self.assertTrue(_to_bool("true", False))
        self.assertTrue(_to_bool(True, False))
        self.assertFalse(_to_bool("false", True))
        self.assertFalse(_to_bool("0", True))
        self.assertTrue(_to_bool(None, True))   # default when missing

    def test_to_int_and_float_fall_back(self):
        self.assertEqual(5, _to_int("5", 0))
        self.assertEqual(9, _to_int("garbage", 9))
        self.assertEqual(4.0, _to_float("4.0", 1.0))
        self.assertEqual(1.5, _to_float(None, 1.5))


class RoundTripTests(unittest.TestCase):
    """Values must survive a save/reload against a real QSettings backend."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._path = os.path.join(self._dir.name, "prefs.ini")

    def _settings(self):
        return AppSettings(QSettings(self._path, QSettings.IniFormat))

    def test_scan_defaults_round_trip(self):
        self._settings().save_scan_defaults(9, 3, 6.5, False)
        s = self._settings()
        self.assertEqual(9, s.threshold(17))
        self.assertEqual(3, s.keep_per_cluster(2))
        self.assertEqual(6.5, s.event_gap_hours(4.0))
        self.assertFalse(s.face_detection(True))

    def test_defaults_used_when_unset(self):
        s = self._settings()
        self.assertEqual(17, s.threshold(17))
        self.assertTrue(s.face_detection(True))
        self.assertEqual(180, s.zoom(180))

    def test_zoom_and_hide_round_trip(self):
        s1 = self._settings()
        s1.save_zoom(320)
        s1.save_hide_singletons(False)
        s2 = self._settings()
        self.assertEqual(320, s2.zoom(180))
        self.assertFalse(s2.hide_singletons(True))


if __name__ == "__main__":
    unittest.main()
