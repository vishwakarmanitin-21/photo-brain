import os
import tempfile
import unittest

import cv2
import numpy as np

from app.core.image_io import read_image
from app.core.scoring import compute_brightness, compute_sharpness


class UnicodeImageReadTests(unittest.TestCase):
    def test_scoring_reads_hindi_and_emoji_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            unicode_dir = os.path.join(temp_dir, "शादी 📷")
            os.makedirs(unicode_dir)
            image_path = os.path.join(unicode_dir, "फोटो.png")

            image = np.full((40, 40, 3), 220, dtype=np.uint8)
            image[10:30, 10:30] = 20
            encoded, buffer = cv2.imencode(".png", image)
            self.assertTrue(encoded)
            buffer.tofile(image_path)

            decoded = read_image(image_path)
            self.assertIsNotNone(decoded)
            self.assertEqual((40, 40, 3), decoded.shape)
            self.assertGreater(compute_brightness(image_path), 0.0)
            self.assertGreater(compute_sharpness(image_path), 0.0)


if __name__ == "__main__":
    unittest.main()
