import os
import tempfile
import unittest
from types import SimpleNamespace

from app.core.models import Cluster, Photo, Verdict
from app.core.session_store import SessionStore
from app.ui.main_window import MainWindow


class ReviewPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SessionStore(os.path.join(self.temp_dir.name, "session.db"))
        self.session_id = "session-1"
        self.store.create_session(self.session_id, self.temp_dir.name)
        self.photo = Photo(
            id="photo-1",
            filepath=os.path.join(self.temp_dir.name, "photo.jpg"),
            filename="photo.jpg",
            file_size=10,
            cluster_id="cluster-1",
        )
        self.cluster = Cluster(
            id="cluster-1",
            label="Cluster 1",
            member_count=1,
        )
        self.store.insert_photos_batch(self.session_id, [self.photo])
        self.store.insert_clusters_batch(self.session_id, [self.cluster])

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_flush_persists_verdict_and_review_marker(self):
        self.photo.verdict = Verdict.DELETE
        self.photo.user_override = True
        self.cluster.delete_count = 1
        self.cluster.reviewed = True
        review_view = SimpleNamespace(
            get_all_photos=lambda: [self.photo],
            get_all_clusters=lambda: [self.cluster],
        )
        window = SimpleNamespace(
            store=self.store,
            session_id=self.session_id,
            review_view=review_view,
        )

        MainWindow._persist_review_state(window)

        saved_photo = self.store.get_photos_by_session(self.session_id)[0]
        saved_cluster = self.store.get_clusters_by_session(self.session_id)[0]
        self.assertEqual(Verdict.DELETE, saved_photo.verdict)
        self.assertTrue(saved_photo.user_override)
        self.assertTrue(saved_cluster.reviewed)
        self.assertEqual(1, saved_cluster.delete_count)


if __name__ == "__main__":
    unittest.main()
