import os
import tempfile
import unittest

from PIL import Image, ImageDraw

from app.core.image_io import verify_decodable
from app.core.models import Photo, Verdict
from app.core.scoring import score_photo, suggest_verdicts


def _valid_jpeg(path: str):
    img = Image.new("RGB", (256, 256), (140, 110, 80))
    draw = ImageDraw.Draw(img)
    for i in range(0, 256, 16):
        draw.line([(i, 0), (i, 256)], fill=(20, 20, 20), width=2)
        draw.ellipse([i, i, i + 30, i + 30], fill=(210, 90, 70))
    img.save(path, quality=92)


def _truncate(path: str, keep_fraction: float):
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data[: int(len(data) * keep_fraction)])


class DamagedImageTests(unittest.TestCase):
    """DISTILL-02: corrupt/truncated files must never score as good photos."""

    def test_verify_decodable_true_for_valid_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ok.jpg")
            _valid_jpeg(path)
            self.assertTrue(verify_decodable(path))

    def test_verify_decodable_false_for_truncated_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "bad.jpg")
            _valid_jpeg(path)
            _truncate(path, 0.6)  # enough header for a partial decode
            self.assertFalse(verify_decodable(path))

    def test_truncated_image_is_not_scored(self):
        # Whether OpenCV returns partial pixels or None, the damaged file
        # must come back unscoreable (0, 0, 0), never a positive score.
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "bad.jpg")
            _valid_jpeg(path)
            _truncate(path, 0.6)
            sharpness, brightness, quality = score_photo(path)
            self.assertEqual((0.0, 0.0, 0.0), (sharpness, brightness, quality))

    def test_valid_image_still_scores(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ok.jpg")
            _valid_jpeg(path)
            sharpness, brightness, quality = score_photo(path)
            self.assertGreater(sharpness, 0)
            self.assertGreater(quality, 0)

    def test_damaged_singleton_is_left_for_review_not_kept(self):
        photo = Photo(
            id="p", filepath="C:/x/bad.jpg", filename="bad.jpg",
            file_size=10, sharpness=0.0, brightness=0.0, quality_score=0.0,
        )
        suggest_verdicts([photo])
        self.assertEqual(Verdict.REVIEW, photo.verdict)


if __name__ == "__main__":
    unittest.main()
