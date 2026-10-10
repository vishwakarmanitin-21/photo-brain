"""The scan analysis pipeline — hash, score, faces, dates, group, suggest.

One implementation shared by the app's ScanWorker and the ranking scorecard
(scripts/eval_ranking.py, RANK-01). The scorecard must measure exactly what a
user's scan produces; a second hand-written copy of this sequence would drift
from the app the first time a phase changed, and the scorecard would then
grade code nobody runs.

Pure core: no Qt, no persistence. Callers observe progress through hooks and
persist the result themselves.
"""
import logging
from dataclasses import dataclass, field, fields
from typing import Callable, Optional

from app.core.faces import DEFAULT_FACE_MIN_CONFIDENCE
from app.core.models import Cluster, Event, Photo, SessionState
from app.core.scanner import (
    assign_verdicts, build_photo_events, compute_hashes, detect_and_analyze_faces,
    extract_dates, fingerprint_and_score, run_clustering,
)

log = logging.getLogger("photobrain.pipeline")

_SESSION_DEFAULTS = {f.name: f.default for f in fields(SessionState)}


@dataclass
class AnalysisOptions:
    """Scan settings. Defaults are the app's own session defaults, read from
    SessionState so the scorecard and a fresh scan can never disagree."""
    phash_threshold: int = _SESSION_DEFAULTS["phash_threshold"]
    keep_per_cluster: int = _SESSION_DEFAULTS["keep_per_cluster"]
    event_gap_hours: float = _SESSION_DEFAULTS["event_gap_hours"]
    face_detection_enabled: bool = _SESSION_DEFAULTS["face_detection_enabled"]
    face_min_confidence: float = DEFAULT_FACE_MIN_CONFIDENCE


@dataclass
class PipelineHooks:
    """Optional observers. Every hook defaults to a no-op."""
    phase: Callable[[str], None] = lambda description: None
    progress: Callable[[str, int, int, str], None] = lambda label, cur, total, fname: None
    stat: Callable[[str, int], None] = lambda name, value: None
    # Called once hashing is done, before the slow phases — the app persists
    # the photo rows here so a crash mid-scan still leaves them recorded.
    hashed: Callable[[list[Photo]], None] = lambda photos: None


@dataclass
class AnalysisResult:
    photos: list[Photo]
    clusters: list[Cluster]
    cluster_photos: dict[str, list[Photo]]
    events: list[Event]
    dup_count: int
    face_stats: dict[str, int] = field(default_factory=dict)


def analyze(
    files: list[str],
    options: Optional[AnalysisOptions] = None,
    hooks: Optional[PipelineHooks] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Optional[AnalysisResult]:
    """Run every analysis phase over `files`. Returns None if cancelled."""
    options = options or AnalysisOptions()
    hooks = hooks or PipelineHooks()
    cancelled = cancel_check or (lambda: False)

    def reporter(label: str, *stat_names: str):
        def report(cur: int, total: int, fname: str):
            hooks.progress(label, cur, total, fname)
            for name in stat_names:
                hooks.stat(name, cur)
        return report

    hooks.phase("Computing file hashes...")
    photos = compute_hashes(files, reporter("Hashing", "hashed"), cancelled)
    if cancelled():
        return None
    sha_counts: dict[str, int] = {}
    for p in photos:
        if p.sha256:
            sha_counts[p.sha256] = sha_counts.get(p.sha256, 0) + 1
    dup_count = sum(v - 1 for v in sha_counts.values() if v > 1)
    hooks.stat("duplicates", dup_count)
    hooks.hashed(photos)

    hooks.phase("Fingerprinting and scoring...")
    fingerprint_and_score(photos, reporter("Scoring", "phash_computed", "scored"), cancelled)
    if cancelled():
        return None

    face_stats: dict[str, int] = {}
    if options.face_detection_enabled:
        hooks.phase("Analyzing faces...")
        face_stats = detect_and_analyze_faces(
            photos, reporter("Faces"), cancelled,
            min_confidence=options.face_min_confidence,
        )
        if cancelled():
            return None
        for name in ("faces_total", "faces_close", "faces_far", "faces_none",
                     "group_shots", "expressions_analyzed"):
            hooks.stat("faces_detected" if name == "faces_total" else name, face_stats[name])

    hooks.phase("Extracting dates...")
    extract_dates(photos, reporter("Dates"), cancelled)
    if cancelled():
        return None

    hooks.phase("Grouping into events...")
    events, _ = build_photo_events(photos, options.event_gap_hours)
    if cancelled():
        return None
    hooks.stat("events", len(events))

    hooks.phase("Clustering similar photos...")
    clusters, cluster_photos = run_clustering(photos, options.phash_threshold)
    if cancelled():
        return None
    hooks.stat("clusters", len(clusters))

    hooks.phase("Generating suggestions...")
    assign_verdicts(clusters, cluster_photos, options.keep_per_cluster)

    return AnalysisResult(photos, clusters, cluster_photos, events, dup_count, face_stats)
