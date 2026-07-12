import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core import faces
from app.core.faces import (
    _filter_confident, set_min_confidence, get_min_confidence,
    DEFAULT_FACE_MIN_CONFIDENCE,
)


class _Cat:
    def __init__(self, score):
        self.score = score


class _Det:
    def __init__(self, score):
        self.categories = [_Cat(score)]


class FilterConfidenceTests(unittest.TestCase):
    """QUAL-01: low-confidence detections are dropped before counting."""

    def setUp(self):
        self._prev = get_min_confidence()
        self.addCleanup(set_min_confidence, self._prev)

    def test_filter_drops_below_threshold(self):
        set_min_confidence(0.5)
        dets = [_Det(0.9), _Det(0.4), _Det(0.5), _Det(0.2)]
        kept = _filter_confident(dets)
        self.assertEqual([0.9, 0.5], [d.categories[0].score for d in kept])

    def test_empty_is_safe(self):
        self.assertEqual([], _filter_confident(None))
        self.assertEqual([], _filter_confident([]))

    def test_missing_categories_never_filtered(self):
        set_min_confidence(0.99)

        class NoCats:
            categories = None
        self.assertEqual(1, len(_filter_confident([NoCats()])))

    def test_set_clamps_and_coerces(self):
        set_min_confidence(1.5)
        self.assertEqual(1.0, get_min_confidence())
        set_min_confidence(-0.2)
        self.assertEqual(0.0, get_min_confidence())
        set_min_confidence("bad")
        self.assertEqual(DEFAULT_FACE_MIN_CONFIDENCE, get_min_confidence())


class ScannerThreadingTests(unittest.TestCase):
    """QUAL-01: the scan sets the threshold before the worker pool runs."""

    def setUp(self):
        self._prev = get_min_confidence()
        self.addCleanup(set_min_confidence, self._prev)

    def test_detect_and_analyze_sets_confidence(self):
        from app.core.scanner import detect_and_analyze_faces, compute_hashes

        def _fake(_fp):
            return {"face_count": 0, "face_area_ratio": 0.0,
                    "face_distance": "none", "subject_isolation": 0.0,
                    "eyes_open": 0.0, "smile": 0.0,
                    "expression_naturalness": 0.0, "head_pose_frontal": 0.0}

        with tempfile.TemporaryDirectory() as folder:
            from PIL import Image
            p = os.path.join(folder, "a.jpg")
            Image.new("RGB", (16, 16)).save(p)
            photos = compute_hashes([p])
            with patch("app.core.scanner.analyze_photo", side_effect=_fake):
                detect_and_analyze_faces(photos, min_confidence=0.8, workers=1)
        self.assertAlmostEqual(0.8, get_min_confidence())


if __name__ == "__main__":
    unittest.main()
