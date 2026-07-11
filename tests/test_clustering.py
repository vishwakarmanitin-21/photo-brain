import unittest

from app.core.clustering import build_clusters, group_by_sha256
from app.core.models import DupType, Photo


def make_photo(
    photo_id: str,
    *,
    sha256: str | None,
    phash: str | None,
    quality: float = 1.0,
    filepath: str | None = None,
) -> Photo:
    path = filepath or f"C:/photos/{photo_id}.jpg"
    return Photo(
        id=photo_id,
        filepath=path,
        filename=path.rsplit("/", 1)[-1],
        file_size=100,
        sha256=sha256,
        phash=phash,
        quality_score=quality,
    )


class ClusteringTests(unittest.TestCase):
    def test_empty_input_returns_no_clusters(self):
        self.assertEqual(([], {}), build_clusters([]))

    def test_exact_duplicates_share_one_cluster(self):
        photos = [
            make_photo("b", sha256="same", phash="0" * 16, quality=1.0),
            make_photo("a", sha256="same", phash="0" * 16, quality=2.0),
        ]

        clusters, members = build_clusters(photos)

        self.assertEqual(1, len(clusters))
        cluster = clusters[0]
        self.assertTrue(cluster.is_exact_dup_group)
        self.assertEqual("a", cluster.representative_photo_id)
        self.assertEqual(["a", "b"], [p.id for p in members[cluster.id]])
        self.assertTrue(all(p.dup_type == DupType.EXACT for p in photos))

    def test_near_duplicate_at_threshold_is_included(self):
        zero_hash = "0" * 16
        seventeen_bits = f"{(1 << 17) - 1:016x}"
        photos = [
            make_photo("a", sha256="sha-a", phash=zero_hash),
            make_photo("b", sha256="sha-b", phash=seventeen_bits),
        ]

        clusters, members = build_clusters(photos, threshold=17)

        self.assertEqual(1, len(clusters))
        self.assertEqual(2, len(members[clusters[0].id]))
        self.assertTrue(all(p.dup_type == DupType.NEAR for p in photos))

    def test_near_duplicate_above_threshold_stays_separate(self):
        zero_hash = "0" * 16
        seventeen_bits = f"{(1 << 17) - 1:016x}"
        photos = [
            make_photo("a", sha256="sha-a", phash=zero_hash),
            make_photo("b", sha256="sha-b", phash=seventeen_bits),
        ]

        clusters, members = build_clusters(photos, threshold=16)

        self.assertEqual(2, len(clusters))
        self.assertEqual([1, 1], sorted(len(group) for group in members.values()))
        self.assertTrue(all(p.dup_type == DupType.NONE for p in photos))

    def test_missing_hashes_do_not_merge(self):
        photos = [
            make_photo("a", sha256=None, phash=None),
            make_photo("b", sha256=None, phash=None),
        ]

        groups = group_by_sha256(photos)
        clusters, _ = build_clusters(photos)

        self.assertEqual(2, len(groups))
        self.assertEqual(2, len(clusters))

    def test_member_order_uses_filepath_as_quality_tiebreaker(self):
        photos = [
            make_photo(
                "z",
                sha256="same",
                phash="0" * 16,
                quality=5.0,
                filepath="C:/photos/z.jpg",
            ),
            make_photo(
                "a",
                sha256="same",
                phash="0" * 16,
                quality=5.0,
                filepath="C:/photos/a.jpg",
            ),
        ]

        clusters, members = build_clusters(photos)

        self.assertEqual(["a", "z"], [p.id for p in members[clusters[0].id]])
        self.assertEqual("a", clusters[0].representative_photo_id)


if __name__ == "__main__":
    unittest.main()
