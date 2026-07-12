import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QApplication

from app.ui.review_view import ReviewView


class ShortcutScopingTests(unittest.TestCase):
    """UX-07: review shortcuts must be scoped to the widget, not the window,
    so they can't fire on the Setup/Scan screens."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_shortcuts_are_widget_scoped(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        shortcuts = rv.findChildren(QShortcut)
        self.assertGreater(len(shortcuts), 10)  # sanity: they exist
        for s in shortcuts:
            self.assertEqual(
                Qt.WidgetWithChildrenShortcut, s.context(),
                f"{s.key().toString()} is not widget-scoped",
            )

    def test_view_is_focusable(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        self.assertEqual(Qt.StrongFocus, rv.focusPolicy())


if __name__ == "__main__":
    unittest.main()
