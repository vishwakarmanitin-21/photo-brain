"""Quality scoring for photos."""
import math
import logging
from typing import Optional

import cv2

from app.core.image_io import read_image, verify_decodable, read_gray_verified
from app.core.models import Photo, Verdict, DupType

log = logging.getLogger("photobrain.scoring")

# Contrast-normalized Laplacian variance at or above which a photo is
# decisively sharp — extra micro-detail beyond this no longer makes it a
# "better" photo, it just measures scene texture.
SHARPNESS_REF = 1000.0

# Gray-level standard deviation below which an image is effectively flat
# (blank wall, corrupt gray frame) and focus cannot be judged at all.
_MIN_CONTRAST_STD = 1.0

# Contrast level the Laplacian is normalized to. Laplacian variance scales
# with contrast squared, so without this a darker exposure of the SAME
# frame reads as much "blurrier" — lighting differences would masquerade
# as focus differences and drown out the face/expression signals.
_REF_CONTRAST_STD = 64.0


def _sharpness_from_gray(gray) -> float:
    std = float(gray.std())
    if std < _MIN_CONTRAST_STD:
        return 0.0
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return lap_var * (_REF_CONTRAST_STD / std) ** 2


def compute_sharpness(filepath: str) -> float:
    try:
        gray = read_image(filepath, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.warning("Cannot read image for sharpness: %s", filepath)
            return 0.0
        return _sharpness_from_gray(gray)
    except Exception as e:
        log.warning("Sharpness computation failed for %s: %s", filepath, e)
        return 0.0


def compute_brightness(filepath: str) -> float:
    try:
        gray = read_image(filepath, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.warning("Cannot read image for brightness: %s", filepath)
            return 0.0
        return float(gray.mean())
    except Exception as e:
        log.warning("Brightness computation failed for %s: %s", filepath, e)
        return 0.0


def _normalized_sharpness(sharpness: float) -> float:
    if sharpness <= 0.0:
        return 0.0
    return min(1.0, math.log(sharpness + 1.0) / math.log(SHARPNESS_REF + 1.0))


def _exposure_quality(brightness: float) -> float:
    """Peak at mid-gray. A blown-out white frame scores like a black one."""
    return max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)


def compute_quality_score(
    sharpness: float,
    brightness: float,
    face_count: int = 0,
    eyes_open_score: float = 0.0,
    smile_score: float = 0.0,
    subject_isolation: float = 0.0,
    expression_naturalness: float = 0.0,
    head_pose_frontal: float = 0.0,
) -> float:
    """Weighted quality score in [0, 1].

    Every term is normalized to [0, 1] before weighting, so the weights
    mean what they say: 45% sharpness, 13% exposure, and 42% across the
    face/expression signals. With the previous unbounded sharpness term
    the face signals were mathematically negligible and the "best shot"
    pick degenerated to "sharpest frame".
    """
    return (
        0.45 * _normalized_sharpness(sharpness)
        + 0.13 * _exposure_quality(brightness)
        + 0.10 * (min(face_count, 3) / 3.0)
        + 0.12 * eyes_open_score
        + 0.09 * smile_score
        + 0.05 * subject_isolation
        + 0.04 * expression_naturalness
        + 0.02 * head_pose_frontal
    )


def score_photo(filepath: str) -> tuple[float, float, float]:
    """Return (sharpness, brightness, quality_score) from a single decode.

    Reads the photo exactly once (grayscale, integrity-checked together):
    a truncated/corrupt file comes back as None and stays unscoreable
    (0, 0, 0) so it surfaces for review instead of being silently kept.

    Note: quality_score here uses face_count=0. The score is recalculated
    after face detection in the scan pipeline with the actual face count.
    """
    sharpness = 0.0
    brightness = 0.0
    try:
        gray = read_gray_verified(filepath)
        if gray is None:
            log.warning("Skipping score for unreadable image: %s", filepath)
        else:
            sharpness = _sharpness_from_gray(gray)
            brightness = float(gray.mean())
    except Exception as e:
        log.warning("Scoring failed for %s: %s", filepath, e)
    quality = compute_quality_score(sharpness, brightness)
    return sharpness, brightness, quality


def rescore_with_faces(photo: "Photo") -> float:
    """Recalculate quality score incorporating face count, expressions, and isolation."""
    return compute_quality_score(
        photo.sharpness, photo.brightness, photo.face_count,
        photo.eyes_open_score, photo.smile_score, photo.subject_isolation,
        photo.expression_naturalness, photo.head_pose_frontal,
    )


# Max quality gap (on the [0,1] score) within which a lower-ranked photo is
# still worth keeping alongside the best. Beyond this the runner-up is clearly
# worse, so keeping it just clutters the KEEP set with an inferior near-dup.
KEEP_GAP = 0.05

# A standalone photo (no duplicates) scoring below this on the [0,1] scale is
# genuinely low quality — clearly blurry or badly exposed — and is suggested
# for archiving instead of auto-kept. Deliberately conservative: a decent
# no-face snapshot lands around 0.40+, so only real junk falls below. The
# suggestion is ARCHIVE (a reversible move), never DELETE.
LOW_QUALITY_THRESHOLD = 0.25


def is_low_quality_singleton(photo: Photo) -> bool:
    """True if a standalone photo is scoreable but clearly low quality."""
    scoreable = photo.sharpness > 0.0 or photo.brightness > 0.0
    return scoreable and photo.quality_score < LOW_QUALITY_THRESHOLD


def effective_keep_count(photos: list[Photo], max_keep: int) -> int:
    """How many top photos to keep, given the quality gaps between them.

    Always keeps the best photo, then keeps each next-ranked photo (up to
    max_keep) only while it stays within KEEP_GAP of the best. Near-equal
    alternates are all kept; a clearly-worse runner-up trims the set back
    toward 1. max_keep is the ceiling — the user's setting still caps it.
    """
    if not photos:
        return 0
    if max_keep <= 1:
        return max(0, max_keep)
    ranked = sorted(photos, key=lambda p: (-p.quality_score, p.filepath))
    best = ranked[0].quality_score
    keep = 1
    for p in ranked[1:max_keep]:
        if best - p.quality_score <= KEEP_GAP:
            keep += 1
        else:
            break
    return keep


def suggest_verdicts(
    photos: list[Photo], keep_count: int = 2
) -> list[Photo]:
    """Sort by quality descending, mark top N as KEEP, rest as ARCHIVE.

    Respects user_override: photos manually set by the user are not changed.
    Single-photo clusters (standalone photos, no duplicates) get KEEP,
    except:
      - unreadable/unscoreable files stay undecided (REVIEW) so the user
        actually looks at them instead of silently keeping a broken file;
      - clearly low-quality photos (blurry/badly exposed) are suggested
        for ARCHIVE — the "distill standalone junk" behavior. ARCHIVE is
        a reversible move, so a misfire costs one undo, never a photo.
    """
    if len(photos) <= 1:
        for p in photos:
            if p.user_override:
                continue
            if p.sharpness <= 0.0 and p.brightness <= 0.0:
                p.verdict = Verdict.REVIEW
            elif is_low_quality_singleton(p):
                p.verdict = Verdict.ARCHIVE
            else:
                p.verdict = Verdict.KEEP
        return photos

    # Sort by quality_score desc, then filepath asc for deterministic tiebreak
    ranked = sorted(photos, key=lambda p: (-p.quality_score, p.filepath))
    kept = 0
    for p in ranked:
        if p.user_override:
            continue
        if kept < keep_count:
            p.verdict = Verdict.KEEP
            kept += 1
        else:
            p.verdict = Verdict.ARCHIVE
    return ranked
