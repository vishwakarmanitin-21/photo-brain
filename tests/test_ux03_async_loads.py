import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image

from PySide6.QtWidgets import QApplication

from app.ui.review_view import load_bounded_pixmap, HOVER_PREVIEW_MAX
from app.ui.setup_view import _FolderCountWorker
from app.ui.scan_view import ScanView


class BoundedPixmapTests(unittest.TestCase):
    """UX-03: hover preview must decode downscaled, never the full original."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_large_image_is_capped_to_max_dim(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "big.jpg")
            Image.new("RGB", (4000, 3000), (120, 60, 30)).save(path)
            pm = load_bounded_pixmap(path, HOVER_PREVIEW_MAX)
            self.assertFalse(pm.isNull())
            self.assertLessEqual(max(pm.width(), pm.height()), HOVER_PREVIEW_MAX)
            # Aspect ratio preserved (4:3).
            self.assertAlmostEqual(pm.width() / pm.height(), 4 / 3, places=1)

    def test_small_image_is_not_upscaled(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "small.jpg")
            Image.new("RGB", (300, 200), (10, 20, 30)).save(path)
            pm = load_bounded_pixmap(path, HOVER_PREVIEW_MAX)
            self.assertEqual((300, 200), (pm.width(), pm.height()))

    def test_missing_file_returns_null(self):
        pm = load_bounded_pixmap("C:/nope/missing.jpg", HOVER_PREVIEW_MAX)
        self.assertTrue(pm.isNull())


class FolderCountWorkerTests(unittest.TestCase):
    """UX-03: folder counting runs off the UI thread and skips cache dirs."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_counts_supported_files_and_skips_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            for i in range(3):
                Image.new("RGB", (8, 8)).save(os.path.join(folder, f"p{i}.jpg"))
            # A non-image and a skip-dir file must not be counted.
            with open(os.path.join(folder, "notes.txt"), "w") as f:
                f.write("x")
            cache = os.path.join(folder, ".photobrain")
            os.makedirs(cache)
            Image.new("RGB", (8, 8)).save(os.path.join(cache, "c.jpg"))

            worker = _FolderCountWorker(folder)
            results = []
            worker.counted.connect(results.append)
            worker.run()  # run synchronously in-test
            self.assertEqual([3], results)

    def test_cancel_suppresses_final_emit(self):
        with tempfile.TemporaryDirectory() as folder:
            Image.new("RGB", (8, 8)).save(os.path.join(folder, "p.jpg"))
            worker = _FolderCountWorker(folder)
            results = []
            worker.counted.connect(results.append)
            worker.cancel()
            worker.run()
            self.assertEqual([], results)


class CancelFeedbackTests(unittest.TestCase):
    """UX-03: Cancel gives immediate visual feedback."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_show_cancelling_disables_button(self):
        view = ScanView()
        self.addCleanup(view.deleteLater)
        view.show_cancelling()
        self.assertFalse(view._cancel_btn.isEnabled())
        self.assertEqual("Cancelling…", view._cancel_btn.text())
        # reset restores it for the next scan.
        view.reset()
        self.assertTrue(view._cancel_btn.isEnabled())
        self.assertEqual("Cancel", view._cancel_btn.text())


if __name__ == "__main__":
    unittest.main()
