"""Thumbnail generation and caching."""
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


class ThumbnailCache:
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_thumb_path(self, photo_id: str) -> Optional[str]:
        path = os.path.join(self.cache_dir, f"{photo_id}.jpg")
        return path if os.path.isfile(path) else None

    def generate_thumbnail(self, photo: Photo) -> Optional[str]:
        dest = os.path.join(self.cache_dir, f"{photo.id}.jpg")
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

    def clear_cache(self):
        for f in os.listdir(self.cache_dir):
            fp = os.path.join(self.cache_dir, f)
            if os.path.isfile(fp):
                os.remove(fp)


class PreviewCache:
    """Disk cache for high-resolution review previews keyed by size."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_preview_path(self, photo_id: str, display_size: int) -> Optional[str]:
        path = os.path.join(self.cache_dir, f"{photo_id}_{display_size}.jpg")
        return path if os.path.isfile(path) else None

    def generate_preview(self, photo: Photo, display_size: int) -> Optional[str]:
        """Decode and resize an original image into the requested cache entry."""
        dest = os.path.join(self.cache_dir, f"{photo.id}_{display_size}.jpg")
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
