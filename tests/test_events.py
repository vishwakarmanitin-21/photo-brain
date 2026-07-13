import unittest
from datetime import datetime, timedelta

from app.core.events import build_events
from app.core.models import Photo


def _photo(pid, dt=None):
    return Photo(id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
                 file_size=1, exif_datetime=(dt.isoformat() if dt else None))


BASE = datetime(2024, 6, 1, 12, 0, 0)


class BuildEventsBoundaryTests(unittest.TestCase):
    """TEST-01: time-gap grouping, especially the boundary condition."""

    def _event_of(self, events, event_photos, photo_id):
        for eid, members in event_photos.items():
            if any(p.id == photo_id for p in members):
                return eid
        return None

    def test_gap_exactly_equal_does_not_split(self):
        # Split happens only when the gap strictly *exceeds* gap_hours.
        photos = [_photo("a", BASE), _photo("b", BASE + timedelta(hours=4))]
        events, ep = build_events(photos, gap_hours=4.0)
        self.assertEqual(1, len(events))
        self.assertEqual(self._event_of(events, ep, "a"),
                         self._event_of(events, ep, "b"))

    def test_gap_just_over_splits(self):
        photos = [_photo("a", BASE),
                  _photo("b", BASE + timedelta(hours=4, seconds=1))]
        events, ep = build_events(photos, gap_hours=4.0)
        self.assertEqual(2, len(events))
        self.assertNotEqual(self._event_of(events, ep, "a"),
                            self._event_of(events, ep, "b"))

    def test_photos_are_sorted_before_grouping(self):
        # Input out of order; a & c are 1h apart, b is days later.
        photos = [
            _photo("c", BASE + timedelta(hours=1)),
            _photo("b", BASE + timedelta(days=3)),
            _photo("a", BASE),
        ]
        events, ep = build_events(photos, gap_hours=4.0)
        self.assertEqual(2, len(events))
        self.assertEqual(self._event_of(events, ep, "a"),
                         self._event_of(events, ep, "c"))
        self.assertNotEqual(self._event_of(events, ep, "a"),
                            self._event_of(events, ep, "b"))

    def test_undated_photos_form_their_own_event(self):
        photos = [_photo("a", BASE), _photo("u", None)]
        events, ep = build_events(photos)
        undated = [e for e in events if e.label == "Undated"]
        self.assertEqual(1, len(undated))
        self.assertIsNone(undated[0].start_datetime)
        self.assertEqual("u", ep[undated[0].id][0].id)

    def test_invalid_datetime_is_treated_as_undated(self):
        p = _photo("bad")
        p.exif_datetime = "not-a-date"
        events, ep = build_events([p, _photo("a", BASE)])
        undated = [e for e in events if e.label == "Undated"]
        self.assertEqual(1, len(undated))
        self.assertIn("bad", [x.id for x in ep[undated[0].id]])

    def test_empty_input_produces_no_events(self):
        events, ep = build_events([])
        self.assertEqual([], events)
        self.assertEqual({}, ep)

    def test_every_photo_gets_an_event_id(self):
        photos = [_photo("a", BASE), _photo("b", BASE + timedelta(days=1)),
                  _photo("u", None)]
        build_events(photos, gap_hours=4.0)
        self.assertTrue(all(p.event_id for p in photos))


if __name__ == "__main__":
    unittest.main()
