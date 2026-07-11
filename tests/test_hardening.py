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
