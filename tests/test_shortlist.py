"""O2: best-of shortlist selection + keeper export (copy, originals intact)."""
import os
import tempfile
import unittest

from app.core.models import Photo, Verdict
from app.core.shortlist import select_top_n_global, select_best_per_event
from app.core.file_ops import export_photos
from app.util.paths import copy_no_overwrite


def _photo(pid, score=0.5, event=None, path=None):
    return Photo(id=pid, filepath=path or f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=10, quality_score=score, event_id=event,
                 verdict=Verdict.REVIEW)


class SelectionTests(unittest.TestCase):
    def test_top_n_global(self):
        ps = [_photo("a", 0.2), _photo("b", 0.9), _photo("c", 0.5)]
        self.assertEqual(["b", "c"], [p.id for p in select_top_n_global(ps, 2)])
        self.assertEqual([], select_top_n_global(ps, 0))

    def test_best_per_event_one_each(self):
        ps = [
            _photo("e1_hi", 0.8, event="E1"), _photo("e1_lo", 0.3, event="E1"),
            _photo("e2_hi", 0.6, event="E2"), _photo("e2_lo", 0.1, event="E2"),
        ]
        best = select_best_per_event(ps, 1)
        self.assertEqual({"e1_hi", "e2_hi"}, {p.id for p in best})

    def test_best_per_event_groups_undated_together(self):
        ps = [_photo("u1", 0.9), _photo("u2", 0.4)]  # both event_id=None
        best = select_best_per_event(ps, 1)
        self.assertEqual(["u1"], [p.id for p in best])


class ExportTests(unittest.TestCase):
    def test_export_copies_and_leaves_originals(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            paths = []
            for name in ("k1.jpg", "k2.jpg"):
                fp = os.path.join(src, name)
                with open(fp, "wb") as f:
                    f.write(b"data-" + name.encode())
                paths.append(fp)
            keepers = [_photo("k1", path=paths[0]), _photo("k2", path=paths[1])]

            copied, errors = export_photos(keepers, dst)
            self.assertEqual((2, 0), (copied, errors))
            # copies exist in dst
            self.assertTrue(os.path.isfile(os.path.join(dst, "k1.jpg")))
            self.assertTrue(os.path.isfile(os.path.join(dst, "k2.jpg")))
            # originals untouched
            self.assertTrue(os.path.isfile(paths[0]))
            self.assertTrue(os.path.isfile(paths[1]))

    def test_export_counts_missing_source_as_error(self):
        with tempfile.TemporaryDirectory() as dst:
            copied, errors = export_photos([_photo("gone", path="C:/nope/x.jpg")], dst)
            self.assertEqual((0, 1), (copied, errors))

    def test_copy_no_overwrite_suffixes_on_clash(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "s.jpg")
            with open(src, "wb") as f:
                f.write(b"x")
            dest = os.path.join(d, "out.jpg")
            first = copy_no_overwrite(src, dest)
            second = copy_no_overwrite(src, dest)
            self.assertEqual(dest, first)
            self.assertNotEqual(first, second)  # got a _1 suffix
            self.assertTrue(os.path.isfile(second))


if __name__ == "__main__":
    unittest.main()
