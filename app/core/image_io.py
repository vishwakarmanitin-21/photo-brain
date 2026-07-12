"""Unicode-safe image loading helpers for OpenCV."""
import logging

import cv2
import numpy as np
from PIL import Image, ImageFile

log = logging.getLogger("photobrain.image_io")


def read_image(filepath: str, flags: int = cv2.IMREAD_COLOR):
    """Decode an image from a path without OpenCV's Windows Unicode limit."""
    try:
        encoded = np.fromfile(filepath, dtype=np.uint8)
        if encoded.size == 0:
            return None
        return cv2.imdecode(encoded, flags)
    except (OSError, ValueError) as error:
        log.warning("Cannot read image bytes from %s: %s", filepath, error)
        return None


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
