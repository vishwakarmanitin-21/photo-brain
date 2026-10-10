"""Ranking scorecard (RANK-01): how often does PhotoBrain pick what you picked?

Runs the app's real scan pipeline (app/core/pipeline.py) over the photos you
labelled with scripts/label_photos.py, and compares its scores and suggested
verdicts with your labels. Read-only: photos are never moved or modified.

Usage:
    venv\\Scripts\\python scripts\\eval_ranking.py "D:\\OneDrive\\Pictures\\Camera Roll"
    venv\\Scripts\\python scripts\\eval_ranking.py <folder> --update-baseline

--update-baseline records the result in docs/ranking-baseline.json (aggregate
numbers only — no file names). It REFUSES if any headline number got worse
on the same labels, unless --accept-regression is given; the commit that
changes scoring must carry the refreshed baseline, or
tests/test_ranking_baseline.py fails.

Exit codes: 0 ok · 1 regression refused · 2 nothing labelled yet.
"""
import argparse
import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core.pipeline import AnalysisOptions, PipelineHooks, analyze  # noqa: E402
from app.core.ranking_eval import (  # noqa: E402
    HEADLINES, LabelStore, compute_metrics, headline, labels_path, regressions,
    scorer_fingerprint,
)

BASELINE = os.path.join(ROOT, "docs", "ranking-baseline.json")

# Plain-English names for the headline numbers, in report order.
EXPLAIN = {
    "best_pick": "Best pick - in series where you starred a shot, the app's top photo was one you starred",
    "pairwise": "Pairwise order - of photo pairs you rated differently, the app scored them the same way round",
    "junk_caught": "Junk caught - of photos you marked junk, the app flagged them as low quality",
    "junk_false_alarm": "False alarms - of photos you'd keep, the app wrongly flagged as low quality (lower is better)",
    "verdict_agreement": "Keep/set-aside agreement - the app's suggested verdict matched your keep-or-not call",
    "shortlist": "Shortlist - of the app's top-K photos (K = how many you starred), how many you starred",
}


def _pct(value):
    return "  n/a " if value is None else f"{value:6.1%}"


@contextlib.contextmanager
def _quiet_native_stderr(enabled: bool):
    """Mute the face models' native (C++) log lines, which go straight to the
    process's stderr and bury the report. Python progress goes to stdout and
    stays visible; --verbose turns the native output back on."""
    if not enabled:
        yield
        return
    sys.stderr.flush()
    saved = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        yield
    finally:
        sys.stderr.flush()
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def run(folder: str, quiet: bool = True):
    store = LabelStore(labels_path(folder))
    if not store.labels:
        print(f"No labels yet in {store.path}.\n"
              f"Label some photos first:\n  venv\\Scripts\\python scripts\\label_photos.py \"{folder}\"")
        return None

    missing, files = [], []
    for rel in sorted(store.labels):
        path = os.path.join(folder, rel)
        if os.path.isfile(path):
            files.append(path)
        else:
            missing.append(rel)
    print(f"Grading {len(files):,} labelled photos from {folder}")
    if missing:
        print(f"  ! {len(missing)} labelled photos no longer exist (moved or deleted) - left out.")

    started = time.time()
    last = {"t": 0.0}

    def progress(label, cur, total, fname):
        if time.time() - last["t"] > 5 or cur == total:
            last["t"] = time.time()
            print(f"    {label}: {cur:,} / {total:,}", flush=True)

    hooks = PipelineHooks(phase=lambda d: print(f"  {d}", flush=True), progress=progress)
    with _quiet_native_stderr(quiet):
        result = analyze(files, AnalysisOptions(), hooks)
        try:
            from app.core.faces import cleanup
            cleanup()
        except Exception:
            pass

    photos, changed = {}, []
    for p in result.photos:
        rel = os.path.relpath(p.filepath, folder)
        expected = store.labels[rel].get("sha256")
        if expected and p.sha256 and expected != p.sha256:
            changed.append(rel)  # file edited after labelling - its label may not apply
            continue
        photos[rel] = p
    if changed:
        print(f"  ! {len(changed)} photos changed since you labelled them - left out.")

    labels = {rel: e["label"] for rel, e in store.labels.items()}
    moment_of = {rel: e.get("moment", rel) for rel, e in store.labels.items()}
    metrics = compute_metrics(photos, labels, moment_of)
    print(f"  Analysed in {time.time() - started:,.0f}s")
    return store, metrics


def report(metrics: dict, baseline: dict | None):
    c = metrics["label_counts"]
    print("\n================ PhotoBrain ranking scorecard ================")
    print(f"Graded {metrics['photos_graded']:,} photos in {metrics['moments_graded']:,} moments "
          f"({metrics['series_graded']:,} series of 2+). Your labels: {c['best']} best, {c['keep']} keep, "
          f"{c['redundant']} redundant, {c['junk']} junk.\n")
    now, old = headline(metrics), headline(baseline["metrics"]) if baseline else {}
    for name in HEADLINES:
        delta = ""
        if old.get(name) is not None and now.get(name) is not None:
            d = now[name] - old[name]
            delta = f"  ({'+' if d >= 0 else ''}{d:.1%} vs baseline)" if abs(d) >= 0.0005 else "  (= baseline)"
        print(f"  {_pct(now[name])}  {EXPLAIN[name]}{delta}")
    bp, j, v, s = metrics["best_pick"], metrics["junk"], metrics["verdicts"], metrics["shortlist"]
    print("\nDenominators:")
    print(f"  best pick: {bp['hits']} of {bp['series']} series (a random pick would score {_pct(bp['chance']).strip()})")
    print(f"  pairwise: {metrics['pairwise']['pairs']:,} pairs | junk caught: {j['caught']} of {j['junk_total']}"
          f" | false alarms: {j['wanted_flagged']} of {j['wanted_total']} | shortlist: {s['hits']} of {s['k']}")
    print(f"  verdicts: {v['wanted_set_aside']} photos you'd keep would be ARCHIVED/DELETED by the suggestions; "
          f"{v['unwanted_kept']} you didn't want would be KEPT")
    for key, title in (("wanted_set_aside_examples", "Kept-by-you but set aside by the app"),
                       ("unwanted_kept_examples", "Unwanted but kept by the app")):
        if v[key]:
            print(f"  {title} (first {len(v[key])}):")
            for rel in v[key]:
                print(f"    - {rel}")
    if metrics["photos_graded"] < 200 or bp["series"] < 30:
        print("\n  Note: a small label set - treat differences of a few points as noise. More labels = firmer numbers.")


def public_metrics(metrics: dict) -> dict:
    """Metrics without file names — safe for the public repo."""
    out = json.loads(json.dumps(metrics))
    for key in ("wanted_set_aside_examples", "unwanted_kept_examples"):
        out["verdicts"].pop(key, None)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default=os.environ.get("PHOTOBRAIN_EVAL_ROOT"))
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--accept-regression", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="show the face models' native log output")
    args = parser.parse_args()
    if not args.folder or not os.path.isdir(args.folder):
        parser.error("give the labelled photo folder (or set PHOTOBRAIN_EVAL_ROOT)")
    logging.basicConfig(level=logging.ERROR)
    folder = os.path.abspath(args.folder)

    outcome = run(folder, quiet=not args.verbose)
    if outcome is None:
        return 2
    store, metrics = outcome

    baseline = None
    if os.path.isfile(BASELINE):
        with open(BASELINE, encoding="utf-8") as fh:
            baseline = json.load(fh)
    same_labels = bool(baseline) and baseline.get("labels_fingerprint") == store.fingerprint()
    report(metrics, baseline if same_labels else None)
    if baseline and not same_labels:
        print(f"\n  Labels changed since the baseline ({baseline.get('photos_graded')} -> "
              f"{metrics['photos_graded']} photos), so numbers are not compared.")

    # Private copy beside the labels (includes example file names), plus a history line.
    pb = os.path.dirname(store.path)
    stamp = {"date": date.today().isoformat(), "git_commit": _git_head(),
             "scorer_fingerprint": scorer_fingerprint(ROOT), "labels_fingerprint": store.fingerprint()}
    latest = os.path.join(pb, "ranking-scorecard-latest.json")
    with open(latest + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({**stamp, "metrics": metrics}, fh, indent=1, ensure_ascii=False)
    os.replace(latest + ".tmp", latest)
    with open(os.path.join(pb, "ranking-scorecard-history.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**stamp, "headline": headline(metrics)}) + "\n")

    if not args.update_baseline:
        if baseline and baseline.get("scorer_fingerprint") != stamp["scorer_fingerprint"]:
            print("\n  Scoring code has changed since the baseline. Record this result with --update-baseline "
                  "(tests fail until you do).")
        return 0

    worse = regressions(metrics, baseline["metrics"]) if same_labels else []
    if worse and not args.accept_regression:
        print("\n  REFUSED: the ranking got worse on the same labels:")
        for line in worse:
            print(f"    - {line}")
        print("  Fix the change, or re-run with --accept-regression if the trade-off is deliberate "
              "(say why in the commit message).")
        return 1
    with open(BASELINE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({**stamp, "photos_graded": metrics["photos_graded"],
                   "accepted_regressions": worse, "headline": headline(metrics),
                   "metrics": public_metrics(metrics)}, fh, indent=1)
        fh.write("\n")
    print(f"\n  Baseline updated: {os.path.relpath(BASELINE, ROOT)} - commit it with the scoring change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
