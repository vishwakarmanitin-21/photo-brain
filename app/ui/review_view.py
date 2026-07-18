"""Review view — cluster list + thumbnail grid with keyboard shortcuts."""
import os
import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QScrollArea, QGridLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QComboBox, QApplication, QSlider, QCheckBox,
    QLineEdit, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Signal, Qt, Slot, QSize, QUrl, QPoint, QTimer
from PySide6.QtGui import (
    QPixmap, QKeySequence, QColor, QShortcut, QDesktopServices, QCursor,
    QImageReader,
)

from app.core.models import Photo, Cluster, Event, Verdict, DupType, FaceDistance
from app.core.scoring import is_low_quality
from app.ui.dialogs import ShortcutsHelpDialog
from app.ui.compare_dialog import CompareDialog

# Single source of truth for the review shortcuts — used to bind them AND
# to populate the discoverable help dialog, so the two never drift.
REVIEW_SHORTCUTS = [
    ("K", "Keep the selected photo"),
    ("A", "Archive the selected photo"),
    ("D", "Delete the selected photo (to Recycle Bin)"),
    ("R", "Reset the selected photo to undecided"),
    ("C", "Compare this group's photos side by side"),
    ("Ctrl / Shift + click", "Select several photos; K/A/D then applies to all"),
    ("← / →", "Previous / next photo in the group"),
    ("↑ / ↓", "Move up / down a row in the photo grid"),
    ("J / PageDown / PageUp", "Next / previous group"),
    ("Ctrl+Z", "Undo your last decision"),
    ("Ctrl+Shift+Z", "Undo the last Apply (restore moved files)"),
    ("+ / − / 0", "Zoom in / out / reset"),
    ("Alt + hover", "Full-size preview of a photo"),
    ("Ctrl+Enter", "Apply all changes"),
    ("F1 / ?", "Show this shortcuts list"),
]

log = logging.getLogger("photobrain.review_view")

# Zoom configuration
MIN_THUMB_SIZE = 120  # Minimum thumbnail size
MAX_THUMB_SIZE = 800  # Maximum thumbnail size
BASE_THUMB_SIZE = 180  # Base display size (middle of range)
THUMB_DISPLAY_SIZE = 180  # Keep for backward compatibility
THUMB_CACHE_SIZE = 200  # Resolution of cached thumbnails; above this we
                        # load high-res previews instead

# Colors
COLOR_KEEP = "#4CAF50"
COLOR_ARCHIVE = "#FF9800"
COLOR_DELETE = "#F44336"
COLOR_REVIEW = "#9E9E9E"
COLOR_SELECTED = "#2196F3"

# Colour-independent verdict badge letters (UX-12, colour-blind accessibility)
VERDICT_BADGE_LETTER = {
    Verdict.KEEP: "K",
    Verdict.ARCHIVE: "A",
    Verdict.DELETE: "D",
    Verdict.REVIEW: "?",
}

# Filter constants
FACE_FILTER_ALL = "All Photos"
FACE_FILTER_CLOSE = "Faces (Close-up)"
FACE_FILTER_FAR = "Faces (Distant)"
FACE_FILTER_ANY_FACES = "Has Any Faces"
FACE_FILTER_NO_FACES = "No Faces"
FACE_FILTER_GROUP = "Group Shots (3+)"

EVENT_FILTER_ALL = "All Events"

QUALITY_FILTER_ALL = "All Quality"
QUALITY_FILTER_LOW = "Low Quality"

# Sort options for the photo grid (FEAT-05). Each maps to a (key, reverse) pair.
SORT_BEST = "Best first"
SORT_NEWEST = "Newest first"
SORT_OLDEST = "Oldest first"
SORT_LARGEST = "Largest first"
SORT_SMALLEST = "Smallest first"
SORT_OPTIONS = [SORT_BEST, SORT_NEWEST, SORT_OLDEST, SORT_LARGEST, SORT_SMALLEST]


def sort_photos(photos: list, mode: str) -> list:
    """Return photos ordered per the chosen sort mode, filepath as a stable
    tiebreaker so the grid is deterministic (FEAT-05)."""
    if mode == SORT_NEWEST:
        return sorted(photos, key=lambda p: (p.exif_datetime or "", p.filepath),
                      reverse=True)
    if mode == SORT_OLDEST:
        # Missing dates sort last, not first, so undated photos don't masquerade
        # as the oldest.
        return sorted(photos, key=lambda p: (p.exif_datetime or "￿", p.filepath))
    if mode == SORT_LARGEST:
        return sorted(photos, key=lambda p: (-(p.file_size or 0), p.filepath))
    if mode == SORT_SMALLEST:
        return sorted(photos, key=lambda p: (p.file_size or 0, p.filepath))
    # SORT_BEST (default): highest quality first.
    return sorted(photos, key=lambda p: (-(p.quality_score or 0), p.filepath))


HOVER_PREVIEW_MAX = 1000  # hover overlay never needs more than this


def cluster_display_label(cluster) -> str:
    """Plain-language label for the cluster list — no developer vocabulary
    like 'Cluster 8 [EXACT] [APPLIED]'. (UX-08)"""
    if cluster.is_exact_dup_group:
        name = "Exact duplicates"
    elif cluster.member_count > 1:
        name = "Similar shots"
    else:
        name = "Single photo"
    text = f"{name} ({cluster.member_count})"
    if cluster.applied:
        text += "  ✓ applied"
    elif cluster.reviewed:
        text += "  ✓ reviewed"
    return text


def load_bounded_pixmap(filepath: str, max_dim: int) -> QPixmap:
    """Decode an image downscaled to fit max_dim, using the JPEG decoder's
    own scaling — dramatically faster than loading a full 12–48MP original
    just to shrink it. Returns a null pixmap on failure."""
    reader = QImageReader(filepath)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and (size.width() > max_dim or size.height() > max_dim):
        scaled = size.scaled(max_dim, max_dim, Qt.KeepAspectRatio)
        reader.setScaledSize(scaled)
    image = reader.read()
    if not image.isNull():
        return QPixmap.fromImage(image)
    # Qt can't decode HEIC without a plugin — fall back to Pillow (FEAT-02).
    return _load_bounded_via_pil(filepath, max_dim)


def _load_bounded_via_pil(filepath: str, max_dim: int) -> QPixmap:
    try:
        from PIL import Image, ImageQt
        from app.core import image_formats  # noqa: F401  (registers HEIC)
        with Image.open(filepath) as img:
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim))
            return QPixmap.fromImage(ImageQt.ImageQt(img))
    except Exception:
        return QPixmap()


def _format_size(n: float) -> str:
    n = n or 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def quality_rating_100(score: float) -> int:
    """Map the [0,1] quality score to an honest 0–100 rating for display.

    The raw score is a bounded [0,1] value now, but shown as '0.47' it
    reads like false precision and means nothing to a user. A 0–100
    rating is the same information without pretending to be exact. The
    within-group 'Best' badge carries the comparison that actually
    matters — this number is only a rough per-photo cue.
    """
    return max(0, min(100, round(score * 100)))


class HoverPreviewWidget(QWidget):
    """Floating preview that shows full-size photo on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Frame with shadow
        frame = QFrame()
        frame.setStyleSheet("background: white; border: 2px solid #333;")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignCenter)
        frame_layout.addWidget(self._image_label)

        layout.addWidget(frame)

        self.hide()

    def show_preview(self, pixmap: QPixmap, cursor_pos: QPoint):
        """Show preview near cursor position."""
        # Scale to max 800×800 while preserving aspect ratio
        scaled = pixmap.scaled(
            800, 800,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self.adjustSize()

        # Position near cursor, offset to avoid covering thumbnail
        x = cursor_pos.x() + 20
        y = cursor_pos.y() + 20

        # Adjust if would go off-screen
        screen = QApplication.primaryScreen().geometry()
        if x + self.width() > screen.right():
            x = cursor_pos.x() - self.width() - 20
        if y + self.height() > screen.bottom():
            y = cursor_pos.y() - self.height() - 20

        self.move(x, y)
        self.show()
        self.raise_()

    def hide_preview(self):
        """Hide preview."""
        self.hide()


class ThumbnailWidget(QFrame):
    """Single photo thumbnail with verdict indicator and selection."""

    clicked = Signal(str)  # photo_id
    verdict_changed = Signal(str, str)  # photo_id, verdict_value
    hovered = Signal(str, QPoint)  # photo_id, cursor_pos
    unhovered = Signal()

    def __init__(self, photo: Photo, parent=None, is_best: bool = False):
        super().__init__(parent)
        self.photo = photo
        self._is_best = is_best
        self._selected = False
        self._hover_active = False
        self._display_size = BASE_THUMB_SIZE
        self._source_pixmap = QPixmap()
        self.setFixedSize(BASE_THUMB_SIZE + 16, BASE_THUMB_SIZE + 100)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)  # Enable mouse tracking for hover
        self._build_ui()
        self._update_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Thumbnail image
        self._image_label = QLabel()
        self._image_label.setFixedSize(self._display_size, self._display_size)
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("background-color: palette(alternate-base);")
        self._image_label.setText("Loading...")
        layout.addWidget(self._image_label, alignment=Qt.AlignCenter)

        # Filename
        name = self.photo.filename
        if len(name) > 22:
            name = name[:10] + "..." + name[-9:]
        name_label = QLabel(name)
        name_label.setStyleSheet("font-size: 10px;")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setToolTip(self.photo.filename)
        layout.addWidget(name_label)

        # Quality rating + info row
        info_parts = []
        if self._is_best:
            info_parts.append("★ Best")
        info_parts.append(f"Quality: {quality_rating_100(self.photo.quality_score)}/100")
        if self.photo.dup_type != DupType.NONE:
            info_parts.append(self.photo.dup_type.value.upper())
        if self.photo.face_count > 0:
            face_text = f"{self.photo.face_count} face"
            if self.photo.face_count > 1:
                face_text += "s"
            dist_tag = "close" if self.photo.face_distance == FaceDistance.CLOSE else "far"
            face_text += f" ({dist_tag})"
            info_parts.append(face_text)
        info_label = QLabel(" | ".join(info_parts))
        info_label.setStyleSheet("font-size: 9px; color: #888;")
        info_label.setAlignment(Qt.AlignCenter)
        # Build tooltip with extra metadata
        tooltip_parts = [
            f"File: {self.photo.filename}",
            f"Size: {_format_size(self.photo.file_size)}",
            f"Quality: {quality_rating_100(self.photo.quality_score)}/100"
            + (" (best in group)" if self._is_best else ""),
            f"Sharpness: {self.photo.sharpness:.1f}",
            f"Brightness: {self.photo.brightness:.1f}",
            f"Faces: {self.photo.face_count}",
        ]
        if self.photo.face_count > 0:
            tooltip_parts.append(f"Eyes Open: {self.photo.eyes_open_score * 100:.0f}%")
            tooltip_parts.append(f"Smile: {self.photo.smile_score * 100:.0f}%")
            tooltip_parts.append(f"Isolation: {self.photo.subject_isolation * 100:.0f}%")
            tooltip_parts.append(f"Expression: {self.photo.expression_naturalness * 100:.0f}%")
            tooltip_parts.append(f"Frontal: {self.photo.head_pose_frontal * 100:.0f}%")
        if self.photo.exif_datetime:
            tooltip_parts.append(f"Date: {self.photo.exif_datetime[:19]}")
        info_label.setToolTip("\n".join(tooltip_parts))
        layout.addWidget(info_label)

        # Keep / Archive / Delete buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)

        self._keep_btn = QPushButton("Keep")
        self._keep_btn.setFixedHeight(22)
        self._keep_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9px; padding: 1px 6px; "
            f"background-color: {COLOR_KEEP}; color: white; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #45a049; }}"
        )
        self._keep_btn.setToolTip("Keep (shortcut: K)")
        self._keep_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.KEEP))
        btn_row.addWidget(self._keep_btn)

        self._archive_btn = QPushButton("Archive")
        self._archive_btn.setFixedHeight(22)
        self._archive_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9px; padding: 1px 6px; "
            f"background-color: {COLOR_ARCHIVE}; color: white; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #F57C00; }}"
        )
        self._archive_btn.setToolTip("Archive (shortcut: A)")
        self._archive_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.ARCHIVE))
        btn_row.addWidget(self._archive_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(22)
        self._delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9px; padding: 1px 6px; "
            f"background-color: {COLOR_DELETE}; color: white; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #d32f2f; }}"
        )
        self._delete_btn.setToolTip("Delete to Recycle Bin (shortcut: D)")
        self._delete_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.DELETE))
        btn_row.addWidget(self._delete_btn)

        layout.addLayout(btn_row)

        # Verdict label
        self._verdict_label = QLabel(self.photo.verdict.value)
        self._verdict_label.setAlignment(Qt.AlignCenter)
        self._verdict_label.setStyleSheet("font-size: 10px; font-weight: bold;")
        layout.addWidget(self._verdict_label)

        # Corner badge — a distinct LETTER per verdict so the state is readable
        # without relying on border colour alone (colour-blind safe). (UX-12)
        self._verdict_badge = QLabel(self)
        self._verdict_badge.setAlignment(Qt.AlignCenter)
        self._verdict_badge.setFixedSize(22, 22)
        self._verdict_badge.move(10, 10)
        self._verdict_badge.raise_()

    def _on_verdict_btn(self, verdict: Verdict):
        self.photo.user_override = True
        self.update_verdict(verdict)
        self.verdict_changed.emit(self.photo.id, verdict.value)

    def set_pixmap(self, pixmap: QPixmap, display_size: int = None):
        """Set pixmap scaled to display_size, adjusting for aspect ratio."""
        if display_size is None:
            display_size = self._display_size
        self._display_size = display_size
        self._source_pixmap = QPixmap(pixmap)
        self._render_pixmap()

    def _render_pixmap(self):
        """Rescale the already-decoded pixmap without touching disk."""
        display_size = self._display_size
        pixmap = self._source_pixmap
        if pixmap.isNull():
            self.setFixedSize(display_size + 16, display_size + 116)
            self._image_label.setFixedSize(display_size, display_size)
            return

        # Scale maintaining aspect ratio
        scaled = pixmap.scaled(
            display_size, display_size,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )

        # Set the image label to the actual scaled size (not square)
        actual_width = scaled.width()
        actual_height = scaled.height()
        self._image_label.setFixedSize(actual_width, actual_height)
        self._image_label.setPixmap(scaled)
        self._image_label.setText("")

        # Adjust widget height to match actual image height + UI chrome
        # UI chrome = 8px margins + labels + buttons + verdict ≈ 116px
        self.setFixedSize(display_size + 16, actual_height + 116)

    def update_size(self, display_size: int):
        """Resize widget to accommodate new display size."""
        self._display_size = display_size
        self._render_pixmap()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def update_verdict(self, verdict: Verdict):
        self.photo.verdict = verdict
        self._verdict_label.setText(verdict.value)
        self._update_style()

    def _update_style(self):
        verdict = self.photo.verdict
        if verdict == Verdict.KEEP:
            border_color = COLOR_KEEP
        elif verdict == Verdict.ARCHIVE:
            border_color = COLOR_ARCHIVE
        elif verdict == Verdict.DELETE:
            border_color = COLOR_DELETE
        else:
            border_color = COLOR_REVIEW

        border_width = 4 if self._selected else 3
        outline = f"outline: 2px solid {COLOR_SELECTED};" if self._selected else ""

        self.setStyleSheet(
            f"ThumbnailWidget {{ border: {border_width}px solid {border_color}; "
            f"border-radius: 4px; background-color: palette(base); {outline} }}"
        )

        # Verdict label color
        self._verdict_label.setStyleSheet(
            f"font-size: 10px; font-weight: bold; color: {border_color};"
        )

        # Corner letter badge — colour-independent verdict cue (UX-12).
        letter = VERDICT_BADGE_LETTER.get(verdict, "?")
        self._verdict_badge.setText(letter)
        self._verdict_badge.setToolTip(verdict.value)
        self._verdict_badge.setStyleSheet(
            f"QLabel {{ background-color: {border_color}; color: white; "
            f"font-size: 12px; font-weight: bold; border: 1px solid white; "
            f"border-radius: 11px; }}"
        )

    def mousePressEvent(self, event):
        self.clicked.emit(self.photo.id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """Open the full photo in the system default viewer."""
        filepath = self.photo.filepath
        if os.path.isfile(filepath):
            QDesktopServices.openUrl(QUrl.fromLocalFile(filepath))
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        """Mouse entered widget area."""
        # Only show preview if Alt is pressed
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            self._hover_active = True
            cursor_pos = QCursor.pos()
            self.hovered.emit(self.photo.id, cursor_pos)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Mouse left widget area."""
        if self._hover_active:
            self._hover_active = False
            self.unhovered.emit()
        super().leaveEvent(event)


class ReviewView(QWidget):
    """Main review interface with cluster list and thumbnail grid."""

    apply_requested = Signal()
    apply_cluster_requested = Signal(str)  # cluster_id
    undo_requested = Signal()
    back_requested = Signal()
    open_log_requested = Signal()
    review_state_changed = Signal()
    previews_requested = Signal(object, int)  # photos, display_size

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_clusters: list[Cluster] = []
        self._clusters: list[Cluster] = []  # filtered view
        self._cluster_photos: dict[str, list[Photo]] = {}
        self._events: list[Event] = []
        self._event_photos: dict[str, set[str]] = {}  # event_id -> set of photo_ids
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._current_cluster_idx = -1
        self._selected_photo_id: str | None = None   # anchor / primary
        self._selected_ids: set[str] = set()          # full multi-selection
        self._current_photos: list[Photo] = []  # Current cluster photos
        # Verdict-level undo: shadow of the last-checkpointed (verdict,
        # user_override) per photo, and a stack of prior states to restore.
        self._verdict_shadow: dict[str, tuple] = {}
        self._verdict_undo_stack: list[list[tuple]] = []
        self._current_display_size = BASE_THUMB_SIZE  # Current thumbnail display size
        self._preview_pixmaps: dict[str, QPixmap] = {}
        self._preview_pixmap_size = BASE_THUMB_SIZE
        self._zoom_debounce = QTimer(self)
        self._zoom_debounce.setSingleShot(True)
        self._zoom_debounce.setInterval(150)
        self._zoom_debounce.timeout.connect(self._apply_zoom_change)
        self._build_ui()
        self._bind_shortcuts()
        # Record every verdict change as an undo step (single, button, bulk).
        self.review_state_changed.connect(self._checkpoint_verdicts)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Toolbar ──
        toolbar = QHBoxLayout()

        self._back_btn = QPushButton("< Back")
        self._back_btn.clicked.connect(self.back_requested.emit)
        toolbar.addWidget(self._back_btn)

        self._title_label = QLabel("Review")
        self._title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        toolbar.addWidget(self._title_label, stretch=1)

        self._compare_btn = QPushButton("⇆ Compare")
        self._compare_btn.setToolTip(
            "Compare this group's photos side by side (C)")
        self._compare_btn.clicked.connect(self._open_compare)
        toolbar.addWidget(self._compare_btn)

        self._shortcuts_btn = QPushButton("⌨ Shortcuts")
        self._shortcuts_btn.setToolTip("Show keyboard shortcuts (F1)")
        self._shortcuts_btn.clicked.connect(self._show_shortcuts)
        toolbar.addWidget(self._shortcuts_btn)

        # Export decisions + open the apply log (FEAT-05).
        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setToolTip(
            "Save the full decision list (keep/archive/delete) as a CSV before "
            "applying.")
        self._export_btn.clicked.connect(self._export_decisions)
        toolbar.addWidget(self._export_btn)

        self._open_log_btn = QPushButton("Open Log")
        self._open_log_btn.setToolTip(
            "Open the folder with PhotoBrain's logs and the last apply record.")
        self._open_log_btn.clicked.connect(self.open_log_requested.emit)
        toolbar.addWidget(self._open_log_btn)

        self._undo_btn = QPushButton("Undo Last Apply")
        self._undo_btn.setEnabled(False)
        self._undo_btn.clicked.connect(self.undo_requested.emit)
        toolbar.addWidget(self._undo_btn)

        # Zoom controls - smooth slider
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Zoom:"))

        # Zoom out button
        zoom_out_btn = QPushButton("-")
        zoom_out_btn.setFixedWidth(30)
        zoom_out_btn.setToolTip("Zoom out (smaller thumbnails)")
        zoom_out_btn.clicked.connect(self._zoom_out)
        zoom_layout.addWidget(zoom_out_btn)

        # Smooth zoom slider
        self._zoom_slider = QSlider(Qt.Horizontal)
        self._zoom_slider.setMinimum(MIN_THUMB_SIZE)
        self._zoom_slider.setMaximum(MAX_THUMB_SIZE)
        self._zoom_slider.setValue(BASE_THUMB_SIZE)
        self._zoom_slider.setFixedWidth(150)
        self._zoom_slider.setToolTip(f"Thumbnail size: {BASE_THUMB_SIZE}px")
        self._zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self._zoom_slider.sliderReleased.connect(self._apply_zoom_change_immediately)
        zoom_layout.addWidget(self._zoom_slider)

        # Zoom in button
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedWidth(30)
        zoom_in_btn.setToolTip("Zoom in (larger thumbnails)")
        zoom_in_btn.clicked.connect(self._zoom_in)
        zoom_layout.addWidget(zoom_in_btn)

        # Reset button
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedWidth(50)
        reset_btn.setToolTip("Reset zoom to default")
        reset_btn.clicked.connect(lambda: self._zoom_slider.setValue(BASE_THUMB_SIZE))
        zoom_layout.addWidget(reset_btn)

        toolbar.addLayout(zoom_layout)
        toolbar.addSpacing(10)

        self._apply_btn = QPushButton("Apply Changes")
        self._apply_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-size: 13px; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self._apply_btn.clicked.connect(self.apply_requested.emit)
        toolbar.addWidget(self._apply_btn)

        layout.addLayout(toolbar)

        # ── Filter bar ──
        filter_bar = QHBoxLayout()

        filter_bar.addWidget(QLabel("Faces:"))
        self._face_filter = QComboBox()
        self._face_filter.addItems([
            FACE_FILTER_ALL, FACE_FILTER_CLOSE, FACE_FILTER_FAR,
            FACE_FILTER_ANY_FACES, FACE_FILTER_NO_FACES, FACE_FILTER_GROUP,
        ])
        self._face_filter.currentTextChanged.connect(self._apply_filters)
        self._face_filter.setMinimumWidth(140)
        filter_bar.addWidget(self._face_filter)

        filter_bar.addSpacing(15)

        filter_bar.addWidget(QLabel("Quality:"))
        self._quality_filter = QComboBox()
        self._quality_filter.addItems([QUALITY_FILTER_ALL, QUALITY_FILTER_LOW])
        self._quality_filter.setToolTip(
            "Low Quality: every photo flagged as junk — blurry, or too dark / "
            "blown-out to use — across all groups. These are left undecided "
            "(not kept, not moved) for you to sweep."
        )
        self._quality_filter.currentTextChanged.connect(self._apply_filters)
        self._quality_filter.setMinimumWidth(150)
        filter_bar.addWidget(self._quality_filter)

        filter_bar.addSpacing(15)

        # Hide single auto-keep photos — they need no decision and clutter
        # the list of real duplicate groups. (UX-08)
        self._hide_singletons = QCheckBox("Hide single photos")
        self._hide_singletons.setChecked(True)
        self._hide_singletons.setToolTip(
            "Hide one-photo groups that are already set to Keep — there's "
            "nothing to decide on them. Untick to see every photo.")
        self._hide_singletons.toggled.connect(self._apply_filters)
        filter_bar.addWidget(self._hide_singletons)

        filter_bar.addSpacing(15)

        filter_bar.addWidget(QLabel("Event:"))
        self._event_filter = QComboBox()
        self._event_filter.addItem(EVENT_FILTER_ALL)
        self._event_filter.currentTextChanged.connect(self._apply_filters)
        self._event_filter.setMinimumWidth(200)
        filter_bar.addWidget(self._event_filter)

        filter_bar.addSpacing(15)

        # Filename search (FEAT-05).
        filter_bar.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("filename…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.setMaximumWidth(160)
        self._search_box.textChanged.connect(self._apply_filters)
        filter_bar.addWidget(self._search_box)

        filter_bar.addSpacing(15)

        # Sort within the selected group (FEAT-05).
        filter_bar.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(SORT_OPTIONS)
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        filter_bar.addWidget(self._sort_combo)

        filter_bar.addStretch()

        # Overall review progress (FEAT-05).
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("font-size: 11px; font-weight: bold;")
        filter_bar.addWidget(self._progress_label)

        filter_bar.addSpacing(10)

        self._filter_status = QLabel("")
        self._filter_status.setStyleSheet("font-size: 11px; color: #888;")
        filter_bar.addWidget(self._filter_status)

        layout.addLayout(filter_bar)

        # ── Splitter: cluster list | thumbnail grid ──
        splitter = QSplitter(Qt.Horizontal)

        # Left: Cluster list
        self._cluster_list = QListWidget()
        self._cluster_list.setMinimumWidth(200)
        self._cluster_list.setMaximumWidth(280)
        self._cluster_list.currentRowChanged.connect(self._on_cluster_selected)
        splitter.addWidget(self._cluster_list)

        # Right: Thumbnail scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._scroll.setWidget(self._grid_container)

        splitter.addWidget(self._scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter, stretch=1)

        # ── Action buttons row ──
        actions = QHBoxLayout()

        btn_keep_all = QPushButton("Keep All")
        btn_keep_all.setToolTip("Mark all photos in this cluster as KEEP")
        btn_keep_all.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_KEEP}; color: white; "
            f"padding: 4px 12px; border-radius: 3px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #45a049; }}"
        )
        btn_keep_all.clicked.connect(self._keep_all)
        actions.addWidget(btn_keep_all)

        btn_archive_all = QPushButton("Archive All")
        btn_archive_all.setToolTip("Move all photos in this cluster to archive (safe, reversible)")
        btn_archive_all.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_ARCHIVE}; color: white; "
            f"padding: 4px 12px; border-radius: 3px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #F57C00; }}"
        )
        btn_archive_all.clicked.connect(self._archive_all)
        actions.addWidget(btn_archive_all)

        btn_delete_all = QPushButton("Delete All")
        btn_delete_all.setToolTip("Permanently delete all photos in this cluster (sent to Recycle Bin)")
        btn_delete_all.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_DELETE}; color: white; "
            f"padding: 4px 12px; border-radius: 3px; font-weight: bold; }}"
            f"QPushButton:hover {{ background-color: #d32f2f; }}"
        )
        btn_delete_all.clicked.connect(self._delete_all)
        actions.addWidget(btn_delete_all)

        actions.addSpacing(10)

        btn_keep_top1 = QPushButton("Keep Top 1")
        btn_keep_top1.setToolTip("Keep only the best photo in this cluster")
        btn_keep_top1.clicked.connect(lambda: self._keep_top_n(1))
        actions.addWidget(btn_keep_top1)

        btn_keep_top2 = QPushButton("Keep Top 2")
        btn_keep_top2.setToolTip("Keep the top 2 photos in this cluster")
        btn_keep_top2.clicked.connect(lambda: self._keep_top_n(2))
        actions.addWidget(btn_keep_top2)

        btn_delete_rest = QPushButton("Delete Rest")
        btn_delete_rest.setToolTip("Mark all non-KEEP photos as DELETE")
        btn_delete_rest.clicked.connect(self._delete_rest)
        actions.addWidget(btn_delete_rest)

        btn_mark_reviewed = QPushButton("Mark Reviewed")
        btn_mark_reviewed.clicked.connect(self._mark_reviewed)
        actions.addWidget(btn_mark_reviewed)

        actions.addSpacing(15)

        btn_apply_cluster = QPushButton("Apply Cluster")
        btn_apply_cluster.setToolTip("Apply changes for this cluster only (move/delete files)")
        btn_apply_cluster.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; "
            "padding: 4px 12px; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        btn_apply_cluster.clicked.connect(self._apply_cluster)
        actions.addWidget(btn_apply_cluster)

        actions.addStretch()
        layout.addLayout(actions)

        # ── Status bar ──
        status_row = QHBoxLayout()

        self._cluster_pos_label = QLabel("")
        status_row.addWidget(self._cluster_pos_label)

        status_row.addStretch()

        self._keep_label = QLabel("0 KEEP")
        self._keep_label.setStyleSheet(f"color: {COLOR_KEEP}; font-weight: bold;")
        status_row.addWidget(self._keep_label)

        status_row.addWidget(QLabel("|"))

        self._archive_label = QLabel("0 ARCHIVE")
        self._archive_label.setStyleSheet(f"color: {COLOR_ARCHIVE}; font-weight: bold;")
        status_row.addWidget(self._archive_label)

        status_row.addWidget(QLabel("|"))

        self._delete_label = QLabel("0 DELETE")
        self._delete_label.setStyleSheet(f"color: {COLOR_DELETE}; font-weight: bold;")
        status_row.addWidget(self._delete_label)

        status_row.addWidget(QLabel("|"))

        self._review_label = QLabel("0 REVIEW")
        self._review_label.setStyleSheet(f"color: {COLOR_REVIEW}; font-weight: bold;")
        status_row.addWidget(self._review_label)

        layout.addLayout(status_row)

    def _bind_shortcuts(self):
        # Scope shortcuts to this widget's subtree so they can't fire while
        # the Setup or Scan screen is showing (both live in the same stacked
        # widget). The view grabs focus when shown (showEvent) so the keys
        # work as soon as the review screen appears.
        self.setFocusPolicy(Qt.StrongFocus)

        def sc(keys, target):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(target)

        sc("K", self._mark_keep)
        sc("A", self._mark_archive)
        sc("D", self._mark_delete)
        sc("R", self._mark_review)
        sc("J", self._next_cluster)
        sc(Qt.Key_PageDown, self._next_cluster)
        sc(Qt.Key_PageUp, self._prev_cluster)
        # Arrows navigate the photo grid itself (UX-12): Left/Right by one,
        # Up/Down by a full row.
        sc(Qt.Key_Right, self._select_next_photo)
        sc(Qt.Key_Left, self._select_prev_photo)
        sc(Qt.Key_Down, self._select_photo_below)
        sc(Qt.Key_Up, self._select_photo_above)
        sc("Ctrl+Return", self.apply_requested.emit)
        sc("Ctrl+Z", self._undo_verdict)
        sc("Ctrl+Shift+Z", self.undo_requested.emit)
        sc("F1", self._show_shortcuts)
        sc("?", self._show_shortcuts)
        sc("C", self._open_compare)
        # Zoom shortcuts
        sc("+", self._zoom_in)
        sc("=", self._zoom_in)  # Also + without Shift
        sc("-", self._zoom_out)
        sc("0", lambda: self._zoom_slider.setValue(BASE_THUMB_SIZE))  # Reset

    def showEvent(self, event):
        super().showEvent(event)
        # Take focus so the widget-scoped shortcuts are active immediately.
        self.setFocus()

    # ── Zoom helper methods ──────────────────────────────

    def _get_display_size(self) -> int:
        """Get current thumbnail display size from slider."""
        return self._current_display_size

    def _get_grid_columns(self) -> int:
        """Calculate column count dynamically based on available width and thumb size."""
        # Get available width from scroll area
        available_width = self._scroll.viewport().width()

        # Widget width = display_size + 16px padding
        widget_width = self._current_display_size + 16

        # Add grid spacing (8px between widgets)
        widget_width_with_spacing = widget_width + 8

        # Calculate how many columns fit
        columns = max(1, available_width // widget_width_with_spacing)

        return columns

    def _show_shortcuts(self):
        ShortcutsHelpDialog(REVIEW_SHORTCUTS, self).exec()

    def _export_decisions(self):
        """Write every photo's current decision to a CSV (FEAT-05)."""
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, "Export decision list", "photobrain_decisions.csv",
            "CSV files (*.csv)")
        if not path:
            return
        try:
            rows = 0
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["group", "filename", "verdict", "quality_rating", "filepath"])
                for cluster in self._all_clusters:
                    label = cluster_display_label(cluster)
                    for p in self._cluster_photos.get(cluster.id, []):
                        writer.writerow([
                            label, p.filename, p.verdict.value,
                            quality_rating_100(p.quality_score), p.filepath,
                        ])
                        rows += 1
            QMessageBox.information(
                self, "Exported",
                f"Wrote {rows} photo decisions to:\n{path}")
        except Exception as error:
            QMessageBox.warning(
                self, "Export failed",
                f"Could not write the CSV file.\n\n{error}")

    def _open_compare(self):
        """Open the current group in a side-by-side compare view."""
        photos = self._get_current_photos()
        if not photos:
            return
        CompareDialog(photos, self).exec()
        # Reflect any verdicts set in the dialog back into the grid; the
        # emit lets the undo checkpoint record them.
        for p in photos:
            widget = self._thumb_widgets.get(p.id)
            if widget:
                widget.update_verdict(p.verdict)
        self._update_global_counts()
        self._update_cluster_list_item()
        self.review_state_changed.emit()

    def _zoom_in(self):
        """Increase thumbnail size."""
        current = self._zoom_slider.value()
        # Increase by 20px steps for smooth but noticeable change
        new_value = min(MAX_THUMB_SIZE, current + 20)
        self._zoom_slider.setValue(new_value)

    def _zoom_out(self):
        """Decrease thumbnail size."""
        current = self._zoom_slider.value()
        # Decrease by 20px steps
        new_value = max(MIN_THUMB_SIZE, current - 20)
        self._zoom_slider.setValue(new_value)

    def _on_zoom_changed(self, value: int):
        """Handle zoom slider value change."""
        if value != self._preview_pixmap_size:
            self._preview_pixmaps.clear()
            self._preview_pixmap_size = value
        self._current_display_size = value
        self._zoom_slider.setToolTip(f"Thumbnail size: {value}px")

        # Give immediate feedback using decoded pixmaps already in memory.
        for widget in self._thumb_widgets.values():
            widget.update_size(value)

        # Disk/cache reload and column reflow happen once after dragging pauses.
        self._zoom_debounce.start()

    def _apply_zoom_change(self):
        """Perform the coalesced grid rebuild for the latest slider value."""
        self._rebuild_grid_with_zoom()

        # Re-select current photo if any
        if self._selected_photo_id:
            widget = self._thumb_widgets.get(self._selected_photo_id)
            if widget:
                widget.set_selected(True)

    def _apply_zoom_change_immediately(self):
        """Commit the final slider position when the handle is released."""
        self._zoom_debounce.stop()
        self._apply_zoom_change()

    def _rebuild_grid_with_zoom(self):
        """Rebuild thumbnail grid with current zoom level."""
        # Clear existing grid: detach from the tree immediately (setParent)
        # AND schedule deletion (deleteLater), so old widgets neither linger
        # in the layout nor leak as parentless orphans.
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        self._thumb_widgets.clear()

        if not self._current_photos:
            return

        display_size = self._get_display_size()
        grid_columns = self._get_grid_columns()
        missing_previews: list[Photo] = []

        # "Best in group" cue: the top-scored photo, only when there is a
        # genuine choice (more than one photo in the cluster).
        best_photo_id = None
        if len(self._current_photos) > 1:
            # Same ordering the verdict ranking uses: highest score, then
            # smallest filepath — so 'Best' marks the photo kept first.
            best_photo_id = min(
                self._current_photos,
                key=lambda p: (-p.quality_score, p.filepath),
            ).id

        for i, photo in enumerate(self._current_photos):
            widget = ThumbnailWidget(photo, is_best=(photo.id == best_photo_id))
            widget.update_size(display_size)

            # Load high-res or cached thumbnail
            if display_size > THUMB_CACHE_SIZE:
                pixmap = self._preview_pixmaps.get(photo.id, QPixmap())
                if pixmap.isNull():
                    if photo.thumb_path and os.path.isfile(photo.thumb_path):
                        pixmap = QPixmap(photo.thumb_path)
                    missing_previews.append(photo)
            else:
                # Use cached 200×200 for smaller sizes
                if photo.thumb_path and os.path.isfile(photo.thumb_path):
                    pixmap = QPixmap(photo.thumb_path)
                else:
                    pixmap = QPixmap()

            widget.set_pixmap(pixmap, display_size)

            # Connect signals
            widget.clicked.connect(self._on_photo_clicked)
            widget.verdict_changed.connect(self._on_thumb_verdict_changed)
            widget.hovered.connect(self._show_hover_preview)
            widget.unhovered.connect(self._hide_hover_preview)

            # Add to grid
            row = i // grid_columns
            col = i % grid_columns
            self._grid_layout.addWidget(widget, row, col)

            self._thumb_widgets[photo.id] = widget

        if missing_previews:
            self.previews_requested.emit(missing_previews, display_size)

    @Slot(str, int, object)
    def on_preview_ready(self, photo_id: str, display_size: int, image):
        """Swap in a worker-decoded preview if it still matches the view."""
        if display_size != self._current_display_size:
            return
        if not any(photo.id == photo_id for photo in self._current_photos):
            return
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        self._preview_pixmaps[photo_id] = pixmap
        self._preview_pixmap_size = display_size
        widget = self._thumb_widgets.get(photo_id)
        if widget:
            widget.set_pixmap(pixmap, display_size)

    def _show_hover_preview(self, photo_id: str, cursor_pos: QPoint):
        """Show full-size preview on hover."""
        photo = next((p for p in self._current_photos if p.id == photo_id), None)
        if not photo:
            return

        # Decode downscaled to the overlay size — loading a full 12–48MP
        # original mid-mouse-move would freeze the grid.
        pixmap = load_bounded_pixmap(photo.filepath, HOVER_PREVIEW_MAX)
        if pixmap.isNull():
            return

        if not hasattr(self, '_hover_preview'):
            self._hover_preview = HoverPreviewWidget(self)

        self._hover_preview.show_preview(pixmap, cursor_pos)

    def _hide_hover_preview(self):
        """Hide hover preview."""
        if hasattr(self, '_hover_preview'):
            self._hover_preview.hide_preview()

    # ── Data loading ─────────────────────────────────────

    def load_data(
        self,
        clusters: list[Cluster],
        cluster_photos: dict[str, list[Photo]],
        has_undo: bool = False,
        events: list[Event] | None = None,
    ):
        self._all_clusters = clusters
        self._cluster_photos = cluster_photos
        self._preview_pixmaps.clear()
        self._undo_btn.setEnabled(has_undo)
        # Fresh data => start the verdict-undo history from this state.
        self._reset_verdict_history()

        # Build event data
        self._events = events or []
        self._event_photos.clear()
        for photos in cluster_photos.values():
            for p in photos:
                if p.event_id:
                    if p.event_id not in self._event_photos:
                        self._event_photos[p.event_id] = set()
                    self._event_photos[p.event_id].add(p.id)

        # Populate event filter
        self._event_filter.blockSignals(True)
        self._event_filter.clear()
        self._event_filter.addItem(EVENT_FILTER_ALL)
        for event in self._events:
            count_text = f" ({event.photo_count})" if event.photo_count else ""
            self._event_filter.addItem(f"{event.label}{count_text}", event.id)
        self._event_filter.blockSignals(False)

        # Reset face filter
        self._face_filter.blockSignals(True)
        self._face_filter.setCurrentIndex(0)
        self._face_filter.blockSignals(False)

        # Reset quality filter
        self._quality_filter.blockSignals(True)
        self._quality_filter.setCurrentIndex(0)
        self._quality_filter.blockSignals(False)

        self._apply_filters()

    @Slot(str, str)
    def on_thumb_ready(self, photo_id: str, thumb_path: str):
        widget = self._thumb_widgets.get(photo_id)
        if not widget or not os.path.isfile(thumb_path):
            return
        # Don't let a late 200px thumbnail overwrite a high-res preview the
        # user already zoomed into.
        if widget._display_size > THUMB_CACHE_SIZE:
            return
        pixmap = QPixmap(thumb_path)
        if not pixmap.isNull():
            widget.set_pixmap(pixmap)

    # ── Filtering ────────────────────────────────────────

    def _low_quality_photo_ids(self) -> set[str]:
        """Every photo flagged as low quality, across all groups — so the
        'Low Quality' filter gathers the whole junk pile (standalone shots
        AND members of all-junk similar/duplicate groups) for a quick sweep."""
        ids: set[str] = set()
        for members in self._cluster_photos.values():
            for p in members:
                if is_low_quality(p):
                    ids.add(p.id)
        return ids

    def current_zoom(self) -> int:
        """Current thumbnail zoom (for persistence, UX-13)."""
        return self._zoom_slider.value()

    def set_zoom(self, value: int) -> None:
        self._zoom_slider.setValue(int(value))

    def set_hide_singletons(self, on: bool) -> None:
        self._hide_singletons.setChecked(bool(on))

    def hide_singletons_enabled(self) -> bool:
        return self._hide_singletons.isChecked()

    def get_view_state(self) -> dict:
        """Snapshot the filters and selected group so a reload (e.g. after
        Apply) can put the user back where they were (UX-10)."""
        current_id = None
        if 0 <= self._current_cluster_idx < len(self._clusters):
            current_id = self._clusters[self._current_cluster_idx].id
        return {
            "face": self._face_filter.currentText(),
            "quality": self._quality_filter.currentText(),
            "event_idx": self._event_filter.currentIndex(),
            "hide_singletons": self._hide_singletons.isChecked(),
            "search": self._search_box.text(),
            "sort": self._sort_combo.currentText(),
            "cluster_id": current_id,
        }

    def apply_view_state(self, state: dict):
        """Restore a snapshot from get_view_state()."""
        if not state:
            return
        for widget, setter, value in (
            (self._face_filter, self._face_filter.setCurrentText, state.get("face")),
            (self._quality_filter, self._quality_filter.setCurrentText, state.get("quality")),
            (self._hide_singletons, self._hide_singletons.setChecked, state.get("hide_singletons")),
        ):
            widget.blockSignals(True)
            if value is not None:
                setter(value)
            widget.blockSignals(False)
        self._event_filter.blockSignals(True)
        idx = state.get("event_idx", 0)
        if idx is not None and 0 <= idx < self._event_filter.count():
            self._event_filter.setCurrentIndex(idx)
        self._event_filter.blockSignals(False)

        self._search_box.blockSignals(True)
        self._search_box.setText(state.get("search", "") or "")
        self._search_box.blockSignals(False)
        self._sort_combo.blockSignals(True)
        sort_val = state.get("sort")
        if sort_val:
            self._sort_combo.setCurrentText(sort_val)
        self._sort_combo.blockSignals(False)

        self._apply_filters()

        cid = state.get("cluster_id")
        if cid is not None:
            for row, c in enumerate(self._clusters):
                if c.id == cid:
                    self._cluster_list.setCurrentRow(row)
                    break

    def _is_hideable_singleton(self, cluster) -> bool:
        """A one-photo group whose only photo is set to Keep — there's
        nothing to decide, so it's safe to hide from the review list."""
        if cluster.member_count != 1:
            return False
        members = self._cluster_photos.get(cluster.id, [])
        return len(members) == 1 and members[0].verdict == Verdict.KEEP

    def _apply_filters(self):
        face_filter = self._face_filter.currentText()
        quality_filter = self._quality_filter.currentText()
        event_idx = self._event_filter.currentIndex()
        event_id = self._event_filter.currentData() if event_idx > 0 else None

        # Determine which photo IDs pass the filters
        passing_photo_ids: set[str] | None = None

        # Event filter
        if event_id:
            passing_photo_ids = self._event_photos.get(event_id, set()).copy()

        # Quality filter (every low-quality photo, across all groups)
        if quality_filter == QUALITY_FILTER_LOW:
            low_ids = self._low_quality_photo_ids()
            passing_photo_ids = (
                low_ids if passing_photo_ids is None
                else passing_photo_ids & low_ids
            )

        # Face filter
        if face_filter != FACE_FILTER_ALL:
            face_ids: set[str] = set()
            for photos in self._cluster_photos.values():
                for p in photos:
                    if face_filter == FACE_FILTER_CLOSE and p.face_distance == FaceDistance.CLOSE:
                        face_ids.add(p.id)
                    elif face_filter == FACE_FILTER_FAR and p.face_distance == FaceDistance.FAR:
                        face_ids.add(p.id)
                    elif face_filter == FACE_FILTER_ANY_FACES and p.face_count > 0:
                        face_ids.add(p.id)
                    elif face_filter == FACE_FILTER_NO_FACES and p.face_count == 0:
                        face_ids.add(p.id)
                    elif face_filter == FACE_FILTER_GROUP and p.face_count >= 3:
                        face_ids.add(p.id)

            if passing_photo_ids is not None:
                passing_photo_ids &= face_ids
            else:
                passing_photo_ids = face_ids

        # Filename search (FEAT-05).
        query = self._search_box.text().strip().lower()
        if query:
            search_ids = {
                p.id for photos in self._cluster_photos.values() for p in photos
                if query in p.filename.lower()
            }
            passing_photo_ids = (
                search_ids if passing_photo_ids is None
                else passing_photo_ids & search_ids
            )

        # Filter clusters: show clusters that have at least one passing photo
        if passing_photo_ids is not None:
            self._clusters = []
            for c in self._all_clusters:
                members = self._cluster_photos.get(c.id, [])
                if any(p.id in passing_photo_ids for p in members):
                    self._clusters.append(c)
        else:
            self._clusters = list(self._all_clusters)

        # Hide single auto-keep photos (nothing to decide) unless asked to show
        # them. (UX-08)
        hidden_singletons = 0
        if self._hide_singletons.isChecked():
            kept = [c for c in self._clusters if not self._is_hideable_singleton(c)]
            hidden_singletons = len(self._clusters) - len(kept)
            self._clusters = kept

        # Update filter status
        total_photos = sum(len(self._cluster_photos.get(c.id, [])) for c in self._all_clusters)
        hidden_note = (
            f" · {hidden_singletons} single photo(s) hidden"
            if hidden_singletons else ""
        )
        if passing_photo_ids is not None:
            matching_photos = len(passing_photo_ids)
            self._filter_status.setText(
                f"Showing {len(self._clusters)} of {len(self._all_clusters)} groups "
                f"({matching_photos} of {total_photos} photos){hidden_note}"
            )
        else:
            self._filter_status.setText(
                f"{len(self._clusters)} groups, {total_photos} photos{hidden_note}"
            )

        # Rebuild cluster list
        self._cluster_list.blockSignals(True)
        self._cluster_list.clear()
        for c in self._clusters:
            self._cluster_list.addItem(QListWidgetItem(cluster_display_label(c)))
        self._cluster_list.blockSignals(False)

        self._update_global_counts()

        if self._clusters:
            self._cluster_list.setCurrentRow(0)
        else:
            # Clear grid
            self._clear_grid()
            self._cluster_pos_label.setText(self._empty_state_message())

    def _empty_state_message(self) -> str:
        """Explain *why* the grid is empty in plain language (UX-10)."""
        if not self._all_clusters:
            return ("Your library is already clean — no duplicates or "
                    "groups to review.")
        filters_active = (
            self._face_filter.currentText() != FACE_FILTER_ALL
            or self._quality_filter.currentText() != QUALITY_FILTER_ALL
            or self._event_filter.currentIndex() > 0
        )
        if filters_active:
            return "No groups match the current filters — adjust the filters above."
        # No filters active: everything left was a hidden single auto-keep.
        return ("Your library is already clean — every photo is a keeper "
                "with no duplicates. Untick “Hide single photos” to see them.")

    def _clear_grid(self):
        self._thumb_widgets.clear()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Cluster selection ────────────────────────────────

    @Slot(int)
    def _on_cluster_selected(self, row: int):
        if row < 0 or row >= len(self._clusters):
            return
        self._current_cluster_idx = row
        cluster = self._clusters[row]
        photos = self._cluster_photos.get(cluster.id, [])
        self._show_cluster_photos(cluster, photos)
        self._cluster_pos_label.setText(
            f"Cluster {row + 1} of {len(self._clusters)} "
            f"({cluster.member_count} photos)"
        )

    def _show_cluster_photos(self, cluster: Cluster, photos: list[Photo]):
        ordered = sort_photos(photos, self._sort_combo.currentText())
        if ordered is not self._current_photos:
            self._preview_pixmaps.clear()
        self._current_photos = ordered
        self._rebuild_grid_with_zoom()

        if ordered:
            self._select_photo(ordered[0].id)

    def _on_sort_changed(self):
        """Re-render the current group in the newly chosen order (FEAT-05)."""
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            photos = self._cluster_photos.get(cluster.id, [])
            self._show_cluster_photos(cluster, photos)

    # ── Photo selection ──────────────────────────────────

    @Slot(str)
    def _on_photo_clicked(self, photo_id: str):
        # Ctrl+click toggles one; Shift+click extends a range; plain click
        # selects just one (FEAT-03).
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ControlModifier:
            self._toggle_selection(photo_id)
        elif mods & Qt.ShiftModifier and self._selected_photo_id:
            self._range_selection(photo_id)
        else:
            self._select_photo(photo_id)

    def _select_photo(self, photo_id: str):
        """Single-select: replaces the whole selection with one photo."""
        self._selected_photo_id = photo_id
        self._selected_ids = {photo_id} if photo_id in self._thumb_widgets else set()
        self._apply_selection_visuals()

    def _toggle_selection(self, photo_id: str):
        if photo_id in self._selected_ids:
            self._selected_ids.discard(photo_id)
            if self._selected_photo_id == photo_id:
                self._selected_photo_id = next(iter(self._selected_ids), None)
        else:
            self._selected_ids.add(photo_id)
            self._selected_photo_id = photo_id
        self._apply_selection_visuals()

    def _range_selection(self, photo_id: str):
        ids = [p.id for p in self._get_current_photos()]
        if self._selected_photo_id not in ids or photo_id not in ids:
            self._select_photo(photo_id)
            return
        lo, hi = sorted((ids.index(self._selected_photo_id), ids.index(photo_id)))
        self._selected_ids.update(ids[lo:hi + 1])
        self._apply_selection_visuals()

    def _apply_selection_visuals(self):
        for pid, widget in self._thumb_widgets.items():
            widget.set_selected(pid in self._selected_ids)

    def _get_current_photos(self) -> list[Photo]:
        # The displayed (sorted) order, so keyboard navigation matches the grid.
        return self._current_photos

    def _selected_photo_index(self) -> int:
        photos = self._get_current_photos()
        for i, p in enumerate(photos):
            if p.id == self._selected_photo_id:
                return i
        return -1

    # ── Verdict-level undo (Ctrl+Z) ──────────────────────

    def _all_photos(self) -> list[Photo]:
        photos = []
        for group in self._cluster_photos.values():
            photos.extend(group)
        return photos

    def _reset_verdict_history(self):
        self._verdict_shadow = {
            p.id: (p.verdict, p.user_override) for p in self._all_photos()
        }
        self._verdict_undo_stack.clear()

    def _checkpoint_verdicts(self):
        """Record any verdict changes since the last checkpoint as one undo
        step. Captures single, button and bulk changes uniformly by diffing
        current photo state against the shadow."""
        changed = []
        for p in self._all_photos():
            old = self._verdict_shadow.get(p.id)
            cur = (p.verdict, p.user_override)
            if old is None:
                self._verdict_shadow[p.id] = cur
            elif old != cur:
                changed.append((p.id, old[0], old[1]))
                self._verdict_shadow[p.id] = cur
        if changed:
            self._verdict_undo_stack.append(changed)

    def _undo_verdict(self):
        """Undo the most recent verdict change(s) — the user's last decision."""
        if not self._verdict_undo_stack:
            return
        entry = self._verdict_undo_stack.pop()
        by_id = {p.id: p for p in self._all_photos()}
        for photo_id, verdict, override in entry:
            p = by_id.get(photo_id)
            if p is None:
                continue
            p.verdict = verdict
            p.user_override = override
            self._verdict_shadow[photo_id] = (verdict, override)
            widget = self._thumb_widgets.get(photo_id)
            if widget:
                widget.update_verdict(verdict)
        self._update_global_counts()
        self._update_cluster_list_item()
        # Persist the reverted state; shadow already matches, so this emit
        # will not record a new undo step.
        self.review_state_changed.emit()

    # ── Verdict actions ──────────────────────────────────

    @Slot(str, str)
    def _on_thumb_verdict_changed(self, photo_id: str, verdict_value: str):
        """Handle verdict change from individual thumbnail buttons."""
        for photo in self._current_photos:
            if photo.id == photo_id:
                photo.user_override = True
                break
        self._update_global_counts()
        self._update_cluster_list_item()
        self.review_state_changed.emit()

    def _set_selected_verdict(self, verdict: Verdict):
        # Apply to every selected photo (FEAT-03), or the anchor as a fallback.
        target_ids = self._selected_ids or (
            {self._selected_photo_id} if self._selected_photo_id else set())
        applied = False
        for pid in target_ids:
            widget = self._thumb_widgets.get(pid)
            if widget:
                widget.photo.user_override = True
                widget.update_verdict(verdict)
                applied = True
        if applied:
            self._update_global_counts()
            self._update_cluster_list_item()
            self.review_state_changed.emit()

    def _mark_keep(self):
        self._set_selected_verdict(Verdict.KEEP)

    def _mark_archive(self):
        self._set_selected_verdict(Verdict.ARCHIVE)

    def _mark_delete(self):
        self._set_selected_verdict(Verdict.DELETE)

    def _mark_review(self):
        self._set_selected_verdict(Verdict.REVIEW)

    def _keep_all(self):
        """Mark all photos in the current cluster as KEEP."""
        self._set_all_verdict(Verdict.KEEP)

    def _archive_all(self):
        """Mark all photos in the current cluster as ARCHIVE."""
        self._set_all_verdict(Verdict.ARCHIVE)

    def _delete_all(self):
        """Mark all photos in the current cluster as DELETE."""
        self._set_all_verdict(Verdict.DELETE)

    def _set_all_verdict(self, verdict: Verdict):
        photos = self._get_current_photos()
        for p in photos:
            p.verdict = verdict
            p.user_override = True
            widget = self._thumb_widgets.get(p.id)
            if widget:
                widget.update_verdict(verdict)
        self._update_global_counts()
        self._update_cluster_list_item()
        self.review_state_changed.emit()

    def _keep_top_n(self, n: int):
        photos = self._get_current_photos()
        ranked = sorted(photos, key=lambda p: (-p.quality_score, p.filepath))
        for i, p in enumerate(ranked):
            verdict = Verdict.KEEP if i < n else Verdict.DELETE
            p.verdict = verdict
            p.user_override = True
            widget = self._thumb_widgets.get(p.id)
            if widget:
                widget.update_verdict(verdict)
        self._update_global_counts()
        self._update_cluster_list_item()
        self.review_state_changed.emit()

    def _delete_rest(self):
        photos = self._get_current_photos()
        for p in photos:
            if p.verdict != Verdict.KEEP:
                p.verdict = Verdict.DELETE
                p.user_override = True
                widget = self._thumb_widgets.get(p.id)
                if widget:
                    widget.update_verdict(Verdict.DELETE)
        self._update_global_counts()
        self._update_cluster_list_item()
        self.review_state_changed.emit()

    def _mark_reviewed(self):
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            cluster.reviewed = True
            self._update_cluster_list_item()
            self.review_state_changed.emit()
            self._next_cluster()

    def _apply_cluster(self):
        """Apply changes for the current cluster only."""
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            self.apply_cluster_requested.emit(cluster.id)

    def mark_cluster_applied(self, cluster_id: str):
        """Mark a cluster as applied and navigate to next cluster."""
        for cluster in self._all_clusters:
            if cluster.id == cluster_id:
                cluster.applied = True
                break
        self._update_cluster_list_item()
        self._next_cluster()

    # ── Navigation ───────────────────────────────────────

    def _next_cluster(self):
        if self._current_cluster_idx < len(self._clusters) - 1:
            self._cluster_list.setCurrentRow(self._current_cluster_idx + 1)

    def _prev_cluster(self):
        if self._current_cluster_idx > 0:
            self._cluster_list.setCurrentRow(self._current_cluster_idx - 1)

    def _select_next_photo(self):
        idx = self._selected_photo_index()
        photos = self._get_current_photos()
        if idx < len(photos) - 1:
            self._select_photo(photos[idx + 1].id)

    def _select_prev_photo(self):
        idx = self._selected_photo_index()
        photos = self._get_current_photos()
        if idx > 0:
            self._select_photo(photos[idx - 1].id)

    def _select_photo_below(self):
        self._move_selection_by_rows(1)

    def _select_photo_above(self):
        self._move_selection_by_rows(-1)

    def _move_selection_by_rows(self, direction: int):
        """Move the grid selection up/down by one full row (UX-12)."""
        photos = self._get_current_photos()
        if not photos:
            return
        idx = self._selected_photo_index()
        cols = self._get_grid_columns()
        target = idx + direction * cols
        target = max(0, min(target, len(photos) - 1))
        if target != idx:
            self._select_photo(photos[target].id)

    # ── Status updates ───────────────────────────────────

    def _update_global_counts(self):
        keep = archive = delete = review = 0
        for photos in self._cluster_photos.values():
            for p in photos:
                if p.verdict == Verdict.KEEP:
                    keep += 1
                elif p.verdict == Verdict.ARCHIVE:
                    archive += 1
                elif p.verdict == Verdict.DELETE:
                    delete += 1
                else:
                    review += 1
        self._keep_label.setText(f"{keep} KEEP")
        self._archive_label.setText(f"{archive} ARCHIVE")
        self._delete_label.setText(f"{delete} DELETE")
        self._review_label.setText(f"{review} REVIEW")
        self._update_review_progress()

    def _update_review_progress(self):
        """Overall 'N of M groups reviewed' indicator (FEAT-05)."""
        total = len(self._all_clusters)
        reviewed = sum(1 for c in self._all_clusters if getattr(c, "reviewed", False))
        self._progress_label.setText(
            f"{reviewed} of {total} groups reviewed" if total else "")

    def _update_cluster_list_item(self):
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            photos = self._cluster_photos.get(cluster.id, [])
            keep = sum(1 for p in photos if p.verdict == Verdict.KEEP)
            delete = sum(1 for p in photos if p.verdict == Verdict.DELETE)
            cluster.keep_count = keep
            cluster.delete_count = delete

            item = self._cluster_list.item(self._current_cluster_idx)
            if item:
                item.setText(cluster_display_label(cluster))

    def get_all_photos(self) -> list[Photo]:
        """Return all photos across all clusters for persistence."""
        result = []
        for photos in self._cluster_photos.values():
            result.extend(photos)
        return result

    def get_all_clusters(self) -> list[Cluster]:
        """Return review-state clusters for persistence."""
        return list(self._all_clusters)
