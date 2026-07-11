import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.ui.dialogs import ApplyConfirmDialog


class ApplyDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_last_copy_warning_is_plain_and_visible(self):
        dialog = ApplyConfirmDialog(
            keep=0,
            archive=0,
            delete=2,
            review=0,
            last_copy_delete_count=2,
        )

        text = "\n".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn("Last-copy warning", text)
        self.assertIn("every scanned byte-for-byte copy", text)
        self.assertIn("No scanned copy will remain", text)
        dialog.deleteLater()
