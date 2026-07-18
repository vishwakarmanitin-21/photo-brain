"""Whole-batch 'All photos (ranked)' view + cross-cluster batch actions."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import (
    ReviewView, VIEW_ALL, VIEW_GROUPS, QUALITY_FILTER_LOW, SORT_BEST,
)


def _photo(pid, score, low=False, name=None):
    # A "low" photo is scoreable (sharpness>0) but below the quality bar, so
    # is_low_quality() flags it; a normal one sits above the bar.
    return Photo(
        id=pid, filepath=f"C:/x/{name or pid}.jpg", filename=(name or pid) + ".jpg",
        file_size=10, sharpness=100.0, brightness=120.0,
        quality_score=score, verdict=Verdict.REVIEW, cluster_id="?",
    )


class GlobalViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        c1 = Cluster(id="c1", label="c1", member_count=2)
        c2 = Cluster(id="c2", label="c2", member_count=2)
        photos = {
            "c1": [_photo("g1", 0.60, name="good1"), _photo("j1", 0.05, name="junk1")],
            "c2": [_photo("g2", 0.70, name="good2"), _photo("j2", 0.08, name="junk2")],
        }
        for cid, ps in photos.items():
            for p in ps:
                p.cluster_id = cid
        rv.load_data([c1, c2], photos, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        self.by_id = {p.id: p for ps in photos.values() for p in ps}
        return rv

    def test_flat_view_spans_all_clusters_ranked(self):
        rv = self._view()
        rv._sort_combo.setCurrentText(SORT_BEST)
        rv._view_combo.setCurrentText(VIEW_ALL)
        ids = [p.id for p in rv._current_photos]
        # every photo from both clusters, best score first
        self.assertEqual(["g2", "g1", "j2", "j1"], ids)

    def test_cluster_only_buttons_disabled_in_flat_view(self):
        rv = self._view()
        rv._view_combo.setCurrentText(VIEW_ALL)
        self.assertFalse(rv._btn_keep_top1.isEnabled())
        self.assertFalse(rv._btn_delete_rest.isEnabled())
        self.assertFalse(rv._cluster_list.isEnabled())
        rv._view_combo.setCurrentText(VIEW_GROUPS)
        self.assertTrue(rv._btn_keep_top1.isEnabled())
        self.assertTrue(rv._cluster_list.isEnabled())

    def test_low_quality_filter_gathers_junk_across_clusters(self):
        rv = self._view()
        rv._view_combo.setCurrentText(VIEW_ALL)
        rv._quality_filter.setCurrentText(QUALITY_FILTER_LOW)
        targets = {p.id for p in rv._target_photos_for_bulk()}
        self.assertEqual({"j1", "j2"}, targets)

    def test_batch_purge_deletes_only_the_filtered_junk(self):
        rv = self._view()
        rv._confirm_bulk = lambda *a, **k: True  # auto-confirm the dialog
        rv._view_combo.setCurrentText(VIEW_ALL)
        rv._quality_filter.setCurrentText(QUALITY_FILTER_LOW)
        rv._delete_all()  # "Delete All Shown"
        self.assertEqual(Verdict.DELETE, self.by_id["j1"].verdict)
        self.assertEqual(Verdict.DELETE, self.by_id["j2"].verdict)
        # the good photos are untouched
        self.assertNotEqual(Verdict.DELETE, self.by_id["g1"].verdict)
        self.assertNotEqual(Verdict.DELETE, self.by_id["g2"].verdict)

    def test_batch_purge_undoes_as_one_step(self):
        rv = self._view()
        rv._confirm_bulk = lambda *a, **k: True
        rv._view_combo.setCurrentText(VIEW_ALL)
        rv._quality_filter.setCurrentText(QUALITY_FILTER_LOW)
        rv._delete_all()
        rv._undo_verdict()
        self.assertEqual(Verdict.REVIEW, self.by_id["j1"].verdict)
        self.assertEqual(Verdict.REVIEW, self.by_id["j2"].verdict)


if __name__ == "__main__":
    unittest.main()
