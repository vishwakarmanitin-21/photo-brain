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


# EXIF orientations 5-8 rotate by 90 degrees: width and height swap.
_SWAPS_AXES = {5, 6, 7, 8}


def upright_size(filepath: str):
    """The photo's full size as displayed (after EXIF rotation), read from the
    header only. Returns a QSize, invalid if unreadable."""
    from PySide6.QtCore import QSize
    reader = QImageReader(filepath)
    size = reader.size()
    if size.isValid():
        transform = reader.transformation()
        # Qt reports rotations as transformation flags; a 90-degree turn swaps axes.
        from PySide6.QtGui import QImageIOHandler
        if transform & QImageIOHandler.Transformation.TransformationRotate90:
            size = QSize(size.height(), size.width())
        return size
    try:
        from PIL import Image
        from app.core import image_formats  # noqa: F401  (registers HEIC)
        with Image.open(filepath) as img:
            w, h = img.size
            if img.getexif().get(0x0112) in _SWAPS_AXES:
                w, h = h, w
            return QSize(w, h)
    except Exception:
        return QSize()


def load_full_image(filepath: str) -> QImage:
    """The whole photo at full resolution, upright (for 100% viewing)."""
    return load_bounded_image(filepath, 1 << 20)
