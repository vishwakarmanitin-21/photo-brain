"""Review view — cluster list + thumbnail grid with keyboard shortcuts."""
import os
import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QScrollArea, QGridLayout, QLabel, QFrame,
    QPushButton, QSizePolicy, QComboBox, QApplication, QSlider,
)
from PySide6.QtCore import Signal, Qt, Slot, QSize, QUrl, QPoint
from PySide6.QtGui import QPixmap, QKeySequence, QColor, QShortcut, QDesktopServices, QCursor

from app.core.models import Photo, Cluster, Event, Verdict, DupType, FaceDistance

log = logging.getLogger("photobrain.review_view")

# Zoom configuration
MIN_THUMB_SIZE = 120  # Minimum thumbnail size
MAX_THUMB_SIZE = 800  # Maximum thumbnail size
BASE_THUMB_SIZE = 180  # Base display size (middle of range)
THUMB_DISPLAY_SIZE = 180  # Keep for backward compatibility

# Colors
COLOR_KEEP = "#4CAF50"
COLOR_ARCHIVE = "#FF9800"
COLOR_DELETE = "#F44336"
COLOR_REVIEW = "#9E9E9E"
COLOR_SELECTED = "#2196F3"

# Filter constants
FACE_FILTER_ALL = "All Photos"
FACE_FILTER_CLOSE = "Faces (Close-up)"
FACE_FILTER_FAR = "Faces (Distant)"
FACE_FILTER_ANY_FACES = "Has Any Faces"
FACE_FILTER_NO_FACES = "No Faces"
FACE_FILTER_GROUP = "Group Shots (3+)"

EVENT_FILTER_ALL = "All Events"


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

    def __init__(self, photo: Photo, parent=None):
        super().__init__(parent)
        self.photo = photo
        self._selected = False
        self._hover_active = False
        self._display_size = BASE_THUMB_SIZE
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
        self._image_label.setStyleSheet("background-color: #f0f0f0;")
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

        # Score + info row
        info_parts = [f"Score: {self.photo.quality_score:.1f}"]
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
            f"Score: {self.photo.quality_score:.2f}",
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
        self._keep_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.KEEP))
        btn_row.addWidget(self._keep_btn)

        self._archive_btn = QPushButton("Archive")
        self._archive_btn.setFixedHeight(22)
        self._archive_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9px; padding: 1px 6px; "
            f"background-color: {COLOR_ARCHIVE}; color: white; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #F57C00; }}"
        )
        self._archive_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.ARCHIVE))
        btn_row.addWidget(self._archive_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(22)
        self._delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 9px; padding: 1px 6px; "
            f"background-color: {COLOR_DELETE}; color: white; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: #d32f2f; }}"
        )
        self._delete_btn.clicked.connect(lambda: self._on_verdict_btn(Verdict.DELETE))
        btn_row.addWidget(self._delete_btn)

        layout.addLayout(btn_row)

        # Verdict label
        self._verdict_label = QLabel(self.photo.verdict.value)
        self._verdict_label.setAlignment(Qt.AlignCenter)
        self._verdict_label.setStyleSheet("font-size: 10px; font-weight: bold;")
        layout.addWidget(self._verdict_label)

    def _on_verdict_btn(self, verdict: Verdict):
        self.photo.user_override = True
        self.update_verdict(verdict)
        self.verdict_changed.emit(self.photo.id, verdict.value)

    def set_pixmap(self, pixmap: QPixmap, display_size: int = None):
        """Set pixmap scaled to display_size, adjusting for aspect ratio."""
        if display_size is None:
            display_size = self._display_size

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
        # Set maximum dimensions - actual size will be set when pixmap is loaded
        # This ensures the widget doesn't take up too much space initially
        self.setFixedSize(display_size + 16, display_size + 116)
        self._image_label.setFixedSize(display_size, display_size)

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
            f"border-radius: 4px; background-color: white; {outline} }}"
        )

        # Verdict label color
        self._verdict_label.setStyleSheet(
            f"font-size: 10px; font-weight: bold; color: {border_color};"
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_clusters: list[Cluster] = []
        self._clusters: list[Cluster] = []  # filtered view
        self._cluster_photos: dict[str, list[Photo]] = {}
        self._events: list[Event] = []
        self._event_photos: dict[str, set[str]] = {}  # event_id -> set of photo_ids
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._current_cluster_idx = -1
        self._selected_photo_id: str | None = None
        self._current_photos: list[Photo] = []  # Current cluster photos
        self._current_display_size = BASE_THUMB_SIZE  # Current thumbnail display size
        self._build_ui()
        self._bind_shortcuts()

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

        filter_bar.addWidget(QLabel("Event:"))
        self._event_filter = QComboBox()
        self._event_filter.addItem(EVENT_FILTER_ALL)
        self._event_filter.currentTextChanged.connect(self._apply_filters)
        self._event_filter.setMinimumWidth(200)
        filter_bar.addWidget(self._event_filter)

        filter_bar.addStretch()

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
        QShortcut(QKeySequence("K"), self, self._mark_keep)
        QShortcut(QKeySequence("A"), self, self._mark_archive)
        QShortcut(QKeySequence("D"), self, self._mark_delete)
        QShortcut(QKeySequence("R"), self, self._mark_review)
        QShortcut(QKeySequence("J"), self, self._next_cluster)
        QShortcut(QKeySequence(Qt.Key_Down), self, self._next_cluster)
        QShortcut(QKeySequence(Qt.Key_Up), self, self._prev_cluster)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._select_next_photo)
        QShortcut(QKeySequence(Qt.Key_Left), self, self._select_prev_photo)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.apply_requested.emit)
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo_requested.emit)
        # Zoom shortcuts
        QShortcut(QKeySequence("+"), self, self._zoom_in)
        QShortcut(QKeySequence("="), self, self._zoom_in)  # Also + without Shift
        QShortcut(QKeySequence("-"), self, self._zoom_out)
        QShortcut(QKeySequence("0"), self, lambda: self._zoom_slider.setValue(BASE_THUMB_SIZE))  # Reset

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

    def _load_high_res_pixmap(self, photo: Photo, display_size: int) -> QPixmap:
        """Load photo from original file, scaled to display_size with high quality."""
        from PIL import Image
        from io import BytesIO

        try:
            # Load original
            img = Image.open(photo.filepath)

            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize with high-quality Lanczos filter
            img.thumbnail((display_size, display_size), Image.Resampling.LANCZOS)

            # Convert PIL → QPixmap
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            buffer.seek(0)

            pixmap = QPixmap()
            pixmap.loadFromData(buffer.read())
            return pixmap

        except Exception as e:
            log.warning("Failed to load high-res for %s: %s", photo.filepath, e)
            # Fallback to cached thumbnail
            if photo.thumb_path and os.path.isfile(photo.thumb_path):
                return QPixmap(photo.thumb_path)
            return QPixmap()

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
        self._current_display_size = value
        self._zoom_slider.setToolTip(f"Thumbnail size: {value}px")

        # Rebuild grid with new size
        self._rebuild_grid_with_zoom()

        # Re-select current photo if any
        if self._selected_photo_id:
            widget = self._thumb_widgets.get(self._selected_photo_id)
            if widget:
                widget.set_selected(True)

    def _rebuild_grid_with_zoom(self):
        """Rebuild thumbnail grid with current zoom level."""
        # Clear existing grid
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        self._thumb_widgets.clear()

        if not self._current_photos:
            return

        display_size = self._get_display_size()
        grid_columns = self._get_grid_columns()

        for i, photo in enumerate(self._current_photos):
            widget = ThumbnailWidget(photo)
            widget.update_size(display_size)

            # Load high-res or cached thumbnail
            if display_size > 200:
                pixmap = self._load_high_res_pixmap(photo, display_size)
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

    def _show_hover_preview(self, photo_id: str, cursor_pos: QPoint):
        """Show full-size preview on hover."""
        photo = next((p for p in self._current_photos if p.id == photo_id), None)
        if not photo:
            return

        # Load full-size from original
        pixmap = QPixmap(photo.filepath)
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
        self._undo_btn.setEnabled(has_undo)

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

        self._apply_filters()

    @Slot(str, str)
    def on_thumb_ready(self, photo_id: str, thumb_path: str):
        widget = self._thumb_widgets.get(photo_id)
        if widget and os.path.isfile(thumb_path):
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                widget.set_pixmap(pixmap)

    # ── Filtering ────────────────────────────────────────

    def _apply_filters(self):
        face_filter = self._face_filter.currentText()
        event_idx = self._event_filter.currentIndex()
        event_id = self._event_filter.currentData() if event_idx > 0 else None

        # Determine which photo IDs pass the filters
        passing_photo_ids: set[str] | None = None

        # Event filter
        if event_id:
            passing_photo_ids = self._event_photos.get(event_id, set()).copy()

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

        # Filter clusters: show clusters that have at least one passing photo
        if passing_photo_ids is not None:
            self._clusters = []
            for c in self._all_clusters:
                members = self._cluster_photos.get(c.id, [])
                if any(p.id in passing_photo_ids for p in members):
                    self._clusters.append(c)
        else:
            self._clusters = list(self._all_clusters)

        # Update filter status
        total_photos = sum(len(self._cluster_photos.get(c.id, [])) for c in self._all_clusters)
        if passing_photo_ids is not None:
            matching_photos = len(passing_photo_ids)
            self._filter_status.setText(
                f"Showing {len(self._clusters)} of {len(self._all_clusters)} clusters "
                f"({matching_photos} of {total_photos} photos)"
            )
        else:
            self._filter_status.setText(
                f"{len(self._clusters)} clusters, {total_photos} photos"
            )

        # Rebuild cluster list
        self._cluster_list.blockSignals(True)
        self._cluster_list.clear()
        for c in self._clusters:
            flags = ""
            if c.is_exact_dup_group:
                flags = " [EXACT]"
            if c.reviewed:
                flags += " [OK]"
            if c.applied:
                flags += " [APPLIED]"
            text = f"{c.label} ({c.member_count}){flags}"
            self._cluster_list.addItem(QListWidgetItem(text))
        self._cluster_list.blockSignals(False)

        self._update_global_counts()

        if self._clusters:
            self._cluster_list.setCurrentRow(0)
        else:
            # Clear grid
            self._clear_grid()
            self._cluster_pos_label.setText("No clusters match filters")

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
        self._current_photos = photos
        self._rebuild_grid_with_zoom()

        if photos:
            self._select_photo(photos[0].id)

    # ── Photo selection ──────────────────────────────────

    @Slot(str)
    def _on_photo_clicked(self, photo_id: str):
        self._select_photo(photo_id)

    def _select_photo(self, photo_id: str):
        if self._selected_photo_id and self._selected_photo_id in self._thumb_widgets:
            self._thumb_widgets[self._selected_photo_id].set_selected(False)
        self._selected_photo_id = photo_id
        if photo_id in self._thumb_widgets:
            self._thumb_widgets[photo_id].set_selected(True)

    def _get_current_photos(self) -> list[Photo]:
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            return self._cluster_photos.get(cluster.id, [])
        return []

    def _selected_photo_index(self) -> int:
        photos = self._get_current_photos()
        for i, p in enumerate(photos):
            if p.id == self._selected_photo_id:
                return i
        return -1

    # ── Verdict actions ──────────────────────────────────

    @Slot(str, str)
    def _on_thumb_verdict_changed(self, photo_id: str, verdict_value: str):
        """Handle verdict change from individual thumbnail buttons."""
        self._update_global_counts()
        self._update_cluster_list_item()

    def _set_selected_verdict(self, verdict: Verdict):
        if not self._selected_photo_id:
            return
        widget = self._thumb_widgets.get(self._selected_photo_id)
        if widget:
            widget.photo.user_override = True
            widget.update_verdict(verdict)
            self._update_global_counts()
            self._update_cluster_list_item()

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

    def _mark_reviewed(self):
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            cluster.reviewed = True
            self._update_cluster_list_item()
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

    def _update_cluster_list_item(self):
        if 0 <= self._current_cluster_idx < len(self._clusters):
            cluster = self._clusters[self._current_cluster_idx]
            photos = self._cluster_photos.get(cluster.id, [])
            keep = sum(1 for p in photos if p.verdict == Verdict.KEEP)
            delete = sum(1 for p in photos if p.verdict == Verdict.DELETE)
            cluster.keep_count = keep
            cluster.delete_count = delete

            flags = ""
            if cluster.is_exact_dup_group:
                flags = " [EXACT]"
            if cluster.reviewed:
                flags += " [OK]"
            if cluster.applied:
                flags += " [APPLIED]"
            text = f"{cluster.label} ({cluster.member_count}){flags}"

            item = self._cluster_list.item(self._current_cluster_idx)
            if item:
                item.setText(text)

    def get_all_photos(self) -> list[Photo]:
        """Return all photos across all clusters for persistence."""
        result = []
        for photos in self._cluster_photos.values():
            result.extend(photos)
        return result
