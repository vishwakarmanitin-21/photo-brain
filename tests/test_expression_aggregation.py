import unittest

from app.core.faces import (
    _extract_blendshape_scores,
    _mean,
    _worst_leaning,
)


class _Shape:
    """Minimal stand-in for a mediapipe blendshape category."""

    def __init__(self, score: float):
        self.score = score


def _face(eyes_open: float, smile: float = 0.0) -> list:
    """Build a 46-entry blendshape list for one face.

    Index 9/10 are blink left/right (blink = 1 - eyes_open); index 44/45 are
    smile left/right; all other expression indices are left at 0 (neutral).
    """
    shapes = [_Shape(0.0) for _ in range(46)]
    blink = 1.0 - eyes_open
    shapes[9] = _Shape(blink)
    shapes[10] = _Shape(blink)
    shapes[44] = _Shape(smile)
    shapes[45] = _Shape(smile)
    return shapes


class WorstLeaningTests(unittest.TestCase):
    """SCORE-04: eyes aggregation leans to the worst face."""

    def test_helpers(self):
        self.assertEqual(0.0, _worst_leaning([]))
        self.assertAlmostEqual(0.5, _mean([0.0, 1.0]))
        # 0.7*min + 0.3*mean = 0.7*0 + 0.3*0.5 = 0.15
        self.assertAlmostEqual(0.15, _worst_leaning([0.0, 1.0]))
        # single value is unchanged
        self.assertAlmostEqual(0.8, _worst_leaning([0.8]))

    def test_one_blink_in_a_group_meaningfully_penalizes(self):
        # Four open-eyed faces, one fully closed.
        faces = [_face(1.0), _face(1.0), _face(1.0), _face(1.0), _face(0.0)]
        eyes, _smile, _nat, _frontal = _extract_blendshape_scores(faces)

        plain_mean = 4.0 / 5.0  # what the old averaging returned
        self.assertLess(eyes, plain_mean - 0.15)
        self.assertGreater(eyes, 0.0)  # not fully collapsed by one face

    def test_all_open_eyes_scores_high(self):
        faces = [_face(1.0), _face(1.0), _face(1.0)]
        eyes, *_ = _extract_blendshape_scores(faces)
        self.assertAlmostEqual(1.0, eyes, places=4)

    def test_single_face_is_unchanged(self):
        eyes, *_ = _extract_blendshape_scores([_face(0.85)])
        self.assertAlmostEqual(0.85, eyes, places=4)

    def test_one_frown_in_a_group_drags_smile_down(self):
        # O5: smile now leans to the worst face too — four big smiles and one
        # flat face must score well below the plain average.
        faces = [_face(1.0, smile=1.0)] * 4 + [_face(1.0, smile=0.0)]
        _eyes, smile, _nat, _frontal = _extract_blendshape_scores(faces)
        plain_mean = 4.0 / 5.0
        self.assertLess(smile, plain_mean - 0.15)
        self.assertGreater(smile, 0.0)

    def test_single_face_smile_is_unchanged(self):
        _eyes, smile, *_ = _extract_blendshape_scores([_face(1.0, smile=0.7)])
        self.assertAlmostEqual(0.7, smile, places=4)


if __name__ == "__main__":
    unittest.main()
