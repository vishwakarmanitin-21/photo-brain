import os
import tempfile
import unittest

from app.util.paths import resolve_collision


class ResolveCollisionTests(unittest.TestCase):
    """TEST-01: destination collisions must never overwrite an existing file."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _touch(self, name):
        p = os.path.join(self._dir.name, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")
        return p

    def test_no_collision_returns_same_path(self):
        target = os.path.join(self._dir.name, "photo.jpg")
        self.assertEqual(target, resolve_collision(target))

    def test_single_collision_appends_1(self):
        existing = self._touch("photo.jpg")
        self.assertEqual(
            os.path.join(self._dir.name, "photo_1.jpg"),
            resolve_collision(existing))

    def test_multiple_collisions_increment(self):
        self._touch("photo.jpg")
        self._touch("photo_1.jpg")
        self._touch("photo_2.jpg")
        self.assertEqual(
            os.path.join(self._dir.name, "photo_3.jpg"),
            resolve_collision(os.path.join(self._dir.name, "photo.jpg")))

    def test_preserves_extension_and_stem(self):
        self._touch("my.photo.final.png")
        result = resolve_collision(
            os.path.join(self._dir.name, "my.photo.final.png"))
        self.assertTrue(result.endswith("my.photo.final_1.png"))

    def test_unicode_filename(self):
        existing = self._touch("café_señor_日本.jpg")
        result = resolve_collision(existing)
        self.assertTrue(result.endswith("café_señor_日本_1.jpg"))
        self.assertFalse(os.path.exists(result))


if __name__ == "__main__":
    unittest.main()
