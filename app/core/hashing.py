"""Hash computation for duplicate detection."""
import hashlib
import logging
from typing import Optional

from PIL import Image
import imagehash

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
        img = Image.open(filepath)
        h = imagehash.phash(img, hash_size=hash_size)
        return str(h)
    except Exception as e:
        log.warning("Cannot compute pHash for %s: %s", filepath, e)
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    h1 = int(hash1, 16)
    h2 = int(hash2, 16)
    return bin(h1 ^ h2).count("1")
