"""Side-by-side compare view for choosing the best of a group of near-dupes."""
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QFrame, QDialogButtonBox, QApplication,
)
from PySide6.QtGui import QImage
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal

from app.core.models import Photo, Verdict
from app.ui.image_loading import load_bounded_image, load_full_image, upright_size
from app.ui.zoom_pan_view import ZoomPanView

# Panel image size limits (logical px). The actual size follows the screen:
# up to four photos fit side by side without scrolling (UX-20).
MIN_IMAGE_PX = 320
MAX_IMAGE_PX = 900


def fit_image_px(count: int, avail_w: int, avail_h: int) -> int:
    """Largest square image size so min(count, 4) panels fit the screen."""
    per_row = max(1, min(count, 4))
    by_width = (avail_w - 120) // per_row - 30
    by_height = avail_h - 330  # header, stats, buttons, dialog chrome
    return max(MIN_IMAGE_PX, min(MAX_IMAGE_PX, by_width, by_height))


class _Loaded(QObject):
    done = Signal(str, bool, QImage)  # photo id, full resolution?, image


class _LoadTask(QRunnable):
    """Decode one photo off the UI thread: bounded (or full), upright, any format."""

    def __init__(self, photo: Photo, max_dim: int, relay: _Loaded, full: bool = False):
        super().__init__()
        self.photo, self.max_dim, self.relay, self.full = photo, max_dim, relay, full

    def run(self):
        path = self.photo.filepath
        image = load_full_image(path) if self.full else load_bounded_image(path, self.max_dim)
        try:
            self.relay.done.emit(self.photo.id, self.full, image)
        except RuntimeError:
            pass  # the dialog closed before this decode finished — nothing to update

_VERDICT_COLOR = {
    Verdict.KEEP: "#4CAF50",
    Verdict.ARCHIVE: "#FF9800",
    Verdict.DELETE: "#F44336",
    Verdict.REVIEW: "#9E9E9E",
}


def _fmt_size(n: float) -> str:
    n = n or 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _rating(score: float) -> int:
    return max(0, min(100, round(score * 100)))


class _PhotoPanel(QFrame):
    """One photo in the compare row: large image, stats, verdict buttons."""

    def __init__(self, photo: Photo, is_best: bool, image_px: int, parent=None):
        super().__init__(parent)
        self.photo = photo
        self._image_px = image_px
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Zoomable image, filled in by a background decode (set_image) — never
        # decoded on the UI thread (UX-20). Zoom/pan here is mirrored onto the
        # other photos by the dialog (FEAT-07).
        self._image = ZoomPanView()
        self._image.setFixedSize(image_px, image_px)
        layout.addWidget(self._image)

        star = "★ Best  " if is_best else ""
        head = QLabel(f"{star}{photo.filename}")
        head.setStyleSheet("font-weight: bold;" + (
            " color: #4CAF50;" if is_best else ""))
        head.setAlignment(Qt.AlignCenter)
        layout.addWidget(head)

        stats = [f"Quality {_rating(photo.quality_score)}/100",
                 _fmt_size(photo.file_size),
                 f"sharp {photo.sharpness:.0f}"]
        if photo.face_count:
            stats.append(f"{photo.face_count} face"
                         + ("s" if photo.face_count > 1 else ""))
        info = QLabel("  ·  ".join(stats))
        info.setStyleSheet("font-size: 11px; color: #666;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        # People-photo likability signals — Compare is where you pick between
        # two shots of the same moment, so surface the eyes/smile/facing data
        # that decides which is the keeper.
        if photo.face_count:
            people = QLabel(
                f"eyes {round(photo.eyes_open_score * 100)}%  ·  "
                f"smile {round(photo.smile_score * 100)}%  ·  "
                f"natural {round(photo.expression_naturalness * 100)}%  ·  "
                f"facing {round(photo.head_pose_frontal * 100)}%"
            )
            people.setStyleSheet("font-size: 11px; color: #8a8a8a;")
            people.setAlignment(Qt.AlignCenter)
            layout.addWidget(people)

        btn_row = QHBoxLayout()
        for label, verdict in [("Keep", Verdict.KEEP),
                               ("Archive", Verdict.ARCHIVE),
                               ("Delete", Verdict.DELETE)]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                f"background-color: {_VERDICT_COLOR[verdict]}; color: white; "
                "padding: 4px 10px; border-radius: 3px;")
            btn.clicked.connect(lambda _=False, v=verdict: self._set(v))
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._verdict_label = QLabel()
        self._verdict_label.setAlignment(Qt.AlignCenter)
        self._verdict_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        layout.addWidget(self._verdict_label)

        self._refresh()

    @property
    def view(self) -> ZoomPanView:
        return self._image

    def set_image(self, image: QImage, full: bool = False):
        if image.isNull():
            if not full:
                self._image.set_message("(preview unavailable)")
            return
        # Decoded at screen pixels (panel size x devicePixelRatio) so it is
        # sharp on a scaled display; the full-resolution decode replaces it
        # without moving the view when the user zooms in.
        self._image.set_image(image, upright_size(self.photo.filepath), keep_view=full)

    def _set(self, verdict: Verdict):
        self.photo.verdict = verdict
        self.photo.user_override = True
        self._refresh()

    def _refresh(self):
        color = _VERDICT_COLOR[self.photo.verdict]
        self._verdict_label.setText(self.photo.verdict.value)
        self._verdict_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {color};")
        self.setStyleSheet(
            f"_PhotoPanel {{ border: 3px solid {color}; border-radius: 6px; }}")


class CompareDialog(QDialog):
    """Show a group's photos side by side so the keeper is obvious.

    Verdicts set here are written straight onto the shared Photo objects;
    the caller refreshes the review grid on close.
    """

    def __init__(self, photos: list[Photo], parent=None, image_px: int | None = None,
                 note: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Compare photos")
        screen = (parent.screen() if parent is not None else None) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        if image_px is None:
            image_px = fit_image_px(len(photos), avail.width(), avail.height())
        per_row = min(len(photos), 4)
        self.resize(min(avail.width() - 40, (image_px + 40) * per_row + 60),
                    min(avail.height() - 40, image_px + 300))

        ranked = sorted(photos, key=lambda p: (-p.quality_score, p.filepath))
        best_id = ranked[0].id if len(ranked) > 1 else None

        layout = QVBoxLayout(self)
        header = QLabel(
            "Pick the keeper — set each photo, then close. "
            "Ctrl+Z in the review screen undoes it. Wheel to zoom, drag to pan, "
            "double-click for 100% — every photo follows, so you compare the same spot.")
        header.setStyleSheet("color: #555;")
        layout.addWidget(header)
        if note:
            notice = QLabel(note)
            notice.setStyleSheet("color: #b45309;")
            layout.addWidget(notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        self._panels = []
        for p in photos:
            panel = _PhotoPanel(p, is_best=(p.id == best_id), image_px=image_px)
            self._panels.append(panel)
            row.addWidget(panel)
        scroll.setWidget(row_widget)
        layout.addWidget(scroll, stretch=1)

        # Decode every photo in the background; panels fill in as they land.
        self._relay = _Loaded()
        self._relay.done.connect(self._on_loaded)
        decode_px = int(image_px * screen.devicePixelRatio())
        for p in photos:
            QThreadPool.globalInstance().start(_LoadTask(p, decode_px, self._relay))

        # Linked zoom/pan (FEAT-07): a change in one photo is mirrored on the
        # others; zooming past the loaded resolution fetches full-size decodes.
        self._full_requested = False
        for panel in self._panels:
            panel.view.view_changed.connect(
                lambda z, x, y, src=panel: self._mirror_view(src, z, x, y))
            panel.view.wants_full_resolution.connect(self._load_full_resolution)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _mirror_view(self, source, relative_zoom: float, cx: float, cy: float):
        for panel in self._panels:
            if panel is not source:
                panel.view.set_view(relative_zoom, cx, cy)

    def _load_full_resolution(self):
        if self._full_requested:
            return
        self._full_requested = True
        for panel in self._panels:
            QThreadPool.globalInstance().start(_LoadTask(panel.photo, 0, self._relay, full=True))

    def _on_loaded(self, photo_id: str, full: bool, image: QImage):
        for panel in self._panels:
            if panel.photo.id == photo_id:
                panel.set_image(image, full=full)
