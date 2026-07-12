"""Dialogs for settings, apply confirmation, and undo results."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
    QDoubleSpinBox, QCheckBox, QDialogButtonBox, QFormLayout, QGroupBox,
    QMessageBox,
)
from PySide6.QtCore import Qt


def _format_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


class SettingsDialog(QDialog):
    def __init__(
        self,
        threshold: int = 17,
        keep_count: int = 2,
        event_gap_hours: float = 4.0,
        face_detection_enabled: bool = True,
        parent=None,
        source_folder: str = "",
    ):
        super().__init__(parent)
        self._source_folder = source_folder
        self.setWindowTitle("Settings")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Clustering group
        group = QGroupBox("Clustering")
        form = QFormLayout()

        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 30)
        self._threshold_spin.setValue(threshold)
        self._threshold_spin.setToolTip("Lower = stricter matching (fewer false positives)")
        form.addRow("pHash Threshold:", self._threshold_spin)

        hint = QLabel("Default: 17 (related shots from same location/session).\n"
                       "Lower = stricter. Higher = broader grouping. Range: 1-30")
        hint.setStyleSheet("font-size: 10px; color: #888;")
        form.addRow("", hint)

        self._keep_spin = QSpinBox()
        self._keep_spin.setRange(1, 10)
        self._keep_spin.setValue(keep_count)
        self._keep_spin.setToolTip("Number of best photos to suggest keeping per cluster")
        form.addRow("Keep per cluster:", self._keep_spin)

        group.setLayout(form)
        layout.addWidget(group)

        # Events group
        event_group = QGroupBox("Event Grouping")
        event_form = QFormLayout()

        self._event_gap_spin = QDoubleSpinBox()
        self._event_gap_spin.setRange(0.5, 48.0)
        self._event_gap_spin.setSingleStep(0.5)
        self._event_gap_spin.setDecimals(1)
        self._event_gap_spin.setValue(event_gap_hours)
        self._event_gap_spin.setSuffix(" hours")
        self._event_gap_spin.setToolTip(
            "Photos separated by more than this gap start a new event"
        )
        event_form.addRow("Event gap:", self._event_gap_spin)

        event_hint = QLabel("Smaller gaps create more events.\n"
                            "Larger gaps merge nearby shooting sessions.")
        event_hint.setStyleSheet("font-size: 10px; color: #888;")
        event_form.addRow("", event_hint)

        event_group.setLayout(event_form)
        layout.addWidget(event_group)

        # Detection group
        detect_group = QGroupBox("Detection")
        detect_form = QFormLayout()

        self._face_checkbox = QCheckBox("Enable face detection")
        self._face_checkbox.setChecked(face_detection_enabled)
        self._face_checkbox.setToolTip(
            "Detect faces in photos to boost quality scores and enable face filters"
        )
        detect_form.addRow(self._face_checkbox)

        detect_group.setLayout(detect_form)
        layout.addWidget(detect_group)

        # Storage group — thumbnail/preview cache management
        storage_group = QGroupBox("Storage")
        storage_layout = QVBoxLayout()
        self._cache_label = QLabel()
        self._cache_label.setStyleSheet("font-size: 11px; color: #666;")
        storage_layout.addWidget(self._cache_label)
        self._clear_cache_btn = QPushButton("Clear Cache")
        self._clear_cache_btn.setToolTip(
            "Delete cached thumbnails and previews for this folder. They "
            "rebuild automatically the next time you view photos. Your "
            "photos and review progress are not affected."
        )
        self._clear_cache_btn.clicked.connect(self._on_clear_cache)
        storage_layout.addWidget(self._clear_cache_btn)
        storage_group.setLayout(storage_layout)
        layout.addWidget(storage_group)
        self._refresh_cache_label()

        # Mode info
        mode_label = QLabel("Mode: Assisted (review all suggestions before apply)")
        mode_label.setStyleSheet("font-size: 11px; color: #666; margin-top: 8px;")
        layout.addWidget(mode_label)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_cache_label(self):
        if not self._source_folder:
            self._cache_label.setText("Cache: scan a folder first")
            self._clear_cache_btn.setEnabled(False)
            return
        from app.core.thumbnails import image_cache_bytes
        size = image_cache_bytes(self._source_folder)
        self._cache_label.setText(f"Thumbnail cache: {_format_bytes(size)}")
        self._clear_cache_btn.setEnabled(size > 0)

    def _on_clear_cache(self):
        from app.core.thumbnails import clear_image_caches
        freed = clear_image_caches(self._source_folder)
        self._refresh_cache_label()
        QMessageBox.information(
            self, "Cache Cleared",
            f"Freed {_format_bytes(freed)} of thumbnail cache.\n\n"
            "Thumbnails rebuild automatically the next time you view photos. "
            "Your photos and review progress were not affected.",
        )

    def threshold(self) -> int:
        return self._threshold_spin.value()

    def keep_count(self) -> int:
        return self._keep_spin.value()

    def event_gap_hours(self) -> float:
        return self._event_gap_spin.value()

    def face_detection_enabled(self) -> bool:
        return self._face_checkbox.isChecked()


class ApplyConfirmDialog(QDialog):
    def __init__(
        self, keep: int, archive: int, delete: int, review: int, parent=None,
        last_copy_delete_count: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle("Apply Changes")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        title = QLabel("Confirm file operations")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(10)

        if keep > 0:
            keep_label = QLabel(f"  {keep} files will be moved to 03_KEEP")
            keep_label.setStyleSheet("font-size: 13px; color: #4CAF50;")
            layout.addWidget(keep_label)

        if archive > 0:
            archive_label = QLabel(f"  {archive} files will be archived (safe, reversible)")
            archive_label.setStyleSheet("font-size: 13px; color: #FF9800;")
            layout.addWidget(archive_label)

        if delete > 0:
            delete_label = QLabel(
                f"  {delete} files will be sent to the Recycle Bin "
                "(not undoable in PhotoBrain)"
            )
            delete_label.setStyleSheet("font-size: 13px; color: #F44336; font-weight: bold;")
            layout.addWidget(delete_label)

        if review > 0:
            review_label = QLabel(f"  {review} files are still undecided (will be skipped)")
            review_label.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            layout.addWidget(review_label)

        layout.addSpacing(10)

        if last_copy_delete_count > 0:
            noun = "file" if last_copy_delete_count == 1 else "files"
            last_copy_warning = QLabel(
                f"Last-copy warning: {last_copy_delete_count} {noun} belong "
                "to photos whose every scanned byte-for-byte copy is marked "
                "DELETE. No scanned copy will remain outside the Recycle Bin."
            )
            last_copy_warning.setWordWrap(True)
            last_copy_warning.setStyleSheet(
                "font-size: 12px; color: #B71C1C; font-weight: bold; "
                "padding: 8px; background-color: #FFCDD2; "
                "border: 1px solid #EF5350; border-radius: 4px;"
            )
            layout.addWidget(last_copy_warning)
            layout.addSpacing(6)

        if delete > 0:
            warning = QLabel(
                "Warning: Deleted files will be sent to the Recycle Bin. "
                "Archived files are safely moved and can be undone from the app."
            )
            warning.setStyleSheet(
                "font-size: 12px; color: #F44336; padding: 8px; "
                "background-color: #FFEBEE; border-radius: 4px;"
            )
        else:
            warning = QLabel(
                "Files will be MOVED, not deleted. "
                "You can undo this operation."
            )
            warning.setStyleSheet(
                "font-size: 12px; color: #FF9800; padding: 8px; "
                "background-color: #FFF3E0; border-radius: 4px;"
            )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UndoResultDialog(QDialog):
    def __init__(self, restored: int, skipped: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Undo Complete")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        title = QLabel("Undo Results")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        layout.addSpacing(10)

        layout.addWidget(QLabel(f"  {restored} files restored to original locations"))

        if skipped > 0:
            skip_label = QLabel(
                f"  {skipped} files could not be restored (missing or conflicts)"
            )
            skip_label.setStyleSheet("color: #FF9800;")
            layout.addWidget(skip_label)

        layout.addSpacing(10)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
