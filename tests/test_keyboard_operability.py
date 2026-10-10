"""Keyboard operability: the view-wide single-key shortcuts must not steal
keys that the focused control needs, and must not fire destructive actions
while the user is only navigating filters.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView


def _photo(pid, cid, score=0.5):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=10, sharpness=100.0, brightness=120.0,
                 quality_score=score, verdict=Verdict.REVIEW, cluster_id=cid)


class KeyboardOperabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self, n_clusters=3, per=3):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        # Close each test's window: a shown window left from an earlier test
        # keeps its timers (e.g. the resize reflow) and can disturb the next
        # test's keyboard focus.
        self.addCleanup(rv.close)
        clusters = [Cluster(id=f"c{i}", label=f"c{i}", member_count=per)
                    for i in range(n_clusters)]
        cp = {f"c{i}": [_photo(f"c{i}_p{j}", f"c{i}", 0.9 - 0.1 * j)
                        for j in range(per)] for i in range(n_clusters)}
        rv.load_data(clusters, cp, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        rv.resize(1200, 800)
        rv.show()
        QApplication.processEvents()
        rv._cluster_list.setCurrentRow(0)
        QApplication.processEvents()
        self.photos = {p.id: p for g in cp.values() for p in g}
        return rv

    def _changed(self):
        return {pid: p.verdict for pid, p in self.photos.items()
                if p.verdict != Verdict.REVIEW}

    def test_down_in_group_list_moves_to_next_group(self):
        # The natural thing to try: arrow keys in the group list must change
        # group, not silently move an unseen photo selection.
        rv = self._view()
        rv._cluster_list.setFocus()
        QApplication.processEvents()
        self.assertEqual(0, rv._current_cluster_idx)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        QApplication.processEvents()
        self.assertEqual(1, rv._current_cluster_idx)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Up)
        QApplication.processEvents()
        self.assertEqual(0, rv._current_cluster_idx)

    def test_verdict_keys_still_work_while_browsing_the_group_list(self):
        # Arrows navigate groups AND K/A/D still act on the selected photo.
        rv = self._view()
        rv._cluster_list.setFocus()
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)   # -> group 1
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_D)
        QApplication.processEvents()
        self.assertEqual({"c1_p0": Verdict.DELETE}, self._changed())

    def test_dropdown_keeps_its_own_keys_and_cannot_delete(self):
        # Arrows change the dropdown value, and a letter must never fire a
        # destructive verdict while the user is only changing a filter.
        rv = self._view()
        rv._sort_combo.setFocus()
        QApplication.processEvents()
        before = rv._sort_combo.currentText()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down)
        QApplication.processEvents()
        self.assertNotEqual(before, rv._sort_combo.currentText())
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_D)
        QApplication.processEvents()
        self.assertEqual({}, self._changed())

    def test_typing_in_search_never_fires_verdicts(self):
        rv = self._view()
        rv._search_box.setFocus()
        QApplication.processEvents()
        for key in (Qt.Key_K, Qt.Key_A, Qt.Key_D):
            QTest.keyClick(QApplication.focusWidget(), key)
            QApplication.processEvents()
        self.assertEqual("kad", rv._search_box.text())
        self.assertEqual({}, self._changed())

    def test_grid_arrows_move_photo_selection_and_verdict_applies(self):
        rv = self._view()
        rv.setFocus()
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Right)
        QApplication.processEvents()
        self.assertEqual("c0_p1", rv._selected_photo_id)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_D)
        QApplication.processEvents()
        self.assertEqual({"c0_p1": Verdict.DELETE}, self._changed())

    def test_ctrl_arrows_change_group_from_the_grid(self):
        # Plain Up/Down belong to the grid there, so Ctrl+arrows give the user
        # group navigation without moving focus.
        rv = self._view()
        rv.setFocus()
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Down, Qt.ControlModifier)
        QApplication.processEvents()
        self.assertEqual(1, rv._current_cluster_idx)
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Up, Qt.ControlModifier)
        QApplication.processEvents()
        self.assertEqual(0, rv._current_cluster_idx)

    def test_delete_key_deletes_like_d(self):
        rv = self._view()
        rv.setFocus()
        QApplication.processEvents()
        QTest.keyClick(QApplication.focusWidget(), Qt.Key_Delete)
        QApplication.processEvents()
        self.assertEqual({"c0_p0": Verdict.DELETE}, self._changed())


if __name__ == "__main__":
    unittest.main()
