import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from app.core.hashing import compute_phash, phash_and_gray
from app.core.models import Photo, Verdict
from app.core.scanner import fingerprint_and_score, compute_hashes
from app.core.scoring import score_photo


def _scene(path: str, seed: int = 0):
    img = Image.new("RGB", (256, 200), (150, 150, 150))
    d = ImageDraw.Draw(img)
    for i in range(0, 256, 12):
        d.line([(i, 0), (i, 200)], fill=(20, 20, 20), width=2)
        d.ellipse([i, (i + seed) % 160, i + 20, (i + seed) % 160 + 20],
                  fill=(200, 90, 60))
    img.save(path, quality=92)


class FingerprintAndScoreTests(unittest.TestCase):
    """PERF-03 remainder: one decode must match the two separate passes."""

    def test_matches_separate_phash_and_score(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [os.path.join(folder, f"p{i}.jpg") for i in range(4)]
            for i, p in enumerate(paths):
                _scene(p, seed=i * 30)

            # Reference: the old separate functions.
            ref = {}
            for p in paths:
                sharp, bright, quality = score_photo(p)
                ref[p] = (compute_phash(p), sharp, bright, quality)

            photos = compute_hashes(paths)
            fingerprint_and_score(photos)

            for photo in photos:
                exp_phash, exp_sharp, exp_bright, exp_quality = ref[photo.filepath]
                self.assertEqual(exp_phash, photo.phash)
                self.assertAlmostEqual(exp_sharp, photo.sharpness, places=6)
                self.assertAlmostEqual(exp_bright, photo.brightness, places=6)
                self.assertAlmostEqual(exp_quality, photo.quality_score, places=6)

    def test_exact_duplicates_scored_once_and_shared(self):
        with tempfile.TemporaryDirectory() as folder:
            a = os.path.join(folder, "a.jpg")
            b = os.path.join(folder, "b.jpg")
            _scene(a, seed=5)
            import shutil
            shutil.copyfile(a, b)  # identical sha
            photos = compute_hashes([a, b])
            fingerprint_and_score(photos)
            self.assertEqual(photos[0].phash, photos[1].phash)
            self.assertEqual(photos[0].quality_score, photos[1].quality_score)

    def test_truncated_file_is_unhashed_and_unscored(self):
        with tempfile.TemporaryDirectory() as folder:
            good = os.path.join(folder, "ok.jpg")
            _scene(good)
            with open(good, "rb") as f:
                data = f.read()
            bad = os.path.join(folder, "bad.jpg")
            with open(bad, "wb") as f:
                f.write(data[: len(data) // 2])

            photos = compute_hashes([good, bad])
            fingerprint_and_score(photos)
            by_name = {p.filename: p for p in photos}
            self.assertIsNone(by_name["bad.jpg"].phash)
            self.assertEqual(0.0, by_name["bad.jpg"].quality_score)
            self.assertIsNotNone(by_name["ok.jpg"].phash)
            self.assertGreater(by_name["ok.jpg"].quality_score, 0.0)

    def test_phash_and_gray_returns_none_on_missing_file(self):
        ph, gray = phash_and_gray("C:/nope/missing.jpg")
        self.assertIsNone(ph)
        self.assertIsNone(gray)


if __name__ == "__main__":
    unittest.main()
