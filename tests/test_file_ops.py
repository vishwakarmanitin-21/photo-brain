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

    def test_only_successful_touched_clusters_are_applied(self):
        successful = self._photo("successful.jpg")
        successful.cluster_id = "successful-cluster"
        missing = self._photo("missing.jpg")
        missing.cluster_id = "failed-cluster"
        os.remove(missing.filepath)
        undecided = self._photo("undecided.jpg")
        undecided.cluster_id = "untouched-cluster"
        undecided.verdict = Verdict.REVIEW

        processed, errors = self.operator.apply_verdicts(
            [successful, missing, undecided],
        )

        self.assertEqual((1, 1), (processed, errors))
        self.assertEqual({"successful-cluster"}, self.operator.applied_cluster_ids)

    def test_cluster_with_partial_failure_remains_unapplied(self):
        first = self._photo("first.jpg")
        first.cluster_id = "cluster-1"
        second = self._photo("second.jpg")
        second.cluster_id = "cluster-1"
        real_move = shutil.move

        def fail_second(source, destination):
            if source == second.filepath:
                raise OSError("locked")
            return real_move(source, destination)

        with patch("app.core.file_ops.shutil.move", side_effect=fail_second):
            processed, errors = self.operator.apply_verdicts([first, second])

        self.assertEqual((1, 1), (processed, errors))
        self.assertEqual(set(), self.operator.applied_cluster_ids)

    def test_undo_keeps_failed_restore_for_retry(self):
        first = self._photo("first.jpg")
        second = self._photo("second.jpg")
        self.operator.apply_verdicts([first, second])
        entries = self.store.get_apply_log(self.session_id)
        locked_destination = next(
            entry.destination_path for entry in entries
            if entry.photo_id == second.id
        )
        real_move = shutil.move

        def fail_locked(source, destination):
            if source == locked_destination:
                raise OSError("locked")
            return real_move(source, destination)

        with patch("app.core.file_ops.shutil.move", side_effect=fail_locked):
            restored, skipped = self.operator.undo_last_apply()

        self.assertEqual((1, 1), (restored, skipped))
        remaining = self.store.get_apply_log(self.session_id)
        self.assertEqual([second.id], [entry.photo_id for entry in remaining])
        self.assertTrue(os.path.exists(locked_destination))

        restored, skipped = self.operator.undo_last_apply()
        self.assertEqual((1, 0), (restored, skipped))
        self.assertEqual([], self.store.get_apply_log(self.session_id))
        self.assertTrue(os.path.exists(second.filepath))

    def test_undo_resolves_write_ahead_plan_when_source_is_already_original(self):
        photo = self._photo()
        from app.core.models import ApplyLogEntry

        entry = ApplyLogEntry(
            photo_id=photo.id,
            original_path=photo.filepath,
            destination_path=os.path.join(self.source, "03_KEEP", photo.filename),
            verdict="KEEP",
            dup_type="none",
            destination_folder="03_KEEP",
            cluster_id="cluster-1",
            timestamp="2026-07-11T00:00:00+00:00",
        )
        self.store.insert_apply_log_entry(self.session_id, entry)

        restored, skipped = self.operator.undo_last_apply()

        self.assertEqual((1, 0), (restored, skipped))
        self.assertTrue(os.path.exists(photo.filepath))
        self.assertEqual([], self.store.get_apply_log(self.session_id))


if __name__ == "__main__":
    unittest.main()
