r"""Label photos for the ranking scorecard (RANK-01).

Opens a window that shows your photos one moment (burst) at a time, with no
app scores visible, so you can mark the shot you would keep. Labels save as
you go to <folder>\.photobrain\ranking-labels.json - stop and resume any time.

Usage:
    venv\Scripts\python scripts\label_photos.py "D:\OneDrive\Pictures\Camera Roll"

Then measure the app against your labels:
    venv\Scripts\python scripts\eval_ranking.py "D:\OneDrive\Pictures\Camera Roll"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", default=os.environ.get("PHOTOBRAIN_EVAL_ROOT"),
                        help="photo folder to label (default: PHOTOBRAIN_EVAL_ROOT)")
    args = parser.parse_args()
    if not args.folder or not os.path.isdir(args.folder):
        parser.error(r'give the photo folder to label, e.g. "D:\OneDrive\Pictures\Camera Roll"')

    from PySide6.QtWidgets import QApplication
    from app.ui.ranking_label_window import RankingLabelWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RankingLabelWindow(os.path.abspath(args.folder))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
