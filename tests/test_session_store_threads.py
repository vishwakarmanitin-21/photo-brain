import os
import tempfile
import threading
import unittest

from app.core.models import Photo, Verdict
from app.core.session_store import SessionStore


class SessionStoreThreadTests(unittest.TestCase):
    def test_worker_threads_use_independent_connections(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SessionStore(os.path.join(temp_dir, "session.db"))
            session_id = "session-1"
            store.create_session(session_id, temp_dir)
            photos = [
                Photo(
                    id=f"photo-{index}",
                    filepath=os.path.join(temp_dir, f"photo-{index}.jpg"),
                    filename=f"photo-{index}.jpg",
                    file_size=10,
                )
                for index in range(2)
            ]
            store.insert_photos_batch(session_id, photos)
            main_connection_id = id(store._conn)
            connection_ids = []
            errors = []
            barrier = threading.Barrier(2)

            def update_repeatedly(photo):
                try:
                    barrier.wait()
                    connection_ids.append(id(store._conn))
                    for iteration in range(20):
                        verdict = Verdict.KEEP if iteration % 2 else Verdict.ARCHIVE
                        store.update_photo_verdict(photo.id, verdict)
                        store.get_photos_by_session(session_id)
                except Exception as error:
                    errors.append(error)

            threads = [
                threading.Thread(target=update_repeatedly, args=(photo,))
                for photo in photos
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual([], errors)
            self.assertEqual(2, len(set(connection_ids)))
            self.assertNotIn(main_connection_id, connection_ids)
            saved = store.get_photos_by_session(session_id)
            self.assertEqual([Verdict.KEEP, Verdict.KEEP], [p.verdict for p in saved])
            store.close()


if __name__ == "__main__":
    unittest.main()
