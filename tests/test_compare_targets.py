"""UX-17: Compare opens the selection or the current group — never the whole
'All photos' view, which can hold 600 photos and froze the app."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import MAX_COMPARE, VIEW_ALL, ReviewView, compare_targets


def _p(pid, score=0.5, cluster="c1"):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg", file_size=1,
                 sharpness=100.0, brightness=120.0, quality_score=score,
                 verdict=Verdict.REVIEW, cluster_id=cluster)


class CompareTargetsTests(unittest.TestCase):
    def test_selection_of_two_or_more_wins(self):
        shown = [_p("a"), _p("b"), _p("c")]
        photos, note = compare_targets(shown, {"c", "a"}, view_is_one_group=False)
        self.assertEqual(["a", "c"], [p.id for p in photos])   # grid order
        self.assertEqual("", note)

    def test_flat_view_without_selection_asks_for_one(self):
        shown = [_p(str(i)) for i in range(600)]
        photos, note = compare_targets(shown, {"0"}, view_is_one_group=False)
        self.assertEqual([], photos)
        self.assertIn("Select 2", note)

    def test_group_without_selection_uses_the_group(self):
        shown = [_p("a"), _p("b")]
        photos, _ = compare_targets(shown, {"a"}, view_is_one_group=True)
        self.assertEqual(["a", "b"], [p.id for p in photos])

    def test_single_photo_group_has_nothing_to_compare(self):
        photos, note = compare_targets([_p("a")], {"a"}, view_is_one_group=True)
        self.assertEqual([], photos)
        self.assertIn("only one photo", note)

    def test_capped_with_a_note(self):
        shown = [_p(str(i)) for i in range(20)]
        photos, note = compare_targets(shown, set(), view_is_one_group=True)
        self.assertEqual(MAX_COMPARE, len(photos))
        self.assertIn(f"first {MAX_COMPARE} of 20", note)


class CompareFromReviewViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        photos = {"c1": [_p("a", 0.6), _p("b", 0.4)], "c2": [_p("x", 0.7, "c2"), _p("y", 0.3, "c2")]}
        rv.load_data([Cluster(id="c1", label="c1", member_count=2),
                      Cluster(id="c2", label="c2", member_count=2)],
                     photos, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        return rv

    def test_flat_view_does_not_open_every_photo(self):
        rv = self._view()
        rv._view_combo.setCurrentText(VIEW_ALL)
        with patch("app.ui.review_view.CompareDialog") as dlg, \
                patch("app.ui.review_view.QMessageBox.information") as info:
            rv._open_compare()
        dlg.assert_not_called()
        info.assert_called_once()

    def test_flat_view_compares_the_multi_selection(self):
        rv = self._view()
        rv._view_combo.setCurrentText(VIEW_ALL)
        rv._selected_ids = {"a", "y"}
        with patch("app.ui.review_view.CompareDialog") as dlg:
            rv._open_compare()
        passed = dlg.call_args.args[0]
        self.assertEqual({"a", "y"}, {p.id for p in passed})


if __name__ == "__main__":
    unittest.main()
