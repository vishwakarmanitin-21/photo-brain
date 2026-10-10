"""PERF-08: the thumbnail worker generates in parallel, once per cache key,
does not re-send thumbnails the grid already shows, and reports progress."""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import Photo
from app.core.thumbnails import ThumbnailCache
from app.workers.thumb_worker import ThumbWorker


def _photo(folder, pid, sha, color):
    path = os.path.join(folder, f"{pid}.jpg")
    Image.new("RGB", (640, 480), color).save(path)
    return Photo(id=pid, filepath=path, filename=f"{pid}.jpg", file_size=1, sha256=sha)


class ThumbWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generates_missing_once_per_key_and_skips_already_shown(self):
        with tempfile.TemporaryDirectory() as d:
            cache = ThumbnailCache(os.path.join(d, "thumbs"))
            shown = _photo(d, "shown", "S1", (200, 0, 0))
            shown.thumb_path = cache.generate_thumbnail(shown)   # grid already has it
            dup_a = _photo(d, "dupa", "S2", (0, 200, 0))
            dup_b = _photo(d, "dupb", "S2", (0, 200, 0))          # exact copy: same key
            fresh = [_photo(d, f"f{i}", f"F{i}", (0, 0, 20 * i)) for i in range(6)]
            worker = ThumbWorker([shown, dup_a, dup_b] + fresh, cache)
            ready, progress, finished = [], [], []
            worker.thumb_ready.connect(lambda pid, path: ready.append(pid))
            worker.progress_updated.connect(lambda d_, t: progress.append((d_, t)))
            worker.all_finished.connect(lambda: finished.append(True))
            worker.run()   # synchronous

            self.assertNotIn("shown", ready)                     # no double decode
            self.assertEqual({"dupa", "dupb"} | {f"f{i}" for i in range(6)}, set(ready))
            self.assertEqual(dup_a.thumb_path, dup_b.thumb_path)
            self.assertEqual((0, 7), progress[0])                 # 7 keys to make
            self.assertEqual((7, 7), progress[-1])
            self.assertEqual([True], finished)

    def test_cancel_stops_without_finishing(self):
        with tempfile.TemporaryDirectory() as d:
            cache = ThumbnailCache(os.path.join(d, "thumbs"))
            worker = ThumbWorker([_photo(d, "a", "A", (1, 2, 3))], cache)
            finished = []
            worker.all_finished.connect(lambda: finished.append(True))
            worker.cancel()
            worker.run()
            self.assertEqual([], finished)


class ThumbProgressLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_label_shows_while_working_and_clears_when_done(self):
        from app.ui.review_view import ReviewView
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.set_thumb_progress(340, 3653)
        self.assertIn("340 of 3,653", rv._thumb_status.text())
        rv.set_thumb_progress(3653, 3653)
        self.assertEqual("", rv._thumb_status.text())


if __name__ == "__main__":
    unittest.main()
