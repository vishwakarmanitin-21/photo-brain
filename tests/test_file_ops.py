import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.core.file_ops import FileOperator
from app.core.models import DupType, Photo, Verdict
from app.core.session_store import SessionStore


class FileOperatorJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source = self.temp_dir.name
        self.store = SessionStore(os.path.join(self.source, "session.db"))
        self.session_id = "session-1"
        self.store.create_session(self.session_id, self.source)
        self.operator = FileOperator(self.source, self.store, self.session_id)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def _photo(self, filename="photo.jpg"):
        path = os.path.join(self.source, filename)
        with open(path, "wb") as handle:
            handle.write(b"test image bytes")
        return Photo(
            id=filename,
            filepath=path,
            filename=filename,
            file_size=os.path.getsize(path),
            verdict=Verdict.KEEP,
            dup_type=DupType.NONE,
            cluster_id="cluster-1",
        )

    def test_move_is_journaled_before_filesystem_mutation(self):
        photo = self._photo()
        real_move = shutil.move

        def assert_journal_then_move(source, destination):
            entries = self.store.get_apply_log(self.session_id)
            self.assertEqual(1, len(entries))
            self.assertEqual(source, entries[0].original_path)
            self.assertEqual(destination, entries[0].destination_path)
            self.assertIsNotNone(entries[0].db_id)
            return real_move(source, destination)

        with patch("app.core.file_ops.shutil.move", side_effect=assert_journal_then_move):
            processed, errors = self.operator.apply_verdicts([photo])

        self.assertEqual((1, 0), (processed, errors))
        self.assertFalse(os.path.exists(photo.filepath))
        destination = self.store.get_apply_log(self.session_id)[0].destination_path
        self.assertTrue(os.path.exists(destination))

    def test_failed_move_removes_unused_journal_plan(self):
        photo = self._photo()

        with patch("app.core.file_ops.shutil.move", side_effect=OSError("locked")):
            processed, errors = self.operator.apply_verdicts([photo])

        self.assertEqual((0, 1), (processed, errors))
        self.assertTrue(os.path.exists(photo.filepath))
        self.assertEqual([], self.store.get_apply_log(self.session_id))

    def test_journal_survives_exception_after_source_disappears(self):
        photo = self._photo()
        real_move = shutil.move

        def move_then_raise(source, destination):
            real_move(source, destination)
            raise OSError("late filesystem error")

        with patch("app.core.file_ops.shutil.move", side_effect=move_then_raise):
            processed, errors = self.operator.apply_verdicts([photo])

        self.assertEqual((0, 1), (processed, errors))
        self.assertFalse(os.path.exists(photo.filepath))
        entries = self.store.get_apply_log(self.session_id)
        self.assertEqual(1, len(entries))
        self.assertTrue(os.path.exists(entries[0].destination_path))


if __name__ == "__main__":
    unittest.main()
