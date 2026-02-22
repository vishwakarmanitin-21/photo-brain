"""Background worker thread for the full scan pipeline."""
import logging

from PySide6.QtCore import QThread, Signal

from app.core.scanner import (
    collect_files, compute_hashes, compute_phashes,
    compute_scores, detect_all_faces, analyze_all_expressions,
    extract_dates, build_photo_events, run_clustering, assign_verdicts,
)
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
        phash_threshold: int = 12,
        keep_per_cluster: int = 2,
        event_gap_hours: float = 4.0,
        face_detection_enabled: bool = True,
    ):
        super().__init__()
        self.source_folder = source_folder
        self.store = store
        self.session_id = session_id
        self.phash_threshold = phash_threshold
        self.keep_per_cluster = keep_per_cluster
        self.event_gap_hours = event_gap_hours
        self.face_detection_enabled = face_detection_enabled
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            self._run_pipeline()
        except Exception as e:
            log.exception("Scan failed")
            self.scan_error.emit(str(e))
        finally:
            # Clean up mediapipe resources
            try:
                from app.core.faces import cleanup
                cleanup()
            except Exception:
                pass

    def _run_pipeline(self):
        # Phase 1: Collect files
        self.phase_changed.emit("Collecting files...")
        files = collect_files(self.source_folder)
        if self._cancelled:
            return
        self.stats_updated.emit("total_files", len(files))
        self.store.update_session_progress(self.session_id, len(files), 0)

        if not files:
            self.scan_error.emit("No supported image files found in the selected folder.")
            return

        # Phase 2: SHA256 hashes
        self.phase_changed.emit("Computing file hashes...")
        self.store.update_session_status(self.session_id, SessionStatus.SCANNING)

        def hash_progress(cur, total, fname):
            self.progress_updated.emit("Hashing", cur, total)
            self.current_file.emit(fname)
            self.stats_updated.emit("hashed", cur)

        photos = compute_hashes(files, hash_progress, self._is_cancelled)
        if self._cancelled:
            return

        # Count exact duplicates
        sha_counts: dict[str, int] = {}
        for p in photos:
            if p.sha256:
                sha_counts[p.sha256] = sha_counts.get(p.sha256, 0) + 1
        dup_count = sum(v - 1 for v in sha_counts.values() if v > 1)
        self.stats_updated.emit("duplicates", dup_count)

        # Persist photos
        self.store.insert_photos_batch(self.session_id, photos)

        # Phase 3: pHash
        self.phase_changed.emit("Computing perceptual hashes...")

        def phash_progress(cur, total, fname):
            self.progress_updated.emit("pHash", cur, total)
            self.current_file.emit(fname)
            self.stats_updated.emit("phash_computed", cur)

        compute_phashes(photos, phash_progress, self._is_cancelled)
        if self._cancelled:
            return

        # Phase 4: Quality scoring
        self.phase_changed.emit("Scoring image quality...")

        def score_progress(cur, total, fname):
            self.progress_updated.emit("Scoring", cur, total)
            self.current_file.emit(fname)
            self.stats_updated.emit("scored", cur)

        compute_scores(photos, score_progress, self._is_cancelled)
        if self._cancelled:
            return

        # Phase 5: Face detection (optional)
        if self.face_detection_enabled:
            self.phase_changed.emit("Detecting faces...")

            def face_progress(cur, total, fname):
                self.progress_updated.emit("Faces", cur, total)
                self.current_file.emit(fname)

            face_stats = detect_all_faces(photos, face_progress, self._is_cancelled)
            if self._cancelled:
                return
            self.stats_updated.emit("faces_detected", face_stats["faces_total"])
            self.stats_updated.emit("faces_close", face_stats["faces_close"])
            self.stats_updated.emit("faces_far", face_stats["faces_far"])
            self.stats_updated.emit("faces_none", face_stats["faces_none"])
            self.stats_updated.emit("group_shots", face_stats["group_shots"])

            # Phase 5b: Expression analysis (only on photos with faces)
            if face_stats["faces_total"] > 0:
                self.phase_changed.emit("Analyzing expressions...")

                def expr_progress(cur, total, fname):
                    self.progress_updated.emit("Expressions", cur, total)
                    self.current_file.emit(fname)

                expr_count = analyze_all_expressions(
                    photos, expr_progress, self._is_cancelled
                )
                if self._cancelled:
                    return
                self.stats_updated.emit("expressions_analyzed", expr_count)

        # Phase 6: EXIF dates + event grouping
        self.phase_changed.emit("Extracting dates...")

        def date_progress(cur, total, fname):
            self.progress_updated.emit("Dates", cur, total)
            self.current_file.emit(fname)

        dated_count = extract_dates(photos, date_progress, self._is_cancelled)
        if self._cancelled:
            return

        self.phase_changed.emit("Grouping into events...")
        events, event_photos = build_photo_events(photos, self.event_gap_hours)
        if self._cancelled:
            return
        self.stats_updated.emit("events", len(events))

        # Phase 7: Clustering
        self.phase_changed.emit("Clustering similar photos...")
        clusters, cluster_photos = run_clustering(photos, self.phash_threshold)
        if self._cancelled:
            return
        self.stats_updated.emit("clusters", len(clusters))

        # Phase 8: Suggest verdicts
        self.phase_changed.emit("Generating suggestions...")
        assign_verdicts(clusters, cluster_photos, self.keep_per_cluster)

        # Persist everything
        self.store.update_photos_batch(photos)
        self.store.insert_clusters_batch(self.session_id, clusters)
        self.store.insert_events_batch(self.session_id, events)
        self.store.update_session_status(self.session_id, SessionStatus.SCANNED)
        self.store.update_session_progress(self.session_id, len(files), len(files))

        log.info(
            "Scan complete: %d photos, %d clusters, %d events, %d exact dupes",
            len(photos), len(clusters), len(events), dup_count,
        )
        self.scan_finished.emit()
