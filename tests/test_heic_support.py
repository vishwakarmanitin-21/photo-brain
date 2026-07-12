import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
from PIL import Image

from app.core import image_formats  # noqa: F401  (registers HEIC)
from app.core.image_io import read_image
from app.core.scanner import compute_hashes, fingerprint_and_score
from app.util.paths import SUPPORTED_EXTENSIONS


def _write(path, fmt, color=(120, 80, 40), size=(320, 240)):
    Image.new("RGB", size, color).save(path, format=fmt)


class ExtensionListTests(unittest.TestCase):
    def test_new_formats_are_supported(self):
        for ext in (".heic", ".heif", ".webp"):
            self.assertIn(ext, SUPPORTED_EXTENSIONS)


class HeicDecodeTests(unittest.TestCase):
    """FEAT-02: iPhone HEIC photos must flow through the whole pipeline."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _heic(self):
        p = os.path.join(self._dir.name, "iphone.heic")
        _write(p, "HEIF")
        return p

    def test_read_image_decodes_heic_colour_and_gray(self):
        p = self._heic()
        bgr = read_image(p)
        self.assertIsNotNone(bgr)
        self.assertEqual(3, bgr.shape[2])
        gray = read_image(p, cv2.IMREAD_GRAYSCALE)
        self.assertIsNotNone(gray)
        self.assertEqual(2, gray.ndim)

    def test_pipeline_scores_heic(self):
        p = self._heic()
        photos = compute_hashes([p])
        fingerprint_and_score(photos)
        self.assertIsNotNone(photos[0].phash)
        self.assertIsNotNone(photos[0].sha256)
        self.assertGreaterEqual(photos[0].quality_score, 0.0)

    def test_pipeline_scores_webp(self):
        p = os.path.join(self._dir.name, "shot.webp")
        _write(p, "WEBP")
        photos = compute_hashes([p])
        fingerprint_and_score(photos)
        self.assertIsNotNone(photos[0].phash)


class HeicHoverPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_hover_preview_falls_back_to_pil_for_heic(self):
        from app.ui.review_view import load_bounded_pixmap
        with tempfile.TemporaryDirectory() as folder:
            p = os.path.join(folder, "iphone.heic")
            _write(p, "HEIF", size=(1600, 1200))
            pm = load_bounded_pixmap(p, 1000)
            self.assertFalse(pm.isNull())
            self.assertLessEqual(max(pm.width(), pm.height()), 1000)


if __name__ == "__main__":
    unittest.main()
