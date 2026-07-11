import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.models import Photo, Verdict
from app.core.session_store import SessionStore
from app.ui.main_window import MainWindow
from app.util.paths import get_db_path


class NewScanConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cancelling_replacement_preserves_existing_session(self):
        with tempfile.TemporaryDirectory() as source:
            store = SessionStore(get_db_path(source))
            store.create_session("existing", source)
            photo = Photo(
                id="photo-1",
                filepath=os.path.join(source, "photo.jpg"),
                filename="photo.jpg",
                file_size=10,
                verdict=Verdict.DELETE,
                user_override=True,
            )
            store.insert_photos_batch("existing", [photo])
            self.assertEqual(1, store.count_user_decisions("existing"))
            store.close()

            window = MainWindow()
            with patch("app.ui.main_window.setup_logging"), patch(
                    "app.ui.main_window.QMessageBox.warning",
                    return_value=QMessageBox.No,
                ) as warning:
                window._start_scan(source)

            self.assertEqual("existing", window.store.get_session().id)
            self.assertIsNone(window.scan_worker)
            self.assertIn("1 manual photo decision", warning.call_args.args[2])
            window.store.close()
            window.store = None
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
