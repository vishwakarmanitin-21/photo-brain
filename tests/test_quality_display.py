import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView, ThumbnailWidget, quality_rating_100


class QualityRatingTests(unittest.TestCase):
    """SCORE-03: honest 0–100 rating instead of a raw float."""

    def test_rating_is_bounded_0_to_100(self):
        self.assertEqual(0, quality_rating_100(0.0))
        self.assertEqual(100, quality_rating_100(1.0))
        self.assertEqual(47, quality_rating_100(0.47))
        self.assertEqual(100, quality_rating_100(1.5))   # clamps
        self.assertEqual(0, quality_rating_100(-0.2))    # clamps


class ThumbnailDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _photo(pid: str, score: float) -> Photo:
        return Photo(
            id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
            file_size=10, sharpness=100.0, brightness=120.0,
            quality_score=score, verdict=Verdict.KEEP,
        )

    @staticmethod
    def _labels(widget) -> str:
        from PySide6.QtWidgets import QLabel
        return " ".join(w.text() for w in widget.findChildren(QLabel) if w.text())

    def test_label_shows_rating_not_raw_float(self):
        widget = ThumbnailWidget(self._photo("p", 0.47))
        joined = self._labels(widget)
        self.assertIn("Quality: 47/100", joined)
        self.assertNotIn("0.47", joined)

    def test_best_badge_only_in_multi_photo_cluster(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        best = Cluster(id="c1", label="pair", member_count=2)
        solo = Cluster(id="c2", label="solo", member_count=1)
        cp = {
            "c1": [self._photo("hi", 0.50), self._photo("lo", 0.40)],
            "c2": [self._photo("only", 0.45)],
        }
        rv.load_data([best, solo], cp, has_undo=False, events=[])

        # Cluster with a real choice: exactly one "★ Best".
        rv._cluster_list.setCurrentRow(0)
        self.assertEqual(1, self._labels(rv).count("★ Best"))

        # Single-photo cluster: no "Best" badge (no choice to make).
        rv._cluster_list.setCurrentRow(1)
        self.assertNotIn("★ Best", self._labels(rv))


if __name__ == "__main__":
    unittest.main()
