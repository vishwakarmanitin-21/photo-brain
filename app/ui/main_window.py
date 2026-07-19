"""Main window with stacked navigation: Setup -> Scan -> Review."""
import os
import uuid
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QVBoxLayout, QMessageBox, QDialog,
    QApplication,
)
from PySide6.QtCore import QTimer, Slot

from app.util.app_settings import AppSettings

from app.ui.setup_view import SetupView
from app.ui.scan_view import ScanView
from app.ui.review_view import ReviewView
from app.ui.dialogs import (
    SettingsDialog, ApplyConfirmDialog, UndoResultDialog, _format_bytes,
)
from app.core.session_store import SessionStore
from app.core.models import SessionStatus, Verdict
from app.core.thumbnails import (
    PreviewCache, ThumbnailCache, valid_keys as thumbnail_valid_keys,
)
from app.core.file_ops import FileOperator, find_last_copy_deletions
from app.workers.scan_worker import ScanWorker
from app.workers.thumb_worker import ThumbWorker
from app.workers.preview_worker import PreviewWorker
from app.util.paths import (
    get_db_path, get_thumb_dir, get_preview_dir, get_log_dir, extended_path,
)
from app.util.logging_util import setup_logging

log = logging.getLogger("photobrain.main_window")

VIEW_SETUP = 0
VIEW_SCAN = 1
VIEW_REVIEW = 2


def _friendly_error(exc: Exception) -> str:
    """Translate low-level OS errors into plain guidance instead of dumping
    raw 'WinError 32' text at the user (UX-10). The technical detail still
    goes to the log via the caller's log.exception()."""
    if isinstance(exc, PermissionError):
        return ("PhotoBrain couldn't access one of your files — it may be open "
                "in another program (a photo viewer, backup tool, or Explorer "
                "preview). Close anything using the folder and try again.")
    if isinstance(exc, FileNotFoundError):
        return ("A file or folder couldn't be found — it may have been moved or "
                "renamed outside PhotoBrain since the scan. Re-scan the folder "
                "and try again.")
    if isinstance(exc, OSError) and getattr(exc, "winerror", None):
        return ("Windows reported a problem while moving your photos. Nothing "
                "was deleted. The technical details were saved to the log.")
    text = str(exc).strip()
    return text or "An unexpected error occurred. See the log for details."


def _verdict_bytes(photos) -> tuple[int, int, int]:
    """Total file sizes (keep, archive, delete) for the apply summary."""
    keep = archive = delete = 0
    for p in photos:
        size = p.file_size or 0
        if p.verdict == Verdict.KEEP:
            keep += size
        elif p.verdict == Verdict.ARCHIVE:
            archive += size
        elif p.verdict == Verdict.DELETE:
            delete += size
    return keep, archive, delete


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store: SessionStore | None = None
        self.session_id: str = ""
        self.source_folder: str = ""
        self.scan_worker: ScanWorker | None = None
        self.thumb_worker: ThumbWorker | None = None
        self.thumb_cache: ThumbnailCache | None = None
        self.preview_cache: PreviewCache | None = None
        self.preview_workers: set[PreviewWorker] = set()

        # Settings defaults — seeded from saved preferences so choices persist
        # across launches (UX-13).
        self._settings = AppSettings()
        self._phash_threshold = self._settings.threshold(11)
        self._keep_per_cluster = self._settings.keep_per_cluster(2)
        self._event_gap_hours = self._settings.event_gap_hours(4.0)
        self._face_detection_enabled = self._settings.face_detection(True)
        self._face_min_confidence = self._settings.face_min_confidence(0.5)

        self._review_save_timer = QTimer(self)
        self._review_save_timer.setSingleShot(True)
        self._review_save_timer.setInterval(400)
        self._review_save_timer.timeout.connect(self._persist_review_state)

        self._build_ui()
        self._connect_signals()
        self._restore_geometry()

    def _restore_geometry(self):
        geo = self._settings.geometry()
        if geo is not None:
            try:
                if self.restoreGeometry(geo):
                    return
            except Exception:
                log.exception("Failed to restore window geometry")
        self.resize(1200, 800)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.setup_view = SetupView()
        self.scan_view = ScanView()
        self.review_view = ReviewView()

        # Apply saved review preferences (UX-13).
        self.review_view.set_hide_singletons(self._settings.hide_singletons(True))
        self.review_view.set_zoom(self._settings.zoom(self.review_view.current_zoom()))

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
        self.review_view.delete_now_requested.connect(self._on_delete_now)
        self.review_view.apply_cluster_requested.connect(self._on_apply_cluster)
        self.review_view.undo_requested.connect(self._on_undo)
        self.review_view.back_requested.connect(self._go_home)
        self.review_view.open_log_requested.connect(self._open_log_folder)
        self.review_view.review_state_changed.connect(self._schedule_review_save)
        self.review_view.previews_requested.connect(self._start_preview_worker)

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

        # A worker from a previous scan may still hold a connection to the
        # old store; closing it underneath the worker corrupts mid-writes.
        if not self._ensure_scan_worker_stopped():
            QMessageBox.information(
                self, "Previous Scan Still Stopping",
                "The previous scan is still shutting down.\n"
                "Please try again in a few seconds.",
            )
            return

        # Open/create session store
        db_path = get_db_path(folder)
        if self.store:
            self.store.close()
        self.store = SessionStore(db_path)

        # Never destroy saved review work on a Start Scan misclick.
        existing = self.store.get_session()
        if existing and existing.status == SessionStatus.SCANNING:
            # Leftover from a scan the app never finished (e.g. power loss).
            # A SCANNING session cannot hold review decisions or an undo
            # journal, so there is nothing to warn about — just clear it.
            log.info("Clearing crash-leftover SCANNING session %s", existing.id)
            self.store.delete_session_data(existing.id)
            existing = None
        if existing:
            decision_count = self.store.count_user_decisions(existing.id)
            reply = QMessageBox.warning(
                self,
                "Replace Previous Session?",
                "This folder already has a PhotoBrain session with "
                f"{decision_count} manual photo decision(s).\n\n"
                "Starting a new scan will permanently remove its saved review "
                "progress and undo journal. Files already moved will not be "
                "changed.\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            self.store.delete_session_data(existing.id)

        self.session_id = uuid.uuid4().hex[:12]
        self.store.create_session(
            self.session_id, folder,
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
        )

        self.thumb_cache = ThumbnailCache(get_thumb_dir(folder))
        self.preview_cache = PreviewCache(get_preview_dir(folder))

        # Switch to scan view and start. Phase count drives the weighted
        # progress bar: 8 phases normally, 7 when face detection is off.
        self.scan_view.reset(total_phases=8 if self._face_detection_enabled else 7)
        self._navigate(VIEW_SCAN)
        self.scan_view.start_timer()

        self.scan_worker = ScanWorker(
            folder, self.store, self.session_id,
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
            face_min_confidence=self._face_min_confidence,
        )
        self.scan_worker.progress_updated.connect(self.scan_view.update_progress)
        self.scan_worker.current_file.connect(self.scan_view.update_current_file)
        self.scan_worker.stats_updated.connect(self.scan_view.update_stats)
        self.scan_worker.phase_changed.connect(self.scan_view.update_phase)
        self.scan_worker.scan_finished.connect(self._on_scan_finished)
        self.scan_worker.scan_error.connect(self._on_scan_error)
        self.scan_worker.start()

    def _ensure_scan_worker_stopped(self, timeout_ms: int = 10000) -> bool:
        """Cancel a running scan worker and wait for it to exit.

        Returns True when no scan worker is running afterwards. Callers must
        not close or replace the session store while this returns False —
        the worker thread still holds a live SQLite connection.
        """
        if not (self.scan_worker and self.scan_worker.isRunning()):
            return True
        self.scan_worker.cancel()
        return self.scan_worker.wait(timeout_ms)

    @Slot()
    def _cancel_scan(self):
        # Paint "Cancelling…" immediately so the click is acknowledged before
        # we block waiting for the worker's in-flight batch to unwind.
        self.scan_view.show_cancelling()
        QApplication.processEvents()
        self._ensure_scan_worker_stopped(5000)
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
        try:
            self._load_review()
        except Exception as e:
            log.exception("Failed to load review")
            QMessageBox.critical(self, "Error Loading Review", _friendly_error(e))

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
        self.preview_cache = PreviewCache(get_preview_dir(folder))

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

    def _load_review(self, preserve_place: bool = False):
        if not self.store:
            return
        prev_state = (
            self.review_view.get_view_state() if preserve_place else None
        )
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
        if prev_state:
            self.review_view.apply_view_state(prev_state)

        # Start thumbnail generation in background
        all_photos = []
        for photos in cluster_photos.values():
            all_photos.extend(photos)
        self._prune_caches(all_photos)
        self._start_thumb_worker(all_photos)

        self._navigate(VIEW_REVIEW)

    def _prune_caches(self, photos):
        """Drop cache files not belonging to the current library, so the
        thumbnail/preview caches stay bounded across rescans."""
        keep = thumbnail_valid_keys(photos)
        try:
            if self.thumb_cache:
                self.thumb_cache.prune(keep)
            if self.preview_cache:
                self.preview_cache.prune(keep)
        except Exception:
            log.exception("Cache prune failed")

    def _start_thumb_worker(self, photos):
        if not self.thumb_cache:
            return
        # Stop any previous thumbnail run before replacing it, so an old
        # QThread isn't left running unowned (crash risk) with a stale
        # thumb_ready connection into the review view.
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()
            self.thumb_worker.wait(2000)
        self.thumb_worker = ThumbWorker(photos, self.thumb_cache)
        self.thumb_worker.thumb_ready.connect(self.review_view.on_thumb_ready)
        self.thumb_worker.start()

    @Slot(object, int)
    def _start_preview_worker(self, photos, display_size: int):
        """Decode and resize requested originals outside the UI thread."""
        if not self.preview_cache or not photos:
            return
        for worker in list(self.preview_workers):
            if worker.isRunning():
                worker.cancel()

        worker = PreviewWorker(photos, display_size, self.preview_cache)
        self.preview_workers.add(worker)
        worker.preview_ready.connect(self.review_view.on_preview_ready)
        worker.finished.connect(
            lambda current=worker: self.preview_workers.discard(current)
        )
        worker.start()

    @Slot()
    def _schedule_review_save(self):
        """Debounce frequent verdict changes into one SQLite write."""
        if self.store and self.session_id:
            self._review_save_timer.start()

    @Slot()
    def _persist_review_state(self):
        """Flush verdicts and cluster review markers to SQLite."""
        if not self.store or not self.session_id:
            return
        photos = self.review_view.get_all_photos()
        if photos:
            self.store.update_photos_batch(photos)
        clusters = self.review_view.get_all_clusters()
        if clusters:
            self.store.update_clusters_review_state(clusters)

    # ── Apply ────────────────────────────────────────────

    @Slot()
    def _on_apply(self):
        if not self.store:
            return

        # Persist all user verdict changes from the review view to SQLite
        all_photos = self.review_view.get_all_photos()
        if all_photos:
            self.store.update_photos_batch(all_photos)

        # Get all clusters and filter out already-applied ones
        all_clusters = self.store.get_clusters_by_session(self.session_id)
        applied_cluster_ids = {c.id for c in all_clusters if c.applied}

        # Get photos from unapplied clusters only
        all_session_photos = self.store.get_photos_by_session(self.session_id)
        photos = [p for p in all_session_photos if p.cluster_id not in applied_cluster_ids]

        keep_count = sum(1 for p in photos if p.verdict == Verdict.KEEP)
        archive_count = sum(1 for p in photos if p.verdict == Verdict.ARCHIVE)
        delete_count = sum(1 for p in photos if p.verdict == Verdict.DELETE)
        review_count = sum(1 for p in photos if p.verdict == Verdict.REVIEW)

        if archive_count == 0 and delete_count == 0 and keep_count == 0:
            if applied_cluster_ids:
                QMessageBox.information(
                    self, "Nothing to Apply",
                    "All remaining clusters have either been applied or have no KEEP/ARCHIVE/DELETE verdicts.",
                )
            else:
                QMessageBox.information(
                    self, "Nothing to Apply",
                    "No photos have been marked as KEEP, ARCHIVE, or DELETE.",
                )
            return

        kb, ab, db = _verdict_bytes(photos)
        dialog = ApplyConfirmDialog(
            keep_count, archive_count, delete_count, review_count, self,
            last_copy_delete_count=len(find_last_copy_deletions(photos)),
            keep_bytes=kb, archive_bytes=ab, delete_bytes=db,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        # Execute apply for unapplied clusters
        try:
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            processed, errors = operator.apply_verdicts(photos)

            # Only clusters that actually completed file operations should be
            # hidden from future applies. REVIEW-only and failed clusters stay.
            for cluster_id in operator.applied_cluster_ids:
                self.store.update_cluster_applied(cluster_id, True)

            self.store.update_session_status(self.session_id, SessionStatus.APPLIED)

            msg = f"Processed {processed} files successfully."
            if errors:
                msg += f"\n{errors} files had errors (see log)."
            if applied_cluster_ids:
                msg += f"\n\nSkipped {len(applied_cluster_ids)} already-applied clusters."
            QMessageBox.information(self, "Apply Complete", msg)

            # Reload review with undo available, keeping the user's place.
            self._load_review(preserve_place=True)

        except Exception as e:
            log.exception("Apply failed")
            QMessageBox.critical(self, "Apply Failed", _friendly_error(e))

    @Slot()
    def _on_delete_now(self):
        """Interim step: recycle only the DELETE-marked photos now, leaving
        Keep/Archive decisions pending, so a large folder clears gradually."""
        if not self.store:
            return
        all_photos = self.review_view.get_all_photos()
        to_delete = [p for p in all_photos if p.verdict == Verdict.DELETE]
        if not to_delete:
            QMessageBox.information(
                self, "Nothing marked for deletion",
                "No photos are marked for deletion yet. Mark some with the "
                "Delete button (or the D key), then try again.")
            return

        # Persist the latest verdicts so the store matches the review view.
        self.store.update_photos_batch(all_photos)

        _kb, _ab, del_bytes = _verdict_bytes(to_delete)
        last_copy = len(find_last_copy_deletions(all_photos))
        if not self._confirm_delete_now(len(to_delete), del_bytes, last_copy):
            return

        try:
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            processed, errors = operator.apply_verdicts(to_delete)

            # Purge records whose files are actually gone (recycled) so they
            # don't reappear as broken tiles on reload; a file that errored
            # (still present) keeps its record + DELETE mark for a retry.
            gone = [
                p.id for p in to_delete
                if not os.path.isfile(extended_path(os.path.normpath(p.filepath)))
            ]
            self.store.purge_photos(self.session_id, gone)

            msg = f"Sent {processed} photo(s) to the Recycle Bin."
            if errors:
                msg += f"\n{errors} could not be deleted (see log)."
            msg += "\n\nYour Keep/Archive decisions are still pending."
            QMessageBox.information(self, "Deletions Applied", msg)

            self._load_review(preserve_place=True)
        except Exception as e:
            log.exception("Delete-now failed")
            QMessageBox.critical(self, "Delete Failed", _friendly_error(e))

    def _confirm_delete_now(self, count: int, del_bytes: int, last_copy: int) -> bool:
        text = f"Send {count} photo(s) marked for deletion to the Recycle Bin now?"
        if del_bytes:
            text += (f"\n\nFrees ~{_format_bytes(del_bytes)} once you empty the "
                     "Recycle Bin.")
        text += ("\n\nThis is an interim step — your Keep/Archive decisions "
                 "stay pending. Recycle Bin deletions can't be undone from "
                 "PhotoBrain.")
        if last_copy:
            text += (f"\n\n⚠ {last_copy} of these is the only copy in this "
                     "batch (no kept duplicate).")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete marked photos now?")
        box.setText(text)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        return box.exec() == QMessageBox.Yes

    @Slot(str)
    def _on_apply_cluster(self, cluster_id: str):
        """Apply changes for a single cluster."""
        if not self.store:
            return

        # Get cluster photos
        cluster_photos = {}
        for cid, photos in self.review_view._cluster_photos.items():
            cluster_photos[cid] = photos

        photos = cluster_photos.get(cluster_id, [])
        if not photos:
            QMessageBox.warning(self, "No Photos", "No photos found in this cluster.")
            return

        # Persist verdicts for this cluster's photos
        self.store.update_photos_batch(photos)

        # Count verdicts for this cluster only
        keep_count = sum(1 for p in photos if p.verdict == Verdict.KEEP)
        archive_count = sum(1 for p in photos if p.verdict == Verdict.ARCHIVE)
        delete_count = sum(1 for p in photos if p.verdict == Verdict.DELETE)
        review_count = sum(1 for p in photos if p.verdict == Verdict.REVIEW)

        if archive_count == 0 and delete_count == 0 and keep_count == 0:
            QMessageBox.information(
                self, "Nothing to Apply",
                "No photos in this cluster have been marked as KEEP, ARCHIVE, or DELETE.",
            )
            return

        kb, ab, db = _verdict_bytes(photos)
        dialog = ApplyConfirmDialog(
            keep_count, archive_count, delete_count, review_count, self,
            last_copy_delete_count=len(find_last_copy_deletions(photos)),
            keep_bytes=kb, archive_bytes=ab, delete_bytes=db,
        )
        if dialog.exec() != QDialog.Accepted:
            return

        # Execute apply for this cluster only
        try:
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            processed, errors = operator.apply_verdicts(photos)

            cluster_applied = cluster_id in operator.applied_cluster_ids
            if cluster_applied:
                self.store.update_cluster_applied(cluster_id, True)

            msg = f"Processed {processed} files in this cluster successfully."
            if errors:
                msg += f"\n{errors} files had errors (see log)."
            QMessageBox.information(self, "Apply Complete", msg)

            # Mark cluster as applied in UI and navigate to next only when all
            # of its requested filesystem operations completed.
            if cluster_applied:
                self.review_view.mark_cluster_applied(cluster_id)

        except Exception as e:
            log.exception("Cluster apply failed")
            QMessageBox.critical(self, "Apply Failed", _friendly_error(e))

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
            touched_cluster_ids = {
                entry.cluster_id for entry in apply_log if entry.cluster_id
            }
            operator = FileOperator(self.source_folder, self.store, self.session_id)
            restored, skipped = operator.undo_last_apply()
            for cluster_id in touched_cluster_ids:
                self.store.update_cluster_applied(cluster_id, False)
            self.store.update_session_status(self.session_id, SessionStatus.REVIEWING)

            dialog = UndoResultDialog(restored, skipped, self)
            dialog.exec()

            self._load_review(preserve_place=True)

        except Exception as e:
            log.exception("Undo failed")
            QMessageBox.critical(self, "Undo Failed", _friendly_error(e))

    @Slot()
    def _open_log_folder(self):
        """Open PhotoBrain's log folder in the system file manager (FEAT-05)."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        folder = self.source_folder or self.setup_view.selected_folder()
        if not folder:
            QMessageBox.information(
                self, "No Log Yet",
                "Scan a folder first — logs are written next to your photos.")
            return
        log_dir = get_log_dir(folder)
        os.makedirs(log_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))

    # ── Settings ─────────────────────────────────────────

    @Slot()
    def _show_settings(self):
        # Cache is per source folder; prefer the active session's folder,
        # else whatever is selected on the home screen.
        folder = self.source_folder or self.setup_view.selected_folder()
        dialog = SettingsDialog(
            self._phash_threshold, self._keep_per_cluster,
            self._event_gap_hours, self._face_detection_enabled,
            self, source_folder=folder,
            face_min_confidence=self._face_min_confidence,
        )
        if dialog.exec() == QDialog.Accepted:
            self._phash_threshold = dialog.threshold()
            self._keep_per_cluster = dialog.keep_count()
            self._event_gap_hours = dialog.event_gap_hours()
            self._face_detection_enabled = dialog.face_detection_enabled()
            self._face_min_confidence = dialog.face_min_confidence()
            # Remember these as the defaults for next launch (UX-13).
            self._settings.save_scan_defaults(
                self._phash_threshold, self._keep_per_cluster,
                self._event_gap_hours, self._face_detection_enabled,
                face_min_confidence=self._face_min_confidence,
            )

    # ── Cleanup ──────────────────────────────────────────

    def _save_preferences(self):
        """Persist window + review preferences so they survive a restart."""
        try:
            self._settings.save_geometry(self.saveGeometry())
            self._settings.save_zoom(self.review_view.current_zoom())
            self._settings.save_hide_singletons(
                self.review_view.hide_singletons_enabled())
        except Exception:
            log.exception("Failed to save preferences")

    def closeEvent(self, event):
        self._save_preferences()
        if self._review_save_timer.isActive():
            self._review_save_timer.stop()
        if self.stack.currentIndex() == VIEW_REVIEW:
            try:
                self._persist_review_state()
            except Exception:
                log.exception("Failed to persist review state during close")
        scan_stopped = self._ensure_scan_worker_stopped()
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.cancel()
            self.thumb_worker.wait(2000)
        for worker in list(self.preview_workers):
            if worker.isRunning():
                worker.cancel()
                worker.wait(2000)
        if self.store:
            if scan_stopped:
                self.store.close()
            else:
                # The worker is stuck in a long native call; closing its
                # connection from here would interrupt a live write. WAL
                # makes an unclosed connection at process exit crash-safe,
                # so leaving the store open is the lesser evil.
                log.warning(
                    "Scan worker still running at exit; skipping store close"
                )
        event.accept()
