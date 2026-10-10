"""UX-16 / PERF-08: cached thumbnails and previews are upright (EXIF
orientation applied), decoded at reduced size, and the old sideways cache
files are never shown again and get pruned."""
import os
import tempfile
import unittest

from PIL import Image

from app.core.models import Photo
from app.core.thumbnails import PreviewCache, ThumbnailCache


def _phone_portrait(folder, name="portrait.jpg"):
    """An upright 300x400 portrait stored the way phones do: pixels sideways
    (400x300) plus EXIF orientation 6 ('rotate 90 degrees clockwise')."""
    path = os.path.join(folder, name)
    upright = Image.new("RGB", (300, 400), (200, 40, 40))
    upright.paste((40, 40, 200), (0, 0, 300, 100))   # blue band = the top
    exif = Image.Exif()
    exif[0x0112] = 6
    upright.transpose(Image.Transpose.ROTATE_90).save(path, exif=exif, quality=95)
    return path


def _photo(path, sha="SHA1"):
    return Photo(id="i1", filepath=path, filename=os.path.basename(path), file_size=1, sha256=sha)


class UprightCacheTests(unittest.TestCase):
    def test_thumbnail_of_phone_portrait_is_upright(self):
        with tempfile.TemporaryDirectory() as d:
            cache = ThumbnailCache(os.path.join(d, "thumbs"))
            out = cache.generate_thumbnail(_photo(_phone_portrait(d)))
            with Image.open(out) as im:
                w, h = im.size
                self.assertLess(w, h)                    # portrait, not landscape
                r, g, b = im.convert("RGB").getpixel((w // 2, 5))
                self.assertGreater(b, r)                 # blue band is at the top

    def test_preview_of_phone_portrait_is_upright(self):
        with tempfile.TemporaryDirectory() as d:
            cache = PreviewCache(os.path.join(d, "previews"))
            out = cache.generate_preview(_photo(_phone_portrait(d)), 200)
            with Image.open(out) as im:
                self.assertEqual((150, 200), im.size)

    def test_old_sideways_files_are_ignored_and_pruned(self):
        with tempfile.TemporaryDirectory() as d:
            cache = ThumbnailCache(os.path.join(d, "thumbs"))
            legacy = os.path.join(cache.cache_dir, "SHA1.jpg")   # pre-UX-16 name
            Image.new("RGB", (200, 150)).save(legacy)
            photo = _photo(_phone_portrait(d))
            self.assertIsNone(cache.get_thumb_path(photo))      # never shown again
            fresh = cache.generate_thumbnail(photo)
            self.assertNotEqual(legacy, fresh)
            removed = cache.prune({"SHA1"})
            self.assertEqual(1, removed)
            self.assertEqual([os.path.basename(fresh)], os.listdir(cache.cache_dir))

    def test_large_jpeg_thumbnail_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.jpg")
            Image.new("RGB", (4000, 3000), (90, 120, 150)).save(path, quality=90)
            out = ThumbnailCache(os.path.join(d, "t")).generate_thumbnail(_photo(path))
            with Image.open(out) as im:
                self.assertEqual((320, 240), im.size)


if __name__ == "__main__":
    unittest.main()
