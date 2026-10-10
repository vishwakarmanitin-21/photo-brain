"""CLUST-05: capture time comes from DateTimeOriginal in the Exif sub-IFD —
not from IFD0 DateTime, which records when the file was last saved."""
import json
import os
import tempfile
import unittest

from PIL import Image

from app.core.events import extract_exif_datetime
from app.core.ranking_eval import DATE_CACHE_FORMAT, index_root


def _jpeg(path, original=None, digitized=None, saved=None):
    exif = Image.Exif()
    if saved:
        exif[306] = saved
    sub = exif.get_ifd(0x8769)
    if original:
        sub[36867] = original
    if digitized:
        sub[36868] = digitized
    Image.new("RGB", (16, 16)).save(path, exif=exif)
    return path


class CaptureTimeTests(unittest.TestCase):
    def test_edited_photo_uses_date_taken_not_date_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path = _jpeg(os.path.join(d, "edited.jpg"),
                         original="2025:12:24 14:22:00", saved="2026:03:01 09:00:00")
            with Image.open(path) as im:   # the setup really is sub-IFD-only
                self.assertIsNone(im.getexif().get(36867))
            self.assertEqual("2025-12-24T14:22:00", extract_exif_datetime(path))

    def test_digitized_then_saved_as_fallbacks(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual("2025-01-02T03:04:05", extract_exif_datetime(
                _jpeg(os.path.join(d, "a.jpg"), digitized="2025:01:02 03:04:05", saved="2026:01:01 00:00:00")))
            self.assertEqual("2026-01-01T00:00:00", extract_exif_datetime(
                _jpeg(os.path.join(d, "b.jpg"), saved="2026:01:01 00:00:00")))
            self.assertIsNone(extract_exif_datetime(_jpeg(os.path.join(d, "c.jpg"))))

    def test_bad_original_falls_through_to_next_tag(self):
        with tempfile.TemporaryDirectory() as d:
            path = _jpeg(os.path.join(d, "x.jpg"), original="0000:00:00 00:00:00",
                         saved="2026:05:05 05:05:05")
            self.assertEqual("2026-05-05T05:05:05", extract_exif_datetime(path))

    def test_ranking_date_cache_from_old_reader_is_not_reused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as c:
            path = _jpeg(os.path.join(root, "p.jpg"), original="2025:12:24 14:22:00",
                         saved="2026:03:01 09:00:00")
            st = os.stat(path)
            cache = os.path.join(c, "dates.json")
            with open(cache, "w", encoding="utf-8") as fh:   # written by the old reader
                json.dump({"p.jpg": [st.st_size, int(st.st_mtime), "2026-03-01T09:00:00"]}, fh)
            self.assertEqual([("p.jpg", "2025-12-24T14:22:00")], index_root(root, cache_path=cache))
            with open(cache, encoding="utf-8") as fh:
                self.assertEqual(DATE_CACHE_FORMAT, json.load(fh)["__format__"])


if __name__ == "__main__":
    unittest.main()
