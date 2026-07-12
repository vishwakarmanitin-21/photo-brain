"""Unicode-safe image loading helpers for OpenCV."""
import logging

import cv2
import numpy as np
from PIL import Image, ImageFile

# Registers HEIF/HEIC with Pillow so the fallback path below can decode it.
from app.core import image_formats  # noqa: F401

log = logging.getLogger("photobrain.image_io")


def _read_image_via_pil(filepath: str, flags: int):
    """Fallback decode via Pillow for formats OpenCV can't read (e.g. HEIC).
    Returns a BGR (or grayscale) numpy array matching cv2.imdecode output."""
    try:
        with Image.open(filepath) as img:
            if flags == cv2.IMREAD_GRAYSCALE:
                return np.asarray(img.convert("L"))
            rgb = np.asarray(img.convert("RGB"))
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception as error:
        log.warning("PIL fallback cannot decode %s: %s", filepath, error)
        return None


def read_image(filepath: str, flags: int = cv2.IMREAD_COLOR):
    """Decode an image from a path without OpenCV's Windows Unicode limit.

    Falls back to Pillow for formats OpenCV can't decode (HEIC/HEIF), so
    face detection and scoring work on iPhone photos too (FEAT-02).
    """
    try:
        encoded = np.fromfile(filepath, dtype=np.uint8)
        if encoded.size == 0:
            return None
        decoded = cv2.imdecode(encoded, flags)
        if decoded is None:
            return _read_image_via_pil(filepath, flags)
        return decoded
    except (OSError, ValueError) as error:
        log.warning("Cannot read image bytes from %s: %s", filepath, error)
        return _read_image_via_pil(filepath, flags)


def verify_decodable(filepath: str) -> bool:
    """Return True only if the whole image decodes without truncation.

    OpenCV silently returns a partial array for a truncated JPEG, so a
    corrupt file can score positively and be kept. PIL, with truncated
    loading disabled, raises on the missing scan lines — the reliable
    integrity signal. A false 'not decodable' only routes a photo to
    manual review (safe), never to deletion.
    """
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(filepath) as img:
            img.load()
        return True
    except Exception as error:
        log.warning("Image is not fully decodable: %s (%s)", filepath, error)
        return False
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


def read_gray_verified(filepath: str):
    """Decode to a grayscale numpy array, verifying integrity in one pass.

    Returns the array, or None if the file is missing, unreadable, or
    truncated. Folding the integrity check into the same decode lets
    scoring read each photo once instead of a separate OpenCV decode plus
    a PIL verify — the biggest per-photo cost on large libraries. PIL's
    'L' conversion uses the same ITU-R 601 luma weights as OpenCV's
    grayscale, so sharpness/brightness are equivalent.
    """
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(filepath) as img:
            img.load()  # forces full decode; raises on truncation
            return np.asarray(img.convert("L"))
    except Exception as error:
        log.warning("Cannot decode image %s: %s", filepath, error)
        return None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous
