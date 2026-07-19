"""Interim 'Delete Marked Now': purge recycled records + reconcile clusters,
and the review button that reflects how many are queued for the Recycle Bin."""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Photo, Verdict, Cluster, DupType
from app.core.session_store import SessionStore
from app.core.file_ops import FileOperator
from app.ui.review_view import ReviewView


def _photo(pid, cid, verdict=Verdict.REVIEW):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=10, sharpness=100.0, brightness=120.0,
                 quality_score=0.5, verdict=verdict, cluster_id=cid)


class PurgePhotosTests(unittest.TestCase):
    def _store(self):
        tmp = tempfile.mkdtemp()
        # LIFO cleanup: rmtree registered first runs LAST, after store.close.
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        store = SessionStore(os.path.join(tmp, "session.db"))
        self.addCleanup(store.close)
        store.create_session("s1", tmp)
        store.insert_clusters_batch("s1", [
            Cluster(id="c1", label="c1", member_count=2),
            Cluster(id="c2", label="c2", member_count=1),
        ])
        store.insert_photos_batch("s1", [
            _photo("a", "c1"), _photo("b", "c1"), _photo("solo", "c2")])
        return store

    def test_purge_removes_records_recounts_and_drops_empty(self):
        store = self._store()
        purged = store.purge_photos("s1", ["b", "solo"])
        self.assertEqual(2, purged)
        self.assertEqual({"a"}, {p.id for p in store.get_photos_by_session("s1")})
        clusters = {c.id: c for c in store.get_clusters_by_session("s1")}
        self.assertIn("c1", clusters)
        self.assertEqual(1, clusters["c1"].member_count)  # recounted 2 -> 1
        self.assertNotIn("c2", clusters)                  # emptied -> dropped

    def test_purge_empty_list_is_noop(self):
        store = self._store()
        self.assertEqual(0, store.purge_photos("s1", []))
        self.assertEqual(3, len(store.get_photos_by_session("s1")))


class DeleteNowButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_button_enables_and_counts_deletes(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        rv.load_data([Cluster(id="c", label="c", member_count=2)],
                     {"c": [_photo("a", "c"), _photo("b", "c")]},
                     has_undo=False, events=[])
        rv.set_hide_singletons(False)
        rv._cluster_list.setCurrentRow(0)
        # nothing marked -> disabled
        self.assertFalse(rv._delete_now_btn.isEnabled())
        # mark one for delete -> enabled, count shown
        rv._select_photo("a")
        rv._mark_delete()
        self.assertTrue(rv._delete_now_btn.isEnabled())
        self.assertIn("(1)", rv._delete_now_btn.text())


class DeleteNowIntegrationTests(unittest.TestCase):
    """The core of _on_delete_now without the UI: recycle just the DELETE
    subset, purge the gone records, leave KEEP photos + records intact."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source = self.temp_dir.name
        self.store = SessionStore(os.path.join(self.source, "session.db"))
        self.session_id = "s"
        self.store.create_session(self.session_id, self.source)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def _real_photo(self, pid, cid, verdict):
        path = os.path.join(self.source, f"{pid}.jpg")
        with open(path, "wb") as f:
            f.write(b"bytes-" + pid.encode())
        return Photo(id=pid, filepath=path, filename=f"{pid}.jpg",
                     file_size=os.path.getsize(path), quality_score=0.5,
                     verdict=verdict, dup_type=DupType.NONE, cluster_id=cid)

    def test_delete_now_recycles_and_purges_only_the_deletes(self):
        keep = self._real_photo("keep", "c1", Verdict.KEEP)
        d1 = self._real_photo("d1", "c1", Verdict.DELETE)
        d2 = self._real_photo("d2", "c2", Verdict.DELETE)
        self.store.insert_clusters_batch(self.session_id, [
            Cluster(id="c1", label="c1", member_count=2),
            Cluster(id="c2", label="c2", member_count=1)])
        self.store.insert_photos_batch(self.session_id, [keep, d1, d2])

        operator = FileOperator(self.source, self.store, self.session_id)
        to_delete = [d1, d2]
        # Simulate the Recycle Bin with a plain remove so the test doesn't
        # touch the real trash.
        with patch("app.core.file_ops.send2trash", side_effect=os.remove):
            processed, errors = operator.apply_verdicts(to_delete)
        self.assertEqual((2, 0), (processed, errors))

        gone = [p.id for p in to_delete if not os.path.isfile(p.filepath)]
        self.store.purge_photos(self.session_id, gone)

        # KEEP file + record intact; the two deletes are gone from disk + store.
        self.assertTrue(os.path.isfile(keep.filepath))
        self.assertFalse(os.path.isfile(d1.filepath))
        self.assertFalse(os.path.isfile(d2.filepath))
        self.assertEqual(
            {"keep"},
            {p.id for p in self.store.get_photos_by_session(self.session_id)})
        clusters = {c.id: c for c in self.store.get_clusters_by_session(self.session_id)}
        self.assertEqual(1, clusters["c1"].member_count)  # keep+d1 -> keep only
        self.assertNotIn("c2", clusters)                  # emptied -> dropped


if __name__ == "__main__":
    unittest.main()
