import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from app.core.events import extract_exif_datetime
from app.core.hashing import compute_phash
from app.core.models import Photo
from app.core.scanner import compute_hashes
from app.core.thumbnails import ThumbnailCache


def _write_image(folder: str, name: str, with_exif: bool = False) -> str:
    path = os.path.join(folder, name)
    img = Image.new("RGB", (64, 48), (120, 80, 40))
    if with_exif:
        exif = Image.Exif()
        exif[306] = "2026:07:01 09:00:00"
        img.save(path, quality=85, exif=exif.tobytes())
    else:
        img.save(path, quality=85)
    return path


class HardeningTests(unittest.TestCase):
    """SAFE-12(a): released file handles and vanishing-file tolerance."""

    def test_image_readers_release_file_handles(self):
        # On Windows, renaming fails with a sharing violation while any
        # handle is open — the exact failure mode that used to break
        # apply-moves right after a scan.
        with tempfile.TemporaryDirectory() as folder:
            path = _write_image(folder, "a.jpg", with_exif=True)
            photo = Photo(
                id="p1", filepath=path, filename="a.jpg", file_size=1
            )

            self.assertIsNotNone(compute_phash(path))
            self.assertEqual(
                "2026-07-01T09:00:00", extract_exif_datetime(path)
            )
            cache = ThumbnailCache(os.path.join(folder, "thumbs"))
            self.assertIsNotNone(cache.generate_thumbnail(photo))

            renamed = os.path.join(folder, "renamed.jpg")
            os.rename(path, renamed)  # raises PermissionError if leaked
            self.assertTrue(os.path.isfile(renamed))

    def test_exif_datetime_read_from_memory_after_close(self):
        with tempfile.TemporaryDirectory() as folder:
            path = _write_image(folder, "dated.jpg", with_exif=True)
            self.assertEqual(
                "2026-07-01T09:00:00", extract_exif_datetime(path)
            )

    def test_apply_never_overwrites_file_racing_into_destination(self):
        # SAFE-12(c): a file that appears at the planned destination between
        # planning (resolve_collision) and moving must not be clobbered.
        from app.core.file_ops import FileOperator
        from app.core.models import Verdict
        from app.core.session_store import SessionStore
        from app.util.paths import KEEP_FOLDER, get_db_path

        with tempfile.TemporaryDirectory() as source:
            path = _write_image(source, "a.jpg")
            store = SessionStore(get_db_path(source))
            store.create_session("s1", source)
            photo = Photo(
                id="p1", filepath=path, filename="a.jpg", file_size=1,
                verdict=Verdict.KEEP,
            )

            # Simulate the race: the planned name is already taken by the
            # time the move happens (planning is patched to be a no-op).
            keep_dir = os.path.join(source, KEEP_FOLDER)
            os.makedirs(keep_dir)
            racing = os.path.join(keep_dir, "a.jpg")
            with open(racing, "wb") as f:
                f.write(b"racing-content")

            operator = FileOperator(source, store, "s1")
            with patch(
                "app.core.file_ops.resolve_collision", side_effect=lambda p: p
            ):
                processed, errors = operator.apply_verdicts([photo])

            self.assertEqual((1, 0), (processed, errors))
            with open(racing, "rb") as f:
                self.assertEqual(b"racing-content", f.read())  # untouched
            suffixed = os.path.join(keep_dir, "a_1.jpg")
            self.assertTrue(os.path.isfile(suffixed))
            # The journal must point at where the file actually landed.
            (entry,) = store.get_apply_log("s1")
            self.assertEqual(suffixed, entry.destination_path)

            # And undo must bring it home using the corrected journal.
            restored, skipped = operator.undo_last_apply()
            self.assertEqual((1, 0), (restored, skipped))
            self.assertTrue(os.path.isfile(path))
            store.close()

    def test_move_no_overwrite_handles_paths_beyond_max_path(self):
        from app.util.paths import extended_path, move_no_overwrite

        with tempfile.TemporaryDirectory() as folder:
            deep = os.path.join(folder, *["deep_segment_" + "x" * 40] * 6)
            self.assertGreater(len(deep), 260)
            os.makedirs(extended_path(deep), exist_ok=True)

            src = _write_image(folder, "src.jpg")
            dest = os.path.join(deep, "dest.jpg")
            final = move_no_overwrite(src, dest)

            self.assertEqual(dest, final)
            self.assertTrue(os.path.isfile(extended_path(dest)))
            self.assertFalse(os.path.isfile(src))

    def test_scan_survives_file_vanishing_mid_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [
                _write_image(folder, "a.jpg"),
                _write_image(folder, "b.jpg"),
            ]

            real_getsize = os.path.getsize

            def flaky_getsize(fp):
                if os.path.basename(fp) == "a.jpg":
                    raise OSError("file dehydrated by sync client")
                return real_getsize(fp)

            with patch(
                "app.core.scanner.os.path.getsize",
                side_effect=flaky_getsize,
            ):
                photos = compute_hashes(paths)

            self.assertEqual(2, len(photos))
            by_name = {p.filename: p for p in photos}
            self.assertEqual(0, by_name["a.jpg"].file_size)
            self.assertGreater(by_name["b.jpg"].file_size, 0)


if __name__ == "__main__":
    unittest.main()
