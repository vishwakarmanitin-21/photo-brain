import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView


def _photo(pid: str, score: float) -> Photo:
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=10, sharpness=100.0, brightness=120.0,
                 quality_score=score, verdict=Verdict.KEEP)


class VerdictUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _loaded(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        cluster = Cluster(id="c1", label="c1", member_count=3)
        photos = [_photo("a", 0.5), _photo("b", 0.4), _photo("c", 0.3)]
        rv.load_data([cluster], {"c1": photos}, has_undo=False, events=[])
        rv._cluster_list.setCurrentRow(0)
        return rv, {p.id: p for p in photos}

    def test_single_change_then_undo(self):
        rv, by_id = self._loaded()
        rv._select_photo("b")
        rv._mark_archive()
        self.assertEqual(Verdict.ARCHIVE, by_id["b"].verdict)
        rv._undo_verdict()
        self.assertEqual(Verdict.KEEP, by_id["b"].verdict)

    def test_undo_is_lifo_across_several_changes(self):
        rv, by_id = self._loaded()
        rv._select_photo("a"); rv._mark_delete()
        rv._select_photo("b"); rv._mark_archive()
        self.assertEqual(Verdict.DELETE, by_id["a"].verdict)
        self.assertEqual(Verdict.ARCHIVE, by_id["b"].verdict)

        rv._undo_verdict()   # undoes b
        self.assertEqual(Verdict.KEEP, by_id["b"].verdict)
        self.assertEqual(Verdict.DELETE, by_id["a"].verdict)  # a still changed

        rv._undo_verdict()   # undoes a
        self.assertEqual(Verdict.KEEP, by_id["a"].verdict)

    def test_bulk_change_undoes_as_one_step(self):
        rv, by_id = self._loaded()
        rv._archive_all()
        self.assertTrue(all(p.verdict == Verdict.ARCHIVE for p in by_id.values()))
        rv._undo_verdict()
        self.assertTrue(all(p.verdict == Verdict.KEEP for p in by_id.values()))

    def test_undo_with_empty_stack_is_noop(self):
        rv, by_id = self._loaded()
        rv._undo_verdict()  # nothing to undo
        self.assertTrue(all(p.verdict == Verdict.KEEP for p in by_id.values()))

    def test_undo_does_not_re_record_itself(self):
        rv, by_id = self._loaded()
        rv._select_photo("a"); rv._mark_delete()
        rv._undo_verdict()
        # Stack is now empty; a second undo must not resurrect the change.
        rv._undo_verdict()
        self.assertEqual(Verdict.KEEP, by_id["a"].verdict)


if __name__ == "__main__":
    unittest.main()
