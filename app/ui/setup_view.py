"""Setup/Home view — folder selection and scan trigger."""
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

from app.util.paths import has_existing_session, SUPPORTED_EXTENSIONS, SKIP_DIRS


class SetupView(QWidget):
    scan_requested = Signal(str)       # source folder path
    resume_requested = Signal(str)     # source folder path
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder_path = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        layout.addSpacerItem(
            QSpacerItem(20, 60, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # Title
        title = QLabel("PhotoBrain")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Clean and organize your photos")
        subtitle.setStyleSheet("font-size: 14px; color: #666;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        author = QLabel("Created by Nitin Vishwakarma")
        author.setStyleSheet("font-size: 11px; color: #999; font-style: italic;")
        author.setAlignment(Qt.AlignCenter)
        layout.addWidget(author)

        layout.addSpacing(30)

        # Folder picker row
        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("Select a folder containing photos...")
        self._path_edit.setMinimumWidth(400)
        row.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        # File count label
        self._count_label = QLabel("")
        self._count_label.setAlignment(Qt.AlignCenter)
        self._count_label.setStyleSheet("color: #888;")
        layout.addWidget(self._count_label)

        layout.addSpacing(20)

        # Start Scan button
        self._scan_btn = QPushButton("Start Scan")
        self._scan_btn.setEnabled(False)
        self._scan_btn.setMinimumHeight(40)
        self._scan_btn.setMinimumWidth(200)
        self._scan_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-size: 14px; "
            "border-radius: 4px; padding: 8px 24px; }"
            "QPushButton:disabled { background-color: #ccc; color: #888; }"
            "QPushButton:hover:!disabled { background-color: #45a049; }"
        )
        self._scan_btn.clicked.connect(self._on_scan)
        layout.addWidget(self._scan_btn, alignment=Qt.AlignCenter)

        # Resume button
        self._resume_btn = QPushButton("Resume Previous Session")
        self._resume_btn.setVisible(False)
        self._resume_btn.setMinimumHeight(36)
        self._resume_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 20px; }"
        )
        self._resume_btn.clicked.connect(self._on_resume)
        layout.addWidget(self._resume_btn, alignment=Qt.AlignCenter)

        layout.addSpacing(10)

        # Settings button
        settings_btn = QPushButton("Settings")
        settings_btn.setFlat(True)
        settings_btn.setStyleSheet("font-size: 12px; color: #555;")
        settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(settings_btn, alignment=Qt.AlignCenter)

        layout.addSpacerItem(
            QSpacerItem(20, 60, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

    def _on_browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Photo Folder", "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if not folder:
            return
        self._folder_path = folder
        self._path_edit.setText(folder)

        # Quick file count
        count = self._count_files(folder)
        self._count_label.setText(f"{count} supported image files found")
        self._scan_btn.setEnabled(count > 0)

        # Check for existing session
        self._resume_btn.setVisible(has_existing_session(folder))

    def _count_files(self, folder: str) -> int:
        count = 0
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                    count += 1
        return count

    def _on_scan(self):
        if self._folder_path:
            self.scan_requested.emit(self._folder_path)

    def _on_resume(self):
        if self._folder_path:
            self.resume_requested.emit(self._folder_path)
