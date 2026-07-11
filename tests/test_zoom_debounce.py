import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.review_view import ReviewView


class ZoomDebounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rapid_zoom_changes_trigger_one_grid_rebuild(self):
        view = ReviewView()
        view._rebuild_grid_with_zoom = MagicMock()

        view._on_zoom_changed(240)
        view._on_zoom_changed(280)
        view._on_zoom_changed(320)
        self.assertEqual(0, view._rebuild_grid_with_zoom.call_count)

        QTest.qWait(200)

        self.assertEqual(1, view._rebuild_grid_with_zoom.call_count)
        self.assertEqual(320, view._current_display_size)
        view.deleteLater()


if __name__ == "__main__":
    unittest.main()
