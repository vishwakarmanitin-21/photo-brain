"""RANK-01: the blind labelling window indexes a folder, shows a burst, and
saves the person's labels (unmarked = keep) without showing any app score."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.ranking_eval import LabelStore, labels_path
from app.ui.ranking_label_window import RankingLabelWindow


def _shot(folder, name, when, color):
    exif = Image.Exif()
    exif[306] = when
    Image.new("RGB", (80, 60), color).save(os.path.join(folder, name), exif=exif)


class LabelWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, predicate, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.02)
        return False

    def test_label_a_burst_and_save(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            _shot(root, "b1.jpg", "2024:08:13 07:12:00", (200, 40, 40))
            _shot(root, "b2.jpg", "2024:08:13 07:12:04", (40, 200, 40))
            _shot(root, "b3.jpg", "2024:08:13 07:12:09", (40, 40, 200))
            _shot(root, "lone.jpg", "2024:09:01 10:00:00", (120, 120, 120))
            with patch.dict(os.environ, {"LOCALAPPDATA": local}):
                window = RankingLabelWindow(root)
                self.assertTrue(self._wait(lambda: bool(window.tiles)), "window never indexed")
                # The burst comes first, alone on its page.
                self.assertEqual(["b1.jpg", "b2.jpg", "b3.jpg"], [t.rel for t in window.tiles])
                self.assertTrue(window.title.text().startswith("Series 1 of 1"))
                self.assertTrue(self._wait(lambda: len(window.shas) == 3))
                # No score anywhere on screen: the labels must be the person's own.
                shown = " ".join(lbl.text() for lbl in window.findChildren(type(window.title)))
                for score_word in ("Quality", "/100", "score", "Score"):
                    self.assertNotIn(score_word, shown)

                window._click("b2.jpg")                       # star b2
                window.focus = 2
                QTest.keyClick(window, Qt.Key_4)              # b3 junk
                QTest.keyClick(window, Qt.Key_Return)         # save & next
                self.assertTrue(window.title.text().startswith("Single photos"))
                with patch.object(QMessageBox, "information"):
                    window._next()                           # last page
                window.close()

            store = LabelStore(labels_path(root))
            self.assertEqual({"b1.jpg": "keep", "b2.jpg": "best", "b3.jpg": "junk", "lone.jpg": "keep"},
                             {r: e["label"] for r, e in store.labels.items()})
            self.assertTrue(all(e["sha256"] for e in store.labels.values()))
            self.assertEqual("b1.jpg", store.labels["b3.jpg"]["moment"])

    def test_resume_starts_at_first_unlabelled_page(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            for i in range(2):  # two bursts, far apart
                _shot(root, f"x{i}a.jpg", f"2024:08:1{i} 07:00:00", (200, 40, 40))
                _shot(root, f"x{i}b.jpg", f"2024:08:1{i} 07:00:03", (40, 200, 40))
            with patch.dict(os.environ, {"LOCALAPPDATA": local}):
                first = RankingLabelWindow(root)
                self.assertTrue(self._wait(lambda: bool(first.tiles)))
                done = [t.rel for t in first.tiles]
                first._next()
                first.close()
                second = RankingLabelWindow(root)
                self.assertTrue(self._wait(lambda: bool(second.tiles)))
                self.assertNotEqual(done, [t.rel for t in second.tiles])
                self.assertEqual(1, second.page_idx)
                second.close()


if __name__ == "__main__":
    unittest.main()
