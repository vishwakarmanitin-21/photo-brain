import os
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFilter

from app.core.models import Cluster, Photo, Verdict
from app.core.scanner import (
    assign_verdicts, collect_files, compute_hashes, compute_phashes,
    compute_scores, run_clustering,
)
from app.core.scoring import (
    LOW_QUALITY_THRESHOLD, is_low_quality_singleton, suggest_verdicts,
)


def _photo(pid: str, sharp: float, bright: float, score: float) -> Photo:
    return Photo(
        id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
        file_size=10, sharpness=sharp, brightness=bright, quality_score=score,
    )


class LowQualityClassifierTests(unittest.TestCase):
    """DISTILL-01: standalone junk is flagged, decent photos are spared."""

    def test_blurry_standalone_is_low_quality(self):
        p = _photo("blur", 3.0, 90.0, LOW_QUALITY_THRESHOLD - 0.1)
        self.assertTrue(is_low_quality_singleton(p))

    def test_decent_standalone_is_not_low_quality(self):
        p = _photo("ok", 300.0, 128.0, LOW_QUALITY_THRESHOLD + 0.15)
        self.assertFalse(is_low_quality_singleton(p))

    def test_unscoreable_is_not_low_quality(self):
        # Zero/zero is 'unreadable' (handled separately), not 'low quality'.
        p = _photo("dead", 0.0, 0.0, 0.0)
        self.assertFalse(is_low_quality_singleton(p))


class SuggestVerdictLaneTests(unittest.TestCase):
    def test_low_quality_singleton_is_flagged_not_kept(self):
        # DISTILL-01 policy update: a lone junk photo is FLAGGED (REVIEW), not
        # auto-moved. "Flag, don't move" — REVIEW is skipped on apply, so the
        # user does the final sweep rather than the app archiving it for them.
        p = _photo("blur", 3.0, 90.0, LOW_QUALITY_THRESHOLD - 0.1)
        suggest_verdicts([p])
        self.assertEqual(Verdict.REVIEW, p.verdict)

    def test_good_singleton_still_kept(self):
        p = _photo("ok", 300.0, 128.0, LOW_QUALITY_THRESHOLD + 0.15)
        suggest_verdicts([p])
        self.assertEqual(Verdict.KEEP, p.verdict)

    def test_user_override_is_respected(self):
        p = _photo("blur", 3.0, 90.0, 0.05)
        p.verdict = Verdict.KEEP
        p.user_override = True
        suggest_verdicts([p])
        self.assertEqual(Verdict.KEEP, p.verdict)


class EndToEndDistillTests(unittest.TestCase):
    """A blurry standalone photo must not be auto-kept through the pipeline."""

    def test_blurry_standalone_photo_is_not_auto_kept(self):
        with tempfile.TemporaryDirectory() as src:
            # A sharp, well-exposed standalone scene -> should be kept.
            good = Image.new("RGB", (320, 240), (150, 150, 150))
            gd = ImageDraw.Draw(good)
            for i in range(0, 320, 12):
                gd.line([(i, 0), (i, 240)], fill=(20, 20, 20), width=2)
            good.save(os.path.join(src, "good_scene.jpg"), quality=92)

            # A heavily blurred standalone photo -> should be archived.
            blur = good.filter(ImageFilter.GaussianBlur(8))
            blur.save(os.path.join(src, "blurry_junk.jpg"), quality=92)

            photos = compute_hashes(collect_files(src))
            compute_phashes(photos)
            compute_scores(photos)
            clusters, cluster_photos = run_clustering(photos, 17)
            assign_verdicts(clusters, cluster_photos, keep_per_cluster=2)

            by_name = {p.filename: p for p in photos}
            self.assertEqual(Verdict.KEEP, by_name["good_scene.jpg"].verdict)
            # Must not be auto-kept. Whether it lands as ARCHIVE (a redundant
            # near-dup of the good frame) or REVIEW (flagged standalone junk)
            # depends on whether pHash groups it with the sharp copy; the
            # invariant the pipeline guarantees is simply "never auto-KEEP".
            self.assertNotEqual(Verdict.KEEP, by_name["blurry_junk.jpg"].verdict)


if __name__ == "__main__":
    unittest.main()
