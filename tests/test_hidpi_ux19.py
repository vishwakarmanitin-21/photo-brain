"""UX-19: images are prepared at screen pixels (logical size x the display's
scale factor) and tagged with that ratio, so 125%/150% screens draw them 1:1
instead of stretching; zoom previews come in fixed pixel steps."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui import review_view
from app.ui.review_view import (
    PREVIEW_STEPS, THUMB_CACHE_SIZE, ReviewView, ThumbnailWidget, preview_step,
)


def _p(pid="p"):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg", file_size=1,
                 sharpness=100.0, brightness=120.0, quality_score=0.5,
                 verdict=Verdict.REVIEW, cluster_id="c1")


def _source(w=800, h=600):
    pm = QPixmap(w, h)
    pm.fill(QColor(30, 120, 200))
    return pm


class HiDpiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tile_is_drawn_at_screen_pixels_on_a_150_percent_display(self):
        w = ThumbnailWidget(_p())
        self.addCleanup(w.deleteLater)
        handed = []
        w._image_label.setPixmap = handed.append   # QLabel re-renders for its own (offscreen 1.0) screen
        with patch.object(ThumbnailWidget, "devicePixelRatioF", return_value=1.5):
            w.set_pixmap(_source(), 180)
        shown = handed[-1]
        self.assertEqual(1.5, shown.devicePixelRatio())
        self.assertEqual(270, shown.width())                  # 180 pt x 1.5 = 270 px
        self.assertEqual((180, 135), (w._image_label.width(), w._image_label.height()))

    def test_tile_at_100_percent_is_unchanged(self):
        w = ThumbnailWidget(_p())
        self.addCleanup(w.deleteLater)
        with patch.object(ThumbnailWidget, "devicePixelRatioF", return_value=1.0):
            w.set_pixmap(_source(), 180)
        self.assertEqual((180, 1.0), (w._image_label.pixmap().width(), w._image_label.pixmap().devicePixelRatio()))

    def test_preview_steps(self):
        self.assertEqual(480, preview_step(321))
        self.assertEqual(800, preview_step(481))
        self.assertEqual(PREVIEW_STEPS[-1], preview_step(10_000))

    def test_step_choice_depends_on_screen_scale(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        with patch.object(ReviewView, "devicePixelRatioF", return_value=1.0):
            self.assertEqual(0, rv._preview_step_for(300))     # 300 px: thumbnail is enough
            self.assertEqual(480, rv._preview_step_for(400))
        with patch.object(ReviewView, "devicePixelRatioF", return_value=1.5):
            self.assertEqual(480, rv._preview_step_for(300))   # 450 px needed
            self.assertEqual(0, rv._preview_step_for(200))     # 300 px <= 320 thumbnail

    def test_zooming_within_one_step_keeps_decoded_previews(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.load_data([Cluster(id="c1", label="c1", member_count=1)], {"c1": [_p()]},
                     has_undo=False, events=[])
        with patch.object(ReviewView, "devicePixelRatioF", return_value=1.0):
            rv._on_zoom_changed(420)
            rv._preview_pixmaps["p"] = _source()
            rv._on_zoom_changed(460)                          # same 480 step
            self.assertIn("p", rv._preview_pixmaps)
            rv._on_zoom_changed(600)                          # 800 step: stale
            self.assertNotIn("p", rv._preview_pixmaps)

    def test_grid_requests_the_step_not_the_slider_value(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.load_data([Cluster(id="c1", label="c1", member_count=1)], {"c1": [_p()]},
                     has_undo=False, events=[])
        rv.set_hide_singletons(False)
        requested = []
        rv.previews_requested.connect(lambda photos, step: requested.append(step))
        with patch.object(ReviewView, "devicePixelRatioF", return_value=1.25):
            rv._current_display_size = 500                   # 625 px needed
            rv._rebuild_grid_with_zoom()
            self.assertEqual([800], requested)
            rv.on_preview_ready("p", 800, _source(800, 600).toImage())
        self.assertIn("p", rv._preview_pixmaps)


if __name__ == "__main__":
    unittest.main()
