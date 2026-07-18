"""O5: people-photo likability sorts and expression filters."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import (
    ReviewView, sort_photos, photo_matches_expression,
    SORT_SMILING, SORT_EYES_OPEN, SORT_FRONTAL,
    EXPR_FILTER_SMILING, EXPR_FILTER_EYES_OPEN, EXPR_FILTER_BLINKING,
    EXPR_FILTER_LOOKING_AWAY, EXPR_FILTER_ALL,
)


def _face_photo(pid, faces=1, smile=0.0, eyes=1.0, natural=0.5, frontal=1.0,
                score=0.5):
    return Photo(
        id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg", file_size=10,
        sharpness=100.0, brightness=120.0, quality_score=score,
        face_count=faces, smile_score=smile, eyes_open_score=eyes,
        expression_naturalness=natural, head_pose_frontal=frontal,
        verdict=Verdict.REVIEW,
    )


class PeopleSortTests(unittest.TestCase):
    def test_most_smiling_orders_by_smile_then_no_face_last(self):
        ps = [
            _face_photo("big_smile", smile=0.9),
            _face_photo("small_smile", smile=0.3),
            _face_photo("no_face", faces=0, smile=0.0, score=0.99),  # high quality
        ]
        self.assertEqual(
            ["big_smile", "small_smile", "no_face"],
            [p.id for p in sort_photos(ps, SORT_SMILING)],
        )

    def test_eyes_open_ranks_open_over_blink(self):
        ps = [_face_photo("blink", eyes=0.1), _face_photo("open", eyes=0.95)]
        self.assertEqual(["open", "blink"],
                         [p.id for p in sort_photos(ps, SORT_EYES_OPEN)])

    def test_facing_camera_ranks_frontal_first(self):
        ps = [_face_photo("away", frontal=0.1), _face_photo("front", frontal=0.9)]
        self.assertEqual(["front", "away"],
                         [p.id for p in sort_photos(ps, SORT_FRONTAL)])


class ExpressionPredicateTests(unittest.TestCase):
    def test_no_face_never_matches_a_people_filter(self):
        p = _face_photo("landscape", faces=0, smile=0.9, eyes=0.9, frontal=0.9)
        for f in (EXPR_FILTER_SMILING, EXPR_FILTER_EYES_OPEN,
                  EXPR_FILTER_BLINKING, EXPR_FILTER_LOOKING_AWAY):
            self.assertFalse(photo_matches_expression(p, f))
        self.assertTrue(photo_matches_expression(p, EXPR_FILTER_ALL))

    def test_smiling_and_blinking_and_looking_away(self):
        self.assertTrue(photo_matches_expression(
            _face_photo("s", smile=0.8), EXPR_FILTER_SMILING))
        self.assertFalse(photo_matches_expression(
            _face_photo("s", smile=0.2), EXPR_FILTER_SMILING))
        self.assertTrue(photo_matches_expression(
            _face_photo("b", eyes=0.2), EXPR_FILTER_BLINKING))
        self.assertTrue(photo_matches_expression(
            _face_photo("a", frontal=0.1), EXPR_FILTER_LOOKING_AWAY))


class ExpressionFilterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_filter_narrows_to_smiling_faces(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        smiling = _face_photo("smiler", smile=0.9)
        neutral = _face_photo("neutral", smile=0.1)
        noface = _face_photo("scenery", faces=0)
        rv.load_data(
            [Cluster(id="c1", label="c1", member_count=3)],
            {"c1": [smiling, neutral, noface]}, has_undo=False, events=[],
        )
        rv.set_hide_singletons(False)
        rv._expr_filter.setCurrentText(EXPR_FILTER_SMILING)
        self.assertEqual({"smiler"}, rv._passing_photo_ids)


if __name__ == "__main__":
    unittest.main()
