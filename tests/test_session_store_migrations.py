import os
import sqlite3
import tempfile
import unittest

from app.core.session_store import SessionStore, SCHEMA_VERSION


# A faithful v1 schema: the base tables before any migration — no `events`
# table, none of the face/expression/event columns, no `applied` flag.
_V1_SCHEMA = """
CREATE TABLE session (
    id TEXT PRIMARY KEY, source_folder TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, total_files INTEGER DEFAULT 0,
    scanned_files INTEGER DEFAULT 0, phash_threshold INTEGER DEFAULT 17,
    keep_per_cluster INTEGER DEFAULT 2, last_apply_log TEXT
);
CREATE TABLE photos (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, filepath TEXT NOT NULL,
    filename TEXT NOT NULL, file_size INTEGER NOT NULL, sha256 TEXT, phash TEXT,
    sharpness REAL DEFAULT 0.0, brightness REAL DEFAULT 0.0,
    quality_score REAL DEFAULT 0.0, cluster_id TEXT,
    verdict TEXT DEFAULT 'REVIEW', dup_type TEXT DEFAULT 'none',
    user_override INTEGER DEFAULT 0, thumb_path TEXT, scan_order INTEGER DEFAULT 0
);
CREATE TABLE clusters (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, label TEXT NOT NULL,
    representative_photo_id TEXT, member_count INTEGER DEFAULT 0,
    keep_count INTEGER DEFAULT 0, delete_count INTEGER DEFAULT 0,
    is_exact_dup_group INTEGER DEFAULT 0, reviewed INTEGER DEFAULT 0
);
CREATE TABLE apply_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    photo_id TEXT NOT NULL, original_path TEXT NOT NULL,
    destination_path TEXT NOT NULL, verdict TEXT NOT NULL,
    dup_type TEXT NOT NULL DEFAULT 'none', destination_folder TEXT NOT NULL,
    cluster_id TEXT NOT NULL DEFAULT '', timestamp TEXT NOT NULL
);
"""


def _columns(path, table):
    conn = sqlite3.connect(path)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _user_version(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class MigrationChainTests(unittest.TestCase):
    """TEST-01: the v1→v8 migration chain must upgrade an old database in
    place without data loss."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = os.path.join(self._dir.name, "photobrain.db")

    def _write_v1(self):
        conn = sqlite3.connect(self.path)
        conn.executescript(_V1_SCHEMA)
        conn.execute(
            "INSERT INTO session (id, source_folder, status, created_at, "
            "updated_at) VALUES ('s1','C:/x','NEW','t','t')")
        # A DELETE verdict exercises the v2→v3 rename to ARCHIVE.
        conn.execute(
            "INSERT INTO photos (id, session_id, filepath, filename, file_size, "
            "verdict, user_override) VALUES "
            "('p1','s1','C:/x/a.jpg','a.jpg',10,'DELETE',0)")
        conn.execute(
            "INSERT INTO clusters (id, session_id, label) "
            "VALUES ('c1','s1','Cluster 1')")
        conn.execute("PRAGMA user_version=0")
        conn.commit()
        conn.close()

    def test_v1_database_upgrades_to_current(self):
        self._write_v1()
        store = SessionStore(self.path)
        store.close()

        self.assertEqual(SCHEMA_VERSION, _user_version(self.path))
        photo_cols = _columns(self.path, "photos")
        for col in ("face_count", "exif_datetime", "event_id", "face_distance",
                    "subject_isolation", "expression_naturalness",
                    "head_pose_frontal"):
            self.assertIn(col, photo_cols)
        self.assertIn("applied", _columns(self.path, "clusters"))
        session_cols = _columns(self.path, "session")
        self.assertIn("event_gap_hours", session_cols)
        self.assertIn("face_detection_enabled", session_cols)
        # events table created by the v1→v2 step
        self.assertIn("events", _table_names(self.path))

    def test_v1_data_survives_and_delete_becomes_archive(self):
        self._write_v1()
        SessionStore(self.path).close()
        conn = sqlite3.connect(self.path)
        try:
            verdict = conn.execute(
                "SELECT verdict FROM photos WHERE id='p1'").fetchone()[0]
        finally:
            conn.close()
        # v2→v3 renamed the auto-suggested DELETE to ARCHIVE, row preserved.
        self.assertEqual("ARCHIVE", verdict)

    def test_fresh_database_starts_at_current_version(self):
        store = SessionStore(self.path)
        store.close()
        self.assertEqual(SCHEMA_VERSION, _user_version(self.path))
        self.assertIn("applied", _columns(self.path, "clusters"))

    def test_reopening_current_db_is_idempotent(self):
        SessionStore(self.path).close()
        # Reopen — must not error or downgrade.
        SessionStore(self.path).close()
        self.assertEqual(SCHEMA_VERSION, _user_version(self.path))


def _table_names(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
