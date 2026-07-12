import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import Photo
from app.core.thumbnails import (
    ThumbnailCache, PreviewCache, image_cache_bytes, clear_image_caches,
)
from app.core.session_store import SessionStore
from app.ui.dialogs import SettingsDialog, _format_bytes
from app.util.paths import get_thumb_dir, get_preview_dir, get_db_path


def _seed_caches(folder: str):
    src = os.path.join(folder, "a.jpg")
    Image.new("RGB", (400, 300), (100, 120, 140)).save(src)
    photo = Photo(id="i1", filepath=src, filename="a.jpg", file_size=1,
                  sha256="SHA_A")
    ThumbnailCache(get_thumb_dir(folder)).generate_thumbnail(photo)
    PreviewCache(get_preview_dir(folder)).generate_preview(photo, 400)
    return photo


class ClearCacheHelperTests(unittest.TestCase):
    def test_size_then_clear_frees_bytes_but_keeps_db(self):
        with tempfile.TemporaryDirectory() as folder:
            # A session DB must survive a cache clear.
            store = SessionStore(get_db_path(folder))
            store.create_session("s1", folder)
            store.close()
            db_path = get_db_path(folder)

            _seed_caches(folder)
            before = image_cache_bytes(folder)
            self.assertGreater(before, 0)

            freed = clear_image_caches(folder)
            self.assertEqual(before, freed)
            self.assertEqual(0, image_cache_bytes(folder))
            self.assertTrue(os.path.isfile(db_path))  # session intact

    def test_format_bytes(self):
        self.assertEqual("512 B", _format_bytes(512))
        self.assertEqual("2 KB", _format_bytes(2048))
        self.assertEqual("1.5 MB", _format_bytes(1024 * 1024 * 1.5))


class SettingsDialogCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_disabled_without_folder(self):
        dlg = SettingsDialog(source_folder="")
        self.addCleanup(dlg.deleteLater)
        self.assertFalse(dlg._clear_cache_btn.isEnabled())
        self.assertIn("scan a folder first", dlg._cache_label.text())

    def test_button_clears_and_updates_label(self):
        with tempfile.TemporaryDirectory() as folder:
            _seed_caches(folder)
            dlg = SettingsDialog(source_folder=folder)
            self.addCleanup(dlg.deleteLater)
            self.assertTrue(dlg._clear_cache_btn.isEnabled())
            self.assertIn("Thumbnail cache:", dlg._cache_label.text())

            from unittest.mock import patch
            with patch("app.ui.dialogs.QMessageBox.information"):
                dlg._on_clear_cache()

            self.assertEqual(0, image_cache_bytes(folder))
            self.assertFalse(dlg._clear_cache_btn.isEnabled())  # now empty


if __name__ == "__main__":
    unittest.main()
