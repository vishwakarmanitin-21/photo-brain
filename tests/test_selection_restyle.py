"""UX-18: moving the selection restyles only the tiles whose state changed,
not every card in the grid (it was 6 stylesheet calls x every tile per key)."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView, ThumbnailWidget


def _p(i):
    return Photo(id=f"p{i:02d}", filepath=f"C:/x/p{i:02d}.jpg", filename=f"p{i:02d}.jpg",
                 file_size=1, sharpness=100.0, brightness=120.0, quality_score=0.5 - i / 100,
                 verdict=Verdict.REVIEW, cluster_id="c1")


class SelectionRestyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_arrow_move_restyles_two_tiles_not_all(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        photos = [_p(i) for i in range(40)]
        rv.load_data([Cluster(id="c1", label="c1", member_count=40)], {"c1": photos},
                     has_undo=False, events=[])
        rv.set_hide_singletons(False)
        self.assertEqual(40, len(rv._thumb_widgets))
        first = rv._get_current_photos()[0].id
        rv._select_photo(first)
        with patch.object(ThumbnailWidget, "_update_style", autospec=True) as restyle:
            rv._select_next_photo()
        # the old selection loses its highlight, the new one gains it — nothing else
        self.assertEqual(2, restyle.call_count)
        self.assertEqual(1, len(rv._selected_ids))
        self.assertNotIn(first, rv._selected_ids)

    def test_unchanged_state_is_a_no_op(self):
        w = ThumbnailWidget(_p(1))
        self.addCleanup(w.deleteLater)
        with patch.object(ThumbnailWidget, "_update_style", autospec=True) as restyle:
            w.set_selected(False)
            w.set_selected(True)
            w.set_selected(True)
        self.assertEqual(1, restyle.call_count)


if __name__ == "__main__":
    unittest.main()
