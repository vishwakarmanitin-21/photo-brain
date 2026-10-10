"""A photo panel you can zoom and pan — the shared piece behind the full-size
viewer and Compare's linked zoom (FEAT-07).

Coordinates are kept independent of how much of the photo is loaded:

* the view centre is a point in the photo, normalised to [0, 1] on each axis;
* the zoom is screen pixels per ORIGINAL photo pixel ("100%" = 1.0 means one
  photo pixel per physical screen pixel — the honest way to judge focus).

So a quick screen-sized preview can be swapped for the full-resolution
decode without the view jumping, and two panels can be linked by sharing
(zoom relative to fit, centre) even if their photos differ in size.
"""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

MAX_ZOOM = 8.0          # 800% of original pixels
WHEEL_STEP = 1.25       # zoom factor per mouse-wheel notch


class ZoomPanView(QWidget):
    # zoom relative to "fit", centre x, centre y — emitted on USER changes only,
    # so linked views can follow without echoing back and forth.
    view_changed = Signal(float, float, float)
    # The view is now showing the photo larger than the loaded image's
    # resolution — the owner may want to load the full-resolution decode.
    wants_full_resolution = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.NoFocus)  # keys belong to the owning window
        self._pixmap = QPixmap()
        self._natural = QSize()        # original photo size, upright
        self._zoom = 0.0               # screen px per original px; 0 = fit
        self._cx, self._cy = 0.5, 0.5
        self._drag_from = None
        self._asked_full_res = False
        self._message = "Loading…"

    # ── content ──
    def set_message(self, text: str):
        self._pixmap = QPixmap()
        self._message = text
        self.update()

    def set_image(self, image, natural_size: QSize = None, keep_view: bool = False):
        """Show `image` (QImage or QPixmap). `natural_size` is the photo's full,
        upright size; when omitted the image itself is taken as full size."""
        pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else QPixmap(image)
        if pixmap.isNull():
            self.set_message("(preview unavailable)")
            return
        self._pixmap = pixmap
        self._natural = natural_size if natural_size and natural_size.isValid() else pixmap.size()
        if not keep_view:
            self._zoom, self._cx, self._cy = 0.0, 0.5, 0.5
            self._asked_full_res = False
        self._message = ""
        self.update()

    def has_image(self) -> bool:
        return not self._pixmap.isNull()

    def loaded_is_full_resolution(self) -> bool:
        return self.has_image() and self._pixmap.width() >= self._natural.width()

    # ── geometry ──
    def _ratio(self) -> float:
        return max(1.0, self.devicePixelRatioF())

    def fit_zoom(self) -> float:
        """Screen px per photo px that fits the whole photo in the panel —
        shrink only: a photo smaller than the panel is shown at its true 100%,
        never enlarged, because enlarging softens it and this view exists to
        judge sharpness honestly."""
        if not self._natural.isValid() or self._natural.isEmpty():
            return 1.0
        r = self._ratio()
        return min(1.0, self.width() * r / self._natural.width(),
                   self.height() * r / self._natural.height())

    def zoom(self) -> float:
        return self._zoom or self.fit_zoom()

    def zoom_percent(self) -> int:
        return round(self.zoom() * 100)

    def is_fit(self) -> bool:
        return self._zoom == 0.0

    def _clamp_centre(self):
        """Keep the photo filling the panel when it is larger than the panel;
        centre it when smaller."""
        z, r = self.zoom(), self._ratio()
        shown_w = self._natural.width() * z / r
        shown_h = self._natural.height() * z / r
        if shown_w <= self.width():
            self._cx = 0.5
        else:
            half = self.width() / 2 / shown_w
            self._cx = min(1 - half, max(half, self._cx))
        if shown_h <= self.height():
            self._cy = 0.5
        else:
            half = self.height() / 2 / shown_h
            self._cy = min(1 - half, max(half, self._cy))

    def _target_rect(self) -> QRectF:
        z, r = self.zoom(), self._ratio()
        w = self._natural.width() * z / r
        h = self._natural.height() * z / r
        return QRectF(self.width() / 2 - self._cx * w, self.height() / 2 - self._cy * h, w, h)

    def _photo_point(self, pos: QPointF):
        """Normalised photo coordinates under a widget position."""
        rect = self._target_rect()
        return ((pos.x() - rect.x()) / rect.width(), (pos.y() - rect.y()) / rect.height())

    # ── changing the view ──
    def _set_zoom(self, zoom: float, anchor: QPointF = None, user: bool = True):
        if not self.has_image():
            return
        fit = self.fit_zoom()
        zoom = max(fit, min(MAX_ZOOM, zoom))
        if anchor is not None:
            px, py = self._photo_point(anchor)
        self._zoom = 0.0 if abs(zoom - fit) < 1e-6 else zoom
        if anchor is not None:
            # keep the photo point under the cursor where it was
            z, r = self.zoom(), self._ratio()
            w = self._natural.width() * z / r
            h = self._natural.height() * z / r
            self._cx = px - (anchor.x() - self.width() / 2) / w
            self._cy = py - (anchor.y() - self.height() / 2) / h
        self._clamp_centre()
        self._after_change(user)

    def fit(self, user: bool = True):
        self._zoom, self._cx, self._cy = 0.0, 0.5, 0.5
        self._after_change(user)

    def actual_size(self, anchor: QPointF = None, user: bool = True):
        self._set_zoom(1.0, anchor, user)

    def toggle_fit_actual(self, anchor: QPointF = None):
        if self.is_fit():
            self.actual_size(anchor)
        else:
            self.fit()

    def zoom_by(self, factor: float, anchor: QPointF = None):
        self._set_zoom(self.zoom() * factor, anchor)

    def set_view(self, relative_zoom: float, cx: float, cy: float):
        """Follow a linked view (no view_changed echo)."""
        if not self.has_image():
            return
        if relative_zoom <= 1.0 + 1e-6:
            self._zoom, self._cx, self._cy = 0.0, 0.5, 0.5
        else:
            self._zoom = min(MAX_ZOOM, self.fit_zoom() * relative_zoom)
            self._cx, self._cy = cx, cy
            self._clamp_centre()
        self._after_change(user=False)

    def _after_change(self, user: bool):
        self.update()
        loaded_scale = self._pixmap.width() / max(1, self._natural.width())
        if (not self._asked_full_res and self.has_image()
                and self.zoom() > loaded_scale * 1.05):
            self._asked_full_res = True
            self.wants_full_resolution.emit()
        if user:
            self.view_changed.emit(self.zoom() / self.fit_zoom(), self._cx, self._cy)

    # ── events ──
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 24))
        if not self.has_image():
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(self.rect(), Qt.AlignCenter, self._message)
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom() < 2.0)
        painter.drawPixmap(self._target_rect(), self._pixmap, QRectF(self._pixmap.rect()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_image():
            self._clamp_centre()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if steps:
            self.zoom_by(WHEEL_STEP ** steps, event.position())
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_fit():
            self._drag_from = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_from is None:
            return
        delta = event.position() - self._drag_from
        self._drag_from = event.position()
        rect = self._target_rect()
        self._cx -= delta.x() / rect.width()
        self._cy -= delta.y() / rect.height()
        self._clamp_centre()
        self._after_change(user=True)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, event):
        self.toggle_fit_actual(event.position())
        event.accept()
