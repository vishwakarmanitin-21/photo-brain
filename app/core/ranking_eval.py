"""Ranking scorecard (RANK-01): does the app pick the photos a person would?

Pure core — no Qt. Three parts:

* **Moments.** Photos taken within MOMENT_GAP_SECONDS of the previous one form
  a moment (a burst or a run of retakes). Moments are built from capture time
  only, never from the app's own grouping, so the labels stay independent of
  the code being graded.
* **Labels.** A person marks each photo in a moment: best / keep / redundant /
  junk. Stored as JSON beside the photos (`<root>/.photobrain/ranking-labels.json`)
  keyed by the photo's path relative to that root, with its SHA-256 so a file
  that changed after labelling is detected rather than silently re-graded.
* **Metrics.** The app's scores and suggested verdicts are compared with the
  labels; a baseline of the headline numbers lives in docs/ranking-baseline.json
  so a scoring change that makes picks worse is caught.
"""
import hashlib
import json
import os
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from app.core.models import Photo, Verdict
from app.core.scoring import is_low_quality

LABELS = ("best", "keep", "redundant", "junk")
# Ordering used for pairwise agreement: a best shot outranks a keeper, which
# outranks a redundant near-copy, which outranks junk.
TIER = {"best": 3, "keep": 2, "redundant": 1, "junk": 0}
WANTED = frozenset({"best", "keep"})

# A burst or a quick run of retakes is seconds apart. Measured on the first real
# labelling library (8,490 phone photos, 2024-2026): a 120 s gap chained whole
# outings into 160-photo "moments" (burst mode shoots every ~3 s for minutes at
# a time); 10 s keeps a burst or a reframe-and-retake together and stops there.
MOMENT_GAP_SECONDS = 10.0
# A burst can still run to dozens of frames. Past this size it is split into
# balanced chunks of consecutive shots, so every page is a pick-the-best
# decision a person can make at a glance.
MAX_MOMENT_SIZE = 8

LABELS_FILENAME = "ranking-labels.json"
LABELS_VERSION = 1

# Files whose contents decide a photo's score, its group or its verdict. If
# any of them changes, the scorecard must be re-run (tests/test_ranking_baseline.py).
SCORER_FILES = (
    "app/core/scoring.py", "app/core/faces.py", "app/core/clustering.py",
    "app/core/hashing.py", "app/core/scanner.py", "app/core/pipeline.py",
    "app/core/image_io.py", "app/core/events.py", "app/core/models.py",
    "app/core/ranking_eval.py",
    "assets/models/blaze_face_short_range.tflite", "assets/models/face_landmarker.task",
)

# How far a headline number may drop before an update is refused. Small label
# sets are noisy, so this is a floor for "clearly worse", not a precision bar.
REGRESSION_TOLERANCE = 0.02


# ───────────────────────────── moments ─────────────────────────────

@dataclass(frozen=True)
class Moment:
    id: str                 # relative path of its first photo — stable across runs
    paths: tuple[str, ...]  # relative paths, in capture order
    start: Optional[str]    # ISO capture time of the first photo, if known

    @property
    def is_series(self) -> bool:
        return len(self.paths) > 1


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def build_moments(entries: Iterable[tuple[str, Optional[str]]],
                  gap_seconds: float = MOMENT_GAP_SECONDS,
                  max_size: int = MAX_MOMENT_SIZE) -> list[Moment]:
    """Group (relative_path, iso_capture_time) entries into moments.

    Dated photos are sorted by time (path breaks ties) and split wherever the
    gap to the previous photo exceeds `gap_seconds`; a run longer than
    `max_size` is cut into balanced chunks of consecutive shots. A photo with
    no usable capture time is a moment on its own — it cannot be placed in a burst.
    """
    dated, undated = [], []
    for rel, iso in entries:
        t = _parse_time(iso)
        (dated if t is not None else undated).append((t, rel, iso))
    dated.sort(key=lambda e: (e[0], e[1]))

    moments: list[Moment] = []
    run: list[tuple] = []

    def close_run():
        if not run:
            return
        chunks = -(-len(run) // max_size)              # ceil
        size, extra = divmod(len(run), chunks)          # balanced: 9 -> 5 + 4, not 8 + 1
        start = 0
        for i in range(chunks):
            part = run[start:start + size + (1 if i < extra else 0)]
            start += len(part)
            moments.append(Moment(part[0][1], tuple(e[1] for e in part), part[0][2]))

    for entry in dated:
        if run:
            try:
                gap = (entry[0] - run[-1][0]).total_seconds()
            except TypeError:  # mixed tz-aware / naive timestamps
                gap = gap_seconds + 1
            if gap > gap_seconds:
                close_run()
                run = []
        run.append(entry)
    close_run()
    for _, rel, iso in sorted(undated, key=lambda e: e[1]):
        moments.append(Moment(rel, (rel,), iso))
    return moments


def labelling_order(moments: list[Moment], seed: str = "photobrain-rank-01") -> list[Moment]:
    """Series first, then singles — each in a fixed shuffled order.

    Shuffled so a partial labelling session samples the whole library (all
    years, all occasions) instead of exhausting the oldest folder first;
    seeded so the order is the same every time the tool opens.
    """
    rng = random.Random(seed)
    series = [m for m in moments if m.is_series]
    singles = [m for m in moments if not m.is_series]
    rng.shuffle(series)
    rng.shuffle(singles)
    return series + singles


# ───────────────────────────── labels ─────────────────────────────

def labels_path(root: str) -> str:
    return os.path.join(root, ".photobrain", LABELS_FILENAME)


class LabelStore:
    """The person's labels for one photo root, persisted atomically."""

    def __init__(self, path: str):
        self.path = path
        self.labels: dict[str, dict] = {}       # rel path -> {label, sha256, moment, at}
        self.reviewed_moments: set[str] = set()  # moment ids saved at least once
        self.skipped_moments: set[str] = set()   # moment ids the person chose to skip
        if os.path.isfile(path):
            self._load()

    def _load(self):
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") != LABELS_VERSION:
            raise ValueError(f"Unsupported labels file version in {self.path}")
        self.labels = data.get("labels", {})
        self.reviewed_moments = set(data.get("reviewed_moments", []))
        self.skipped_moments = set(data.get("skipped_moments", []))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {
            "version": LABELS_VERSION,
            "note": "PhotoBrain ranking scorecard labels (RANK-01). Keys are paths "
                    "relative to the folder that holds this .photobrain directory.",
            "labels": dict(sorted(self.labels.items())),
            "reviewed_moments": sorted(self.reviewed_moments),
            "skipped_moments": sorted(self.skipped_moments),
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, self.path)  # never leaves a half-written labels file

    def record_moment(self, moment: Moment, labels: dict[str, str], shas: dict[str, Optional[str]]):
        """Save a reviewed moment. Photos without an explicit label are 'keep'."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for rel in moment.paths:
            label = labels.get(rel, "keep")
            if label not in LABELS:
                raise ValueError(f"Unknown label {label!r}")
            self.labels[rel] = {"label": label, "sha256": shas.get(rel),
                                "moment": moment.id, "at": now}
        self.reviewed_moments.add(moment.id)
        self.skipped_moments.discard(moment.id)

    def skip_moment(self, moment: Moment):
        self.skipped_moments.add(moment.id)

    def label_of(self, rel: str) -> Optional[str]:
        entry = self.labels.get(rel)
        return entry["label"] if entry else None

    def fingerprint(self) -> str:
        """Identity of the label set — metrics are comparable only between
        runs over the same labels."""
        h = hashlib.sha256()
        for rel, entry in sorted(self.labels.items()):
            h.update(f"{rel}\0{entry['label']}\0{entry.get('sha256')}\n".encode("utf-8"))
        return h.hexdigest()[:16]


# ───────────────────────────── metrics ─────────────────────────────

def app_flags_junk(photo: Photo) -> bool:
    """The app's 'this photo is no good' signal: below the low-quality bar,
    or unreadable. These are the photos it marks for review instead of keeping."""
    unscoreable = photo.sharpness <= 0.0 and photo.brightness <= 0.0
    return unscoreable or is_low_quality(photo)


def _ratio(hits: float, total: int) -> Optional[float]:
    return round(float(hits) / total, 4) if total else None


def compute_metrics(photos: dict[str, Photo], labels: dict[str, str],
                    moment_of: dict[str, str]) -> dict:
    """Compare the app's analysis with the person's labels.

    photos:    rel path -> analysed Photo (score + suggested verdict)
    labels:    rel path -> label
    moment_of: rel path -> moment id
    Only photos present in both `photos` and `labels` are graded.
    """
    graded = sorted(r for r in labels if r in photos)
    by_moment: dict[str, list[str]] = {}
    for rel in graded:
        by_moment.setdefault(moment_of.get(rel, rel), []).append(rel)

    def score(rel):  # path tiebreak, exactly like the app's own ranking
        return (-float(photos[rel].quality_score), rel)

    # 1. Best pick: in each series with a starred photo and a non-starred one,
    #    is the app's top-scored photo one the person starred?
    best_total, best_hits, chance = 0, 0, 0.0
    # 2. Pairwise: for every pair in a moment with different tiers, does the
    #    app's score order them the same way? Ties count as half right.
    pair_total, pair_hits = 0, 0.0
    for members in by_moment.values():
        if len(members) < 2:
            continue
        tiers = {r: TIER[labels[r]] for r in members}
        stars = [r for r in members if labels[r] == "best"]
        if stars and len(stars) < len(members):
            best_total += 1
            best_hits += int(min(members, key=score) in stars)
            chance += len(stars) / len(members)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if tiers[a] == tiers[b]:
                    continue
                pair_total += 1
                sa, sb = float(photos[a].quality_score), float(photos[b].quality_score)
                if sa == sb:
                    pair_hits += 0.5
                elif (sa > sb) == (tiers[a] > tiers[b]):
                    pair_hits += 1

    # 3. Junk: of the photos the person called junk, how many does the app
    #    flag — and how many wanted photos does it wrongly flag?
    junk = [r for r in graded if labels[r] == "junk"]
    wanted = [r for r in graded if labels[r] in WANTED]
    junk_caught = sum(1 for r in junk if app_flags_junk(photos[r]))
    wanted_flagged = sum(1 for r in wanted if app_flags_junk(photos[r]))

    # 4. Suggested verdicts, end to end (grouping + keep rules included).
    unwanted = [r for r in graded if labels[r] not in WANTED]
    wanted_set_aside = [r for r in wanted if photos[r].verdict in (Verdict.ARCHIVE, Verdict.DELETE)]
    unwanted_kept = [r for r in unwanted if photos[r].verdict == Verdict.KEEP]
    agree = sum(1 for r in graded if (photos[r].verdict == Verdict.KEEP) == (labels[r] in WANTED))

    # 5. Shortlist: of the app's K highest-scored photos (K = number starred),
    #    how many did the person star?
    stars_all = [r for r in graded if labels[r] == "best"]
    top_k = sorted(graded, key=score)[:len(stars_all)]
    shortlist_hits = len(set(top_k) & set(stars_all))

    counts = {lab: sum(1 for r in graded if labels[r] == lab) for lab in LABELS}
    return {
        "photos_graded": len(graded),
        "moments_graded": len(by_moment),
        "series_graded": sum(1 for m in by_moment.values() if len(m) > 1),
        "label_counts": counts,
        "best_pick": {"rate": _ratio(best_hits, best_total), "hits": best_hits,
                      "series": best_total, "chance": _ratio(chance, best_total)},
        "pairwise": {"rate": _ratio(pair_hits, pair_total), "pairs": pair_total},
        "junk": {"caught_rate": _ratio(junk_caught, len(junk)), "caught": junk_caught,
                 "junk_total": len(junk), "false_alarm_rate": _ratio(wanted_flagged, len(wanted)),
                 "wanted_flagged": wanted_flagged, "wanted_total": len(wanted)},
        "verdicts": {"agreement_rate": _ratio(agree, len(graded)),
                     "wanted_set_aside": len(wanted_set_aside),
                     "unwanted_kept": len(unwanted_kept),
                     "wanted_set_aside_examples": wanted_set_aside[:10],
                     "unwanted_kept_examples": unwanted_kept[:10]},
        "shortlist": {"precision": _ratio(shortlist_hits, len(stars_all)),
                      "hits": shortlist_hits, "k": len(stars_all)},
    }


# Headline numbers gated against the baseline: (path into metrics, higher_is_better)
HEADLINES = {
    "best_pick": (("best_pick", "rate"), True),
    "pairwise": (("pairwise", "rate"), True),
    "junk_caught": (("junk", "caught_rate"), True),
    "junk_false_alarm": (("junk", "false_alarm_rate"), False),
    "verdict_agreement": (("verdicts", "agreement_rate"), True),
    "shortlist": (("shortlist", "precision"), True),
}


def headline(metrics: dict) -> dict[str, Optional[float]]:
    out = {}
    for name, (path, _) in HEADLINES.items():
        value = metrics
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        out[name] = value
    return out


def regressions(new: dict, old: dict, tolerance: float = REGRESSION_TOLERANCE) -> list[str]:
    """Headline numbers that got worse by more than `tolerance` (plain-English lines)."""
    worse = []
    new_h, old_h = headline(new), headline(old)
    for name, (_, higher_better) in HEADLINES.items():
        a, b = old_h.get(name), new_h.get(name)
        if a is None or b is None:
            continue
        drop = (a - b) if higher_better else (b - a)
        if drop > tolerance:
            worse.append(f"{name}: {a:.1%} -> {b:.1%}")
    return worse


# ───────────────────────────── scorer fingerprint ─────────────────────────────

def scorer_fingerprint(repo_root: str) -> str:
    """Hash of every file that decides scores, groups or verdicts.

    Line endings are normalised so a Windows checkout (CRLF) and CI agree.
    """
    h = hashlib.sha256()
    for rel in SCORER_FILES:
        path = os.path.join(repo_root, rel)
        with open(path, "rb") as fh:
            data = fh.read()
        if not rel.endswith((".tflite", ".task")):
            data = data.replace(b"\r\n", b"\n")
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()[:16]


# ───────────────────────────── indexing a photo root ─────────────────────────────

def date_cache_path(root: str) -> str:
    """Capture-time cache for a root, kept OUT of the photo folder (it is
    rebuildable, so it does not need OneDrive backup like the labels do)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    key = hashlib.sha1(os.path.normcase(os.path.abspath(root)).encode("utf-8")).hexdigest()[:12]
    return os.path.join(base, "PhotoBrain", "ranking", f"dates-{key}.json")


def index_root(root: str, progress_cb=None, cancel_check=None,
               cache_path: Optional[str] = None) -> Optional[list[tuple[str, Optional[str]]]]:
    """Every supported photo under `root` as (relative_path, iso_capture_time).

    Uses the app's own file collection and EXIF reader, so moments line up with
    what a scan sees. Capture times are cached by (size, mtime) — re-opening a
    9,800-photo root reads only the new or changed files. Returns None if cancelled.
    """
    from app.core.events import extract_exif_datetime
    from app.core.scanner import collect_files

    cache_path = cache_path or date_cache_path(root)
    cache: dict = {}
    if os.path.isfile(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}

    files = collect_files(root)
    entries, fresh = [], {}
    for i, path in enumerate(files):
        if cancel_check and cancel_check():
            return None
        rel = os.path.relpath(path, root)
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp = [st.st_size, int(st.st_mtime)]
        hit = cache.get(rel)
        iso = hit[2] if hit and hit[:2] == stamp else extract_exif_datetime(path)
        fresh[rel] = stamp + [iso]
        entries.append((rel, iso))
        if progress_cb and (i % 50 == 0 or i == len(files) - 1):
            progress_cb(i + 1, len(files))

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(fresh, fh)
    os.replace(tmp, cache_path)
    return entries
