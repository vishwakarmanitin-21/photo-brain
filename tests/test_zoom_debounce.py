import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.review_view import ReviewView


class ZoomDebounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rapid_zoom_changes_coalesce_into_one_rebuild(self):
        # Deterministic (no wall-clock waits): rapid slider changes must not
        # rebuild the grid immediately — they arm a single pending rebuild —
        # and firing the debounce rebuilds exactly once at the final size.
        view = ReviewView()
        self.addCleanup(view.deleteLater)
        view._rebuild_grid_with_zoom = MagicMock()

        view._on_zoom_changed(240)
        view._on_zoom_changed(280)
        view._on_zoom_changed(320)

        # No rebuild yet; the change is debounced (timer pending).
        self.assertEqual(0, view._rebuild_grid_with_zoom.call_count)
        self.assertTrue(view._zoom_debounce.isActive())
        self.assertEqual(320, view._current_display_size)

        # Firing the debounce slot (what the QTimer.timeout does) rebuilds
        # exactly once, for the latest value.
        view._apply_zoom_change()
        self.assertEqual(1, view._rebuild_grid_with_zoom.call_count)

    def test_slider_release_applies_immediately_and_cancels_debounce(self):
        view = ReviewView()
        self.addCleanup(view.deleteLater)
        view._rebuild_grid_with_zoom = MagicMock()

        view._on_zoom_changed(300)
        self.assertTrue(view._zoom_debounce.isActive())

        view._apply_zoom_change_immediately()
        self.assertFalse(view._zoom_debounce.isActive())   # debounce cancelled
        self.assertEqual(1, view._rebuild_grid_with_zoom.call_count)


if __name__ == "__main__":
    unittest.main()
