"""O4: duplicate-type filter and one-click exact-duplicate resolution."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict, DupType
from app.ui.review_view import (
    ReviewView, photo_matches_dup,
    DUP_FILTER_EXACT, DUP_FILTER_NEAR, DUP_FILTER_UNIQUE,
)


def _photo(pid, dup=DupType.NONE, score=0.5, cid="c"):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=10, sharpness=100.0, brightness=120.0,
                 quality_score=score, dup_type=dup, verdict=Verdict.REVIEW,
                 cluster_id=cid)


class DupPredicateTests(unittest.TestCase):
    def test_predicate(self):
        self.assertTrue(photo_matches_dup(_photo("a", DupType.EXACT), DUP_FILTER_EXACT))
        self.assertFalse(photo_matches_dup(_photo("a", DupType.NEAR), DUP_FILTER_EXACT))
        self.assertTrue(photo_matches_dup(_photo("a", DupType.NEAR), DUP_FILTER_NEAR))
        self.assertTrue(photo_matches_dup(_photo("a", DupType.NONE), DUP_FILTER_UNIQUE))


class DupResolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        exact = Cluster(id="e", label="e", member_count=2, is_exact_dup_group=True)
        near = Cluster(id="n", label="n", member_count=2)
        photos = {
            "e": [_photo("e_best", DupType.EXACT, 0.8, "e"),
                  _photo("e_dup", DupType.EXACT, 0.6, "e")],
            "n": [_photo("n1", DupType.NEAR, 0.7, "n"),
                  _photo("n2", DupType.NEAR, 0.5, "n")],
        }
        rv.load_data([exact, near], photos, has_undo=False, events=[])
        rv.set_hide_singletons(False)
        self.by_id = {p.id: p for ps in photos.values() for p in ps}
        return rv

    def test_dup_filter_isolates_exact(self):
        rv = self._view()
        rv._dup_filter.setCurrentText(DUP_FILTER_EXACT)
        self.assertEqual({"e_best", "e_dup"}, rv._passing_photo_ids)
        rv._dup_filter.setCurrentText(DUP_FILTER_NEAR)
        self.assertEqual({"n1", "n2"}, rv._passing_photo_ids)

    def test_resolve_keeps_best_archives_rest_of_exact_only(self):
        rv = self._view()
        plan = rv._plan_exact_dup_resolution()
        rv._apply_resolution(plan)
        # exact group: best kept, other archived
        self.assertEqual(Verdict.KEEP, self.by_id["e_best"].verdict)
        self.assertEqual(Verdict.ARCHIVE, self.by_id["e_dup"].verdict)
        # near-dup group untouched by the *exact* resolver
        self.assertEqual(Verdict.REVIEW, self.by_id["n1"].verdict)
        self.assertEqual(Verdict.REVIEW, self.by_id["n2"].verdict)

    def test_resolution_undoes_as_one_step(self):
        rv = self._view()
        rv._apply_resolution(rv._plan_exact_dup_resolution())
        rv._undo_verdict()
        self.assertEqual(Verdict.REVIEW, self.by_id["e_best"].verdict)
        self.assertEqual(Verdict.REVIEW, self.by_id["e_dup"].verdict)


if __name__ == "__main__":
    unittest.main()
