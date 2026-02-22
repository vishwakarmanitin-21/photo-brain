"""Dialogs for settings, apply confirmation, and undo results."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QDoubleSpinBox, QCheckBox, QDialogButtonBox, QFormLayout, QGroupBox,
)
from PySide6.QtCore import Qt


class SettingsDialog(QDialog):
    def __init__(
        self,
        threshold: int = 12,
        keep_count: int = 2,
        event_gap_hours: float = 4.0,
        face_detection_enabled: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        # Clustering group
        group = QGroupBox("Clustering")
        form = QFormLayout()

        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 20)
        self._threshold_spin.setValue(threshold)
        self._threshold_spin.setToolTip("Lower = stricter matching (fewer false positives)")
        form.addRow("pHash Threshold:", self._threshold_spin)

        hint = QLabel("Default: 12 (similar shots from same scene).\n"
                       "Lower values = stricter matching. Higher = broader grouping.")
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

        # Mode info
        mode_label = QLabel("Mode: Assisted (review all suggestions before apply)")
        mode_label.setStyleSheet("font-size: 11px; color: #666; margin-top: 8px;")
        layout.addWidget(mode_label)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        self, keep: int, archive: int, delete: int, review: int, parent=None
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
                f"  {delete} files will be permanently deleted (sent to Recycle Bin)"
            )
            delete_label.setStyleSheet("font-size: 13px; color: #F44336; font-weight: bold;")
            layout.addWidget(delete_label)

        if review > 0:
            review_label = QLabel(f"  {review} files are still undecided (will be skipped)")
            review_label.setStyleSheet("font-size: 13px; color: #9E9E9E;")
            layout.addWidget(review_label)

        layout.addSpacing(10)

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
