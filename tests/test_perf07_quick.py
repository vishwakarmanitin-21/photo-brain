"""PERF-07 (quick half): search waits for a pause in typing, and decoded
thumbnails are kept in memory instead of re-read on every grid rebuild."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui import review_view
from app.ui.review_view import ReviewView


def _p(pid, cid, name):
    return Photo(id=pid, filepath=f"C:/x/{name}.jpg", filename=f"{name}.jpg", file_size=1,
                 sharpness=100.0, brightness=120.0, quality_score=0.5,
                 verdict=Verdict.REVIEW, cluster_id=cid)


class SearchDebounceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.load_data([Cluster(id="c1", label="c1", member_count=2), Cluster(id="c2", label="c2", member_count=2)],
                     {"c1": [_p("a", "c1", "beach1"), _p("b", "c1", "beach2")],
                      "c2": [_p("c", "c2", "lake1"), _p("d", "c2", "lake2")]},
                     has_undo=False, events=[])
        rv.set_hide_singletons(False)
        return rv

    def test_typing_filters_once_after_a_pause(self):
        rv = self._view()
        fired = []
        rv._search_timer.timeout.connect(lambda: fired.append(True))
        for prefix in ("b", "be", "bea", "beac", "beach"):
            rv._search_box.setText(prefix)
        # nothing filtered per keystroke
        self.assertEqual({"c1", "c2"}, {c.id for c in rv._clusters})
        end = time.time() + 2
        while time.time() < end and not fired:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertEqual(1, len(fired))                    # one pass after the pause
        self.assertEqual(["c1"], [c.id for c in rv._clusters])

    def test_clearing_applies_immediately(self):
        rv = self._view()
        rv._search_box.setText("beach")
        rv.flush_search()
        rv._search_box.setText("")
        self.assertEqual({"c1", "c2"}, {c.id for c in rv._clusters})


class ThumbMemoryCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_request_does_not_touch_disk_and_lru_is_bounded(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for i in range(4):
                path = os.path.join(d, f"t{i}.jpg")
                Image.new("RGB", (200, 150), (i * 40, 0, 0)).save(path)
                paths.append(path)
            first = rv._thumb_pixmap(paths[0])
            os.remove(paths[0])                            # disk copy gone...
            self.assertFalse(rv._thumb_pixmap(paths[0]).isNull())   # ...still served
            self.assertIs(first, rv._thumb_pixmap(paths[0]))
            with patch.object(review_view, "THUMB_MEMORY_CACHE", 2):
                for path in paths[1:]:
                    rv._thumb_pixmap(path)
                self.assertEqual(2, len(rv._thumb_memory))
                self.assertNotIn(paths[0], rv._thumb_memory)      # least recent evicted


if __name__ == "__main__":
    unittest.main()
