import unittest
from unittest.mock import patch, MagicMock

import numpy as np

from app.core import faces


class DecodeOnceTests(unittest.TestCase):
    """PERF-03: the face phase must decode each photo once and reuse the
    RGB array for both detection and expression analysis."""

    def test_analyze_photo_decodes_once_and_shares_rgb(self):
        fake_bgr = np.zeros((120, 160, 3), dtype=np.uint8)
        seen = {}

        def _fake_detect(fp, rgb=None):
            seen["detect_rgb"] = rgb
            return 2, 0.3, "close", 1.0

        def _fake_expr(fp, rgb=None):
            seen["expr_rgb"] = rgb
            return 0.9, 0.6, 0.8, 0.7

        with patch("app.core.faces.read_image",
                   return_value=fake_bgr) as mock_read, \
             patch("app.core.faces.detect_faces", side_effect=_fake_detect), \
             patch("app.core.faces.analyze_expressions", side_effect=_fake_expr):
            result = faces.analyze_photo("C:/x/a.jpg")

        # Decoded exactly once.
        self.assertEqual(1, mock_read.call_count)
        # Both stages received a (non-None) RGB array — the SAME one.
        self.assertIsNotNone(seen["detect_rgb"])
        self.assertIs(seen["detect_rgb"], seen["expr_rgb"])
        # And the scores flowed through.
        self.assertEqual(2, result["face_count"])
        self.assertEqual(0.9, result["eyes_open"])

    def test_no_expression_decode_when_no_faces(self):
        fake_bgr = np.zeros((100, 100, 3), dtype=np.uint8)
        with patch("app.core.faces.read_image",
                   return_value=fake_bgr) as mock_read, \
             patch("app.core.faces.detect_faces",
                   return_value=(0, 0.0, "none", 0.0)), \
             patch("app.core.faces.analyze_expressions") as mock_expr:
            result = faces.analyze_photo("C:/x/a.jpg")
        mock_expr.assert_not_called()          # skipped when no faces
        self.assertEqual(1, mock_read.call_count)
        self.assertEqual(0, result["face_count"])

    def test_unreadable_photo_returns_zeros_without_detection(self):
        with patch("app.core.faces.read_image", return_value=None), \
             patch("app.core.faces.detect_faces") as mock_detect:
            result = faces.analyze_photo("C:/x/missing.jpg")
        mock_detect.assert_not_called()
        self.assertEqual(0, result["face_count"])
        self.assertEqual("none", result["face_distance"])

    def test_detect_faces_with_rgb_skips_read(self):
        rgb = np.zeros((80, 80, 3), dtype=np.uint8)
        with patch("app.core.faces.read_image",
                   side_effect=AssertionError("should not decode")), \
             patch("app.core.faces._get_detector", return_value=MagicMock()), \
             patch("app.core.faces._detect_at_scale", return_value=[]):
            # rgb supplied → no read_image; no faces → clean zero result.
            self.assertEqual((0, 0.0, "none", 0.0),
                             faces.detect_faces("C:/x/a.jpg", rgb=rgb))


if __name__ == "__main__":
    unittest.main()
