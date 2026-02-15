"""File operations for apply/undo — safe moves with logging."""
import os
import csv
import json
import shutil
import logging
from datetime import datetime, timezone

from send2trash import send2trash

from app.core.models import Photo, Verdict, DupType, ApplyLogEntry
from app.core.session_store import SessionStore
from app.util.paths import (
    KEEP_FOLDER, ARCHIVE_DUPES_FOLDER, ARCHIVE_LOW_QUALITY_FOLDER,
    get_output_dir, get_log_dir, resolve_collision,
)

log = logging.getLogger("photobrain.file_ops")


class FileOperator:
    def __init__(self, source_folder: str, store: SessionStore, session_id: str):
        self.source_folder = source_folder
        self.store = store
        self.session_id = session_id

    def apply_verdicts(self, photos: list[Photo]) -> tuple[int, int]:
        """Move/delete photos based on verdicts.

        - KEEP: moved to 03_KEEP folder
        - ARCHIVE: moved to archive folders (safe, reversible)
        - DELETE: sent to system Recycle Bin (not reversible from app)
        - REVIEW: skipped

        Returns (processed_count, error_count).
        """
        # Build a lookup of SHA256 -> has a KEEP photo
        keep_shas: set[str] = set()
        for p in photos:
            if p.verdict == Verdict.KEEP and p.sha256:
                keep_shas.add(p.sha256)

        entries: list[ApplyLogEntry] = []
        processed = 0
        errors = 0
        now = datetime.now(timezone.utc).isoformat()

        for photo in photos:
            if photo.verdict == Verdict.REVIEW:
                continue  # Skip undecided

            try:
                # Normalize path separators — send2trash uses \\?\ prefix
                # on Windows which requires pure backslashes
                filepath = os.path.normpath(photo.filepath)

                if not os.path.isfile(filepath):
                    log.warning("Source file missing: %s", filepath)
                    errors += 1
                    continue

                if photo.verdict == Verdict.DELETE:
                    # Permanent delete — send to Recycle Bin
                    send2trash(filepath)
                    entries.append(ApplyLogEntry(
                        photo_id=photo.id,
                        original_path=filepath,
                        destination_path="[RECYCLE BIN]",
                        verdict=photo.verdict.value,
                        dup_type=photo.dup_type.value,
                        destination_folder="[RECYCLE BIN]",
                        cluster_id=photo.cluster_id or "",
                        timestamp=now,
                    ))
                else:
                    # KEEP or ARCHIVE — move to destination folder
                    dest_folder_name = self._get_dest_folder(photo)
                    dest_dir = get_output_dir(self.source_folder, dest_folder_name)
                    dest_path = os.path.join(dest_dir, photo.filename)
                    dest_path = resolve_collision(dest_path)

                    shutil.move(filepath, dest_path)

                    entries.append(ApplyLogEntry(
                        photo_id=photo.id,
                        original_path=filepath,
                        destination_path=dest_path,
                        verdict=photo.verdict.value,
                        dup_type=photo.dup_type.value,
                        destination_folder=dest_folder_name,
                        cluster_id=photo.cluster_id or "",
                        timestamp=now,
                    ))

                processed += 1

            except Exception as e:
                log.error("Failed to process %s: %s", photo.filepath, e)
                errors += 1

        # Write logs
        if entries:
            self._write_logs(entries, now)
            self.store.insert_apply_log_batch(self.session_id, entries)

        log.info("Apply complete: %d processed, %d errors", processed, errors)
        return processed, errors

    def _get_dest_folder(self, photo: Photo) -> str:
        if photo.verdict == Verdict.KEEP:
            return KEEP_FOLDER

        # ARCHIVE — determine archive folder by dup type
        if photo.dup_type == DupType.EXACT:
            return ARCHIVE_DUPES_FOLDER
        elif photo.dup_type == DupType.NEAR:
            return ARCHIVE_LOW_QUALITY_FOLDER
        else:
            return ARCHIVE_LOW_QUALITY_FOLDER

    def _write_logs(self, entries: list[ApplyLogEntry], timestamp: str):
        log_dir = get_log_dir(self.source_folder)
        safe_ts = timestamp.replace(":", "-").replace(".", "-")[:19]

        # CSV log
        csv_path = os.path.join(log_dir, f"apply_{safe_ts}.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "photo_id", "original_path", "destination_path",
                    "verdict", "dup_type", "destination_folder",
                    "cluster_id", "timestamp",
                ])
                for e in entries:
                    writer.writerow([
                        e.photo_id, e.original_path, e.destination_path,
                        e.verdict, e.dup_type, e.destination_folder,
                        e.cluster_id, e.timestamp,
                    ])
        except Exception as ex:
            log.error("Failed to write CSV log: %s", ex)

        # JSON log
        json_path = os.path.join(log_dir, f"apply_{safe_ts}.json")
        try:
            data = {
                "session_id": self.session_id,
                "applied_at": timestamp,
                "source_folder": self.source_folder,
                "entries": [
                    {
                        "photo_id": e.photo_id,
                        "original_path": e.original_path,
                        "destination_path": e.destination_path,
                        "verdict": e.verdict,
                        "dup_type": e.dup_type,
                        "destination_folder": e.destination_folder,
                        "cluster_id": e.cluster_id,
                        "timestamp": e.timestamp,
                    }
                    for e in entries
                ],
                "summary": {
                    "total_processed": len(entries),
                    "kept": sum(1 for e in entries if e.verdict == "KEEP"),
                    "archived": sum(1 for e in entries if e.verdict == "ARCHIVE"),
                    "deleted": sum(1 for e in entries if e.verdict == "DELETE"),
                    "archived_dupes": sum(
                        1 for e in entries
                        if e.destination_folder == ARCHIVE_DUPES_FOLDER
                    ),
                    "archived_low_quality": sum(
                        1 for e in entries
                        if e.destination_folder == ARCHIVE_LOW_QUALITY_FOLDER
                    ),
                },
            }
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as ex:
            log.error("Failed to write JSON log: %s", ex)

        self.store.update_session_apply_log(self.session_id, json_path)

    def undo_last_apply(self) -> tuple[int, int]:
        """Undo the last apply by moving files back. Returns (restored, skipped)."""
        entries = self.store.get_apply_log(self.session_id)
        if not entries:
            return 0, 0

        restored = 0
        skipped = 0

        # Reverse order for undo
        for entry in reversed(entries):
            try:
                # Cannot undo permanent deletes (sent to Recycle Bin)
                if entry.verdict == "DELETE":
                    log.info("Skipping deleted file (in Recycle Bin): %s", entry.original_path)
                    skipped += 1
                    continue

                if not os.path.isfile(entry.destination_path):
                    log.warning("File no longer at destination: %s", entry.destination_path)
                    skipped += 1
                    continue

                # Ensure original directory exists
                orig_dir = os.path.dirname(entry.original_path)
                os.makedirs(orig_dir, exist_ok=True)

                # Handle collision at original location
                restore_path = entry.original_path
                if os.path.exists(restore_path):
                    restore_path = resolve_collision(restore_path)
                    log.warning(
                        "Original path occupied, restoring to: %s", restore_path
                    )

                shutil.move(entry.destination_path, restore_path)
                restored += 1

            except Exception as e:
                log.error("Failed to undo move for %s: %s", entry.photo_id, e)
                skipped += 1

        # Clear apply log
        self.store.clear_apply_log(self.session_id)

        # Clean up empty output directories
        for folder_name in (KEEP_FOLDER, ARCHIVE_DUPES_FOLDER, ARCHIVE_LOW_QUALITY_FOLDER):
            folder_path = os.path.join(self.source_folder, folder_name)
            if os.path.isdir(folder_path) and not os.listdir(folder_path):
                try:
                    os.rmdir(folder_path)
                except OSError:
                    pass

        log.info("Undo complete: %d restored, %d skipped", restored, skipped)
        return restored, skipped
