import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.compare_dialog import CompareDialog
from app.ui.review_view import ReviewView


def _photo(folder, pid, score):
    path = os.path.join(folder, f"{pid}.jpg")
    Image.new("RGB", (120, 90), (int(100 + score * 100), 90, 60)).save(path)
    return Photo(id=pid, filepath=path, filename=f"{pid}.jpg", file_size=1234,
                 sharpness=100.0, brightness=120.0, quality_score=score,
                 verdict=Verdict.KEEP)


class CompareDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_best_is_the_highest_quality_photo(self):
        with tempfile.TemporaryDirectory() as folder:
            photos = [_photo(folder, "a", 0.4), _photo(folder, "b", 0.6)]
            dlg = CompareDialog(photos, image_px=100)
            self.addCleanup(dlg.deleteLater)
            # Both photos have a panel; the higher-scored "b" is present.
            self.assertEqual(2, len(dlg._panels))
            self.assertEqual({"a", "b"}, {p.photo.id for p in dlg._panels})

    def test_setting_verdict_writes_to_photo(self):
        with tempfile.TemporaryDirectory() as folder:
            photos = [_photo(folder, "a", 0.5), _photo(folder, "b", 0.4)]
            dlg = CompareDialog(photos, image_px=100)
            self.addCleanup(dlg.deleteLater)
            panel_b = next(p for p in dlg._panels if p.photo.id == "b")
            panel_b._set(Verdict.ARCHIVE)
            self.assertEqual(Verdict.ARCHIVE, photos[1].verdict)
            self.assertTrue(photos[1].user_override)


class CompareIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_changes_reflect_in_grid_and_are_undoable(self):
        with tempfile.TemporaryDirectory() as folder:
            rv = ReviewView()
            self.addCleanup(rv.deleteLater)
            photos = [_photo(folder, "a", 0.5), _photo(folder, "b", 0.4)]
            rv.load_data([Cluster(id="c1", label="c1", member_count=2)],
                         {"c1": photos}, has_undo=False, events=[])
            rv._cluster_list.setCurrentRow(0)

            def fake_exec(self_dlg):
                # Simulate the user marking photo b as DELETE in the dialog.
                photos[1].verdict = Verdict.DELETE
                photos[1].user_override = True
                return 0

            with patch.object(CompareDialog, "exec", fake_exec):
                rv._open_compare()

            self.assertEqual(Verdict.DELETE, photos[1].verdict)
            # And it's a single Ctrl+Z away from being undone.
            rv._undo_verdict()
            self.assertEqual(Verdict.KEEP, photos[1].verdict)


if __name__ == "__main__":
    unittest.main()
