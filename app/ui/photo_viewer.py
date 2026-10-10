"""Full-size photo viewer (FEAT-07): look at one photo large, zoom to 100%
and pan to check focus and eyes, flick through the grid with the arrow keys,
and decide with K/A/D — without leaving the app.

Opens instantly with a screen-sized decode; the full-resolution decode is
loaded in the background only when the view needs more pixels than that
(zooming past the screen-sized copy). Neighbouring photos are prefetched so
←/→ feels immediate. Widgets only — decisions go back through callbacks so
the review screen stays the single owner of verdicts and undo.
"""
import math
import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.core.models import Photo, Verdict
from app.ui.image_loading import load_bounded_image, load_full_image, upright_size
from app.ui.zoom_pan_view import WHEEL_STEP, ZoomPanView

_VERDICT_COLOR = {
    Verdict.KEEP: "#4CAF50", Verdict.ARCHIVE: "#FF9800",
    Verdict.DELETE: "#F44336", Verdict.REVIEW: "#9E9E9E",
}
_KEY_VERDICT = {
    Qt.Key_K: Verdict.KEEP, Qt.Key_A: Verdict.ARCHIVE, Qt.Key_D: Verdict.DELETE,
    Qt.Key_Delete: Verdict.DELETE, Qt.Key_R: Verdict.REVIEW,
}
SCREEN_CACHE = 7   # screen-sized decodes kept (current + neighbours)
PREFETCH = (1, -1, 2)

VIEWER_HELP = ("←/→ previous/next  ·  K keep · A archive · D delete · R undecided  ·  Ctrl+Z undo  ·  "
               "Space or double-click: fit ↔ 100%  ·  wheel or +/−: zoom  ·  drag: pan  ·  "
               "O: open in Windows  ·  Esc: back to the grid")


class _Loaded(QObject):
    done = Signal(str, str, QImage)  # photo id, kind ("screen" | "full"), image


class _Load(QRunnable):
    def __init__(self, photo: Photo, kind: str, max_px: int, relay: _Loaded):
        super().__init__()
        self.photo, self.kind, self.max_px, self.relay = photo, kind, max_px, relay

    def run(self):
        path = self.photo.filepath
        image = load_full_image(path) if self.kind == "full" else load_bounded_image(path, self.max_px)
        try:
            self.relay.done.emit(self.photo.id, self.kind, image)
        except RuntimeError:
            pass  # viewer closed before this finished


class PhotoViewer(QDialog):
    def __init__(self, photos: list[Photo], start_index: int = 0,
                 on_verdict=None, on_undo=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PhotoBrain — photo")
        self.setWindowFlags(self.windowFlags() | Qt.Window | Qt.WindowMaximizeButtonHint)
        self._photos = photos
        self._index = max(0, min(start_index, len(photos) - 1))
        self._on_verdict = on_verdict
        self._on_undo = on_undo
        self._screen_images: OrderedDict[str, QImage] = OrderedDict()
        self._natural: dict[str, QSize] = {}
        self._pending: set[tuple[str, str]] = set()
        self._relay = _Loaded()
        self._relay.done.connect(self._on_loaded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        top = QHBoxLayout()
        self._title = QLabel()
        self._title.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._verdict = QLabel()
        self._verdict.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._zoom_label = QLabel()
        top.addWidget(self._title, 1)
        top.addWidget(self._verdict)
        top.addSpacing(16)
        top.addWidget(self._zoom_label)
        layout.addLayout(top)
        self._view = ZoomPanView()
        self._view.view_changed.connect(lambda *_: self._update_zoom_label())
        self._view.wants_full_resolution.connect(self._load_full_for_current)
        layout.addWidget(self._view, 1)
        help_label = QLabel(VIEWER_HELP)
        help_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(help_label)

        screen = (parent.screen() if parent is not None else None)
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(avail.width(), avail.height())
            self._screen_px = math.ceil(max(avail.width(), avail.height()) * screen.devicePixelRatio())
        else:
            self.resize(1400, 900)
            self._screen_px = 2400
        self.setWindowState(Qt.WindowMaximized)
        self._show_current()

    # ── public ──
    def current_photo(self) -> Photo:
        return self._photos[self._index]

    # ── loading ──
    def _request(self, photo: Photo, kind: str):
        key = (photo.id, kind)
        if key in self._pending:
            return
        self._pending.add(key)
        QThreadPool.globalInstance().start(_Load(photo, kind, self._screen_px, self._relay))

    def _natural_size(self, photo: Photo) -> QSize:
        if photo.id not in self._natural:
            self._natural[photo.id] = upright_size(photo.filepath)
        return self._natural[photo.id]

    def _on_loaded(self, photo_id: str, kind: str, image: QImage):
        self._pending.discard((photo_id, kind))
        current = self.current_photo()
        if kind == "screen":
            self._screen_images[photo_id] = image
            self._screen_images.move_to_end(photo_id)
            while len(self._screen_images) > SCREEN_CACHE:
                self._screen_images.popitem(last=False)
            if photo_id == current.id and not self._view.has_image():
                self._view.set_image(image, self._natural_size(current))
                self._update_zoom_label()
        elif photo_id == current.id:
            # Swap in full resolution without moving the view.
            self._view.set_image(image, self._natural_size(current), keep_view=True)

    def _load_full_for_current(self):
        if not self._view.loaded_is_full_resolution():
            self._request(self.current_photo(), "full")

    # ── display ──
    def _show_current(self):
        photo = self.current_photo()
        cached = self._screen_images.get(photo.id)
        if cached is not None and not cached.isNull():
            self._view.set_image(cached, self._natural_size(photo))
        elif cached is not None:
            self._view.set_message("(preview unavailable)")
        else:
            self._view.set_message("Loading…")
            self._request(photo, "screen")
        for step in PREFETCH:
            j = self._index + step
            if 0 <= j < len(self._photos) and self._photos[j].id not in self._screen_images:
                self._request(self._photos[j], "screen")
        self._update_info()

    def _update_info(self):
        photo = self.current_photo()
        quality = max(0, min(100, round((photo.quality_score or 0) * 100)))
        self._title.setText(f"{self._index + 1} of {len(self._photos)}   ·   {photo.filename}"
                            f"   ·   Quality {quality}/100")
        color = _VERDICT_COLOR[photo.verdict]
        self._verdict.setText(photo.verdict.value)
        self._verdict.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {color};")
        self._update_zoom_label()

    def _update_zoom_label(self):
        if self._view.has_image():
            fit = " (fit)" if self._view.is_fit() else ""
            self._zoom_label.setText(f"{self._view.zoom_percent()}%{fit}")
        else:
            self._zoom_label.setText("")

    def _go(self, step: int):
        new = max(0, min(len(self._photos) - 1, self._index + step))
        if new != self._index:
            self._index = new
            self._show_current()

    # ── keys ──
    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key == Qt.Key_Z and mods & Qt.ControlModifier:
            if self._on_undo:
                self._on_undo()
                self._update_info()
        elif key in _KEY_VERDICT and not mods & (Qt.ControlModifier | Qt.AltModifier):
            photo = self.current_photo()
            if self._on_verdict:
                self._on_verdict(photo, _KEY_VERDICT[key])
            else:
                photo.verdict = _KEY_VERDICT[key]
                photo.user_override = True
            self._update_info()
        elif key in (Qt.Key_Right, Qt.Key_PageDown):
            self._go(1)
        elif key in (Qt.Key_Left, Qt.Key_PageUp):
            self._go(-1)
        elif key == Qt.Key_Home:
            self._go(-len(self._photos))
        elif key == Qt.Key_End:
            self._go(len(self._photos))
        elif key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._view.toggle_fit_actual()
            self._update_zoom_label()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self._view.zoom_by(WHEEL_STEP)
        elif key == Qt.Key_Minus:
            self._view.zoom_by(1 / WHEEL_STEP)
        elif key == Qt.Key_0:
            self._view.fit()
        elif key == Qt.Key_1:
            self._view.actual_size()
        elif key == Qt.Key_O:
            path = self.current_photo().filepath
            if os.path.isfile(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            super().keyPressEvent(event)  # Esc closes
