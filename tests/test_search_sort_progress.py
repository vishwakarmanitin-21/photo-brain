import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import (
    ReviewView, sort_photos,
    SORT_BEST, SORT_NEWEST, SORT_OLDEST, SORT_LARGEST, SORT_SMALLEST,
)


def _photo(pid, score=0.5, size=10, dt=None, name=None):
    return Photo(id=pid, filepath=f"C:/x/{name or pid}.jpg",
                 filename=(name or pid) + ".jpg", file_size=size,
                 quality_score=score, verdict=Verdict.REVIEW,
                 exif_datetime=dt, cluster_id="c")


class SortPhotosTests(unittest.TestCase):
    """FEAT-05: pure sort helper — deterministic, filepath tiebreak."""

    def _ids(self, photos, mode):
        return [p.id for p in sort_photos(photos, mode)]

    def test_best_first(self):
        ps = [_photo("a", score=0.2), _photo("b", score=0.9), _photo("c", score=0.5)]
        self.assertEqual(["b", "c", "a"], self._ids(ps, SORT_BEST))

    def test_size_sorts(self):
        ps = [_photo("a", size=100), _photo("b", size=5), _photo("c", size=50)]
        self.assertEqual(["a", "c", "b"], self._ids(ps, SORT_LARGEST))
        self.assertEqual(["b", "c", "a"], self._ids(ps, SORT_SMALLEST))

    def test_date_sorts_and_undated_go_last_when_oldest(self):
        ps = [
            _photo("new", dt="2024-01-02 10:00:00"),
            _photo("old", dt="2020-01-01 10:00:00"),
            _photo("undated", dt=None),
        ]
        self.assertEqual(["new", "old", "undated"], self._ids(ps, SORT_NEWEST))
        # Oldest first, but a missing date must not masquerade as oldest.
        self.assertEqual(["old", "new", "undated"], self._ids(ps, SORT_OLDEST))


class SearchAndProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        c1 = Cluster(id="c1", label="c1", member_count=2)
        c2 = Cluster(id="c2", label="c2", member_count=2)
        c1.reviewed = True
        c2.reviewed = False
        photos = {
            "c1": [_photo("a", name="beach_sunset"), _photo("b", name="beach_wave")],
            "c2": [_photo("c", name="mountain"), _photo("d", name="lake")],
        }
        rv.load_data([c1, c2], photos, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        return rv

    def test_search_narrows_to_matching_groups(self):
        rv = self._view()
        rv._search_box.setText("beach")
        self.assertEqual(["c1"], [c.id for c in rv._clusters])
        rv._search_box.setText("")  # cleared → all groups
        self.assertEqual({"c1", "c2"}, {c.id for c in rv._clusters})

    def test_progress_counts_reviewed_groups(self):
        rv = self._view()
        rv._update_review_progress()
        self.assertIn("1 of 2 groups reviewed", rv._progress_label.text())

    def test_sort_reorders_current_grid(self):
        rv = self._view()
        rv._cluster_list.setCurrentRow(0)  # c1: beach_sunset, beach_wave
        rv._sort_combo.setCurrentText(SORT_SMALLEST)
        # Deterministic order by name tiebreak (equal sizes) → sunset before wave.
        self.assertEqual(["a", "b"], [p.id for p in rv._current_photos])


if __name__ == "__main__":
    unittest.main()
