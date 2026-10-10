"""Bounded, upright image loading for on-screen display.

One loader for every view that shows a photo larger than a thumbnail (hover
preview, Compare, the ranking-label window), so they all get the same three
guarantees:

* **Fast** — Qt's JPEG decoder scales while decoding, so a 48 MP original is
  never fully decoded just to be shrunk.
* **Upright** — the camera's EXIF orientation is applied (phones store
  portraits sideways with a "rotate me" tag). This shows the photo as taken;
  the file itself is never modified.
* **Every supported format** — Qt has no HEIC plugin, so iPhone photos fall
  back to Pillow (pillow-heif), also rotated upright.

`load_bounded_image` returns a QImage and is safe to call from worker threads;
convert to QPixmap on the UI thread.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

from app.core.thumbnails import _draft_size


def load_bounded_image(filepath: str, max_dim: int) -> QImage:
    """Decode `filepath` scaled to fit within max_dim x max_dim, upright.
    Returns a null QImage on failure."""
    reader = QImageReader(filepath)
    reader.setAutoTransform(True)
    size = reader.size()  # stored (pre-rotation) size; scaling keeps its aspect
    if size.isValid() and (size.width() > max_dim or size.height() > max_dim):
        reader.setScaledSize(size.scaled(max_dim, max_dim, Qt.KeepAspectRatio))
    image = reader.read()
    if not image.isNull():
        return image
    return _load_via_pil(filepath, max_dim)


def load_bounded_pixmap(filepath: str, max_dim: int) -> QPixmap:
    """UI-thread convenience wrapper around load_bounded_image."""
    image = load_bounded_image(filepath, max_dim)
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def _load_via_pil(filepath: str, max_dim: int) -> QImage:
    try:
        from PIL import Image, ImageOps
        from app.core import image_formats  # noqa: F401  (registers HEIC)
        with Image.open(filepath) as img:
            img.draft("RGB", _draft_size(img.size, max_dim))  # JPEG: decode at reduced size
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_dim, max_dim))
            data = img.tobytes()
            return QImage(data, img.width, img.height, 3 * img.width,
                          QImage.Format_RGB888).copy()
    except Exception:
        return QImage()
