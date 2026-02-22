"""SQLite persistence layer for PhotoBrain sessions."""
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app.core.models import (
    Photo, Cluster, Event, SessionState, ApplyLogEntry,
    Verdict, DupType, FaceDistance, SessionStatus,
)

log = logging.getLogger("photobrain.session_store")

SCHEMA_VERSION = 8

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    source_folder TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    total_files INTEGER DEFAULT 0,
    scanned_files INTEGER DEFAULT 0,
    phash_threshold INTEGER DEFAULT 12,
    keep_per_cluster INTEGER DEFAULT 2,
    last_apply_log TEXT,
    event_gap_hours REAL DEFAULT 4.0,
    face_detection_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS photos (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    filepath TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    sha256 TEXT,
    phash TEXT,
    sharpness REAL DEFAULT 0.0,
    brightness REAL DEFAULT 0.0,
    quality_score REAL DEFAULT 0.0,
    cluster_id TEXT,
    verdict TEXT DEFAULT 'REVIEW',
    dup_type TEXT DEFAULT 'none',
    user_override INTEGER DEFAULT 0,
    thumb_path TEXT,
    scan_order INTEGER DEFAULT 0,
    face_count INTEGER DEFAULT 0,
    face_area_ratio REAL DEFAULT 0.0,
    face_distance TEXT DEFAULT 'none',
    eyes_open_score REAL DEFAULT 0.0,
    smile_score REAL DEFAULT 0.0,
    subject_isolation REAL DEFAULT 0.0,
    expression_naturalness REAL DEFAULT 0.0,
    head_pose_frontal REAL DEFAULT 0.0,
    exif_datetime TEXT,
    event_id TEXT,
    FOREIGN KEY (session_id) REFERENCES session(id)
);

CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    label TEXT NOT NULL,
    representative_photo_id TEXT,
    member_count INTEGER DEFAULT 0,
    keep_count INTEGER DEFAULT 0,
    delete_count INTEGER DEFAULT 0,
    is_exact_dup_group INTEGER DEFAULT 0,
    reviewed INTEGER DEFAULT 0,
    applied INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES session(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    label TEXT NOT NULL,
    start_datetime TEXT,
    end_datetime TEXT,
    photo_count INTEGER DEFAULT 0,
    FOREIGN KEY (session_id) REFERENCES session(id)
);

CREATE TABLE IF NOT EXISTS apply_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    photo_id TEXT NOT NULL,
    original_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    verdict TEXT NOT NULL,
    dup_type TEXT NOT NULL DEFAULT 'none',
    destination_folder TEXT NOT NULL,
    cluster_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES session(id)
);

CREATE INDEX IF NOT EXISTS idx_photos_session ON photos(session_id);
CREATE INDEX IF NOT EXISTS idx_photos_sha256 ON photos(sha256);
CREATE INDEX IF NOT EXISTS idx_photos_cluster ON photos(cluster_id);
CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id);
CREATE INDEX IF NOT EXISTS idx_clusters_session ON clusters(session_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_apply_log_session ON apply_log(session_id);
"""

# Migration from v1 to v2
MIGRATION_V1_TO_V2 = [
    "ALTER TABLE photos ADD COLUMN face_count INTEGER DEFAULT 0",
    "ALTER TABLE photos ADD COLUMN face_area_ratio REAL DEFAULT 0.0",
    "ALTER TABLE photos ADD COLUMN exif_datetime TEXT",
    "ALTER TABLE photos ADD COLUMN event_id TEXT",
    "ALTER TABLE session ADD COLUMN event_gap_hours REAL DEFAULT 4.0",
    "ALTER TABLE session ADD COLUMN face_detection_enabled INTEGER DEFAULT 1",
    """CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        label TEXT NOT NULL,
        start_datetime TEXT,
        end_datetime TEXT,
        photo_count INTEGER DEFAULT 0,
        FOREIGN KEY (session_id) REFERENCES session(id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)",
]

# Migration from v2 to v3: rename auto-suggested DELETE verdicts to ARCHIVE
MIGRATION_V2_TO_V3 = [
    # Convert old DELETE verdicts (auto-suggested, not user-overridden) to ARCHIVE
    "UPDATE photos SET verdict='ARCHIVE' WHERE verdict='DELETE' AND user_override=0",
]

# Migration from v3 to v4: add face_distance column
MIGRATION_V3_TO_V4 = [
    "ALTER TABLE photos ADD COLUMN face_distance TEXT DEFAULT 'none'",
    # Backfill: photos with faces detected are assumed "close" (short-range was the only model)
    "UPDATE photos SET face_distance='close' WHERE face_count > 0",
]

# Migration from v4 to v5: add expression scores
MIGRATION_V4_TO_V5 = [
    "ALTER TABLE photos ADD COLUMN eyes_open_score REAL DEFAULT 0.0",
    "ALTER TABLE photos ADD COLUMN smile_score REAL DEFAULT 0.0",
]

# Migration from v5 to v6: add subject isolation score
MIGRATION_V5_TO_V6 = [
    "ALTER TABLE photos ADD COLUMN subject_isolation REAL DEFAULT 0.0",
]

# Migration from v6 to v7: add expression naturalness and head pose
MIGRATION_V6_TO_V7 = [
    "ALTER TABLE photos ADD COLUMN expression_naturalness REAL DEFAULT 0.0",
    "ALTER TABLE photos ADD COLUMN head_pose_frontal REAL DEFAULT 0.0",
]

# Migration from v7 to v8: add applied flag to clusters
MIGRATION_V7_TO_V8 = [
    "ALTER TABLE clusters ADD COLUMN applied INTEGER DEFAULT 0",
]


class SessionStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]

        if version == 0:
            # Fresh database or v1 without version tracking
            # Check if tables already exist (v1 database)
            tables = {
                r[0] for r in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "photos" in tables and "events" not in tables:
                # v1 database — run migration to v2
                log.info("Migrating database from v1 to v2")
                for sql in MIGRATION_V1_TO_V2:
                    try:
                        self._conn.execute(sql)
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                            log.warning("Migration statement failed: %s", e)
                self._conn.commit()
                version = 2  # continue to v2→v3 migration below
            elif "photos" in tables:
                # v2 database without version set
                version = 2
            else:
                # Fresh database
                self._conn.executescript(SCHEMA_V2)
                self._conn.commit()
                version = SCHEMA_VERSION  # skip migrations

        if version == 2:
            log.info("Migrating database from v2 to v3 (DELETE → ARCHIVE)")
            for sql in MIGRATION_V2_TO_V3:
                self._conn.execute(sql)
            self._conn.commit()
            version = 3

        if version == 3:
            log.info("Migrating database from v3 to v4 (add face_distance)")
            for sql in MIGRATION_V3_TO_V4:
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)
            self._conn.commit()
            version = 4

        if version == 4:
            log.info("Migrating database from v4 to v5 (add expression scores)")
            for sql in MIGRATION_V4_TO_V5:
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)
            self._conn.commit()
            version = 5

        if version == 5:
            log.info("Migrating database from v5 to v6 (add subject isolation)")
            for sql in MIGRATION_V5_TO_V6:
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)
            self._conn.commit()
            version = 6

        if version == 6:
            log.info("Migrating database from v6 to v7 (add expression naturalness, head pose)")
            for sql in MIGRATION_V6_TO_V7:
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)
            self._conn.commit()
            version = 7

        if version == 7:
            log.info("Migrating database from v7 to v8 (add applied flag to clusters)")
            for sql in MIGRATION_V7_TO_V8:
                try:
                    self._conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        log.warning("Migration statement failed: %s", e)
            self._conn.commit()

        self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._conn.commit()

    def close(self):
        self._conn.close()

    @contextmanager
    def _transaction(self):
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ── Session ──────────────────────────────────────────

    def create_session(
        self, session_id: str, source_folder: str,
        threshold: int = 8, keep_count: int = 2,
        event_gap_hours: float = 4.0, face_detection: bool = True,
    ) -> SessionState:
        now = datetime.now(timezone.utc).isoformat()
        session = SessionState(
            id=session_id, source_folder=source_folder,
            status=SessionStatus.NEW, created_at=now, updated_at=now,
            phash_threshold=threshold, keep_per_cluster=keep_count,
            event_gap_hours=event_gap_hours,
            face_detection_enabled=face_detection,
        )
        with self._transaction() as conn:
            conn.execute(
                """INSERT INTO session
                   (id, source_folder, status, created_at, updated_at,
                    total_files, scanned_files, phash_threshold, keep_per_cluster,
                    last_apply_log, event_gap_hours, face_detection_enabled)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session.id, session.source_folder, session.status.value,
                 session.created_at, session.updated_at,
                 session.total_files, session.scanned_files,
                 session.phash_threshold, session.keep_per_cluster,
                 session.last_apply_log, session.event_gap_hours,
                 int(session.face_detection_enabled)),
            )
        return session

    def get_session(self) -> Optional[SessionState]:
        row = self._conn.execute(
            "SELECT * FROM session ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def update_session_status(self, session_id: str, status: SessionStatus):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE session SET status=?, updated_at=? WHERE id=?",
            (status.value, now, session_id),
        )
        self._conn.commit()

    def update_session_progress(self, session_id: str, total: int, scanned: int):
        self._conn.execute(
            "UPDATE session SET total_files=?, scanned_files=? WHERE id=?",
            (total, scanned, session_id),
        )
        self._conn.commit()

    def update_session_apply_log(self, session_id: str, log_path: str):
        self._conn.execute(
            "UPDATE session SET last_apply_log=? WHERE id=?",
            (log_path, session_id),
        )
        self._conn.commit()

    # ── Photos ───────────────────────────────────────────

    def insert_photos_batch(self, session_id: str, photos: list[Photo]):
        with self._transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO photos
                   (id, session_id, filepath, filename, file_size,
                    sha256, phash, sharpness, brightness, quality_score,
                    cluster_id, verdict, dup_type, user_override, thumb_path,
                    scan_order, face_count, face_area_ratio, face_distance,
                    eyes_open_score, smile_score, subject_isolation,
                    expression_naturalness, head_pose_frontal,
                    exif_datetime, event_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (p.id, session_id, p.filepath, p.filename, p.file_size,
                     p.sha256, p.phash, p.sharpness, p.brightness, p.quality_score,
                     p.cluster_id, p.verdict.value, p.dup_type.value,
                     int(p.user_override), p.thumb_path, p.scan_order,
                     p.face_count, p.face_area_ratio, p.face_distance.value,
                     p.eyes_open_score, p.smile_score, p.subject_isolation,
                     p.expression_naturalness, p.head_pose_frontal,
                     p.exif_datetime, p.event_id)
                    for p in photos
                ],
            )

    def get_photos_by_session(self, session_id: str) -> list[Photo]:
        rows = self._conn.execute(
            "SELECT * FROM photos WHERE session_id=? ORDER BY scan_order",
            (session_id,),
        ).fetchall()
        return [self._row_to_photo(r) for r in rows]

    def get_photos_by_cluster(self, cluster_id: str) -> list[Photo]:
        rows = self._conn.execute(
            "SELECT * FROM photos WHERE cluster_id=? ORDER BY quality_score DESC",
            (cluster_id,),
        ).fetchall()
        return [self._row_to_photo(r) for r in rows]

    def update_photo_verdict(
        self, photo_id: str, verdict: Verdict, user_override: bool = True
    ):
        self._conn.execute(
            "UPDATE photos SET verdict=?, user_override=? WHERE id=?",
            (verdict.value, int(user_override), photo_id),
        )
        self._conn.commit()

    def update_photos_batch(self, photos: list[Photo]):
        with self._transaction() as conn:
            conn.executemany(
                """UPDATE photos SET sha256=?, phash=?, sharpness=?, brightness=?,
                   quality_score=?, cluster_id=?, verdict=?, dup_type=?,
                   user_override=?, thumb_path=?, face_count=?, face_area_ratio=?,
                   face_distance=?, eyes_open_score=?, smile_score=?,
                   subject_isolation=?, expression_naturalness=?, head_pose_frontal=?,
                   exif_datetime=?, event_id=?
                   WHERE id=?""",
                [
                    (p.sha256, p.phash, p.sharpness, p.brightness,
                     p.quality_score, p.cluster_id, p.verdict.value,
                     p.dup_type.value, int(p.user_override), p.thumb_path,
                     p.face_count, p.face_area_ratio, p.face_distance.value,
                     p.eyes_open_score, p.smile_score, p.subject_isolation,
                     p.expression_naturalness, p.head_pose_frontal,
                     p.exif_datetime, p.event_id, p.id)
                    for p in photos
                ],
            )

    # ── Clusters ─────────────────────────────────────────

    def insert_clusters_batch(self, session_id: str, clusters: list[Cluster]):
        with self._transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO clusters
                   (id, session_id, label, representative_photo_id,
                    member_count, keep_count, delete_count,
                    is_exact_dup_group, reviewed, applied)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    (c.id, session_id, c.label, c.representative_photo_id,
                     c.member_count, c.keep_count, c.delete_count,
                     int(c.is_exact_dup_group), int(c.reviewed), int(c.applied))
                    for c in clusters
                ],
            )

    def get_clusters_by_session(self, session_id: str) -> list[Cluster]:
        rows = self._conn.execute(
            "SELECT * FROM clusters WHERE session_id=? ORDER BY member_count DESC",
            (session_id,),
        ).fetchall()
        return [self._row_to_cluster(r) for r in rows]

    def update_cluster_counts(self, cluster_id: str, keep: int, delete: int):
        self._conn.execute(
            "UPDATE clusters SET keep_count=?, delete_count=? WHERE id=?",
            (keep, delete, cluster_id),
        )
        self._conn.commit()

    def update_cluster_reviewed(self, cluster_id: str, reviewed: bool):
        self._conn.execute(
            "UPDATE clusters SET reviewed=? WHERE id=?",
            (int(reviewed), cluster_id),
        )
        self._conn.commit()

    def update_cluster_applied(self, cluster_id: str, applied: bool):
        self._conn.execute(
            "UPDATE clusters SET applied=? WHERE id=?",
            (int(applied), cluster_id),
        )
        self._conn.commit()

    # ── Events ───────────────────────────────────────────

    def insert_events_batch(self, session_id: str, events: list[Event]):
        with self._transaction() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO events
                   (id, session_id, label, start_datetime, end_datetime, photo_count)
                   VALUES (?,?,?,?,?,?)""",
                [
                    (e.id, session_id, e.label, e.start_datetime,
                     e.end_datetime, e.photo_count)
                    for e in events
                ],
            )

    def get_events_by_session(self, session_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE session_id=? ORDER BY start_datetime",
            (session_id,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    # ── Apply Log ────────────────────────────────────────

    def insert_apply_log_batch(self, session_id: str, entries: list[ApplyLogEntry]):
        with self._transaction() as conn:
            conn.executemany(
                """INSERT INTO apply_log
                   (session_id, photo_id, original_path, destination_path,
                    verdict, dup_type, destination_folder, cluster_id, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (session_id, e.photo_id, e.original_path, e.destination_path,
                     e.verdict, e.dup_type, e.destination_folder,
                     e.cluster_id, e.timestamp)
                    for e in entries
                ],
            )

    def get_apply_log(self, session_id: str) -> list[ApplyLogEntry]:
        rows = self._conn.execute(
            "SELECT * FROM apply_log WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            ApplyLogEntry(
                photo_id=r["photo_id"],
                original_path=r["original_path"],
                destination_path=r["destination_path"],
                verdict=r["verdict"],
                dup_type=r["dup_type"],
                destination_folder=r["destination_folder"],
                cluster_id=r["cluster_id"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    def clear_apply_log(self, session_id: str):
        self._conn.execute(
            "DELETE FROM apply_log WHERE session_id=?", (session_id,),
        )
        self._conn.commit()

    def delete_session_data(self, session_id: str):
        with self._transaction() as conn:
            conn.execute("DELETE FROM apply_log WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM photos WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM clusters WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM session WHERE id=?", (session_id,))

    # ── Row mapping ──────────────────────────────────────

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> SessionState:
        return SessionState(
            id=row["id"],
            source_folder=row["source_folder"],
            status=SessionStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            total_files=row["total_files"],
            scanned_files=row["scanned_files"],
            phash_threshold=row["phash_threshold"],
            keep_per_cluster=row["keep_per_cluster"],
            last_apply_log=row["last_apply_log"],
            event_gap_hours=row["event_gap_hours"],
            face_detection_enabled=bool(row["face_detection_enabled"]),
        )

    @staticmethod
    def _row_to_photo(row: sqlite3.Row) -> Photo:
        return Photo(
            id=row["id"],
            filepath=row["filepath"],
            filename=row["filename"],
            file_size=row["file_size"],
            sha256=row["sha256"],
            phash=row["phash"],
            sharpness=row["sharpness"],
            brightness=row["brightness"],
            quality_score=row["quality_score"],
            cluster_id=row["cluster_id"],
            verdict=Verdict(row["verdict"]),
            dup_type=DupType(row["dup_type"]),
            user_override=bool(row["user_override"]),
            thumb_path=row["thumb_path"],
            scan_order=row["scan_order"],
            face_count=row["face_count"],
            face_area_ratio=row["face_area_ratio"],
            face_distance=FaceDistance(row["face_distance"]) if row["face_distance"] else FaceDistance.NONE,
            eyes_open_score=row["eyes_open_score"] or 0.0,
            smile_score=row["smile_score"] or 0.0,
            subject_isolation=row["subject_isolation"] or 0.0,
            expression_naturalness=row["expression_naturalness"] or 0.0,
            head_pose_frontal=row["head_pose_frontal"] or 0.0,
            exif_datetime=row["exif_datetime"],
            event_id=row["event_id"],
        )

    @staticmethod
    def _row_to_cluster(row: sqlite3.Row) -> Cluster:
        # Handle optional 'applied' column for backward compatibility
        try:
            applied = bool(row["applied"])
        except (KeyError, IndexError):
            applied = False

        return Cluster(
            id=row["id"],
            label=row["label"],
            representative_photo_id=row["representative_photo_id"],
            member_count=row["member_count"],
            keep_count=row["keep_count"],
            delete_count=row["delete_count"],
            is_exact_dup_group=bool(row["is_exact_dup_group"]),
            reviewed=bool(row["reviewed"]),
            applied=applied,
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            label=row["label"],
            start_datetime=row["start_datetime"],
            end_datetime=row["end_datetime"],
            photo_count=row["photo_count"],
        )
