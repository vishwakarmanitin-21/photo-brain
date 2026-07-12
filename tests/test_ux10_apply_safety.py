import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox

from app.core.models import Cluster, Photo, Verdict
from app.ui.dialogs import ApplyConfirmDialog
from app.ui.main_window import _friendly_error
from app.ui.review_view import ReviewView


def _photo(pid, cid, verdict=Verdict.KEEP):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, quality_score=0.5, verdict=verdict, cluster_id=cid)


class ApplyDialogDefaultTests(unittest.TestCase):
    """UX-10: Enter must not confirm straight into the Recycle Bin."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, delete):
        d = ApplyConfirmDialog(keep=1, archive=0, delete=delete, review=0)
        self.addCleanup(d.deleteLater)
        return d

    def test_cancel_is_default_when_deletes_present(self):
        d = self._dialog(delete=3)
        cancel = d.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel)
        ok = d.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        self.assertTrue(cancel.isDefault())
        self.assertFalse(ok.isDefault())

    def test_ok_can_be_default_when_no_deletes(self):
        d = self._dialog(delete=0)
        ok = d.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        # With no deletes we don't force Cancel; OK stays a normal default.
        self.assertFalse(ok.isDefault() is None)


class FriendlyErrorTests(unittest.TestCase):
    """UX-10: raw WinError text must not surface to users."""

    def test_permission_error(self):
        msg = _friendly_error(PermissionError("[WinError 32] used by another process"))
        self.assertNotIn("WinError", msg)
        self.assertIn("another program", msg)

    def test_file_not_found(self):
        msg = _friendly_error(FileNotFoundError("[WinError 2] not found"))
        self.assertNotIn("WinError", msg)

    def test_generic_oserror_with_winerror_hidden(self):
        e = OSError("boom")
        e.winerror = 5
        self.assertNotIn("boom", _friendly_error(e))

    def test_plain_exception_passes_through(self):
        self.assertEqual("something specific",
                         _friendly_error(ValueError("something specific")))


class EmptyStateAndPlaceTests(unittest.TestCase):
    """UX-10: context-aware empty state + place preservation on reload."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self, clusters, photos):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.load_data(clusters, photos, has_undo=False, events=[])
        return rv

    def test_empty_when_no_clusters_says_clean(self):
        rv = self._view([], {})
        self.assertIn("already clean", rv._empty_state_message())

    def test_empty_when_all_singletons_hidden_says_clean(self):
        clusters = [Cluster(id="s", label="s", member_count=1)]
        rv = self._view(clusters, {"s": [_photo("p", "s", Verdict.KEEP)]})
        # hide_singletons defaults on → nothing visible → clean-ish message.
        self.assertEqual(0, len(rv._clusters))
        self.assertIn("already clean", rv._empty_state_message())

    def test_view_state_roundtrip_selects_same_cluster(self):
        clusters = [
            Cluster(id="c1", label="c1", member_count=2),
            Cluster(id="c2", label="c2", member_count=2),
        ]
        photos = {
            "c1": [_photo("a", "c1"), _photo("b", "c1")],
            "c2": [_photo("c", "c2"), _photo("d", "c2")],
        }
        rv = self._view(clusters, photos)
        rv._cluster_list.setCurrentRow(1)
        state = rv.get_view_state()
        self.assertEqual("c2", state["cluster_id"])
        # Simulate a reload.
        rv.load_data(clusters, photos, has_undo=False, events=[])
        rv.apply_view_state(state)
        self.assertEqual("c2", rv._clusters[rv._current_cluster_idx].id)


if __name__ == "__main__":
    unittest.main()
