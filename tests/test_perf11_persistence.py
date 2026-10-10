"""PERF-11: review autosave writes only what changed, and the review screen
loads every photo in one query (same per-group order as before)."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.models import Cluster, Photo, Verdict
from app.core.session_store import SessionStore
from app.ui import main_window
from app.ui.main_window import MainWindow


def _photo(pid, cid, score):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg", file_size=1,
                 cluster_id=cid, quality_score=score)


class Perf11Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(os.path.join(self.tmp.name, "s.db"))
        self.store.create_session("s1", self.tmp.name)
        self.photos = [_photo("a", "c1", 0.5), _photo("b", "c1", 0.9), _photo("t", "c1", 0.5),
                       _photo("c", "c2", 0.2), _photo("d", "c2", 0.7)]
        self.clusters = [Cluster(id="c1", label="c1", member_count=3),
                         Cluster(id="c2", label="c2", member_count=2)]
        self.store.insert_photos_batch("s1", self.photos)
        self.store.insert_clusters_batch("s1", self.clusters)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_grouped_query_matches_per_cluster_queries(self):
        grouped = self.store.get_photos_grouped_by_cluster("s1")
        for c in self.clusters:
            self.assertEqual([p.id for p in self.store.get_photos_by_cluster(c.id)],
                             [p.id for p in grouped[c.id]])
        self.assertEqual(["b", "a", "t"], [p.id for p in grouped["c1"]])  # score desc, rowid tiebreak

    def test_only_changed_photos_and_groups_are_written(self):
        window = SimpleNamespace(store=self.store, session_id="s1", review_view=SimpleNamespace(
            get_all_photos=lambda: self.photos, get_all_clusters=lambda: self.clusters))
        window._persisted_photos = {p.id: main_window._photo_review_state(p) for p in self.photos}
        window._persisted_clusters = {c.id: main_window._cluster_review_state(c) for c in self.clusters}

        self.photos[3].verdict = Verdict.DELETE
        self.photos[3].user_override = True
        self.clusters[1].reviewed = True
        with patch.object(self.store, "update_photos_batch", wraps=self.store.update_photos_batch) as up, \
                patch.object(self.store, "update_clusters_review_state",
                             wraps=self.store.update_clusters_review_state) as uc:
            MainWindow._persist_review_state(window)
            self.assertEqual(["c"], [p.id for p in up.call_args.args[0]])
            self.assertEqual(["c2"], [c.id for c in uc.call_args.args[0]])
            # nothing new -> nothing written
            MainWindow._persist_review_state(window)
            self.assertEqual(1, up.call_count)
            self.assertEqual(1, uc.call_count)

        saved = {p.id: p for p in self.store.get_photos_by_session("s1")}
        self.assertEqual(Verdict.DELETE, saved["c"].verdict)
        self.assertTrue(next(c for c in self.store.get_clusters_by_session("s1") if c.id == "c2").reviewed)

    def test_without_snapshot_everything_is_written(self):
        self.assertEqual(5, len(main_window._changed(self.photos, main_window._photo_review_state, None)))


if __name__ == "__main__":
    unittest.main()
