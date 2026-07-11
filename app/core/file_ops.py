"""File operations for apply/undo — safe moves with logging."""
import os
import csv
import json
import logging
from datetime import datetime, timezone

from send2trash import send2trash

from app.core.models import Photo, Verdict, DupType, ApplyLogEntry
from app.core.session_store import SessionStore
from app.util.paths import (
    KEEP_FOLDER, ARCHIVE_DUPES_FOLDER, ARCHIVE_LOW_QUALITY_FOLDER,
    get_output_dir, get_log_dir, resolve_collision,
    extended_path, move_no_overwrite,
)

log = logging.getLogger("photobrain.file_ops")


def find_last_copy_deletions(photos: list[Photo]) -> list[Photo]:
    """Return DELETE photos whose every scanned exact copy is also DELETE."""
    copy_groups: dict[str, list[Photo]] = {}
    for photo in photos:
        # A missing SHA cannot be matched safely, so treat that file as its
        # own known copy rather than assuming another photo will survive.
        key = photo.sha256 or f"__unique_{photo.id}"
        copy_groups.setdefault(key, []).append(photo)

    risky: list[Photo] = []
    for group in copy_groups.values():
        if group and all(photo.verdict == Verdict.DELETE for photo in group):
            risky.extend(group)
    return sorted(risky, key=lambda photo: photo.filepath)


class FileOperator:
    def __init__(self, source_folder: str, store: SessionStore, session_id: str):
        self.source_folder = source_folder
        self.store = store
        self.session_id = session_id
        self.processed_cluster_ids: set[str] = set()
        self.failed_cluster_ids: set[str] = set()

    def apply_verdicts(self, photos: list[Photo]) -> tuple[int, int]:
        """Move/delete photos based on verdicts.

        - KEEP: moved to 03_KEEP folder
        - ARCHIVE: moved to archive folders (safe, reversible)
        - DELETE: sent to system Recycle Bin (not reversible from app)
        - REVIEW: skipped

        Returns (processed_count, error_count).
        """
        entries: list[ApplyLogEntry] = []
        self.processed_cluster_ids.clear()
        self.failed_cluster_ids.clear()
        processed = 0
        errors = 0
        now = datetime.now(timezone.utc).isoformat()

        for photo in photos:
            if photo.verdict == Verdict.REVIEW:
                continue  # Skip undecided

            entry = None
            try:
                # Normalize path separators — send2trash uses \\?\ prefix
                # on Windows which requires pure backslashes
                filepath = os.path.normpath(photo.filepath)

                if not os.path.isfile(extended_path(filepath)):
                    log.warning("Source file missing: %s", filepath)
                    if photo.cluster_id:
                        self.failed_cluster_ids.add(photo.cluster_id)
                    errors += 1
                    continue

                if photo.verdict == Verdict.DELETE:
                    entry = ApplyLogEntry(
                        photo_id=photo.id,
                        original_path=filepath,
                        destination_path="[RECYCLE BIN]",
                        verdict=photo.verdict.value,
                        dup_type=photo.dup_type.value,
                        destination_folder="[RECYCLE BIN]",
                        cluster_id=photo.cluster_id or "",
                        timestamp=now,
                    )
                else:
                    # KEEP or ARCHIVE — move to destination folder
                    dest_folder_name = self._get_dest_folder(photo)
                    dest_dir = get_output_dir(self.source_folder, dest_folder_name)
                    dest_path = os.path.join(dest_dir, photo.filename)
                    dest_path = resolve_collision(dest_path)

                    entry = ApplyLogEntry(
                        photo_id=photo.id,
                        original_path=filepath,
                        destination_path=dest_path,
                        verdict=photo.verdict.value,
                        dup_type=photo.dup_type.value,
                        destination_folder=dest_folder_name,
                        cluster_id=photo.cluster_id or "",
                        timestamp=now,
                    )

                # Commit the undo plan before mutating the filesystem. If the
                # process dies after this point, recovery still has a record.
                entry.db_id = self.store.insert_apply_log_entry(
                    self.session_id, entry,
                )

                if photo.verdict == Verdict.DELETE:
                    # Permanent delete — send to Recycle Bin
                    send2trash(filepath)
                else:
                    final_dest = move_no_overwrite(
                        filepath, entry.destination_path,
                    )
                    if final_dest != entry.destination_path:
                        # The planned name got taken between planning and
                        # moving — keep the journal pointing at reality.
                        entry.destination_path = final_dest
                        self.store.update_apply_log_destination(
                            entry.db_id, final_dest,
                        )
                    self.store.update_photo_path(photo.id, final_dest)

                entries.append(entry)
                if photo.cluster_id:
                    self.processed_cluster_ids.add(photo.cluster_id)
                processed += 1

            except Exception as e:
                log.error("Failed to process %s: %s", photo.filepath, e)
                if photo.cluster_id:
                    self.failed_cluster_ids.add(photo.cluster_id)
                # Remove the plan only when the source still proves no
                # destructive mutation completed. Some filesystem APIs can
                # raise after doing part (or all) of the requested operation;
                # in that ambiguous case the recovery record must survive.
                if entry is not None and entry.db_id is not None:
                    if os.path.exists(extended_path(entry.original_path)):
                        try:
                            self.store.delete_apply_log_entry(entry.db_id)
                        except Exception:
                            log.exception(
                                "Failed to remove unused journal entry %s",
                                entry.db_id,
                            )
                    else:
                        log.warning(
                            "Retaining journal entry %s after ambiguous failure",
                            entry.db_id,
                        )
                errors += 1

        # CSV/JSON are human-readable end-of-run summaries. SQLite above is
        # the crash-safe undo journal and is committed before every mutation.
        if entries:
            self._write_logs(entries, now)

        log.info("Apply complete: %d processed, %d errors", processed, errors)
        return processed, errors

    @property
    def applied_cluster_ids(self) -> set[str]:
        """Clusters with completed work and no failed file operations."""
        return self.processed_cluster_ids - self.failed_cluster_ids

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
        resolved_entry_ids: list[int] = []

        # Reverse order for undo
        for entry in reversed(entries):
            try:
                # Cannot undo permanent deletes (sent to Recycle Bin)
                if entry.verdict == "DELETE":
                    log.info("Skipping deleted file (in Recycle Bin): %s", entry.original_path)
                    skipped += 1
                    if entry.db_id is not None:
                        # Recycle Bin operations cannot be retried by app Undo;
                        # the end-of-run JSON remains the permanent audit log.
                        resolved_entry_ids.append(entry.db_id)
                    continue

                if not os.path.isfile(extended_path(entry.destination_path)):
                    if os.path.isfile(extended_path(entry.original_path)):
                        # Crash after journaling but before the move, or the
                        # user already restored it manually: desired state is
                        # satisfied, so this journal row is resolved.
                        log.info("File already at original path: %s", entry.original_path)
                        self.store.update_photo_path(
                            entry.photo_id, entry.original_path,
                        )
                        restored += 1
                        if entry.db_id is not None:
                            resolved_entry_ids.append(entry.db_id)
                    else:
                        log.warning("File no longer at destination: %s", entry.destination_path)
                        skipped += 1
                    continue

                # Ensure original directory exists
                orig_dir = os.path.dirname(entry.original_path)
                os.makedirs(extended_path(orig_dir), exist_ok=True)

                # Never overwrite whatever now occupies the original path —
                # move_no_overwrite suffixes _1, _2, ... when it is taken.
                restore_path = move_no_overwrite(
                    entry.destination_path, entry.original_path,
                )
                if restore_path != entry.original_path:
                    log.warning(
                        "Original path occupied, restored to: %s", restore_path
                    )
                self.store.update_photo_path(entry.photo_id, restore_path)
                restored += 1
                if entry.db_id is not None:
                    resolved_entry_ids.append(entry.db_id)

            except Exception as e:
                log.error("Failed to undo move for %s: %s", entry.photo_id, e)
                skipped += 1

        # Keep unresolved rows (locked/missing files) so Undo remains
        # available and can retry them later.
        self.store.delete_apply_log_entries(resolved_entry_ids)

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
