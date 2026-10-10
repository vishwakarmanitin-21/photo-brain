"""Background worker for thumbnail generation."""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

from app.core.models import Photo
from app.core.thumbnails import ThumbnailCache, cache_key

log = logging.getLogger("photobrain.thumb_worker")

# Pillow's JPEG decode and resize release the GIL, so a few threads make
# thumbnails several times faster; more than this competes with the UI.
THUMB_WORKERS = 3


class ThumbWorker(QThread):
    progress_updated = Signal(int, int)      # done, total (thumbnails to make)
    thumb_ready = Signal(str, str)           # photo_id, thumb_path
    all_finished = Signal()

    def __init__(self, photos: list[Photo], thumb_cache: ThumbnailCache):
        """`photos` in priority order — the caller puts on-screen photos first."""
        super().__init__()
        self.photos = photos
        self.thumb_cache = thumb_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # 1. Already cached: tell the grid only if it is not already showing
        #    that exact file (on resume it loaded it at build time — emitting
        #    again made every visible tile decode twice).
        todo: dict[str, list[Photo]] = {}
        for photo in self.photos:
            if self._cancelled:
                return
            existing = self.thumb_cache.get_thumb_path(photo)
            if existing:
                if photo.thumb_path != existing:
                    photo.thumb_path = existing
                    self.thumb_ready.emit(photo.id, existing)
                continue
            # One generation per cache key: exact duplicates share a file, and
            # two threads must never write the same file.
            todo.setdefault(cache_key(photo), []).append(photo)

        # 2. Generate the missing ones, a few at a time, in priority order
        #    (the pool takes submissions first-in, first-out).
        total, done = len(todo), 0
        if total:
            self.progress_updated.emit(0, total)
        with ThreadPoolExecutor(max_workers=THUMB_WORKERS) as pool:
            futures = {pool.submit(self.thumb_cache.generate_thumbnail, group[0]): group
                       for group in todo.values()}
            for future in as_completed(futures):
                if self._cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                group = futures[future]
                try:
                    path = future.result()
                except Exception:
                    log.exception("Thumbnail failed for %s", group[0].filepath)
                    path = None
                done += 1
                if path:
                    for photo in group:
                        photo.thumb_path = path
                        self.thumb_ready.emit(photo.id, path)
                if done % 10 == 0 or done == total:
                    self.progress_updated.emit(done, total)

        if not self._cancelled:
            self.all_finished.emit()
