"""Quality scoring for photos."""
import math
import logging
from typing import Optional

import cv2

from app.core.image_io import read_image, verify_decodable
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

    Note: quality_score here uses face_count=0. The score is recalculated
    after face detection in the scan pipeline with the actual face count.
    """
    sharpness = 0.0
    brightness = 0.0
    try:
        gray = read_image(filepath, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.warning("Cannot read image for scoring: %s", filepath)
        elif not verify_decodable(filepath):
            # Truncated/corrupt: OpenCV gave us partial pixels, but the file
            # is damaged. Leave it unscoreable so it surfaces for review
            # instead of being silently kept.
            log.warning("Skipping score for damaged image: %s", filepath)
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


def suggest_verdicts(
    photos: list[Photo], keep_count: int = 2
) -> list[Photo]:
    """Sort by quality descending, mark top N as KEEP, rest as ARCHIVE.

    Respects user_override: photos manually set by the user are not changed.
    Single-photo clusters get KEEP — except unreadable/unscoreable files
    (no sharpness AND no brightness), which stay undecided so the user
    actually looks at them instead of silently keeping a broken file.
    """
    if len(photos) <= 1:
        for p in photos:
            if p.user_override:
                continue
            if p.sharpness <= 0.0 and p.brightness <= 0.0:
                p.verdict = Verdict.REVIEW
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
