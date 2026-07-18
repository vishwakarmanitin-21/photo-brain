"""Side-by-side compare view for choosing the best of a group of near-dupes."""
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QWidget, QFrame, QDialogButtonBox,
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from app.core.models import Photo, Verdict

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

        # Large image, scaled down from the original (never upscaled).
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignCenter)
        self._image.setFixedSize(image_px, image_px)
        pixmap = QPixmap(photo.filepath)
        if not pixmap.isNull():
            self._image.setPixmap(pixmap.scaled(
                image_px, image_px, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self._image.setText("(preview unavailable)")
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

    def __init__(self, photos: list[Photo], parent=None, image_px: int = 460):
        super().__init__(parent)
        self.setWindowTitle("Compare photos")
        self.setMinimumSize(min(1200, image_px * len(photos) + 80), image_px + 220)

        ranked = sorted(photos, key=lambda p: (-p.quality_score, p.filepath))
        best_id = ranked[0].id if len(ranked) > 1 else None

        layout = QVBoxLayout(self)
        header = QLabel(
            "Pick the keeper — set each photo, then close. "
            "Ctrl+Z in the review screen undoes it.")
        header.setStyleSheet("color: #555;")
        layout.addWidget(header)

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

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
