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
    4. Union-Find on representatives using pHash Hamming distance.
    5. Merge SHA256 groups into their pHash clusters.
    6. Build Cluster objects.
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

    # Step 3: pick representatives (highest quality_score per SHA group)
    representatives: list[Photo] = []
    rep_to_sha: dict[str, str] = {}  # rep photo id -> sha256 key
    for sha_key, group in sha_groups.items():
        ranked = sorted(group, key=lambda p: (-p.quality_score, p.filepath))
        rep = ranked[0]
        representatives.append(rep)
        rep_to_sha[rep.id] = sha_key

    # Step 4: Union-Find on representatives using pHash
    uf = UnionFind()
    for rep in representatives:
        uf.add(rep.id)

    # Only compare if both have valid phash
    reps_with_hash = [r for r in representatives if r.phash]
    n = len(reps_with_hash)
    comparisons = 0
    for i in range(n):
        for j in range(i + 1, n):
            dist = hamming_distance(reps_with_hash[i].phash, reps_with_hash[j].phash)
            if dist <= threshold:
                uf.union(reps_with_hash[i].id, reps_with_hash[j].id)
            comparisons += 1

    log.info("pHash comparisons: %d", comparisons)

    # Step 5: merge SHA256 groups into pHash clusters
    components = uf.components()
    cluster_photos: dict[str, list[Photo]] = {}
    clusters: list[Cluster] = []
    cluster_idx = 0

    # Sort component keys for deterministic ordering
    for root_id in sorted(components.keys()):
        rep_ids = components[root_id]
        cluster_id = uuid.uuid4().hex[:12]
        cluster_idx += 1
        all_photos: list[Photo] = []

        is_exact_only = True
        for rep_id in rep_ids:
            sha_key = rep_to_sha[rep_id]
            group = sha_groups[sha_key]
            all_photos.extend(group)
            if len(rep_ids) > 1:
                # Multiple SHA groups merged by pHash → near duplicates
                is_exact_only = False
                for p in group:
                    if p.dup_type == DupType.NONE:
                        p.dup_type = DupType.NEAR

        # Assign cluster_id to all member photos
        for p in all_photos:
            p.cluster_id = cluster_id

        # Determine if this is purely an exact-dup cluster
        # (single SHA group with multiple files)
        is_exact = (
            len(rep_ids) == 1
            and len(all_photos) > 1
            and all(p.dup_type == DupType.EXACT for p in all_photos)
        )

        # Sort members by quality desc for consistent ordering
        all_photos.sort(key=lambda p: (-p.quality_score, p.filepath))
        best = all_photos[0]

        cluster = Cluster(
            id=cluster_id,
            label=f"Cluster {cluster_idx}",
            representative_photo_id=best.id,
            member_count=len(all_photos),
            is_exact_dup_group=is_exact,
        )
        clusters.append(cluster)
        cluster_photos[cluster_id] = all_photos

    # Sort clusters by member_count desc for display
    clusters.sort(key=lambda c: -c.member_count)

    log.info("Final clusters: %d", len(clusters))
    return clusters, cluster_photos
