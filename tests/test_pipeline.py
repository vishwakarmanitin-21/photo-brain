"""The shared scan pipeline (RANK-01): one implementation for the app's scan
and the ranking scorecard, so the scorecard grades what users actually get."""
import os
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageFilter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.models import Verdict
from app.core.pipeline import AnalysisOptions, PipelineHooks, analyze
from app.core.scanner import collect_files


def _textured(path, blur=0, seed=1):
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(40, 220, (120, 160, 3), dtype=np.uint8))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    img.save(path, quality=92)


class PipelineTests(unittest.TestCase):
    def test_exact_copies_grouped_and_one_kept(self):
        with tempfile.TemporaryDirectory() as d:
            _textured(os.path.join(d, "a.jpg"))
            with open(os.path.join(d, "a.jpg"), "rb") as src, open(os.path.join(d, "a_copy.jpg"), "wb") as dst:
                dst.write(src.read())
            _textured(os.path.join(d, "other.jpg"), seed=7)
            phases, stats = [], {}
            hooks = PipelineHooks(phase=phases.append, stat=stats.__setitem__)
            result = analyze(collect_files(d), AnalysisOptions(face_detection_enabled=False), hooks)
            self.assertIsNotNone(result)
            self.assertEqual(1, result.dup_count)
            self.assertEqual(1, stats["duplicates"])
            copies = [p for p in result.photos if p.filename.startswith("a")]
            self.assertEqual(copies[0].cluster_id, copies[1].cluster_id)
            self.assertEqual(1, sum(p.verdict == Verdict.KEEP for p in copies))
            self.assertEqual("Generating suggestions...", phases[-1])
            self.assertNotIn("Analyzing faces...", phases)

    def test_hashed_hook_sees_photos_before_scoring(self):
        with tempfile.TemporaryDirectory() as d:
            _textured(os.path.join(d, "a.jpg"))
            seen = []
            hooks = PipelineHooks(hashed=lambda photos: seen.append([p.quality_score for p in photos]))
            analyze(collect_files(d), AnalysisOptions(face_detection_enabled=False), hooks)
            self.assertEqual([[0.0]], seen)  # persisted before the slow phases ran

    def test_cancel_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            _textured(os.path.join(d, "a.jpg"))
            self.assertIsNone(analyze(collect_files(d), AnalysisOptions(face_detection_enabled=False),
                                      cancel_check=lambda: True))

    def test_defaults_match_a_fresh_session(self):
        from app.core.models import SessionState
        s = SessionState(id="x", source_folder="y")
        o = AnalysisOptions()
        self.assertEqual((s.phash_threshold, s.keep_per_cluster, s.event_gap_hours, s.face_detection_enabled),
                         (o.phash_threshold, o.keep_per_cluster, o.event_gap_hours, o.face_detection_enabled))


if __name__ == "__main__":
    unittest.main()
