"""UX-23: the photo grid reflows when its width changes, without recreating
tiles, and Up/Down moves by the columns actually on screen."""
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView


def _p(i):
    return Photo(id=f"p{i:02d}", filepath=f"C:/x/p{i:02d}.jpg", filename=f"p{i:02d}.jpg",
                 file_size=1, sharpness=100.0, brightness=120.0, quality_score=0.9 - i / 100,
                 verdict=Verdict.REVIEW, cluster_id="c1")


class GridReflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _settle(self, seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def test_widening_reflows_existing_tiles_and_rows_follow(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        narrow = rv.minimumSizeHint().width()
        rv.resize(narrow, 700)
        rv.show()
        rv.load_data([Cluster(id="c1", label="c1", member_count=30)],
                     {"c1": [_p(i) for i in range(30)]}, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        self._settle()
        rv._rebuild_grid_with_zoom()
        before_cols = rv._laid_out_columns
        tiles_before = dict(rv._thumb_widgets)

        rv.resize(narrow + 1200, 700)
        self._settle()
        self.assertGreater(rv._laid_out_columns, before_cols)
        # same widget objects — moved, not recreated
        self.assertEqual({k: id(v) for k, v in tiles_before.items()},
                         {k: id(v) for k, v in rv._thumb_widgets.items()})
        # the layout really has that many columns
        first_row = [rv._grid_layout.getItemPosition(rv._grid_layout.indexOf(w))[0]
                     for w in rv._thumb_widgets.values()].count(0)
        self.assertEqual(rv._laid_out_columns, first_row)

        # Down moves exactly one laid-out row
        photos = rv._get_current_photos()
        rv._select_photo(photos[0].id)
        rv._select_photo_below()
        self.assertEqual(photos[rv._laid_out_columns].id, rv._selected_photo_id)


if __name__ == "__main__":
    unittest.main()
