import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def _stuck_worker() -> Mock:
    worker = Mock()
    worker.isRunning.return_value = True
    worker.wait.return_value = False  # never finishes within the timeout
    return worker


class ShutdownGuardTests(unittest.TestCase):
    """SAFE-12(b): never close the session store under a live scan worker."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self) -> MainWindow:
        window = MainWindow()
        self.addCleanup(window.deleteLater)
        return window

    def test_close_event_skips_store_close_when_worker_stuck(self):
        window = self._window()
        window.store = Mock()
        window.scan_worker = _stuck_worker()

        window.closeEvent(Mock())

        window.scan_worker.cancel.assert_called_once()
        window.store.close.assert_not_called()
        window.store = None

    def test_close_event_closes_store_once_worker_stops(self):
        window = self._window()
        window.store = Mock()
        window.scan_worker = Mock()
        window.scan_worker.isRunning.return_value = True
        window.scan_worker.wait.return_value = True

        window.closeEvent(Mock())

        window.store.close.assert_called_once()
        window.store = None

    def test_start_scan_refuses_while_previous_worker_stuck(self):
        window = self._window()
        window.scan_worker = _stuck_worker()

        with tempfile.TemporaryDirectory() as source, patch(
            "app.ui.main_window.setup_logging"
        ), patch(
            "app.ui.main_window.QMessageBox.information"
        ) as info:
            window._start_scan(source)

        info.assert_called_once()
        self.assertIn("still shutting down", info.call_args.args[2])
        self.assertIsNone(window.store)


if __name__ == "__main__":
    unittest.main()
