"""Main window with stacked navigation: Setup -> Scan -> Review."""
import uuid
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout, QMessageBox, QDialog,
)
from PySide6.QtCore import Slot

from app.ui.setup_view import SetupView
from app.ui.scan_view import ScanView
from app.ui.review_view import ReviewView
from app.ui.dialogs import SettingsDialog, ApplyConfirmDialog, UndoResultDialog
from app.core.session_store import SessionStore
from app.core.models import SessionStatus, Verdict
from app.core.thumbnails import ThumbnailCache
from app.core.file_ops import FileOperator
from app.workers.scan_worker import ScanWorker
from app.workers.thumb_worker import ThumbWorker
from app.util.paths import get_db_path, get_thumb_dir, get_log_dir
from app.util.logging_util import setup_logging

log = logging.getLogger("photobrain.main_window")

VIEW_SETUP = 0
VIEW_SCAN = 1
VIEW_REVIEW = 2


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store: SessionStore | None = None
        self.session_id: str = ""
        self.source_folder: str = ""
        self.scan_worker: ScanWorker | None = None
        self.thumb_worker: ThumbWorker | None = None
        self.thumb_cache: ThumbnailCache | None = None

        # Settings defaults
        self._phash_threshold = 8
        self._keep_per_cluster = 2
        self._event_gap_hours = 4.0
        self._face_detection_enabled = True

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.setup_view = SetupView()
        self.scan_view = ScanView()
        self.review_view = ReviewView()

        self.stack.addWidget(self.setup_view)   # 0
        self.stack.addWidget(self.scan_view)    # 1
        self.stack.addWidget(self.review_view)  # 2

        layout.addWidget(self.stack)

    def _connect_signals(self):
        self.setup_view.scan_requested.connect(self._start_scan)
        self.setup_view.resume_requested.connect(self._resume_session)
        self.setup_view.settings_requested.connect(self._show_settings)
        self.scan_view.cancel_requested.connect(self._cancel_scan)
        self.scan_view.continue_requested.connect(self._on_continue_to_review)
        self.review_view.apply_requested.connect(self._on_apply)
        self.review_view.undo_requested.connect(self._on_undo)
        self.review_view.back_requested.connect(self._go_home)

    # ── Navigation ───────────────────────────────────────

    def _navigate(self, index: int):
        self.stack.setCurrentIndex(index)

    def _go_home(self):
        self._navigate(VIEW_SETUP)

    # ── Scan ─────────────────────────────────────────────

    @Slot(str)
    def _start_scan(self, folder: str):
        self.source_folder = folder
        setup_logging(get_log_dir(folder))

        # Open/create session store
        db_path = get_db_path(folder)
        if self.store:
            self.store.close()
        self.store = SessionStore(db_path)

        # Check for existing session and clear it
        existing = self.store.get_session()
        if existing:
            self.store.delete_session_data(existing.id)

        self.session_id = uuid.uuid4().hex[:12]
        self.store.create_session(
            self.session_id, folder,
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
        )

        self.thumb_cache = ThumbnailCache(get_thumb_dir(folder))

        # Switch to scan view and start
        self.scan_view.reset()
        self._navigate(VIEW_SCAN)
        self.scan_view.start_timer()

        self.scan_worker = ScanWorker(
            folder, self.store, self.session_id,
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
        )
        self.scan_worker.progress_updated.connect(self.scan_view.update_progress)
        self.scan_worker.current_file.connect(self.scan_view.update_current_file)
        self.scan_worker.stats_updated.connect(self.scan_view.update_stats)
        self.scan_worker.phase_changed.connect(self.scan_view.update_phase)
        self.scan_worker.scan_finished.connect(self._on_scan_finished)
        self.scan_worker.scan_error.connect(self._on_scan_error)
        self.scan_worker.start()

    @Slot()
    def _cancel_scan(self):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_worker.wait(5000)
        self.scan_view.stop_timer()
        self._navigate(VIEW_SETUP)

    @Slot()
    def _on_scan_finished(self):
        self.scan_view.stop_timer()
        self.scan_view.show_completed()
        log.info("Scan finished — showing summary")

    @Slot()
    def _on_continue_to_review(self):
        log.info("User continuing to review")
        self._load_review()

    @Slot(str)
    def _on_scan_error(self, msg: str):
        self.scan_view.stop_timer()
        QMessageBox.warning(self, "Scan Error", msg)
        self._navigate(VIEW_SETUP)

    # ── Resume ───────────────────────────────────────────

    @Slot(str)
    def _resume_session(self, folder: str):
        self.source_folder = folder
        setup_logging(get_log_dir(folder))

        db_path = get_db_path(folder)
        if self.store:
            self.store.close()
        self.store = SessionStore(db_path)
        self.thumb_cache = ThumbnailCache(get_thumb_dir(folder))

        session = self.store.get_session()
        if not session:
            QMessageBox.information(self, "No Session", "No previous session found.")
            return

        self.session_id = session.id
        self._phash_threshold = session.phash_threshold
        self._keep_per_cluster = session.keep_per_cluster
        self._event_gap_hours = session.event_gap_hours
        self._face_detection_enabled = session.face_detection_enabled

        if session.status in (SessionStatus.SCANNED, SessionStatus.REVIEWING):
            self._load_review()
        else:
            QMessageBox.information(
                self, "Session Incomplete",
                "The previous session did not complete scanning. Please start a new scan.",
            )

    # ── Review ───────────────────────────────────────────

    def _load_review(self):
        if not self.store:
            return
        self.store.update_session_status(self.session_id, SessionStatus.REVIEWING)

        clusters = self.store.get_clusters_by_session(self.session_id)
        cluster_photos = {}
        for c in clusters:
            cluster_photos[c.id] = self.store.get_photos_by_cluster(c.id)

        # Load events
        events = self.store.get_events_by_session(self.session_id)

        # Check if undo is available
        apply_log = self.store.get_apply_log(self.session_id)
        has_undo = len(apply_log) > 0

        self.review_view.load_data(clusters, cluster_photos, has_undo, events=events)

        # Start thumbnail generation in background
        all_photos = []
        for photos in cluster_photos.values():
            all_photos.extend(photos)
        self._start_thumb_worker(all_photos)

        self._navigate(VIEW_REVIEW)

    def _start_thumb_worker(self, photos):
        if not self.thumb_cache:
            return
        self.thumb_worker = ThumbWorker(photos, self.thumb_cache)
        self.thumb_worker.thumb_ready.connect(self.review_view.on_thumb_ready)
        self.thumb_worker.start()

    # ── Apply ────────────────────────────────────────────

    @Slot()
    def _on_apply(self):
        if not self.store:
            return

        # Persist all user verdict changes from the review view to SQLite
        all_photos = self.review_view.get_all_photos()
        if all_photos:
            self.store.update_photos_batch(all_photos)

        photos = self.store.get_photos_by_session(self.session_id)
        keep_count = sum(1 for p in photos if p.verdict == Verdict.KEEP)
        archive_count = sum(1 for p in photos if p.verdict == Verdict.ARCHIVE)
        delete_count = sum(1 for p in photos if p.verdict == Verdict.DELETE)
        review_count = sum(1 for p in photos if p.verdict == Verdict.REVIEW)

        if archive_count == 0 and delete_count == 0 and keep_count == 0:
            QMessageBox.information(
                self, "Nothing to Apply",
                "No photos have been marked as KEEP, ARCHIVE, or DELETE.",
            )
            return

        dialog = ApplyConfirmDialog(
            keep_count, archive_count, delete_count, review_count, self
        )
        if dialog.exec() != QDialog.Accepted:
            return

        # Execute apply
        try:
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            processed, errors = operator.apply_verdicts(photos)
            self.store.update_session_status(self.session_id, SessionStatus.APPLIED)

            msg = f"Processed {processed} files successfully."
            if errors:
                msg += f"\n{errors} files had errors (see log)."
            QMessageBox.information(self, "Apply Complete", msg)

            # Reload review with undo available
            self._load_review()

        except Exception as e:
            log.exception("Apply failed")
            QMessageBox.critical(self, "Apply Failed", str(e))

    # ── Undo ─────────────────────────────────────────────

    @Slot()
    def _on_undo(self):
        if not self.store:
            return

        apply_log = self.store.get_apply_log(self.session_id)
        if not apply_log:
            QMessageBox.information(self, "Nothing to Undo", "No apply log found.")
            return

        reply = QMessageBox.question(
            self, "Undo Last Apply",
            f"This will restore {len(apply_log)} files to their original locations.\n\nProceed?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            restored, skipped = operator.undo_last_apply()
            self.store.update_session_status(self.session_id, SessionStatus.REVIEWING)

            dialog = UndoResultDialog(restored, skipped, self)
            dialog.exec()

            self._load_review()

        except Exception as e:
            log.exception("Undo failed")
            QMessageBox.critical(self, "Undo Failed", str(e))

    # ── Settings ─────────────────────────────────────────

    @Slot()
    def _show_settings(self):
        dialog = SettingsDialog(
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._phash_threshold = dialog.threshold()
            self._keep_per_cluster = dialog.keep_count()
            self._event_gap_hours = dialog.event_gap_hours()
            self._face_detection_enabled = dialog.face_detection_enabled()

    # ── Cleanup ──────────────────────────────────────────

    def closeEvent(self, event):
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.cancel()
            self.scan_worker.wait(3000)
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()
            self.thumb_worker.wait(2000)
        if self.store:
            self.store.close()
        event.accept()
