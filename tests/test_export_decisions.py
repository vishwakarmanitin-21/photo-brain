import csv
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView


def _photo(pid, verdict=Verdict.KEEP, score=0.6):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, quality_score=score, verdict=verdict, cluster_id="c1")


class ExportDecisionsTests(unittest.TestCase):
    """FEAT-05: pre-apply CSV export of every decision."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        c = Cluster(id="c1", label="c1", member_count=2, is_exact_dup_group=True)
        rv.load_data([c], {"c1": [_photo("a", Verdict.KEEP),
                                  _photo("b", Verdict.DELETE)]},
                     has_undo=False, events=[])
        return rv

    def test_export_writes_all_decisions(self):
        rv = self._view()
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "decisions.csv")
            with patch("app.ui.review_view.QFileDialog.getSaveFileName",
                       return_value=(out, "CSV files (*.csv)")), \
                 patch("app.ui.review_view.QMessageBox.information"):
                rv._export_decisions()

            with open(out, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        self.assertEqual(["group", "filename", "verdict", "quality_rating",
                          "filepath"], rows[0])
        body = {r[1]: r[2] for r in rows[1:]}
        self.assertEqual("KEEP", body["a.jpg"])
        self.assertEqual("DELETE", body["b.jpg"])
        self.assertIn("Exact duplicates", rows[1][0])

    def test_export_cancelled_writes_nothing(self):
        rv = self._view()
        with patch("app.ui.review_view.QFileDialog.getSaveFileName",
                   return_value=("", "")):
            rv._export_decisions()  # user cancelled → no exception, no file

    def test_open_log_signal_emits(self):
        rv = self._view()
        fired = []
        rv.open_log_requested.connect(lambda: fired.append(True))
        rv._open_log_btn.click()
        self.assertEqual([True], fired)


if __name__ == "__main__":
    unittest.main()
