import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.review_view import ReviewView, cluster_display_label


def _cluster(cid, count, exact=False, reviewed=False, applied=False):
    c = Cluster(id=cid, label=f"Cluster {cid}", member_count=count,
                is_exact_dup_group=exact)
    c.reviewed = reviewed
    c.applied = applied
    return c


def _photo(pid, cid, verdict=Verdict.KEEP):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, quality_score=0.5, verdict=verdict, cluster_id=cid)


class ClusterLabelTests(unittest.TestCase):
    """UX-08: plain-language labels, no [EXACT]/[OK]/[APPLIED] jargon."""

    def test_exact_group(self):
        self.assertEqual("Exact duplicates (3)",
                         cluster_display_label(_cluster("a", 3, exact=True)))

    def test_similar_group(self):
        self.assertEqual("Similar shots (4)",
                         cluster_display_label(_cluster("a", 4)))

    def test_single_photo(self):
        self.assertEqual("Single photo (1)",
                         cluster_display_label(_cluster("a", 1)))

    def test_reviewed_and_applied_suffixes(self):
        self.assertIn("✓ reviewed",
                      cluster_display_label(_cluster("a", 2, reviewed=True)))
        self.assertIn("✓ applied",
                      cluster_display_label(_cluster("a", 2, reviewed=True, applied=True)))


class HideSingletonTests(unittest.TestCase):
    """UX-08: single auto-keep photos are hidden by default."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        clusters = [
            _cluster("dup", 2, exact=True),
            _cluster("solo_keep", 1),
            _cluster("solo_delete", 1),
        ]
        photos = {
            "dup": [_photo("d1", "dup"), _photo("d2", "dup")],
            "solo_keep": [_photo("s1", "solo_keep", Verdict.KEEP)],
            "solo_delete": [_photo("s2", "solo_delete", Verdict.DELETE)],
        }
        rv.load_data(clusters, photos, has_undo=False, events=[])
        return rv

    def test_single_keep_hidden_by_default(self):
        rv = self._view()
        ids = [c.id for c in rv._clusters]
        self.assertIn("dup", ids)
        self.assertIn("solo_delete", ids)      # needs a decision → stays
        self.assertNotIn("solo_keep", ids)     # nothing to decide → hidden

    def test_unchecking_shows_all(self):
        rv = self._view()
        rv._hide_singletons.setChecked(False)
        ids = [c.id for c in rv._clusters]
        self.assertIn("solo_keep", ids)


if __name__ == "__main__":
    unittest.main()
