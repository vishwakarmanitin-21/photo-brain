import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import SessionStatus
from app.core.session_store import SessionStore
from app.workers.scan_worker import ScanWorker
from app.util.paths import get_db_path


def _write_image(folder: str, name: str, color: tuple[int, int, int]) -> str:
    path = os.path.join(folder, name)
    Image.new("RGB", (64, 48), color).save(path, quality=85)
    return path


class ScanResetTests(unittest.TestCase):
    """SAFE-11: cancelled or failed scans must not leave a half-written
    session stuck in SCANNING."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_worker(self, source: str, store: SessionStore) -> ScanWorker:
        store.create_session("scan-1", source)
        return ScanWorker(
            source, store, "scan-1", face_detection_enabled=False
        )

    def test_cancelled_scan_discards_session(self):
        with tempfile.TemporaryDirectory() as source:
            _write_image(source, "a.jpg", (200, 30, 30))
            store = SessionStore(get_db_path(source))
            worker = self._make_worker(source, store)
            worker.cancel()

            worker.run()  # synchronous: QThread.run without start()

            self.assertIsNone(store.get_session())
            self.assertEqual([], store.get_photos_by_session("scan-1"))
            store.close()

    def test_failed_scan_discards_session(self):
        with tempfile.TemporaryDirectory() as source:
            _write_image(source, "a.jpg", (30, 200, 30))
            store = SessionStore(get_db_path(source))
            worker = self._make_worker(source, store)

            errors = []
            worker.scan_error.connect(errors.append)
            with patch(
                "app.workers.scan_worker.compute_hashes",
                side_effect=RuntimeError("disk on fire"),
            ):
                worker.run()

            self.assertEqual(["disk on fire"], errors)
            self.assertIsNone(store.get_session())
            store.close()

    def test_successful_scan_keeps_session(self):
        with tempfile.TemporaryDirectory() as source:
            _write_image(source, "a.jpg", (30, 30, 200))
            _write_image(source, "b.jpg", (220, 220, 40))
            store = SessionStore(get_db_path(source))
            worker = self._make_worker(source, store)

            worker.run()

            session = store.get_session()
            self.assertIsNotNone(session)
            self.assertEqual(SessionStatus.SCANNED, session.status)
            self.assertEqual(
                2, len(store.get_photos_by_session("scan-1"))
            )
            store.close()

    def test_start_scan_clears_crash_leftover_without_warning(self):
        from PySide6.QtWidgets import QMessageBox
        from app.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as source:
            # Simulate a power-loss leftover: session frozen in SCANNING.
            store = SessionStore(get_db_path(source))
            store.create_session("stale", source)
            store.update_session_status("stale", SessionStatus.SCANNING)
            store.close()

            window = MainWindow()
            with patch("app.ui.main_window.setup_logging"), patch(
                    "app.ui.main_window.QMessageBox.warning",
                    return_value=QMessageBox.No,
                ) as warning, patch(
                    "app.ui.main_window.ScanWorker"
                ) as worker_cls:
                window._start_scan(source)

            warning.assert_not_called()
            worker_cls.return_value.start.assert_called_once()
            session = window.store.get_session()
            self.assertIsNotNone(session)
            self.assertNotEqual("stale", session.id)
            window.store.close()
            window.store = None
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
