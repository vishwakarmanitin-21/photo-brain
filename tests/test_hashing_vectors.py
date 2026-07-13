import hashlib
import os
import tempfile
import unittest

from PIL import Image

from app.core.hashing import compute_sha256, compute_phash


class Sha256Tests(unittest.TestCase):
    """TEST-01: content hashing must match a known vector and be stable."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def test_matches_hashlib_known_vector(self):
        data = b"PhotoBrain test bytes \x00\x01\x02"
        p = os.path.join(self._dir.name, "blob.bin")
        with open(p, "wb") as f:
            f.write(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), compute_sha256(p))

    def test_identical_content_same_hash(self):
        a = os.path.join(self._dir.name, "a.bin")
        b = os.path.join(self._dir.name, "b.bin")
        for path in (a, b):
            with open(path, "wb") as f:
                f.write(b"same content")
        self.assertEqual(compute_sha256(a), compute_sha256(b))

    def test_missing_file_returns_none(self):
        self.assertIsNone(compute_sha256("C:/nope/missing.bin"))


class PhashTests(unittest.TestCase):
    """TEST-01: perceptual hashing is deterministic and distance-sensitive."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _img(self, name, color):
        p = os.path.join(self._dir.name, name)
        Image.new("RGB", (128, 96), color).save(p)
        return p

    def test_phash_is_deterministic(self):
        p = self._img("a.png", (40, 90, 160))
        self.assertEqual(compute_phash(p), compute_phash(p))

    def test_identical_images_hash_equal(self):
        a = self._img("a.png", (200, 30, 30))
        b = self._img("b.png", (200, 30, 30))
        self.assertEqual(compute_phash(a), compute_phash(b))

    def test_phash_is_hex_of_expected_length(self):
        # hash_size=8 → 64 bits → 16 hex chars.
        h = compute_phash(self._img("a.png", (10, 20, 30)))
        self.assertEqual(16, len(h))
        int(h, 16)  # must parse as hex

    def test_missing_file_returns_none(self):
        self.assertIsNone(compute_phash("C:/nope/missing.png"))


if __name__ == "__main__":
    unittest.main()
