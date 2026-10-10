"""Background indexing for the ranking-label window (RANK-01): find every photo
under a root and read its capture time, without freezing the window."""
from PySide6.QtCore import QThread, Signal

from app.core.ranking_eval import index_root


class LabelIndexWorker(QThread):
    progress = Signal(int, int)        # done, total
    finished_index = Signal(list)      # [(relative_path, iso_time_or_None), ...]
    failed = Signal(str)

    def __init__(self, root: str):
        super().__init__()
        self.root = root
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            entries = index_root(self.root, self.progress.emit, lambda: self._cancelled)
        except Exception as e:  # surfaced to the window, not swallowed
            self.failed.emit(str(e))
            return
        if entries is not None:
            self.finished_index.emit(entries)
