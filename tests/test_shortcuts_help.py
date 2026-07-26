import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.ui.dialogs import ShortcutsHelpDialog
from app.ui.review_view import REVIEW_SHORTCUTS, ReviewView


def _split_keys(entry: str) -> set[str]:
    """The individual keys an entry documents, e.g. 'D / Del' -> {'D','Del'}."""
    return {part.strip() for part in entry.split("/")}


class ShortcutsHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_lists_every_shortcut(self):
        dlg = ShortcutsHelpDialog(REVIEW_SHORTCUTS)
        self.addCleanup(dlg.deleteLater)
        text = " ".join(w.text() for w in dlg.findChildren(QLabel))
        for keys, desc in REVIEW_SHORTCUTS:
            self.assertIn(keys, text)
            self.assertIn(desc, text)

    def test_core_verdict_keys_are_documented(self):
        # Match per-entry rather than exact labels: an entry may legitimately
        # document aliases (e.g. "D / Del") without dropping the core key.
        entries = [k for k, _ in REVIEW_SHORTCUTS]
        for k in ("K", "A", "D", "R"):
            self.assertTrue(
                any(k in _split_keys(entry) for entry in entries),
                f"verdict key {k!r} is not documented in {entries}",
            )
        # The help entry itself must be listed so it's discoverable.
        self.assertTrue(any("F1" in k for k, _ in REVIEW_SHORTCUTS))

    def test_review_view_exposes_shortcuts_button_and_handler(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        self.assertTrue(hasattr(rv, "_shortcuts_btn"))
        self.assertIn("Shortcuts", rv._shortcuts_btn.text())
        # The handler opens a modal dialog; just confirm it's callable without
        # actually exec()-ing (which would block). Patch exec to a no-op.
        from unittest.mock import patch
        with patch.object(ShortcutsHelpDialog, "exec", return_value=0) as ex:
            rv._show_shortcuts()
            ex.assert_called_once()


if __name__ == "__main__":
    unittest.main()
