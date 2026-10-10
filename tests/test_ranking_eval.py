"""RANK-01: ranking scorecard core — moments, labels file, metrics, gate."""
import json
import os
import tempfile
import unittest

from PIL import Image

from app.core.models import Photo, Verdict
from app.core.ranking_eval import (
    LabelStore, Moment, build_moments, compute_metrics, headline, index_root,
    labelling_order, regressions, scorer_fingerprint, SCORER_FILES,
)


def _photo(rel, score, verdict=Verdict.KEEP, sharp=500.0, bright=120.0):
    return Photo(id=rel, filepath=rel, filename=rel, file_size=1, quality_score=score,
                 verdict=verdict, sharpness=sharp, brightness=bright)


class MomentTests(unittest.TestCase):
    def test_splits_on_gap_and_keeps_bursts_together(self):
        entries = [
            ("b.jpg", "2024-08-13T07:12:05"), ("a.jpg", "2024-08-13T07:12:00"),
            ("c.jpg", "2024-08-13T07:12:14"),           # 9 s after b → same moment
            ("d.jpg", "2024-08-13T09:00:00"),           # far later → new moment
            ("e.jpg", None),                            # undated → alone
        ]
        moments = build_moments(entries)
        self.assertEqual([("a.jpg", "b.jpg", "c.jpg"), ("d.jpg",), ("e.jpg",)],
                         [m.paths for m in moments])
        self.assertEqual("a.jpg", moments[0].id)
        self.assertTrue(moments[0].is_series)
        self.assertFalse(moments[1].is_series)

    def test_long_burst_is_split_into_balanced_chunks(self):
        entries = [(f"{i:02d}.jpg", f"2024-08-13T07:12:{i * 3:02d}") for i in range(17)]
        moments = build_moments(entries, max_size=8)
        self.assertEqual([6, 6, 5], [len(m.paths) for m in moments])
        self.assertEqual([e[0] for e in entries], [p for m in moments for p in m.paths])
        self.assertEqual(["00.jpg", "06.jpg", "12.jpg"], [m.id for m in moments])

    def test_bad_timestamp_is_treated_as_undated(self):
        moments = build_moments([("x.jpg", "not-a-date"), ("y.jpg", "2024-01-01T00:00:00")])
        self.assertEqual({("x.jpg",), ("y.jpg",)}, {m.paths for m in moments})

    def test_labelling_order_is_series_first_and_deterministic(self):
        moments = [Moment(f"s{i}", (f"s{i}a", f"s{i}b"), None) for i in range(5)] + \
                  [Moment(f"o{i}", (f"o{i}",), None) for i in range(5)]
        first = labelling_order(moments)
        self.assertEqual(first, labelling_order(moments))
        self.assertTrue(all(m.is_series for m in first[:5]))
        self.assertFalse(any(m.is_series for m in first[5:]))


class LabelStoreTests(unittest.TestCase):
    def test_round_trip_defaults_unmarked_to_keep(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".photobrain", "ranking-labels.json")
            store = LabelStore(path)
            m = Moment("a.jpg", ("a.jpg", "b.jpg", "c.jpg"), None)
            store.record_moment(m, {"a.jpg": "best", "c.jpg": "junk"},
                                {"a.jpg": "s1", "b.jpg": "s2", "c.jpg": "s3"})
            store.save()
            again = LabelStore(path)
            self.assertEqual("best", again.label_of("a.jpg"))
            self.assertEqual("keep", again.label_of("b.jpg"))
            self.assertEqual("junk", again.label_of("c.jpg"))
            self.assertEqual({"a.jpg"}, again.reviewed_moments)
            self.assertEqual("s2", again.labels["b.jpg"]["sha256"])
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_rejects_unknown_label(self):
        with tempfile.TemporaryDirectory() as d:
            store = LabelStore(os.path.join(d, "l.json"))
            with self.assertRaises(ValueError):
                store.record_moment(Moment("a", ("a",), None), {"a": "great"}, {})

    def test_fingerprint_changes_with_labels(self):
        with tempfile.TemporaryDirectory() as d:
            store = LabelStore(os.path.join(d, "l.json"))
            store.record_moment(Moment("a", ("a",), None), {}, {"a": "x"})
            before = store.fingerprint()
            store.record_moment(Moment("a", ("a",), None), {"a": "junk"}, {"a": "x"})
            self.assertNotEqual(before, store.fingerprint())

    def test_skip_then_review_clears_skip(self):
        with tempfile.TemporaryDirectory() as d:
            store = LabelStore(os.path.join(d, "l.json"))
            m = Moment("a", ("a",), None)
            store.skip_moment(m)
            store.record_moment(m, {}, {})
            self.assertNotIn("a", store.skipped_moments)


class MetricTests(unittest.TestCase):
    def _case(self):
        # Series 1: app ranks the starred photo top (hit). Series 2: app prefers
        # the redundant one over the star (miss). One junk single, flagged.
        photos = {
            "s1a": _photo("s1a", 0.80), "s1b": _photo("s1b", 0.60, Verdict.ARCHIVE),
            "s2a": _photo("s2a", 0.50, Verdict.ARCHIVE), "s2b": _photo("s2b", 0.70),
            "j": _photo("j", 0.10, Verdict.REVIEW),
            "k": _photo("k", 0.45),
        }
        labels = {"s1a": "best", "s1b": "redundant", "s2a": "best", "s2b": "redundant",
                  "j": "junk", "k": "keep"}
        moments = {"s1a": "s1", "s1b": "s1", "s2a": "s2", "s2b": "s2", "j": "j", "k": "k"}
        return photos, labels, moments

    def test_best_pick_pairwise_and_chance(self):
        m = compute_metrics(*self._case())
        self.assertEqual(2, m["best_pick"]["series"])
        self.assertEqual(1, m["best_pick"]["hits"])
        self.assertEqual(0.5, m["best_pick"]["rate"])
        self.assertEqual(0.5, m["best_pick"]["chance"])
        self.assertEqual(2, m["pairwise"]["pairs"])
        self.assertEqual(0.5, m["pairwise"]["rate"])

    def test_junk_and_verdicts(self):
        m = compute_metrics(*self._case())
        self.assertEqual(1.0, m["junk"]["caught_rate"])
        self.assertEqual(0.0, m["junk"]["false_alarm_rate"])
        # s2a is starred but the app would archive it; s2b is redundant but kept.
        self.assertEqual(1, m["verdicts"]["wanted_set_aside"])
        self.assertEqual(1, m["verdicts"]["unwanted_kept"])
        self.assertEqual(["s2a"], m["verdicts"]["wanted_set_aside_examples"])

    def test_shortlist_precision(self):
        m = compute_metrics(*self._case())
        # 2 stars → app's top-2 scores are s1a (star) and s2b (not) → 1 of 2.
        self.assertEqual(2, m["shortlist"]["k"])
        self.assertEqual(0.5, m["shortlist"]["precision"])

    def test_ties_count_half(self):
        photos = {"a": _photo("a", 0.5), "b": _photo("b", 0.5)}
        m = compute_metrics(photos, {"a": "best", "b": "junk"}, {"a": "m", "b": "m"})
        self.assertEqual(0.5, m["pairwise"]["rate"])

    def test_unlabelled_or_unanalysed_photos_are_ignored(self):
        photos, labels, moments = self._case()
        photos["extra"] = _photo("extra", 0.99)
        labels["gone"] = "best"
        m = compute_metrics(photos, labels, moments)
        self.assertEqual(6, m["photos_graded"])

    def test_empty_denominators_are_none_not_zero(self):
        m = compute_metrics({"k": _photo("k", 0.5)}, {"k": "keep"}, {"k": "k"})
        self.assertIsNone(m["best_pick"]["rate"])
        self.assertIsNone(m["junk"]["caught_rate"])

    def test_regressions_respect_direction_and_tolerance(self):
        old = compute_metrics(*self._case())
        new = json.loads(json.dumps(old))
        new["best_pick"]["rate"] = 0.40          # -10 points → regression
        new["junk"]["false_alarm_rate"] = 0.01   # +1 point → within tolerance
        new["pairwise"]["rate"] = 0.90           # better → fine
        worse = regressions(new, old)
        self.assertEqual(1, len(worse))
        self.assertTrue(worse[0].startswith("best_pick"))
        self.assertEqual(set(headline(old)), {"best_pick", "pairwise", "junk_caught",
                                              "junk_false_alarm", "verdict_agreement", "shortlist"})


class FingerprintAndIndexTests(unittest.TestCase):
    def test_fingerprint_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for root, eol in ((a, b"\n"), (b, b"\r\n")):
                for rel in SCORER_FILES:
                    path = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    body = b"model bytes" if rel.endswith((".tflite", ".task")) else                         b"line one" + eol + b"line two" + eol
                    with open(path, "wb") as fh:
                        fh.write(body)
            self.assertEqual(scorer_fingerprint(a), scorer_fingerprint(b))
            with open(os.path.join(b, "app/core/scoring.py"), "ab") as fh:
                fh.write(b"# tweak")
            self.assertNotEqual(scorer_fingerprint(a), scorer_fingerprint(b))

    def test_index_reads_capture_times_and_uses_cache(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as cache_dir:
            for name, when in (("a.jpg", "2024:08:13 07:12:00"), ("sub/b.jpg", None)):
                path = os.path.join(root, name)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                exif = Image.Exif()
                if when:
                    exif[306] = when
                Image.new("RGB", (32, 24), (90, 120, 150)).save(path, exif=exif)
            cache = os.path.join(cache_dir, "dates.json")
            entries = dict(index_root(root, cache_path=cache))
            self.assertEqual("2024-08-13T07:12:00", entries["a.jpg"])
            self.assertIsNone(entries[os.path.join("sub", "b.jpg")])
            with open(cache, encoding="utf-8") as fh:
                self.assertIn("a.jpg", json.load(fh))
            # Second run with the cache: same answer without re-reading EXIF.
            from unittest.mock import patch
            with patch("app.core.events.extract_exif_datetime", side_effect=AssertionError("re-read")):
                self.assertEqual(entries, dict(index_root(root, cache_path=cache)))

    def test_index_cancel_returns_none(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as cache_dir:
            Image.new("RGB", (8, 8)).save(os.path.join(root, "a.jpg"))
            self.assertIsNone(index_root(root, cancel_check=lambda: True,
                                         cache_path=os.path.join(cache_dir, "d.json")))


if __name__ == "__main__":
    unittest.main()
