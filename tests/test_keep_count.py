import unittest

from app.core.models import Cluster, Photo, Verdict
from app.core.scanner import assign_verdicts
from app.core.scoring import KEEP_GAP, effective_keep_count


def _photo(pid: str, score: float) -> Photo:
    return Photo(
        id=pid, filepath=f"C:/x/{pid}.jpg", filename=f"{pid}.jpg",
        file_size=10, quality_score=score,
    )


class EffectiveKeepCountTests(unittest.TestCase):
    """DISTILL-03: keep count follows the quality gaps, capped by max_keep."""

    def test_near_equal_pair_keeps_both(self):
        photos = [_photo("a", 0.49), _photo("b", 0.48)]
        self.assertEqual(2, effective_keep_count(photos, 2))

    def test_clearly_worse_runner_up_keeps_one(self):
        photos = [_photo("a", 0.49), _photo("b", 0.31)]
        self.assertEqual(1, effective_keep_count(photos, 2))

    def test_ceiling_is_respected_when_all_close(self):
        photos = [_photo("a", 0.50), _photo("b", 0.49),
                  _photo("c", 0.48), _photo("d", 0.47)]
        self.assertEqual(2, effective_keep_count(photos, 2))
        self.assertEqual(3, effective_keep_count(photos, 3))

    def test_gap_measured_against_the_best_not_the_neighbor(self):
        # A slow drift must not keep everything: c is > KEEP_GAP below the
        # best even though each step is small.
        photos = [_photo("a", 0.50), _photo("b", 0.47), _photo("c", 0.44)]
        self.assertLessEqual(0.03, KEEP_GAP)  # guards the fixture's intent
        self.assertEqual(2, effective_keep_count(photos, 3))

    def test_single_and_empty(self):
        self.assertEqual(1, effective_keep_count([_photo("a", 0.4)], 2))
        self.assertEqual(0, effective_keep_count([], 2))
        self.assertEqual(1, effective_keep_count([_photo("a", 0.4)], 1))


class AssignVerdictsGapTests(unittest.TestCase):
    def _cluster_with(self, scores: list[float]) -> tuple[Cluster, dict]:
        photos = [_photo(f"p{i}", s) for i, s in enumerate(scores)]
        cluster = Cluster(id="c1", label="c1", member_count=len(photos))
        return cluster, {"c1": photos}

    def test_clearly_worse_runner_up_is_archived(self):
        cluster, cp = self._cluster_with([0.49, 0.31])
        assign_verdicts([cluster], cp, keep_per_cluster=2)
        verdicts = {p.id: p.verdict for p in cp["c1"]}
        self.assertEqual(Verdict.KEEP, verdicts["p0"])
        self.assertEqual(Verdict.ARCHIVE, verdicts["p1"])
        self.assertEqual(1, cluster.keep_count)

    def test_near_equal_members_both_kept(self):
        cluster, cp = self._cluster_with([0.49, 0.48, 0.20])
        assign_verdicts([cluster], cp, keep_per_cluster=2)
        kept = [p.id for p in cp["c1"] if p.verdict == Verdict.KEEP]
        self.assertEqual(["p0", "p1"], sorted(kept))

    def test_exact_dup_cluster_still_keeps_one(self):
        cluster, cp = self._cluster_with([0.49, 0.49])
        cluster.is_exact_dup_group = True
        assign_verdicts([cluster], cp, keep_per_cluster=2)
        self.assertEqual(1, cluster.keep_count)


if __name__ == "__main__":
    unittest.main()
