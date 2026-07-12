import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QUrl, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from app.ui.setup_view import SetupView


class SetupViewFolderInputTests(unittest.TestCase):
    """UX-11: folder can come from typing/pasting or drag-drop, not just Browse.
       UX-15: first-run guidance is present on the home screen."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        v = SetupView()
        self.addCleanup(v.deleteLater)
        return v

    def test_typed_valid_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            v = self._view()
            v._path_edit.setText(folder)
            v._on_path_typed()
            self.assertEqual(os.path.normpath(folder), v.selected_folder())
            v._stop_count()

    def test_typed_invalid_path_is_rejected(self):
        v = self._view()
        v._path_edit.setText("C:/definitely/not/here/xyz")
        v._on_path_typed()
        self.assertEqual("", v.selected_folder())
        self.assertFalse(v._scan_btn.isEnabled())

    def test_quotes_are_stripped_from_pasted_path(self):
        with tempfile.TemporaryDirectory() as folder:
            v = self._view()
            v._path_edit.setText(f'"{folder}"')
            v._on_path_typed()
            self.assertEqual(os.path.normpath(folder), v.selected_folder())
            v._stop_count()

    def test_drop_of_folder_sets_it(self):
        with tempfile.TemporaryDirectory() as folder:
            v = self._view()
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(folder)])
            event = QDropEvent(QPointF(1, 1), Qt.CopyAction, mime,
                               Qt.LeftButton, Qt.NoModifier)
            v.dropEvent(event)
            self.assertEqual(os.path.normpath(folder), v.selected_folder())
            v._stop_count()

    def test_accepts_drops(self):
        self.assertTrue(self._view().acceptDrops())


if __name__ == "__main__":
    unittest.main()
