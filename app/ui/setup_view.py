"""Setup/Home view — folder selection and scan trigger."""
import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QSpacerItem, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt, QThread

from app.util.paths import has_existing_session, SUPPORTED_EXTENSIONS, SKIP_DIRS


class _FolderCountWorker(QThread):
    """Walks a folder tree off the UI thread so picking a huge or network
    folder never freezes the Browse click. Emits the running total as it
    goes, and reports partial results if cancelled."""

    progress = Signal(int)   # count so far
    counted = Signal(int)    # final count (only if not cancelled)

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        count = 0
        for dirpath, dirnames, filenames in os.walk(self._folder):
            if self._cancelled:
                return
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in filenames:
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS:
                    count += 1
            self.progress.emit(count)
        if not self._cancelled:
            self.counted.emit(count)


class SetupView(QWidget):
    scan_requested = Signal(str)       # source folder path
    resume_requested = Signal(str)     # source folder path
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder_path = ""
        self._build_ui()
        self.setAcceptDrops(True)

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

        author = QLabel("Created by Nitin Vishwakarma (vishwakarma.nitin@gmail.com)")
        author.setStyleSheet("font-size: 11px; color: #999; font-style: italic;")
        author.setAlignment(Qt.AlignCenter)
        layout.addWidget(author)

        layout.addSpacing(30)

        # Folder picker row
        row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            "Select, type, or drag a folder containing photos...")
        self._path_edit.setMinimumWidth(400)
        self._path_edit.editingFinished.connect(self._on_path_typed)
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

        layout.addSpacing(28)

        # First-run guidance — what the app does and what it will create.
        how = QLabel(
            "<b>How it works</b><br>"
            "1. <b>Scan</b> — PhotoBrain groups near-duplicate shots and rates each one.<br>"
            "2. <b>Review</b> — you decide what to keep, archive, or delete.<br>"
            "3. <b>Apply</b> — kept photos are <i>moved</i> into a <code>03_KEEP</code> "
            "folder, archived ones into archive folders, and deletes go to the "
            "Recycle Bin.<br>"
            "<span style='color:#999;'>A small <code>.photobrain</code> folder is created "
            "inside your photo folder to remember progress. Your originals are never "
            "changed until you press Apply.</span>"
        )
        how.setWordWrap(True)
        how.setAlignment(Qt.AlignLeft)
        how.setMaximumWidth(460)
        how.setStyleSheet(
            "font-size: 12px; color: #666; background: #f5f5f5; "
            "border: 1px solid #e0e0e0; border-radius: 6px; padding: 12px 16px;"
        )
        layout.addWidget(how, alignment=Qt.AlignCenter)

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
        self._set_folder(folder)

    def _on_path_typed(self):
        """Accept a folder the user typed or pasted into the path box."""
        text = self._path_edit.text().strip().strip('"')
        if text and text != self._folder_path:
            self._set_folder(text)

    def _set_folder(self, folder: str):
        """Single entry point for choosing a folder — from Browse, typing,
        or drag-and-drop. Validates, then counts off the UI thread."""
        folder = os.path.normpath(folder)
        self._path_edit.setText(folder)
        if not os.path.isdir(folder):
            self._folder_path = ""
            self._stop_count()
            self._count_label.setText("That folder doesn't exist.")
            self._scan_btn.setEnabled(False)
            self._resume_btn.setVisible(False)
            return

        self._folder_path = folder
        # Check for existing session (cheap, stays on the UI thread)
        self._resume_btn.setVisible(has_existing_session(folder))
        # Count files off the UI thread so a huge/network folder can't freeze
        # the app mid-click. Show immediate feedback while it runs.
        self._start_count(folder)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(u.isLocalFile() for u in mime.urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            if folder:
                self._set_folder(folder)
                event.acceptProposedAction()
                return

    def _start_count(self, folder: str):
        self._stop_count()
        self._count_label.setText("Counting image files…")
        self._scan_btn.setEnabled(False)
        worker = _FolderCountWorker(folder, self)
        worker.progress.connect(self._on_count_progress)
        worker.counted.connect(self._on_count_done)
        self._count_worker = worker
        worker.start()

    def _stop_count(self):
        worker = getattr(self, "_count_worker", None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(2000)
        self._count_worker = None

    def _on_count_progress(self, count: int):
        self._count_label.setText(f"Counting… {count} so far")

    def _on_count_done(self, count: int):
        self._count_label.setText(f"{count} supported image files found")
        self._scan_btn.setEnabled(count > 0)

    def selected_folder(self) -> str:
        """The folder currently chosen on the home screen (may be empty)."""
        return self._folder_path

    def _on_scan(self):
        self._stop_count()
        if self._folder_path:
            self.scan_requested.emit(self._folder_path)

    def _on_resume(self):
        if self._folder_path:
            self.resume_requested.emit(self._folder_path)
