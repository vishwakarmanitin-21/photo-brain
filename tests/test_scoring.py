import math
import os
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFilter

from app.core.models import Photo, Verdict
from app.core.scoring import (
    LOW_QUALITY_THRESHOLD,
    SHARPNESS_REF,
    compute_quality_score,
    compute_sharpness,
    suggest_verdicts,
)


def _scene(path: str, brightness: float = 1.0, blur: float = 0.0):
    img = Image.new("RGB", (320, 240), (150, 150, 150))
    draw = ImageDraw.Draw(img)
    for i in range(0, 320, 20):
        draw.line([(i, 0), (i, 240)], fill=(30, 30, 30), width=3)
        draw.ellipse([i, i % 200, i + 24, (i % 200) + 24], fill=(220, 90, 60))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if brightness != 1.0:
        img = Image.eval(img, lambda px: min(255, int(px * brightness)))
    img.save(path, quality=92)


class QualityScoreFormulaTests(unittest.TestCase):
    """SCORE-01/02: normalized weights and exposure handling."""

    def test_score_is_bounded_zero_to_one(self):
        self.assertEqual(0.0, compute_quality_score(0.0, 0.0))
        best = compute_quality_score(
            sharpness=SHARPNESS_REF * 10, brightness=128.0, face_count=3,
            eyes_open_score=1.0, smile_score=1.0, subject_isolation=1.0,
            expression_naturalness=1.0, head_pose_frontal=1.0,
        )
        self.assertAlmostEqual(1.0, best, places=9)

    def test_formula_regression_pin(self):
        # Pins the exact formula so unintended changes fail loudly.
        score = compute_quality_score(
            sharpness=250.0, brightness=160.0, face_count=2,
            eyes_open_score=0.8, smile_score=0.5, subject_isolation=1.0,
            expression_naturalness=0.9, head_pose_frontal=0.6,
        )
        expected = (
            0.45 * (math.log(251.0) / math.log(SHARPNESS_REF + 1.0))
            + 0.13 * (1.0 - abs(160.0 - 128.0) / 128.0)
            + 0.10 * (2 / 3.0)
            + 0.12 * 0.8
            + 0.09 * 0.5
            + 0.05 * 1.0
            + 0.04 * 0.9
            + 0.02 * 0.6
        )
        self.assertAlmostEqual(expected, score, places=12)

    def test_overexposed_scores_like_underexposed(self):
        blown_out = compute_quality_score(sharpness=500.0, brightness=255.0)
        pitch_black = compute_quality_score(sharpness=500.0, brightness=1.0)
        well_exposed = compute_quality_score(sharpness=500.0, brightness=128.0)
        self.assertGreater(well_exposed, blown_out)
        self.assertAlmostEqual(blown_out, pitch_black, places=2)

    def test_blink_outweighs_modest_sharpness_advantage(self):
        # The whole point of SCORE-01: between two acceptably sharp frames
        # of the same people, the open-eyed one must win even if the
        # blinking frame is somewhat sharper.
        blinking_but_sharper = compute_quality_score(
            sharpness=400.0, brightness=128.0, face_count=1,
            eyes_open_score=0.0, smile_score=0.5,
        )
        open_eyed = compute_quality_score(
            sharpness=200.0, brightness=128.0, face_count=1,
            eyes_open_score=1.0, smile_score=0.5,
        )
        self.assertGreater(open_eyed, blinking_but_sharper)

    def test_sharpness_still_dominates_real_blur(self):
        # A genuinely blurred frame must not be rescued by a smile.
        blurred_smiling = compute_quality_score(
            sharpness=5.0, brightness=128.0, face_count=1,
            eyes_open_score=1.0, smile_score=1.0,
        )
        sharp_neutral = compute_quality_score(
            sharpness=500.0, brightness=128.0, face_count=1,
            eyes_open_score=1.0, smile_score=0.0,
        )
        self.assertGreater(sharp_neutral, blurred_smiling)


class ExposureUsabilityGateTests(unittest.TestCase):
    """A pitch-black or blown-out frame must not ride sharpness to a decent
    score — the exposure gate collapses it into the low-quality lane, while
    leaving the normal exposure range (and the pinned formula) untouched."""

    def test_pitch_black_sharp_frame_scores_below_junk_bar(self):
        # Near-black but 'in focus' — this is the screenshot case that used to
        # score ~0.41 and get auto-kept.
        black = compute_quality_score(sharpness=500.0, brightness=12.0)
        self.assertLess(black, LOW_QUALITY_THRESHOLD)

    def test_blown_out_sharp_frame_scores_below_junk_bar(self):
        blown = compute_quality_score(sharpness=500.0, brightness=250.0)
        self.assertLess(blown, LOW_QUALITY_THRESHOLD)

    def test_normal_exposure_is_not_gated(self):
        # The gate is exactly 1.0 across the normal range: a mid-exposed sharp
        # frame keeps the full ungated formula value.
        gated = compute_quality_score(sharpness=250.0, brightness=160.0)
        ungated = (
            0.45 * (math.log(251.0) / math.log(SHARPNESS_REF + 1.0))
            + 0.13 * (1.0 - abs(160.0 - 128.0) / 128.0)
        )
        self.assertAlmostEqual(ungated, gated, places=12)

    def test_dim_but_visible_frame_is_spared(self):
        # A dim indoor frame (mean gray 64) is usable and must not be junked.
        dim = compute_quality_score(sharpness=300.0, brightness=64.0)
        self.assertGreater(dim, LOW_QUALITY_THRESHOLD)


class SharpnessMeasurementTests(unittest.TestCase):
    def test_darkened_copy_keeps_its_sharpness(self):
        # Laplacian variance scales with contrast^2; the contrast
        # normalization must cancel that so exposure differences do not
        # read as focus differences (measured live: -70% at 55% brightness
        # before this fix).
        with tempfile.TemporaryDirectory() as folder:
            normal = os.path.join(folder, "normal.jpg")
            dark = os.path.join(folder, "dark.jpg")
            _scene(normal)
            _scene(dark, brightness=0.55)

            s_normal = compute_sharpness(normal)
            s_dark = compute_sharpness(dark)

            self.assertGreater(s_normal, 0)
            ratio = s_dark / s_normal
            self.assertGreater(ratio, 0.75, f"ratio={ratio:.2f}")
            self.assertLess(ratio, 1.35, f"ratio={ratio:.2f}")

    def test_blur_still_reduces_sharpness(self):
        with tempfile.TemporaryDirectory() as folder:
            sharp = os.path.join(folder, "sharp.jpg")
            blurred = os.path.join(folder, "blurred.jpg")
            _scene(sharp)
            _scene(blurred, blur=3.0)

            self.assertGreater(
                compute_sharpness(sharp), 3 * compute_sharpness(blurred)
            )

    def test_flat_image_has_zero_sharpness(self):
        with tempfile.TemporaryDirectory() as folder:
            flat = os.path.join(folder, "flat.png")
            Image.new("RGB", (100, 100), (128, 128, 128)).save(flat)
            self.assertEqual(0.0, compute_sharpness(flat))


class SingletonSuggestionTests(unittest.TestCase):
    """Unreadable singletons stay undecided; good ones are kept."""

    @staticmethod
    def _photo(sharpness: float, brightness: float) -> Photo:
        # Score the photo the way the pipeline does, so the fixture is
        # consistent with the low-quality lane's threshold.
        return Photo(
            id="p1", filepath="C:/photos/p1.jpg", filename="p1.jpg",
            file_size=10, sharpness=sharpness, brightness=brightness,
            quality_score=compute_quality_score(sharpness, brightness),
        )

    def test_unscoreable_singleton_stays_undecided(self):
        photo = self._photo(0.0, 0.0)
        suggest_verdicts([photo])
        self.assertEqual(Verdict.REVIEW, photo.verdict)

    def test_normal_singleton_still_keeps(self):
        photo = self._photo(300.0, 130.0)
        suggest_verdicts([photo])
        self.assertEqual(Verdict.KEEP, photo.verdict)

    def test_user_override_is_respected(self):
        photo = self._photo(0.0, 0.0)
        photo.verdict = Verdict.DELETE
        photo.user_override = True
        suggest_verdicts([photo])
        self.assertEqual(Verdict.DELETE, photo.verdict)


class MultiPhotoSuggestionTests(unittest.TestCase):
    """TEST-01: multi-photo clusters keep the top N by score, archive the
    rest, deterministically, and never overwrite a user's decision."""

    @staticmethod
    def _photo(pid, score):
        return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                     file_size=10, quality_score=score, verdict=Verdict.REVIEW)

    def test_top_n_kept_rest_archived(self):
        photos = [self._photo("a", 0.9), self._photo("b", 0.5),
                  self._photo("c", 0.7), self._photo("d", 0.2)]
        suggest_verdicts(photos, keep_count=2)
        by_id = {p.id: p.verdict for p in photos}
        # Highest two (a=0.9, c=0.7) kept; others archived.
        self.assertEqual(Verdict.KEEP, by_id["a"])
        self.assertEqual(Verdict.KEEP, by_id["c"])
        self.assertEqual(Verdict.ARCHIVE, by_id["b"])
        self.assertEqual(Verdict.ARCHIVE, by_id["d"])

    def test_ties_break_by_filepath_deterministically(self):
        # Equal scores → the lexicographically smaller filepath is kept first.
        photos = [self._photo("b", 0.5), self._photo("a", 0.5)]
        suggest_verdicts(photos, keep_count=1)
        by_id = {p.id: p.verdict for p in photos}
        self.assertEqual(Verdict.KEEP, by_id["a"])
        self.assertEqual(Verdict.ARCHIVE, by_id["b"])

    def test_user_override_not_counted_against_keep_budget(self):
        # b is a manual KEEP; it must stay KEEP and not consume a slot that
        # would otherwise change the auto-picks.
        photos = [self._photo("a", 0.9), self._photo("b", 0.1),
                  self._photo("c", 0.8)]
        photos[1].verdict = Verdict.KEEP
        photos[1].user_override = True
        suggest_verdicts(photos, keep_count=2)
        by_id = {p.id: p.verdict for p in photos}
        self.assertEqual(Verdict.KEEP, by_id["b"])   # override preserved
        self.assertEqual(Verdict.KEEP, by_id["a"])   # top score kept
        self.assertEqual(Verdict.KEEP, by_id["c"])   # second score kept

    def test_all_junk_group_is_flagged_not_kept(self):
        # Every frame below the bar (e.g. a burst of near-black shots): none
        # is auto-kept and none is auto-archived — all are flagged REVIEW so
        # the user sweeps them. REVIEW is skipped on apply, so nothing moves.
        photos = [self._photo("a", 0.10), self._photo("b", 0.08),
                  self._photo("c", 0.05)]
        for p in photos:            # make them scoreable (not 'unreadable')
            p.sharpness = 100.0
        suggest_verdicts(photos, keep_count=2)
        self.assertTrue(all(p.verdict == Verdict.REVIEW for p in photos))

    def test_junk_runner_up_of_a_good_keeper_is_still_archived(self):
        # A good frame anchors the group, so a clearly-worse near-dup is
        # redundancy (ARCHIVE), not junk (REVIEW) — the old behavior stands
        # whenever there is a genuine keeper.
        photos = [self._photo("a", 0.80), self._photo("b", 0.10)]
        for p in photos:
            p.sharpness = 100.0
        suggest_verdicts(photos, keep_count=1)
        by_id = {p.id: p.verdict for p in photos}
        self.assertEqual(Verdict.KEEP, by_id["a"])
        self.assertEqual(Verdict.ARCHIVE, by_id["b"])


if __name__ == "__main__":
    unittest.main()
