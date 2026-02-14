"""Scan progress view — shows live progress during scanning."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QLabel,
    QProgressBar, QPushButton, QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QTimer, Slot


class ScanView(QWidget):
    cancel_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._elapsed_seconds = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # Title
        title = QLabel("Scanning...")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Phase label
        self._phase_label = QLabel("Preparing...")
        self._phase_label.setStyleSheet("font-size: 14px; color: #555;")
        self._phase_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._phase_label)

        layout.addSpacing(10)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setMinimumWidth(400)
        self._progress.setMaximumWidth(600)
        layout.addWidget(self._progress, alignment=Qt.AlignCenter)

        # Current file
        self._file_label = QLabel("")
        self._file_label.setStyleSheet("font-size: 11px; color: #888;")
        self._file_label.setAlignment(Qt.AlignCenter)
        self._file_label.setMaximumWidth(500)
        layout.addWidget(self._file_label, alignment=Qt.AlignCenter)

        layout.addSpacing(15)

        # Stats grid
        stats = QGridLayout()
        stats.setHorizontalSpacing(20)
        stats.setVerticalSpacing(6)

        self._stat_labels: dict[str, QLabel] = {}
        stat_items = [
            ("total_files", "Files found:"),
            ("hashed", "Hashed:"),
            ("duplicates", "Exact duplicates:"),
            ("phash_computed", "Perceptual hashes:"),
            ("scored", "Scored:"),
            ("faces_detected", "Photos with faces:"),
            ("events", "Events:"),
            ("clusters", "Clusters:"),
        ]
        for row, (key, text) in enumerate(stat_items):
            label = QLabel(text)
            label.setStyleSheet("font-size: 13px;")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            stats.addWidget(label, row, 0)

            value = QLabel("0")
            value.setStyleSheet("font-size: 13px; font-weight: bold;")
            value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            stats.addWidget(value, row, 1)
            self._stat_labels[key] = value

        stats_widget = QWidget()
        stats_widget.setLayout(stats)
        layout.addWidget(stats_widget, alignment=Qt.AlignCenter)

        layout.addSpacing(15)

        # Elapsed time
        self._elapsed_label = QLabel("Elapsed: 00:00")
        self._elapsed_label.setStyleSheet("font-size: 12px; color: #888;")
        self._elapsed_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._elapsed_label)

        layout.addSpacing(15)

        # Cancel button
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setMinimumWidth(120)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self._cancel_btn, alignment=Qt.AlignCenter)

        # Continue to Review button (hidden during scan)
        self._continue_btn = QPushButton("Continue to Review →")
        self._continue_btn.setMinimumWidth(180)
        self._continue_btn.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 8px 16px;"
        )
        self._continue_btn.clicked.connect(self.continue_requested.emit)
        self._continue_btn.setVisible(False)
        layout.addWidget(self._continue_btn, alignment=Qt.AlignCenter)

        layout.addSpacerItem(
            QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

    def start_timer(self):
        self._elapsed_seconds = 0
        self._timer.start(1000)

    def stop_timer(self):
        self._timer.stop()

    def reset(self):
        self._progress.setValue(0)
        self._phase_label.setText("Preparing...")
        self._file_label.setText("")
        self._elapsed_seconds = 0
        self._elapsed_label.setText("Elapsed: 00:00")
        for lbl in self._stat_labels.values():
            lbl.setText("0")
        self._cancel_btn.setVisible(True)
        self._continue_btn.setVisible(False)

    def show_completed(self):
        """Switch UI to completed state with summary visible."""
        self._phase_label.setText("Scan Complete!")
        self._phase_label.setStyleSheet("font-size: 14px; color: #4CAF50; font-weight: bold;")
        self._progress.setValue(100)
        self._file_label.setText("")
        self._cancel_btn.setVisible(False)
        self._continue_btn.setVisible(True)

    @Slot(str, int, int)
    def update_progress(self, phase: str, current: int, total: int):
        if total > 0:
            self._progress.setValue(int(current / total * 100))

    @Slot(str)
    def update_current_file(self, filename: str):
        elided = filename if len(filename) < 60 else "..." + filename[-57:]
        self._file_label.setText(f"Processing: {elided}")

    @Slot(str, int)
    def update_stats(self, stat_name: str, value: int):
        if stat_name in self._stat_labels:
            self._stat_labels[stat_name].setText(str(value))

    @Slot(str)
    def update_phase(self, phase: str):
        self._phase_label.setText(phase)

    def _tick(self):
        self._elapsed_seconds += 1
        m, s = divmod(self._elapsed_seconds, 60)
        self._elapsed_label.setText(f"Elapsed: {m:02d}:{s:02d}")
