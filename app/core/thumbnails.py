"""Thumbnail generation and caching.

Cache files are keyed by the photo's content hash (sha256), not its
per-scan id, so rescanning the same folder reuses the existing files
instead of writing a fresh set every time and orphaning the old one.
Exact-duplicate photos therefore share a single cache entry, and
`prune()` keeps each cache bounded to the photos currently in the
library.
"""
import os
import logging
import threading
from typing import Callable, Optional

from PIL import Image

from app.core.models import Photo

log = logging.getLogger("photobrain.thumbnails")

THUMB_SIZE = (200, 200)
THUMB_QUALITY = 85
PREVIEW_QUALITY = 92


def cache_key(photo: Photo) -> str:
    """Stable, scan-independent cache key. Falls back to id if unhashed."""
    return photo.sha256 or photo.id


def valid_keys(photos: list[Photo]) -> set[str]:
    return {cache_key(p) for p in photos}


class ThumbnailCache:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_thumb_path(self, photo: Photo) -> Optional[str]:
        path = os.path.join(self.cache_dir, f"{cache_key(photo)}.jpg")
        return path if os.path.isfile(path) else None

    def generate_thumbnail(self, photo: Photo) -> Optional[str]:
        dest = os.path.join(self.cache_dir, f"{cache_key(photo)}.jpg")
        if os.path.isfile(dest):
            return dest
        try:
            with Image.open(photo.filepath) as img:
                img = img.convert("RGB")
                img.thumbnail(THUMB_SIZE, Image.LANCZOS)
                img.save(dest, "JPEG", quality=THUMB_QUALITY)
            return dest
        except Exception as e:
            log.warning("Thumbnail failed for %s: %s", photo.filepath, e)
            return None

    def generate_batch(
        self,
        photos: list[Photo],
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        total = len(photos)
        for i, photo in enumerate(photos):
            if cancel_check and cancel_check():
                break
            path = self.generate_thumbnail(photo)
            if path:
                photo.thumb_path = path
                result[photo.id] = path
            if progress_cb and (i % 20 == 0 or i == total - 1):
                progress_cb(i + 1, total)
        return result

    def prune(self, keep_keys: set[str]) -> int:
        """Delete cached thumbnails not belonging to the current library.

        `keep_keys` is the set of cache keys for the photos still present.
        Returns the number of files removed.
        """
        return _prune_dir(self.cache_dir, keep_keys, _thumb_key_of)

    def clear_cache(self):
        _clear_dir(self.cache_dir)


class PreviewCache:
    """Disk cache for high-resolution review previews keyed by size."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_preview_path(self, photo: Photo, display_size: int) -> Optional[str]:
        path = os.path.join(
            self.cache_dir, f"{cache_key(photo)}_{display_size}.jpg"
        )
        return path if os.path.isfile(path) else None

    def generate_preview(self, photo: Photo, display_size: int) -> Optional[str]:
        """Decode and resize an original image into the requested cache entry."""
        dest = os.path.join(
            self.cache_dir, f"{cache_key(photo)}_{display_size}.jpg"
        )
        if os.path.isfile(dest):
            return dest
        temp_path = f"{dest}.{threading.get_ident()}.tmp"
        try:
            with Image.open(photo.filepath) as image:
                image = image.convert("RGB")
                image.thumbnail(
                    (display_size, display_size),
                    Image.Resampling.LANCZOS,
                )
                image.save(
                    temp_path,
                    format="JPEG",
                    quality=PREVIEW_QUALITY,
                )
            os.replace(temp_path, dest)
            return dest
        except Exception as error:
            log.warning("Preview failed for %s: %s", photo.filepath, error)
            return None
        finally:
            if os.path.isfile(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def prune(self, keep_keys: set[str]) -> int:
        """Delete cached previews (any size) not in the current library."""
        return _prune_dir(self.cache_dir, keep_keys, _preview_key_of)

    def clear_cache(self):
        _clear_dir(self.cache_dir)


# ── Shared cache-file helpers ────────────────────────────────────────

def _thumb_key_of(filename: str) -> Optional[str]:
    """Key for a thumbnail file: '<key>.jpg' -> '<key>'."""
    if not filename.endswith(".jpg"):
        return None
    return filename[: -len(".jpg")]


def _preview_key_of(filename: str) -> Optional[str]:
    """Key for a preview file: '<key>_<size>.jpg' -> '<key>'.

    Cache keys (sha256 / 12-hex id) never contain '_', so splitting on the
    last underscore recovers the key regardless of the size suffix.
    """
    if not filename.endswith(".jpg"):
        return None
    stem = filename[: -len(".jpg")]
    if "_" not in stem:
        return None
    return stem.rsplit("_", 1)[0]


def _prune_dir(cache_dir: str, keep_keys: set[str], key_of) -> int:
    removed = 0
    try:
        entries = os.listdir(cache_dir)
    except OSError:
        return 0
    for name in entries:
        fp = os.path.join(cache_dir, name)
        if not os.path.isfile(fp):
            continue
        key = key_of(name)
        # Unrecognized names (e.g. leftover .tmp) and stale keys are removed.
        if key is not None and key in keep_keys:
            continue
        try:
            os.remove(fp)
            removed += 1
        except OSError:
            log.warning("Could not prune cache file %s", fp)
    if removed:
        log.info("Pruned %d stale cache files from %s", removed, cache_dir)
    return removed


def _clear_dir(cache_dir: str):
    try:
        entries = os.listdir(cache_dir)
    except OSError:
        return
    for name in entries:
        fp = os.path.join(cache_dir, name)
        if os.path.isfile(fp):
            try:
                os.remove(fp)
            except OSError:
                pass


def _dir_bytes(cache_dir: str) -> int:
    total = 0
    try:
        entries = os.listdir(cache_dir)
    except OSError:
        return 0
    for name in entries:
        fp = os.path.join(cache_dir, name)
        if os.path.isfile(fp):
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def image_cache_bytes(source_folder: str) -> int:
    """Total on-disk size of the thumbnail + preview caches for a folder."""
    from app.util.paths import get_thumb_dir, get_preview_dir
    return _dir_bytes(get_thumb_dir(source_folder)) + \
        _dir_bytes(get_preview_dir(source_folder))


def clear_image_caches(source_folder: str) -> int:
    """Delete all cached thumbnails and previews for a folder.

    Leaves the session database and apply logs intact — only the
    regenerable image caches are removed. Returns the bytes freed.
    """
    from app.util.paths import get_thumb_dir, get_preview_dir
    freed = image_cache_bytes(source_folder)
    _clear_dir(get_thumb_dir(source_folder))
    _clear_dir(get_preview_dir(source_folder))
    log.info("Cleared %d bytes of image cache for %s", freed, source_folder)
    return freed
