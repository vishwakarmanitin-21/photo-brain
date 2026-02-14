"""Quality scoring for photos."""
import math
import logging
from typing import Optional

import cv2

from app.core.models import Photo, Verdict, DupType

log = logging.getLogger("photobrain.scoring")


def compute_sharpness(filepath: str) -> float:
    try:
        gray = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.warning("Cannot read image for sharpness: %s", filepath)
            return 0.0
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception as e:
        log.warning("Sharpness computation failed for %s: %s", filepath, e)
        return 0.0


def compute_brightness(filepath: str) -> float:
    try:
        gray = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.warning("Cannot read image for brightness: %s", filepath)
            return 0.0
        return float(gray.mean())
    except Exception as e:
        log.warning("Brightness computation failed for %s: %s", filepath, e)
        return 0.0


def compute_quality_score(
    sharpness: float, brightness: float, face_count: int = 0
) -> float:
    face_bonus = 0.15 * min(face_count, 3)
    return (
        0.65 * math.log(sharpness + 1)
        + 0.20 * (brightness / 255.0)
        + face_bonus
    )


def score_photo(filepath: str) -> tuple[float, float, float]:
    """Return (sharpness, brightness, quality_score).

    Note: quality_score here uses face_count=0. The score is recalculated
    after face detection in the scan pipeline with the actual face count.
    """
    sharpness = compute_sharpness(filepath)
    brightness = compute_brightness(filepath)
    quality = compute_quality_score(sharpness, brightness)
    return sharpness, brightness, quality


def rescore_with_faces(photo: "Photo") -> float:
    """Recalculate quality score incorporating face count."""
    return compute_quality_score(photo.sharpness, photo.brightness, photo.face_count)


def suggest_verdicts(
    photos: list[Photo], keep_count: int = 2
) -> list[Photo]:
    """Sort by quality descending, mark top N as KEEP, rest as ARCHIVE.

    Respects user_override: photos manually set by the user are not changed.
    Single-photo clusters always get KEEP.
    """
    if len(photos) <= 1:
        for p in photos:
            if not p.user_override:
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
