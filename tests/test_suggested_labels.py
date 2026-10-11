"""Suggested labels (Claude pre-labels, Nitin reviews): suggestions are kept
apart from labels, count only once a page is confirmed, are shown first and
marked in the window, and their acceptance rate is reported."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.ranking_eval import LabelStore, Moment, labels_path, suggestion_agreement
from app.ui.ranking_label_window import RankingLabelWindow


class SuggestionStoreTests(unittest.TestCase):
    def test_suggestions_are_not_labels_until_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            store = LabelStore(os.path.join(d, "l.json"))
            m = Moment("a", ("a", "b", "c"), None)
            store.suggest_moment(m, {"b": "best", "c": "junk"}, by="claude")
            store.save()
            again = LabelStore(os.path.join(d, "l.json"))
            self.assertEqual({}, again.labels)                       # nothing counts yet
            self.assertEqual("keep", again.suggestion_for("a"))      # unmarked -> keep
            self.assertEqual({"a"}, again.pending_suggested_moments())
            # The person confirms, changing c from junk to redundant.
            again.record_moment(m, {"b": "best", "c": "redundant"}, {})
            self.assertEqual(set(), again.pending_suggested_moments())
            self.assertEqual("junk", again.labels["c"]["suggested"])
            self.assertEqual("redundant", again.labels["c"]["label"])
            self.assertEqual("claude", again.labels["b"]["suggested_by"])

    def test_agreement_report(self):
        labels = {
            "a": {"label": "keep", "suggested": "keep", "moment": "m1"},
            "b": {"label": "best", "suggested": "best", "moment": "m1"},
            "c": {"label": "best", "suggested": "keep", "moment": "m2"},   # best moved
            "d": {"label": "keep", "suggested": "best", "moment": "m2"},
            "e": {"label": "junk", "moment": "m3"},                         # never suggested
        }
        r = suggestion_agreement(labels)
        self.assertEqual(4, r["photos"])
        self.assertEqual(2, r["photos_changed"])
        self.assertEqual(0.5, r["kept_rate"])
        self.assertEqual(2, r["moments"])
        self.assertEqual(1, r["moments_best_changed"])
        self.assertEqual(["c", "d"], r["changed_examples"])


def _shot(folder, name, when, color):
    exif = Image.Exif()
    exif[306] = when
    Image.new("RGB", (80, 60), color).save(os.path.join(folder, name), exif=exif)


class SuggestionWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, cond, timeout=10):
        end = time.time() + timeout
        while time.time() < end and not cond():
            self.app.processEvents()
            time.sleep(0.02)
        return cond()

    def test_suggested_burst_comes_first_prefilled_and_confirmed_by_enter(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as local:
            for i in range(3):   # three bursts on different days
                _shot(root, f"d{i}a.jpg", f"2024:08:1{i} 07:00:00", (200, 40, 40))
                _shot(root, f"d{i}b.jpg", f"2024:08:1{i} 07:00:04", (40, 200, 40))
            store = LabelStore(labels_path(root))
            store.suggest_moment(Moment("d2a.jpg", ("d2a.jpg", "d2b.jpg"), None),
                                 {"d2b.jpg": "best", "d2a.jpg": "redundant"}, by="claude")
            store.save()
            with patch.dict(os.environ, {"LOCALAPPDATA": local}):
                w = RankingLabelWindow(root)
                w.show()
                w.activateWindow()
                self.addCleanup(w.close)
                self.assertTrue(self._wait(lambda: bool(w.tiles)))
                # Claude's burst first, pre-filled and marked as a suggestion.
                self.assertEqual(["d2a.jpg", "d2b.jpg"], [t.rel for t in w.tiles])
                self.assertEqual({"d2a.jpg", "d2b.jpg"}, w.suggested_rels)
                self.assertIn("Claude's pick", w.tiles[1].badge.text())
                self.assertIn("Claude's suggestion", w.help.text())
                self.assertIn("1 of Claude's suggested bursts", w.status.text())
                # Nitin disagrees on one photo: its marker goes, the other stays.
                w._set("d2a.jpg", "keep")
                self.assertNotIn("Claude's pick", w.tiles[0].badge.text())
                self.assertIn("Claude's pick", w.tiles[1].badge.text())
                QTest.keyClick(w, Qt.Key_Return)   # confirm
                self.assertTrue(self._wait(lambda: "d2a.jpg" in w.store.labels))
                w.dirty = False
            saved = LabelStore(labels_path(root))
            self.assertEqual({"d2a.jpg": "keep", "d2b.jpg": "best"},
                             {r: e["label"] for r, e in saved.labels.items()})
            self.assertEqual("redundant", saved.labels["d2a.jpg"]["suggested"])
            self.assertEqual(set(), saved.pending_suggested_moments())


if __name__ == "__main__":
    unittest.main()
