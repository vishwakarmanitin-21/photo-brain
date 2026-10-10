"""RANK-01 gate: a change to scoring code must ship with a fresh scorecard.

docs/ranking-baseline.json records the fingerprint of every file that decides
a photo's score, group or verdict (ranking_eval.SCORER_FILES) at the time the
scorecard was last run. If any of them changes and the baseline is not
refreshed, this test fails — so a ranking change cannot land unmeasured.

To fix a failure: run
    venv\\Scripts\\python scripts\\eval_ranking.py <labelled folder> --update-baseline
and commit docs/ranking-baseline.json with the change. The script refuses to
record a result that is worse on the same labels unless told the trade-off
is deliberate (--accept-regression).
"""
import json
import os
import unittest

from app.core.ranking_eval import scorer_fingerprint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "docs", "ranking-baseline.json")


class RankingBaselineTests(unittest.TestCase):
    def test_baseline_matches_current_scoring_code(self):
        if not os.path.isfile(BASELINE):
            self.skipTest("no ranking baseline yet — the first scorecard run creates it (RANK-01)")
        with open(BASELINE, encoding="utf-8") as fh:
            recorded = json.load(fh)["scorer_fingerprint"]
        self.assertEqual(
            recorded, scorer_fingerprint(ROOT),
            "Scoring code changed since the ranking scorecard was last run. Run "
            "scripts/eval_ranking.py <folder> --update-baseline and commit "
            "docs/ranking-baseline.json with this change.")


if __name__ == "__main__":
    unittest.main()
