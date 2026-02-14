"""EXIF date extraction and time-based event grouping."""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from PIL import Image
from PIL.ExifTags import Base as ExifBase

from app.core.models import Photo, Event

log = logging.getLogger("photobrain.events")

# EXIF tag IDs for date/time
_DATE_TAGS = [
    ExifBase.DateTimeOriginal,   # 36867
    ExifBase.DateTimeDigitized,  # 36868
    ExifBase.DateTime,           # 306
]

_EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def extract_exif_datetime(filepath: str) -> Optional[str]:
    """Extract the earliest date/time from EXIF data.

    Returns ISO 8601 string or None if no date found.
    """
    try:
        img = Image.open(filepath)
        exif = img.getexif()
        if not exif:
            return None

        for tag_id in _DATE_TAGS:
            val = exif.get(tag_id)
            if val and isinstance(val, str):
                try:
                    dt = datetime.strptime(val.strip(), _EXIF_DATE_FORMAT)
                    return dt.isoformat()
                except ValueError:
                    continue

        return None
    except Exception as e:
        log.debug("EXIF extraction failed for %s: %s", filepath, e)
        return None


def build_events(
    photos: list[Photo], gap_hours: float = 4.0
) -> tuple[list[Event], dict[str, list[Photo]]]:
    """Group photos into time-based events.

    Photos are sorted by EXIF datetime. A new event starts when the gap
    between consecutive photos exceeds gap_hours. Photos without dates
    go into an "Undated" event.

    Returns (events, event_id_to_photos_map).
    """
    gap = timedelta(hours=gap_hours)

    # Separate dated and undated photos
    dated: list[tuple[datetime, Photo]] = []
    undated: list[Photo] = []

    for photo in photos:
        if photo.exif_datetime:
            try:
                dt = datetime.fromisoformat(photo.exif_datetime)
                dated.append((dt, photo))
            except ValueError:
                undated.append(photo)
        else:
            undated.append(photo)

    # Sort by datetime
    dated.sort(key=lambda x: x[0])

    events: list[Event] = []
    event_photos: dict[str, list[Photo]] = {}
    event_idx = 0

    # Build events from dated photos
    if dated:
        current_event_id = uuid.uuid4().hex[:12]
        current_start = dated[0][0]
        current_members: list[Photo] = [dated[0][1]]
        dated[0][1].event_id = current_event_id

        for i in range(1, len(dated)):
            dt, photo = dated[i]
            prev_dt = dated[i - 1][0]

            if dt - prev_dt > gap:
                # Close current event
                event_idx += 1
                events.append(_make_event(
                    current_event_id, event_idx,
                    current_start, dated[i - 1][0],
                    len(current_members),
                ))
                event_photos[current_event_id] = current_members

                # Start new event
                current_event_id = uuid.uuid4().hex[:12]
                current_start = dt
                current_members = []

            photo.event_id = current_event_id
            current_members.append(photo)

        # Close final event
        event_idx += 1
        events.append(_make_event(
            current_event_id, event_idx,
            current_start, dated[-1][0],
            len(current_members),
        ))
        event_photos[current_event_id] = current_members

    # Undated event
    if undated:
        undated_id = uuid.uuid4().hex[:12]
        for p in undated:
            p.event_id = undated_id
        events.append(Event(
            id=undated_id,
            label="Undated",
            start_datetime=None,
            end_datetime=None,
            photo_count=len(undated),
        ))
        event_photos[undated_id] = undated

    log.info("Built %d events (%d dated, %d undated photos)",
             len(events), len(dated), len(undated))
    return events, event_photos


def _make_event(
    event_id: str, index: int,
    start: datetime, end: datetime, count: int,
) -> Event:
    label = f"Event {index} — {start.strftime('%b %d, %Y')}"
    if start.date() != end.date():
        label = f"Event {index} — {start.strftime('%b %d')}–{end.strftime('%b %d, %Y')}"
    return Event(
        id=event_id,
        label=label,
        start_datetime=start.isoformat(),
        end_datetime=end.isoformat(),
        photo_count=count,
    )
