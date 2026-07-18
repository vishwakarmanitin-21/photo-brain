"""Best-of shortlisting (O2): pick the keepers to grab quickly.

Pure selection logic — no Qt, no file IO. Ranks by the same
(-quality_score, filepath) key the verdict engine uses, so a shortlist is
consistent with the per-group "best" picks and is deterministic.
"""
from app.core.models import Photo


def _rank(photo: Photo):
    return (-(photo.quality_score or 0.0), photo.filepath)


def select_top_n_global(photos: list[Photo], n: int) -> list[Photo]:
    """The n highest-quality photos across the whole batch, best first."""
    if n <= 0:
        return []
    return sorted(photos, key=_rank)[:n]


def select_best_per_event(photos: list[Photo], per_event_n: int = 1) -> list[Photo]:
    """The best `per_event_n` photos from each event (grouped by event_id).

    Photos with no event_id are grouped together as a single bucket. The
    result is deterministic and ordered by the same rank key.
    """
    if per_event_n <= 0:
        return []
    buckets: dict = {}
    for p in photos:
        buckets.setdefault(p.event_id, []).append(p)
    selected: list[Photo] = []
    for members in buckets.values():
        selected.extend(sorted(members, key=_rank)[:per_event_n])
    return sorted(selected, key=_rank)
