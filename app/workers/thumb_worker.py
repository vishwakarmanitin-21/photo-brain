"""Background worker for thumbnail generation."""
import logging

from PySide6.QtCore import QThread, Signal

from app.core.models import Photo
from app.core.thumbnails import ThumbnailCache

log = logging.getLogger("photobrain.thumb_worker")


class ThumbWorker(QThread):
    progress_updated = Signal(int, int)      # current, total
    thumb_ready = Signal(str, str)           # photo_id, thumb_path
    all_finished = Signal()

    def __init__(self, photos: list[Photo], thumb_cache: ThumbnailCache):
        super().__init__()
        self.photos = photos
        self.thumb_cache = thumb_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.photos)
        for i, photo in enumerate(self.photos):
            if self._cancelled:
                break
            path = self.thumb_cache.generate_thumbnail(photo)
            if path:
                photo.thumb_path = path
                self.thumb_ready.emit(photo.id, path)
            if i % 20 == 0 or i == total - 1:
                self.progress_updated.emit(i + 1, total)

        if not self._cancelled:
            self.all_finished.emit()
