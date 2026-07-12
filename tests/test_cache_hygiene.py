import os
import tempfile
import unittest

from PIL import Image

from app.core.models import Photo
from app.core.thumbnails import (
    PreviewCache, ThumbnailCache, cache_key, valid_keys,
)


def _img(folder: str, name: str, color=(120, 90, 60)) -> str:
    path = os.path.join(folder, name)
    Image.new("RGB", (400, 300), color).save(path, quality=88)
    return path


def _photo(pid: str, path: str, sha: str) -> Photo:
    return Photo(id=pid, filepath=path, filename=os.path.basename(path),
                 file_size=10, sha256=sha)


class CacheKeyTests(unittest.TestCase):
    def test_key_is_sha_with_id_fallback(self):
        self.assertEqual("abc", cache_key(_photo("id1", "x.jpg", "abc")))
        self.assertEqual("id1", cache_key(
            Photo(id="id1", filepath="x.jpg", filename="x.jpg", file_size=1)))


class ThumbnailAccumulationTests(unittest.TestCase):
    def test_rescan_reuses_files_and_does_not_accumulate(self):
        with tempfile.TemporaryDirectory() as folder:
            src = _img(folder, "a.jpg")
            cache = ThumbnailCache(os.path.join(folder, "thumbs"))

            # Scan 1: photo gets a random id but a stable sha.
            p1 = _photo("scan1id", src, "SHA_A")
            cache.generate_thumbnail(p1)
            after_first = set(os.listdir(cache.cache_dir))

            # Scan 2 of the same file: new id, same sha -> same cache file.
            p2 = _photo("scan2id", src, "SHA_A")
            cache.generate_thumbnail(p2)
            after_second = set(os.listdir(cache.cache_dir))

            self.assertEqual(after_first, after_second)
            self.assertEqual(1, len(after_second))  # no orphan accumulation

    def test_exact_duplicates_share_one_thumbnail(self):
        with tempfile.TemporaryDirectory() as folder:
            src = _img(folder, "a.jpg")
            copy = _img(folder, "a_copy.jpg", color=(120, 90, 60))
            cache = ThumbnailCache(os.path.join(folder, "thumbs"))
            cache.generate_thumbnail(_photo("id1", src, "SAME"))
            cache.generate_thumbnail(_photo("id2", copy, "SAME"))
            self.assertEqual(1, len(os.listdir(cache.cache_dir)))

    def test_prune_removes_stale_and_keeps_current(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = ThumbnailCache(os.path.join(folder, "thumbs"))
            cache.generate_thumbnail(_photo("i1", _img(folder, "a.jpg"), "KEEP"))
            cache.generate_thumbnail(
                _photo("i2", _img(folder, "b.jpg", (10, 200, 10)), "STALE"))
            self.assertEqual(2, len(os.listdir(cache.cache_dir)))

            removed = cache.prune({"KEEP"})
            self.assertEqual(1, removed)
            self.assertEqual(["KEEP.jpg"], os.listdir(cache.cache_dir))


class PreviewAccumulationTests(unittest.TestCase):
    def test_preview_keyed_by_sha_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            src = _img(folder, "a.jpg")
            cache = PreviewCache(os.path.join(folder, "prev"))
            cache.generate_preview(_photo("id1", src, "SHA_A"), 400)
            cache.generate_preview(_photo("id2", src, "SHA_A"), 400)  # rescan
            files = os.listdir(cache.cache_dir)
            self.assertEqual(["SHA_A_400.jpg"], files)

    def test_prune_keeps_all_sizes_of_current_photos(self):
        with tempfile.TemporaryDirectory() as folder:
            src = _img(folder, "a.jpg")
            other = _img(folder, "b.jpg", (10, 10, 200))
            cache = PreviewCache(os.path.join(folder, "prev"))
            cache.generate_preview(_photo("i1", src, "KEEP"), 400)
            cache.generate_preview(_photo("i1", src, "KEEP"), 800)
            cache.generate_preview(_photo("i2", other, "STALE"), 400)
            self.assertEqual(3, len(os.listdir(cache.cache_dir)))

            removed = cache.prune({"KEEP"})
            self.assertEqual(1, removed)
            self.assertEqual(
                {"KEEP_400.jpg", "KEEP_800.jpg"},
                set(os.listdir(cache.cache_dir)),
            )

    def test_prune_removes_leftover_tmp_files(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = PreviewCache(os.path.join(folder, "prev"))
            # An interrupted write can leave a .tmp file behind.
            with open(os.path.join(cache.cache_dir, "x_400.jpg.99.tmp"), "w") as f:
                f.write("junk")
            cache.prune({"anything"})
            self.assertEqual([], os.listdir(cache.cache_dir))


class ValidKeysTests(unittest.TestCase):
    def test_valid_keys_collects_sha_and_id_fallback(self):
        photos = [
            _photo("i1", "a.jpg", "SHA1"),
            Photo(id="i2", filepath="b.jpg", filename="b.jpg", file_size=1),
        ]
        self.assertEqual({"SHA1", "i2"}, valid_keys(photos))


if __name__ == "__main__":
    unittest.main()
