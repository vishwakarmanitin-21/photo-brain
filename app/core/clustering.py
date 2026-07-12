"""Clustering via Union-Find for duplicate and near-duplicate grouping."""
import logging
import uuid
from collections import defaultdict

from app.core.models import Photo, Cluster, DupType
from app.core.hashing import hamming_distance

log = logging.getLogger("photobrain.clustering")


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def add(self, x: str):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: str, y: str):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for x in self.parent:
            groups[self.find(x)].append(x)
        return dict(groups)


def group_by_sha256(photos: list[Photo]) -> dict[str, list[Photo]]:
    """Group photos by SHA256. Photos with sha256=None get their own group."""
    groups: dict[str, list[Photo]] = defaultdict(list)
    for p in photos:
        key = p.sha256 if p.sha256 else f"__none_{p.id}"
        groups[key].append(p)
    return dict(groups)


def build_clusters(
    photos: list[Photo], threshold: int = 17
) -> tuple[list[Cluster], dict[str, list[Photo]]]:
    """Full clustering pipeline.

    1. Group exact duplicates by SHA256.
    2. Mark exact dup groups (size > 1) with dup_type=EXACT.
    3. Pick one representative per SHA256 group for pHash comparison.
    4. Anchor-based clustering: each representative joins the first cluster
       whose anchor is within `threshold`, else it starts a new cluster.
    5. Merge SHA256 groups into their pHash clusters.
    6. Build Cluster objects.

    Anchoring (step 4) replaces transitive union-find on purpose: a photo
    is compared only to cluster anchors, never to arbitrary members, so a
    chain A~B~C~…~Z can no longer collapse into one blob when the endpoints
    are dissimilar. On real libraries plain union-find built clusters of
    dozens of unrelated photos spanning hours; anchoring caps each cluster
    to a ball of radius `threshold` around its representative.
    """
    if not photos:
        return [], {}

    # Step 1: group by SHA256
    sha_groups = group_by_sha256(photos)
    log.info("SHA256 groups: %d (from %d photos)", len(sha_groups), len(photos))

    # Step 2: mark exact duplicates
    for sha, group in sha_groups.items():
        if len(group) > 1:
            for p in group:
                p.dup_type = DupType.EXACT

    # Step 3: pick representatives (highest quality_score per SHA group),
    # processed in deterministic quality order so the best photo anchors.
    rep_to_sha: dict[str, str] = {}  # rep photo id -> sha256 key
    representatives: list[Photo] = []
    for sha_key, group in sha_groups.items():
        rep = sorted(group, key=lambda p: (-p.quality_score, p.filepath))[0]
        representatives.append(rep)
        rep_to_sha[rep.id] = sha_key
    representatives.sort(key=lambda p: (-p.quality_score, p.filepath))

    # Step 4: anchor-based clustering (diameter cap)
    anchors: list[Photo] = []
    anchor_members: dict[str, list[str]] = {}  # anchor id -> member rep ids
    comparisons = 0
    for rep in representatives:
        chosen = None
        if rep.phash:
            for anchor in anchors:
                if not anchor.phash:
                    continue
                comparisons += 1
                if hamming_distance(rep.phash, anchor.phash) <= threshold:
                    chosen = anchor
                    break
        if chosen is None:
            anchors.append(rep)
            anchor_members[rep.id] = [rep.id]
        else:
            anchor_members[chosen.id].append(rep.id)

    log.info("pHash comparisons: %d (anchor-based)", comparisons)

    # Step 5: build clusters from anchors (deterministic quality order)
    cluster_photos: dict[str, list[Photo]] = {}
    clusters: list[Cluster] = []
    cluster_idx = 0

    for anchor in anchors:
        rep_ids = anchor_members[anchor.id]
        cluster_id = uuid.uuid4().hex[:12]
        cluster_idx += 1
        all_photos: list[Photo] = []
        for rep_id in rep_ids:
            all_photos.extend(sha_groups[rep_to_sha[rep_id]])

        # Multiple SHA groups merged by pHash → near duplicates
        if len(rep_ids) > 1:
            for p in all_photos:
                if p.dup_type == DupType.NONE:
                    p.dup_type = DupType.NEAR

        for p in all_photos:
            p.cluster_id = cluster_id

        # Purely an exact-dup cluster: single SHA group with multiple files
        is_exact = (
            len(rep_ids) == 1
            and len(all_photos) > 1
            and all(p.dup_type == DupType.EXACT for p in all_photos)
        )

        all_photos.sort(key=lambda p: (-p.quality_score, p.filepath))
        best = all_photos[0]

        clusters.append(Cluster(
            id=cluster_id,
            label=f"Cluster {cluster_idx}",
            representative_photo_id=best.id,
            member_count=len(all_photos),
            is_exact_dup_group=is_exact,
        ))
        cluster_photos[cluster_id] = all_photos

    # Sort clusters by member_count desc for display
    clusters.sort(key=lambda c: -c.member_count)

    log.info("Final clusters: %d", len(clusters))
    return clusters, cluster_photos
