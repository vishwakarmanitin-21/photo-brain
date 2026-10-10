"""UX-20: Compare decodes in the background, shows phone portraits upright,
handles formats Qt cannot read, and sizes its images to the screen."""
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import Photo, Verdict
from app.ui.compare_dialog import MAX_IMAGE_PX, MIN_IMAGE_PX, CompareDialog, fit_image_px
from app.ui.image_loading import load_bounded_image


def _portrait(folder, name):
    path = os.path.join(folder, name)
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (300, 400), (200, 40, 40)).transpose(Image.Transpose.ROTATE_90).save(path, exif=exif)
    return path


def _photo(path, pid):
    return Photo(id=pid, filepath=path, filename=os.path.basename(path), file_size=1,
                 quality_score=0.5, verdict=Verdict.KEEP)


class CompareUx20Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end and not cond():
            self.app.processEvents()
            time.sleep(0.02)
        return cond()

    def test_panels_fill_in_upright_from_background_decode(self):
        with tempfile.TemporaryDirectory() as d:
            photos = [_photo(_portrait(d, "a.jpg"), "a"), _photo(_portrait(d, "b.jpg"), "b")]
            dlg = CompareDialog(photos, image_px=200)
            self.addCleanup(dlg.deleteLater)
            # Opens immediately with placeholders — nothing decoded on the UI thread.
            self.assertTrue(all(not p.view.has_image() for p in dlg._panels))
            self.assertTrue(self._wait(lambda: all(p.view.has_image() for p in dlg._panels)))
            pm = dlg._panels[0].view._pixmap
            self.assertLess(pm.width(), pm.height())   # portrait, not sideways

    def test_unreadable_file_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.jpg")
            with open(bad, "wb") as fh:
                fh.write(b"not an image")
            dlg = CompareDialog([_photo(bad, "x"), _photo(_portrait(d, "ok.jpg"), "y")], image_px=150)
            self.addCleanup(dlg.deleteLater)
            self.assertTrue(self._wait(lambda: dlg._panels[0].view._message == "(preview unavailable)"))

    def test_heic_style_fallback_through_pillow_is_upright(self):
        # A format Qt has no plugin for goes through Pillow; simulate with a
        # path Qt reads but force the fallback by calling it directly.
        from app.ui.image_loading import _load_via_pil
        with tempfile.TemporaryDirectory() as d:
            img = _load_via_pil(_portrait(d, "p.jpg"), 100)
            self.assertFalse(img.isNull())
            self.assertLess(img.width(), img.height())

    def test_image_size_follows_the_screen(self):
        self.assertEqual(MAX_IMAGE_PX, fit_image_px(2, 3840, 2160))
        self.assertGreater(fit_image_px(2, 1920, 1040), fit_image_px(4, 1920, 1040))
        self.assertEqual(MIN_IMAGE_PX, fit_image_px(8, 1000, 600))
        self.assertEqual(fit_image_px(4, 1920, 1040), fit_image_px(8, 1920, 1040))  # >4 scrolls

    def test_shared_loader_bounds_and_rotates(self):
        with tempfile.TemporaryDirectory() as d:
            img = load_bounded_image(_portrait(d, "q.jpg"), 100)
            self.assertEqual((75, 100), (img.width(), img.height()))


if __name__ == "__main__":
    unittest.main()


class CompareCloseEarlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_closing_before_images_load_is_harmless(self):
        import gc
        from PySide6.QtCore import QThreadPool
        with tempfile.TemporaryDirectory() as d:
            photos = [_photo(_portrait(d, f"{i}.jpg"), str(i)) for i in range(4)]
            for _ in range(3):
                dlg = CompareDialog(photos, image_px=150)
                dlg.close()
                dlg.deleteLater()
                del dlg
                gc.collect()
                self.app.processEvents()
            self.assertTrue(QThreadPool.globalInstance().waitForDone(10000))
