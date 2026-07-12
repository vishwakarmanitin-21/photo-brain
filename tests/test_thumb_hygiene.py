import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.main_window import MainWindow
from app.ui.review_view import ReviewView, THUMB_CACHE_SIZE


class ThumbWorkerHygieneTests(unittest.TestCase):
    """UX-04: a new thumbnail run must stop the previous one."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_start_thumb_worker_stops_running_previous(self):
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        window.thumb_cache = MagicMock()
        prev = MagicMock()
        prev.isRunning.return_value = True
        window.thumb_worker = prev

        with patch("app.ui.main_window.ThumbWorker") as WorkerCls:
            WorkerCls.return_value.thumb_ready = MagicMock()
            window._start_thumb_worker([])

        prev.cancel.assert_called_once()
        prev.wait.assert_called_once()
        WorkerCls.return_value.start.assert_called_once()


class ThumbDowngradeGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_one_photo(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        photo = Photo(id="p", filepath="C:/x/p.jpg", filename="p.jpg",
                      file_size=1, quality_score=0.5, verdict=Verdict.KEEP)
        rv.load_data([Cluster(id="c", label="c", member_count=1)],
                     {"c": [photo]}, has_undo=False, events=[])
        rv._hide_singletons.setChecked(False)  # keep the single-photo cluster visible
        rv._cluster_list.setCurrentRow(0)
        return rv

    def test_late_thumbnail_skipped_when_zoomed_high_res(self):
        with tempfile.TemporaryDirectory() as folder:
            thumb = os.path.join(folder, "t.jpg")
            from PIL import Image
            Image.new("RGB", (200, 200), (10, 20, 30)).save(thumb)

            rv = self._view_with_one_photo()
            widget = rv._thumb_widgets["p"]
            widget.set_pixmap = MagicMock()

            # Zoomed into high-res: a late 200px thumbnail must be ignored.
            widget._display_size = THUMB_CACHE_SIZE + 200
            rv.on_thumb_ready("p", thumb)
            widget.set_pixmap.assert_not_called()

            # At/below thumbnail size, it's applied.
            widget._display_size = THUMB_CACHE_SIZE
            rv.on_thumb_ready("p", thumb)
            widget.set_pixmap.assert_called_once()


if __name__ == "__main__":
    unittest.main()
