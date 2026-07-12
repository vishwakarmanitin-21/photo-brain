import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import (
    ReviewView, ThumbnailWidget, VERDICT_BADGE_LETTER,
)


def _photo(pid, cid="c", verdict=Verdict.REVIEW):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, quality_score=0.5, verdict=verdict, cluster_id=cid)


class VerdictBadgeTests(unittest.TestCase):
    """UX-12: each verdict shows a distinct LETTER, not colour alone."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_letters_are_distinct(self):
        letters = set(VERDICT_BADGE_LETTER.values())
        self.assertEqual(len(letters), len(VERDICT_BADGE_LETTER))

    def test_badge_reflects_verdict(self):
        w = ThumbnailWidget(_photo("p", verdict=Verdict.KEEP))
        self.addCleanup(w.deleteLater)
        self.assertEqual("K", w._verdict_badge.text())
        w.update_verdict(Verdict.DELETE)
        self.assertEqual("D", w._verdict_badge.text())
        self.assertEqual("DELETE", w._verdict_badge.toolTip())


class GridNavigationTests(unittest.TestCase):
    """UX-12: Up/Down move a full grid row, not just linearly."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view_with_photos(self, n):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        cluster = Cluster(id="c", label="c", member_count=n)
        photos = [_photo(f"p{i}") for i in range(n)]
        rv.load_data([cluster], {"c": photos}, has_undo=False, events=[])
        rv._cluster_list.setCurrentRow(0)
        return rv, photos

    def test_down_moves_by_one_row(self):
        rv, photos = self._view_with_photos(9)
        rv._get_grid_columns = lambda: 3  # deterministic 3-wide grid
        rv._select_photo(photos[0].id)
        rv._select_photo_below()
        self.assertEqual(photos[3].id, rv._selected_photo_id)  # down one row
        rv._select_photo_above()
        self.assertEqual(photos[0].id, rv._selected_photo_id)  # back up

    def test_down_clamps_at_last_photo(self):
        rv, photos = self._view_with_photos(9)
        rv._get_grid_columns = lambda: 3
        rv._select_photo(photos[7].id)
        rv._select_photo_below()  # 7 + 3 = 10 → clamp to last (8)
        self.assertEqual(photos[8].id, rv._selected_photo_id)

    def test_up_from_top_stays(self):
        rv, photos = self._view_with_photos(9)
        rv._get_grid_columns = lambda: 3
        rv._select_photo(photos[1].id)
        rv._select_photo_above()  # 1 - 3 = -2 → clamp to 0
        self.assertEqual(photos[0].id, rv._selected_photo_id)


if __name__ == "__main__":
    unittest.main()
