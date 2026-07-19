import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView


def _photo(pid):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, quality_score=0.5, verdict=Verdict.REVIEW,
                 cluster_id="c")


class MultiSelectTests(unittest.TestCase):
    """FEAT-03: select several photos, then one verdict key hits them all."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self, n=5):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        photos = [_photo(f"p{i}") for i in range(n)]
        rv.load_data([Cluster(id="c", label="c", member_count=n)],
                     {"c": photos}, has_undo=False, events=[])
        rv._cluster_list.setCurrentRow(0)
        return rv, photos

    def test_ctrl_toggle_builds_and_shrinks_selection(self):
        rv, photos = self._view()
        rv._select_photo("p0")
        rv._toggle_selection("p2")
        rv._toggle_selection("p4")
        self.assertEqual({"p0", "p2", "p4"}, rv._selected_ids)
        rv._toggle_selection("p2")  # toggle off
        self.assertEqual({"p0", "p4"}, rv._selected_ids)

    def test_shift_selects_inclusive_range(self):
        rv, photos = self._view()
        rv._select_photo("p1")            # anchor
        rv._range_selection("p3")
        self.assertEqual({"p1", "p2", "p3"}, rv._selected_ids)

    def test_verdict_applies_to_all_selected(self):
        rv, photos = self._view()
        rv._select_photo("p0")
        rv._toggle_selection("p1")
        rv._toggle_selection("p2")
        rv._mark_delete()
        by_id = {p.id: p for p in photos}
        self.assertEqual(Verdict.DELETE, by_id["p0"].verdict)
        self.assertEqual(Verdict.DELETE, by_id["p1"].verdict)
        self.assertEqual(Verdict.DELETE, by_id["p2"].verdict)
        self.assertEqual(Verdict.REVIEW, by_id["p3"].verdict)  # untouched

    def test_multi_verdict_undoes_as_one_step(self):
        rv, photos = self._view()
        rv._select_photo("p0")
        rv._toggle_selection("p1")
        rv._mark_delete()
        rv._undo_verdict()  # one undo restores both
        by_id = {p.id: p for p in photos}
        self.assertEqual(Verdict.REVIEW, by_id["p0"].verdict)
        self.assertEqual(Verdict.REVIEW, by_id["p1"].verdict)

    def test_plain_select_resets_to_one(self):
        rv, photos = self._view()
        rv._toggle_selection("p0")
        rv._toggle_selection("p1")
        rv._select_photo("p3")
        self.assertEqual({"p3"}, rv._selected_ids)

    def test_select_all_shown_and_clear(self):
        rv, photos = self._view()
        rv._select_all_shown()
        self.assertEqual({p.id for p in photos}, rv._selected_ids)
        rv._clear_selection()
        self.assertEqual(set(), rv._selected_ids)

    def test_on_card_button_applies_to_whole_selection(self):
        # Clicking one card's Delete while several are selected hits them all.
        rv, photos = self._view()
        rv._select_photo("p0")
        rv._toggle_selection("p1")
        rv._toggle_selection("p2")
        rv._on_thumb_verdict_changed("p1", "DELETE")
        by_id = {p.id: p for p in photos}
        self.assertEqual(Verdict.DELETE, by_id["p0"].verdict)
        self.assertEqual(Verdict.DELETE, by_id["p1"].verdict)
        self.assertEqual(Verdict.DELETE, by_id["p2"].verdict)
        self.assertEqual(Verdict.REVIEW, by_id["p3"].verdict)  # untouched

    def test_selection_bar_switches_to_actions_when_multi(self):
        rv, photos = self._view()
        rv._select_photo("p0")  # single selection -> idle bar
        self.assertFalse(rv._btn_select_all.isHidden())
        self.assertTrue(rv._btn_delete_sel.isHidden())
        rv._toggle_selection("p1")  # now 2 selected -> action bar
        self.assertIn("2 photos selected", rv._selection_count_label.text())
        self.assertFalse(rv._btn_delete_sel.isHidden())
        self.assertTrue(rv._btn_select_all.isHidden())


if __name__ == "__main__":
    unittest.main()
