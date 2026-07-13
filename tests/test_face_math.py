import unittest

import numpy as np
from scipy.spatial.transform import Rotation

from app.core.faces import (
    _compute_isolation,
    _compute_head_pose_frontal,
    _compute_expression_naturalness,
)


class _Shape:
    """Stub blendshape category with a .score, like mediapipe's output."""
    def __init__(self, score):
        self.score = score


def _neutral_blendshapes(n=52):
    return [_Shape(0.0) for _ in range(n)]


class IsolationTests(unittest.TestCase):
    """TEST-01: subject isolation from face-area distribution."""

    def test_single_face_is_fully_isolated(self):
        self.assertEqual(1.0, _compute_isolation([500.0]))

    def test_empty_is_isolated(self):
        self.assertEqual(1.0, _compute_isolation([]))

    def test_uniform_group_is_isolated(self):
        # Three similar faces are all "primary" → 1.0.
        self.assertEqual(1.0, _compute_isolation([100.0, 100.0, 100.0]))

    def test_tiny_background_face_lowers_isolation(self):
        # A large subject plus a small background face (< 25% of largest).
        score = _compute_isolation([1000.0, 100.0])
        self.assertLess(score, 1.0)
        self.assertAlmostEqual(1000.0 / 1100.0, score, places=3)


class HeadPoseTests(unittest.TestCase):
    """TEST-01: head-pose frontal score from the transform matrix."""

    def _matrix(self, yaw=0.0, pitch=0.0, roll=0.0):
        m = np.eye(4)
        m[:3, :3] = Rotation.from_euler(
            "yxz", [yaw, pitch, roll], degrees=True).as_matrix()
        return m

    def test_identity_is_perfectly_frontal(self):
        self.assertAlmostEqual(1.0, _compute_head_pose_frontal(self._matrix()))

    def test_yaw_reduces_frontal(self):
        turned = _compute_head_pose_frontal(self._matrix(yaw=30.0))
        self.assertLess(turned, 1.0)
        self.assertGreaterEqual(turned, 0.0)

    def test_extreme_profile_clamps_at_zero(self):
        self.assertEqual(0.0, _compute_head_pose_frontal(self._matrix(yaw=90.0)))

    def test_invalid_matrix_returns_zero(self):
        self.assertEqual(0.0, _compute_head_pose_frontal("not-a-matrix"))


class ExpressionNaturalnessTests(unittest.TestCase):
    """TEST-01: naturalness penalty from blendshapes."""

    def test_neutral_face_is_natural(self):
        self.assertEqual(1.0, _compute_expression_naturalness(_neutral_blendshapes()))

    def test_frown_reduces_naturalness(self):
        shapes = _neutral_blendshapes()
        shapes[30] = _Shape(1.0)   # mouthFrownLeft
        shapes[31] = _Shape(1.0)   # mouthFrownRight
        self.assertLess(_compute_expression_naturalness(shapes), 1.0)

    def test_result_is_clamped_to_unit_range(self):
        shapes = _neutral_blendshapes()
        for i in (19, 20, 25, 30, 31, 32, 1, 2):
            shapes[i] = _Shape(1.0)  # everything awkward at once
        v = _compute_expression_naturalness(shapes)
        self.assertGreaterEqual(v, 0.0)
        self.assertLessEqual(v, 1.0)


if __name__ == "__main__":
    unittest.main()
