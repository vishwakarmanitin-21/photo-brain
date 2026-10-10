"""Background worker thread for the full scan pipeline."""
import logging

from PySide6.QtCore import QThread, Signal

from app.core.pipeline import AnalysisOptions, PipelineHooks, analyze
from app.core.scanner import collect_files
from app.core.session_store import SessionStore
from app.core.models import SessionStatus

log = logging.getLogger("photobrain.scan_worker")


class ScanWorker(QThread):
    progress_updated = Signal(str, int, int)   # phase, current, total
    current_file = Signal(str)                  # filename being processed
    stats_updated = Signal(str, int)            # stat_name, value
    phase_changed = Signal(str)                 # phase description
    scan_finished = Signal()
    scan_error = Signal(str)

    def __init__(
        self,
        source_folder: str,
        store: SessionStore,
        session_id: str,
        phash_threshold: int = 11,
        keep_per_cluster: int = 2,
        event_gap_hours: float = 4.0,
        face_detection_enabled: bool = True,
        face_min_confidence: float = 0.5,
    ):
        super().__init__()
        self.source_folder = source_folder
        self.store = store
        self.session_id = session_id
        self.phash_threshold = phash_threshold
        self.keep_per_cluster = keep_per_cluster
        self.event_gap_hours = event_gap_hours
        self.face_detection_enabled = face_detection_enabled
        self.face_min_confidence = face_min_confidence
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        completed = False
        try:
            completed = bool(self._run_pipeline())
        except Exception as e:
            log.exception("Scan failed")
            self.scan_error.emit(str(e))
        finally:
            if not completed:
                self._discard_incomplete_session()
            # Clean up mediapipe resources
            try:
                from app.core.faces import cleanup
                cleanup()
            except Exception:
                pass

    def _discard_incomplete_session(self):
        """Remove the half-written session after a cancelled or failed scan.

        Without this, the session stays in SCANNING with partial photo rows
        and no clusters — a state no other code path expects to load.
        """
        try:
            self.store.delete_session_data(self.session_id)
            log.info("Discarded incomplete scan session %s", self.session_id)
        except Exception:
            log.exception(
                "Failed to discard incomplete session %s", self.session_id
            )

    def _run_pipeline(self):
        # Phase 1: Collect files
        self.phase_changed.emit("Collecting files...")
        files = collect_files(self.source_folder)
        if self._cancelled:
            return False
        self.stats_updated.emit("total_files", len(files))
        self.store.update_session_progress(self.session_id, len(files), 0)

        if not files:
            self.scan_error.emit("No supported image files found in the selected folder.")
            return False

        self.store.update_session_status(self.session_id, SessionStatus.SCANNING)

        # Phases 2-8 run in the shared core pipeline (app/core/pipeline.py) —
        # the same code the ranking scorecard measures (RANK-01).
        def progress(label, cur, total, fname):
            self.progress_updated.emit(label, cur, total)
            self.current_file.emit(fname)

        hooks = PipelineHooks(
            phase=self.phase_changed.emit,
            progress=progress,
            stat=self.stats_updated.emit,
            hashed=lambda photos: self.store.insert_photos_batch(self.session_id, photos),
        )
        options = AnalysisOptions(
            phash_threshold=self.phash_threshold,
            keep_per_cluster=self.keep_per_cluster,
            event_gap_hours=self.event_gap_hours,
            face_detection_enabled=self.face_detection_enabled,
            face_min_confidence=self.face_min_confidence,
        )
        result = analyze(files, options, hooks, self._is_cancelled)
        if result is None or self._cancelled:
            return False

        # Persist everything
        self.store.update_photos_batch(result.photos)
        self.store.insert_clusters_batch(self.session_id, result.clusters)
        self.store.insert_events_batch(self.session_id, result.events)
        self.store.update_session_status(self.session_id, SessionStatus.SCANNED)
        self.store.update_session_progress(self.session_id, len(files), len(files))

        log.info(
            "Scan complete: %d photos, %d clusters, %d events, %d exact dupes",
            len(result.photos), len(result.clusters), len(result.events),
            result.dup_count,
        )
        self.scan_finished.emit()
        return True
