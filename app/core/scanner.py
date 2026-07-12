"""Scan pipeline orchestrator."""
import os
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from app.core.models import Photo, Cluster, Event, Verdict, DupType, FaceDistance
from app.core.hashing import compute_sha256, compute_phash, phash_and_gray
from app.core.scoring import (
    score_photo, suggest_verdicts, rescore_with_faces, effective_keep_count,
    compute_quality_score, _sharpness_from_gray,
)
from app.core.clustering import build_clusters, group_by_sha256
from app.core.faces import detect_faces, analyze_expressions, analyze_photo
from app.core.events import extract_exif_datetime, build_events
from app.util.paths import SUPPORTED_EXTENSIONS, SKIP_DIRS

log = logging.getLogger("photobrain.scanner")

ProgressCallback = Callable[[int, int, str], None]  # current, total, filename


def face_worker_count() -> int:
    """Threads for the face phase — one below the core count, 2–8."""
    return max(2, min(8, (os.cpu_count() or 4) - 1))


def collect_files(root_folder: str) -> list[str]:
    """Recursively collect supported image files, skipping output dirs."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root_folder):
        # Prune output directories in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(os.path.normpath(os.path.join(dirpath, fname)))
    files.sort()  # deterministic ordering
    log.info("Collected %d files from %s", len(files), root_folder)
    return files


def compute_hashes(
    filepaths: list[str],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list[Photo]:
    """Create Photo objects and compute SHA256 for each file."""
    photos = []
    total = len(filepaths)
    for i, fp in enumerate(filepaths):
        if cancel_check and cancel_check():
            return photos

        sha = compute_sha256(fp)
        try:
            # The file can vanish between collection and here (sync clients
            # dehydrating placeholders) — never abort a whole scan for it.
            file_size = os.path.getsize(fp)
        except OSError:
            file_size = 0
        photo = Photo(
            id=uuid.uuid4().hex[:12],
            filepath=fp,
            filename=os.path.basename(fp),
            file_size=file_size,
            sha256=sha,
            scan_order=i,
        )
        photos.append(photo)

        if progress_cb and (i % 50 == 0 or i == total - 1):
            progress_cb(i + 1, total, photo.filename)

    return photos


def _fingerprint_score_one(filepath: str) -> tuple:
    """One decode → (phash, sharpness, brightness, quality). The unit of
    parallel work for fingerprint_and_score."""
    phash, gray = phash_and_gray(filepath)
    if gray is None:
        return phash, 0.0, 0.0, 0.0
    sharpness = _sharpness_from_gray(gray)
    brightness = float(gray.mean())
    return phash, sharpness, brightness, compute_quality_score(sharpness, brightness)


def fingerprint_and_score(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    workers: Optional[int] = None,
) -> None:
    """Compute pHash + quality score for each SHA group from one decode.

    Replaces the separate compute_phashes + compute_scores passes (one
    decode instead of two) and runs across a thread pool — the decode +
    DCT (pHash) + Laplacian (sharpness) are CPU-bound work that releases
    the GIL, so this was ~73% of scan wall-clock and scales with cores.
    Results are per-photo independent, so the outcome is identical
    regardless of completion order.
    """
    sha_groups = group_by_sha256(photos)
    groups = list(sha_groups.values())
    total = len(photos)
    if not groups:
        return

    workers = workers or face_worker_count()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_group = {
            pool.submit(_fingerprint_score_one, group[0].filepath): group
            for group in groups
        }
        for future in as_completed(future_to_group):
            if cancel_check and cancel_check():
                pool.shutdown(wait=False, cancel_futures=True)
                return
            group = future_to_group[future]
            try:
                phash, sharpness, brightness, quality = future.result()
            except Exception as e:
                log.warning("Fingerprint/score failed for %s: %s",
                            group[0].filepath, e)
                phash, sharpness, brightness, quality = None, 0.0, 0.0, 0.0

            for p in group:
                p.phash = phash
                p.sharpness = sharpness
                p.brightness = brightness
                p.quality_score = quality

            done += len(group)
            if progress_cb and (done % 50 < len(group) or done == total):
                progress_cb(min(done, total), total, group[0].filename)


def compute_phashes(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Compute pHash for each unique SHA256 group representative, copy to group."""
    sha_groups = group_by_sha256(photos)
    # Only compute pHash for one representative per SHA group
    representatives: dict[str, Photo] = {}
    for sha_key, group in sha_groups.items():
        representatives[sha_key] = group[0]

    total = len(representatives)
    for i, (sha_key, rep) in enumerate(representatives.items()):
        if cancel_check and cancel_check():
            return

        phash = compute_phash(rep.filepath)
        # Copy pHash to all members of the SHA group
        for p in sha_groups[sha_key]:
            p.phash = phash

        if progress_cb and (i % 50 == 0 or i == total - 1):
            progress_cb(i + 1, total, rep.filename)


def compute_scores(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Compute quality metrics for each unique SHA256 group, copy to group."""
    sha_groups = group_by_sha256(photos)
    scored_shas: dict[str, tuple[float, float, float]] = {}

    total = len(photos)
    done = 0
    for sha_key, group in sha_groups.items():
        if cancel_check and cancel_check():
            return

        # Compute once per SHA group (identical files have identical scores)
        rep = group[0]
        sharpness, brightness, quality = score_photo(rep.filepath)
        for p in group:
            p.sharpness = sharpness
            p.brightness = brightness
            p.quality_score = quality

        done += len(group)
        if progress_cb and (done % 50 < len(group) or done == total):
            progress_cb(min(done, total), total, rep.filename)


def detect_and_analyze_faces(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    workers: Optional[int] = None,
) -> dict[str, int]:
    """Face detection + expression analysis for the whole library, in parallel.

    Runs one worker per SHA256 group representative across a thread pool
    (each thread has its own mediapipe detector), so the dominant scan
    cost scales with cores. Results are per-photo independent, so the
    outcome is identical regardless of completion order. Returns the same
    stats dict as detect_all_faces plus 'expressions_analyzed'.
    """
    sha_groups = group_by_sha256(photos)
    groups = list(sha_groups.values())
    total = len(groups)
    stats = {
        "faces_total": 0, "faces_close": 0, "faces_far": 0,
        "faces_none": 0, "group_shots": 0, "expressions_analyzed": 0,
    }
    if total == 0:
        return stats

    workers = workers or face_worker_count()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_group = {
            pool.submit(analyze_photo, group[0].filepath): group
            for group in groups
        }
        for future in as_completed(future_to_group):
            if cancel_check and cancel_check():
                pool.shutdown(wait=False, cancel_futures=True)
                return stats
            group = future_to_group[future]
            try:
                r = future.result()
            except Exception as e:
                log.warning("Face analysis failed for %s: %s",
                            group[0].filepath, e)
                r = {
                    "face_count": 0, "face_area_ratio": 0.0,
                    "face_distance": "none", "subject_isolation": 0.0,
                    "eyes_open": 0.0, "smile": 0.0,
                    "expression_naturalness": 0.0, "head_pose_frontal": 0.0,
                }

            fd = FaceDistance(r["face_distance"])
            n = len(group)
            for p in group:
                p.face_count = r["face_count"]
                p.face_area_ratio = r["face_area_ratio"]
                p.face_distance = fd
                p.subject_isolation = r["subject_isolation"]
                p.eyes_open_score = r["eyes_open"]
                p.smile_score = r["smile"]
                p.expression_naturalness = r["expression_naturalness"]
                p.head_pose_frontal = r["head_pose_frontal"]
                p.quality_score = rescore_with_faces(p)

            if r["face_count"] > 0:
                stats["faces_total"] += n
                if fd == FaceDistance.CLOSE:
                    stats["faces_close"] += n
                else:
                    stats["faces_far"] += n
                if r["face_count"] >= 3:
                    stats["group_shots"] += n
                stats["expressions_analyzed"] += n
            else:
                stats["faces_none"] += n

            done += 1
            if progress_cb and (done % 10 == 0 or done == total):
                progress_cb(done, total, group[0].filename)

    return stats


def detect_all_faces(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict[str, int]:
    """Detect faces for each unique SHA256 group, copy results to group.

    Returns dict with keys: faces_total, faces_close, faces_far,
    faces_none, group_shots (photos with 3+ faces).
    """
    sha_groups = group_by_sha256(photos)
    total = len(sha_groups)
    stats = {
        "faces_total": 0,
        "faces_close": 0,
        "faces_far": 0,
        "faces_none": 0,
        "group_shots": 0,
    }

    for i, (sha_key, group) in enumerate(sha_groups.items()):
        if cancel_check and cancel_check():
            return stats

        rep = group[0]
        face_count, face_area_ratio, face_dist, isolation = detect_faces(rep.filepath)
        fd = FaceDistance(face_dist)
        for p in group:
            p.face_count = face_count
            p.face_area_ratio = face_area_ratio
            p.face_distance = fd
            p.subject_isolation = isolation

        n = len(group)
        if face_count > 0:
            stats["faces_total"] += n
            if fd == FaceDistance.CLOSE:
                stats["faces_close"] += n
            else:
                stats["faces_far"] += n
            if face_count >= 3:
                stats["group_shots"] += n
        else:
            stats["faces_none"] += n

        if progress_cb and (i % 30 == 0 or i == total - 1):
            progress_cb(i + 1, total, rep.filename)

    return stats


def analyze_all_expressions(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> int:
    """Analyze expressions for photos with faces, then rescore.

    For close-up faces, runs the landmarker on the full image.
    For distant faces, crops and upscales each face region before analysis.

    Returns count of photos where expressions were analyzed.
    """
    sha_groups = group_by_sha256(photos)
    # Process all groups where faces were detected (close or far)
    face_groups = {k: g for k, g in sha_groups.items() if g[0].face_count > 0}
    total = len(face_groups)
    analyzed = 0

    for i, (sha_key, group) in enumerate(face_groups.items()):
        if cancel_check and cancel_check():
            return analyzed

        rep = group[0]
        eyes_open, smile, expr_natural, head_frontal = analyze_expressions(rep.filepath)
        for p in group:
            p.eyes_open_score = eyes_open
            p.smile_score = smile
            p.expression_naturalness = expr_natural
            p.head_pose_frontal = head_frontal
            p.quality_score = rescore_with_faces(p)

        analyzed += len(group)

        if progress_cb and (i % 30 == 0 or i == total - 1):
            progress_cb(i + 1, total, rep.filename)

    return analyzed


def extract_dates(
    photos: list[Photo],
    progress_cb: Optional[ProgressCallback] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> int:
    """Extract EXIF datetime for each photo. Returns count of photos with dates."""
    total = len(photos)
    dated = 0
    for i, photo in enumerate(photos):
        if cancel_check and cancel_check():
            return dated

        dt = extract_exif_datetime(photo.filepath)
        if dt:
            photo.exif_datetime = dt
            dated += 1

        if progress_cb and (i % 50 == 0 or i == total - 1):
            progress_cb(i + 1, total, photo.filename)

    return dated


def build_photo_events(
    photos: list[Photo], gap_hours: float = 4.0
) -> tuple[list[Event], dict[str, list[Photo]]]:
    """Build time-based events from photos with EXIF dates."""
    return build_events(photos, gap_hours)


def run_clustering(
    photos: list[Photo], threshold: int = 8
) -> tuple[list[Cluster], dict[str, list[Photo]]]:
    """Delegate to clustering module."""
    return build_clusters(photos, threshold)


def assign_verdicts(
    clusters: list[Cluster],
    cluster_photos: dict[str, list[Photo]],
    keep_per_cluster: int = 2,
) -> None:
    """Suggest KEEP/ARCHIVE for each cluster and update cluster counts."""
    for cluster in clusters:
        members = cluster_photos.get(cluster.id, [])
        if not members:
            continue

        # For exact-dup-only clusters, keep only 1 regardless of setting.
        # Otherwise start from the user's ceiling but trim it when the
        # lower-ranked members are clearly worse than the best.
        if cluster.is_exact_dup_group:
            keep_n = 1
        else:
            keep_n = effective_keep_count(members, keep_per_cluster)
        suggest_verdicts(members, keep_count=keep_n)

        cluster.keep_count = sum(1 for p in members if p.verdict == Verdict.KEEP)
        cluster.delete_count = sum(
            1 for p in members if p.verdict in (Verdict.ARCHIVE, Verdict.DELETE)
        )
