"""Background worker for high-resolution review previews."""
import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.core.models import Photo
from app.core.thumbnails import PreviewCache

log = logging.getLogger("photobrain.preview_worker")


class PreviewWorker(QThread):
    preview_ready = Signal(str, int, object)  # photo_id, display_size, QImage
    all_finished = Signal()

    def __init__(
        self,
        photos: list[Photo],
        display_size: int,
        preview_cache: PreviewCache,
    ):
        super().__init__()
        self.photos = photos
        self.display_size = display_size
        self.preview_cache = preview_cache
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for photo in self.photos:
            if self._cancelled:
                break
            path = self.preview_cache.generate_preview(photo, self.display_size)
            if not path or self._cancelled:
                continue
            image = QImage(path)
            if not image.isNull():
                self.preview_ready.emit(photo.id, self.display_size, image)

        if not self._cancelled:
            self.all_finished.emit()
