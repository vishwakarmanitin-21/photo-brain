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

    def test_chaining_is_prevented_by_the_diameter_cap(self):
        # A~B (dist 17) and B~C (dist 17) but A≁C (dist 26). Plain union-find
        # would merge all three into one blob; anchoring must not — C stays
        # out of A's cluster because it is compared to the anchor A, not B.
        a_hash = "0" * 16                      # 0 bits
        b_hash = f"{0x1FFFF:016x}"             # bits 0..16  -> dist(A,B)=17
        c_hash = f"{0x3FFFFFF0:016x}"          # bits 4..29  -> dist(A,C)=26,
                                               #               dist(B,C)=17
        from app.core.hashing import hamming_distance
        self.assertEqual(17, hamming_distance(a_hash, b_hash))
        self.assertEqual(17, hamming_distance(b_hash, c_hash))
        self.assertEqual(26, hamming_distance(a_hash, c_hash))

        photos = [
            make_photo("a", sha256="sa", phash=a_hash, quality=3.0),
            make_photo("b", sha256="sb", phash=b_hash, quality=2.0),
            make_photo("c", sha256="sc", phash=c_hash, quality=1.0),
        ]
        clusters, members = build_clusters(photos, threshold=17)

        by_photo = {p.id: c.id for c in clusters for p in members[c.id]}
        self.assertEqual(2, len(clusters))
        self.assertEqual(by_photo["a"], by_photo["b"])      # A and B together
        self.assertNotEqual(by_photo["a"], by_photo["c"])   # C is separate

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
