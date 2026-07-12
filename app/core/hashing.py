"""Hash computation for duplicate detection."""
import hashlib
import logging
from typing import Optional

import numpy as np
from PIL import Image, ImageFile
import imagehash

# Register HEIF/HEIC with Pillow before any decode (FEAT-02).
from app.core import image_formats  # noqa: F401

log = logging.getLogger("photobrain.hashing")

CHUNK_SIZE = 65536  # 64 KB


def compute_sha256(filepath: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (IOError, OSError, PermissionError) as e:
        log.warning("Cannot hash %s: %s", filepath, e)
        return None


def compute_phash(filepath: str, hash_size: int = 8) -> Optional[str]:
    try:
        # Context manager releases the OS file handle immediately; a handle
        # left open until GC can block the apply-move of this same file on
        # Windows (sharing violation).
        with Image.open(filepath) as img:
            h = imagehash.phash(img, hash_size=hash_size)
        return str(h)
    except Exception as e:
        log.warning("Cannot compute pHash for %s: %s", filepath, e)
        return None


def phash_and_gray(
    filepath: str, hash_size: int = 8
) -> tuple[Optional[str], Optional["np.ndarray"]]:
    """Decode once → (pHash string, grayscale array), verifying integrity.

    pHash and quality scoring both need the decoded image; computing them
    from a single decode halves the per-photo decode cost, the dominant
    time on large libraries. Truncated loading is disabled so a damaged
    file raises here and comes back (None, None) — unhashable and
    unscoreable — instead of yielding partial pixels. PIL 'L' uses the
    same ITU-R 601 luma weights as OpenCV, so sharpness/brightness match.
    """
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    try:
        with Image.open(filepath) as img:
            img.load()  # full decode; raises on truncation
            phash = str(imagehash.phash(img, hash_size=hash_size))
            gray = np.asarray(img.convert("L"))
        return phash, gray
    except Exception as e:
        log.warning("Cannot fingerprint/score %s: %s", filepath, e)
        return None, None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


def hamming_distance(hash1: str, hash2: str) -> int:
    h1 = int(hash1, 16)
    h2 = int(hash2, 16)
    return bin(h1 ^ h2).count("1")
