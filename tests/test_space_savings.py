import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.core.models import Photo, Verdict
from app.ui.main_window import _verdict_bytes
from app.ui.dialogs import ApplyConfirmDialog
from app.ui.review_view import _format_size


def _p(verdict, size):
    return Photo(id="x", filepath="a.jpg", filename="a.jpg", file_size=size,
                 verdict=verdict)


class VerdictBytesTests(unittest.TestCase):
    def test_sums_by_verdict(self):
        photos = [
            _p(Verdict.KEEP, 100), _p(Verdict.KEEP, 50),
            _p(Verdict.ARCHIVE, 200),
            _p(Verdict.DELETE, 300),
            _p(Verdict.REVIEW, 999),  # not counted
        ]
        self.assertEqual((150, 200, 300), _verdict_bytes(photos))

    def test_format_size(self):
        self.assertEqual("512 B", _format_size(512))
        self.assertEqual("2 KB", _format_size(2048))
        self.assertEqual("1.5 MB", _format_size(int(1024 * 1024 * 1.5)))
        self.assertEqual("0 B", _format_size(None))


class ApplyDialogSavingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _text(self, dlg):
        return " ".join(w.text() for w in dlg.findChildren(QLabel) if w.text())

    def test_delete_shows_reclaimable(self):
        dlg = ApplyConfirmDialog(
            keep=1, archive=1, delete=1, review=0,
            keep_bytes=1024 * 1024, archive_bytes=2 * 1024 * 1024,
            delete_bytes=3 * 1024 * 1024,
        )
        self.addCleanup(dlg.deleteLater)
        text = self._text(dlg)
        self.assertIn("Frees ~3.0 MB", text)
        self.assertIn("set aside", text)          # archived bytes noted
        self.assertIn("(3.0 MB)", text)            # per-line size

    def test_archive_only_is_set_aside_not_freed(self):
        dlg = ApplyConfirmDialog(
            keep=0, archive=2, delete=0, review=0,
            archive_bytes=5 * 1024 * 1024,
        )
        self.addCleanup(dlg.deleteLater)
        text = self._text(dlg)
        self.assertIn("set aside", text)
        self.assertNotIn("Frees", text)           # nothing actually freed

    def test_no_sizes_when_zero(self):
        dlg = ApplyConfirmDialog(keep=1, archive=0, delete=0, review=0)
        self.addCleanup(dlg.deleteLater)
        text = self._text(dlg)
        self.assertNotIn("Frees", text)
        self.assertNotIn("set aside", text)


if __name__ == "__main__":
    unittest.main()
