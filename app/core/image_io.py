"""Unicode-safe image loading helpers for OpenCV."""
import logging

import cv2
import numpy as np

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
