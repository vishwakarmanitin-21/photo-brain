"""Blind labelling window for the ranking scorecard (RANK-01).

Shows the photos of one moment (a burst / run of retakes) at a time, with NO
app scores or suggestions on screen, so the person's picks are their own and
can grade the app fairly. Labels: ★ best / keep / redundant / junk. Every
saved page is written to disk immediately, so closing the window mid-way
loses nothing. All logic (moments, ordering, storage) lives in
app/core/ranking_eval.py; this module is widgets only.
"""
import os

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.hashing import compute_sha256
from app.ui.image_loading import load_bounded_image
from app.core.ranking_eval import (
    LabelStore, Moment, build_moments, labelling_order, labels_path,
)
from app.workers.label_index_worker import LabelIndexWorker

# 4 across x 3 down fits a 1400x900 window without scrolling; each tile's
# button row sets its minimum width, so more columns would overflow.
SINGLES_PER_PAGE = 12
COLUMNS = 4
LABEL_TEXT = {"best": "★ Best", "keep": "Keep", "redundant": "Redundant", "junk": "Junk"}
LABEL_COLOR = {"best": "#d97706", "keep": "#16a34a", "redundant": "#6b7280", "junk": "#dc2626"}
KEY_LABEL = {Qt.Key_1: "best", Qt.Key_2: "keep", Qt.Key_3: "redundant", Qt.Key_4: "junk"}

SERIES_HELP = ("<b>Pick the shot you would keep.</b> Click a photo to star it as ★ Best (you can star more "
               "than one). Mark weaker near-copies <b>Redundant</b> and bad photos <b>Junk</b>; anything "
               "unmarked counts as Keep. Keys: <b>1</b> best · <b>2</b> keep · <b>3</b> redundant · "
               "<b>4</b> junk · arrows move · <b>Enter</b> save &amp; next · <b>S</b> skip · "
               "<b>Backspace</b> back · <b>O</b> or double-click opens full size.")
SINGLES_HELP = ("<b>Mark the bad ones.</b> Click a photo to toggle <b>Junk</b> (blurry, dark, accidental, "
                "useless). Anything unmarked counts as Keep. Press <b>1</b> on a photo you think is "
                "genuinely great (★ Best). Same keys as before; <b>Enter</b> saves the page.")


class _LoadSignals(QObject):
    loaded = Signal(int, str, QImage, str)  # page token, rel path, image, sha256


class _LoadTask(QRunnable):
    def __init__(self, token: int, root: str, rel: str, edge: int, signals: _LoadSignals):
        super().__init__()
        self.token, self.root, self.rel, self.edge, self.signals = token, root, rel, edge, signals

    def run(self):
        path = os.path.join(self.root, self.rel)
        image = load_bounded_image(path, self.edge)
        sha = compute_sha256(path) or ""
        try:
            self.signals.loaded.emit(self.token, self.rel, image, sha)
        except RuntimeError:
            pass  # the window closed before this load finished


class _ClickLabel(QLabel):
    clicked = Signal()
    double_clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()


class _Tile(QFrame):
    def __init__(self, rel: str, edge: int, on_click, on_open, on_set):
        super().__init__()
        self.rel = rel
        self.setFrameShape(QFrame.Box)
        self.setLineWidth(3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        self.image = _ClickLabel("Loading…")
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setFixedSize(edge, edge)
        self.image.clicked.connect(on_click)
        self.image.double_clicked.connect(on_open)
        layout.addWidget(self.image, 0, Qt.AlignHCenter)
        self.badge = QLabel()
        self.badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.badge)
        row = QHBoxLayout()
        for label in ("best", "keep", "redundant", "junk"):
            button = QPushButton(LABEL_TEXT[label])
            button.setFocusPolicy(Qt.NoFocus)
            button.setStyleSheet("padding: 3px 4px;")  # compact: four must fit under one photo
            button.clicked.connect(lambda _=False, lab=label: on_set(lab))
            row.addWidget(button)
        layout.addLayout(row)
        name = QLabel(os.path.basename(rel))
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(name)
        self._label = None
        self._focused = False

    def set_image(self, image: QImage):
        if image.isNull():
            self.image.setText("Cannot display")
            return
        ratio = max(1.0, self.devicePixelRatioF())  # sharp on scaled displays (UX-19)
        pix = QPixmap.fromImage(image).scaled(self.image.size() * ratio, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
        pix.setDevicePixelRatio(ratio)
        self.image.setPixmap(pix)

    def set_label(self, label):
        self._label = label
        self._restyle()

    def set_focused(self, focused: bool):
        self._focused = focused
        self._restyle()

    def _restyle(self):
        shown = self._label or "keep"
        color = LABEL_COLOR[shown] if self._label else "#9ca3af"
        text = LABEL_TEXT[shown] + ("" if self._label else " (default)")
        self.badge.setText(text)
        self.badge.setStyleSheet(f"font-weight: bold; color: {color};")
        outline = "#2563eb" if self._focused else color
        self.setStyleSheet(f"_Tile {{ border: 3px solid {outline}; border-radius: 6px; }}")


class RankingLabelWindow(QMainWindow):
    def __init__(self, root: str):
        super().__init__()
        self.root = root
        self.store = LabelStore(labels_path(root))
        self.pages: list[list[Moment]] = []
        self.series_ids: set[str] = set()
        self.page_idx = 0
        self.token = 0
        self.current: dict[str, str | None] = {}
        self.shas: dict[str, str] = {}
        self.tiles: list[_Tile] = []
        self.cols = 1
        self.focus = 0
        self.dirty = False
        self.pool = QThreadPool.globalInstance()
        self.signals = _LoadSignals()
        self.signals.loaded.connect(self._on_loaded)

        self.setWindowTitle("PhotoBrain — label photos for the ranking scorecard")
        self.resize(1400, 900)
        central = QWidget()
        outer = QVBoxLayout(central)
        self.title = QLabel("Finding photos and reading their dates…")
        self.title.setStyleSheet("font-size: 17px; font-weight: bold;")
        outer.addWidget(self.title)
        self.help = QLabel()
        self.help.setWordWrap(True)
        outer.addWidget(self.help)
        self.bar = QProgressBar()
        outer.addWidget(self.bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.scroll.setWidget(self.grid_host)
        outer.addWidget(self.scroll, 1)
        buttons = QHBoxLayout()
        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")
        buttons.addWidget(self.status, 1)
        self.back_btn = QPushButton("◀ Back")
        self.skip_btn = QPushButton("Skip")
        self.next_btn = QPushButton("Save && next ▶")
        for b, slot in ((self.back_btn, self._back), (self.skip_btn, self._skip), (self.next_btn, self._next)):
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(slot)
            b.setEnabled(False)
            buttons.addWidget(b)
        outer.addLayout(buttons)
        self.setCentralWidget(central)
        self.setFocusPolicy(Qt.StrongFocus)

        self.worker = LabelIndexWorker(root)
        self.worker.progress.connect(self._on_index_progress)
        self.worker.finished_index.connect(self._on_indexed)
        self.worker.failed.connect(lambda msg: QMessageBox.critical(self, "Cannot read folder", msg))
        self.worker.start()

    # ── indexing ──
    def _on_index_progress(self, done: int, total: int):
        self.bar.setMaximum(total)
        self.bar.setValue(done)
        self.title.setText(f"Finding photos and reading their dates… {done:,} of {total:,}")

    def _on_indexed(self, entries: list):
        self.bar.hide()
        ordered = labelling_order(build_moments(entries))
        series = [m for m in ordered if m.is_series]
        singles = [m for m in ordered if not m.is_series]
        self.series_ids = {m.id for m in series}
        self.pages = [[m] for m in series] + [
            singles[i:i + SINGLES_PER_PAGE] for i in range(0, len(singles), SINGLES_PER_PAGE)
        ]
        if not self.pages:
            self.title.setText("No photos found in this folder.")
            return
        done = self.store.reviewed_moments | self.store.skipped_moments
        start = next((i for i, page in enumerate(self.pages)
                      if any(m.id not in done for m in page)), None)
        if start is None:
            QMessageBox.information(self, "All labelled", "Every moment here is already labelled or skipped.")
            start = 0
        for b in (self.back_btn, self.skip_btn, self.next_btn):
            b.setEnabled(True)
        self._show_page(start)

    # ── page display ──
    def _is_series_page(self) -> bool:
        page = self.pages[self.page_idx]
        return len(page) == 1 and page[0].is_series

    def _show_page(self, idx: int):
        self.page_idx = idx
        self.token += 1
        self.dirty = False
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        page = self.pages[idx]
        rels = [r for m in page for r in m.paths]
        self.current = {r: self.store.label_of(r) for r in rels}
        series = self._is_series_page()
        self.cols = min(len(rels), COLUMNS)
        edge = self._tile_edge(len(rels))
        self.tiles = []
        for i, rel in enumerate(rels):
            tile = _Tile(rel, edge,
                         on_click=lambda r=rel: self._click(r),
                         on_open=lambda r=rel: self._open(r),
                         on_set=lambda lab, r=rel: self._set(r, lab))
            tile.set_label(self.current[rel])
            self.grid.addWidget(tile, i // self.cols, i % self.cols)
            self.tiles.append(tile)
            decode_px = int(edge * max(1.0, self.devicePixelRatioF()))
            self.pool.start(_LoadTask(self.token, self.root, rel, decode_px, self.signals))
        self.focus = 0
        self._refocus()
        if series:
            m = page[0]
            when = (m.start or "").replace("T", " ")[:16] or "unknown time"
            self.title.setText(f"Series {idx + 1:,} of {len(self.series_ids):,} — {len(rels)} photos taken {when}")
            self.help.setText(SERIES_HELP)
        else:
            n_single_pages = len(self.pages) - len(self.series_ids)
            k = idx - len(self.series_ids) + 1
            self.title.setText(f"Single photos — page {k:,} of {n_single_pages:,}")
            self.help.setText(SINGLES_HELP)
        self.back_btn.setEnabled(idx > 0)
        self._update_status()
        self.scroll.verticalScrollBar().setValue(0)
        self.setFocus()

    # Space a tile needs beyond its image: frame + margins sideways; the label,
    # button row and file name below. Sized so a whole page fits the window
    # without scrolling, so every frame of a burst can be compared at once.
    _TILE_EXTRA_W = 44
    _TILE_EXTRA_H = 100

    def _tile_edge(self, count: int) -> int:
        viewport = self.scroll.viewport()
        rows = -(-count // self.cols)
        spacing = self.grid.horizontalSpacing() + 2
        by_width = (viewport.width() - spacing * (self.cols + 1)) // self.cols - self._TILE_EXTRA_W
        by_height = (viewport.height() - spacing * (rows + 1)) // rows - self._TILE_EXTRA_H
        return max(140, min(560, by_width, by_height))

    def _on_loaded(self, token: int, rel: str, image: QImage, sha: str):
        if sha:
            self.shas[rel] = sha
        if token != self.token:
            return  # a late load for a page already left
        for tile in self.tiles:
            if tile.rel == rel:
                tile.set_image(image)

    def _update_status(self):
        series_done = len(self.series_ids & self.store.reviewed_moments)
        self.status.setText(
            f"Labelled so far: {len(self.store.labels):,} photos · {series_done:,} of "
            f"{len(self.series_ids):,} series · saved to {self.store.path}")

    # ── labelling ──
    def _set(self, rel: str, label: str):
        self.current[rel] = label
        self.dirty = True
        for i, tile in enumerate(self.tiles):
            if tile.rel == rel:
                tile.set_label(label)
                self.focus = i
        self._refocus()

    def _click(self, rel: str):
        now = self.current.get(rel)
        if self._is_series_page():
            self._set(rel, "keep" if now == "best" else "best")
        else:
            self._set(rel, "keep" if now == "junk" else "junk")

    def _open(self, rel: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.join(self.root, rel)))

    def _refocus(self):
        for i, tile in enumerate(self.tiles):
            tile.set_focused(i == self.focus)
        if self.tiles:
            self.scroll.ensureWidgetVisible(self.tiles[self.focus])

    # ── navigation ──
    def _save_page(self):
        for moment in self.pages[self.page_idx]:
            labels = {r: lab for r in moment.paths if (lab := self.current.get(r))}
            shas = {r: self.shas.get(r) or compute_sha256(os.path.join(self.root, r)) for r in moment.paths}
            self.store.record_moment(moment, labels, shas)
        self.store.save()
        self.dirty = False

    def _next(self):
        self._save_page()
        if self.page_idx + 1 >= len(self.pages):
            QMessageBox.information(self, "Done", "That was the last page — every moment is labelled. Thank you!")
            self._update_status()
            return
        self._show_page(self.page_idx + 1)

    def _skip(self):
        for moment in self.pages[self.page_idx]:
            if moment.id not in self.store.reviewed_moments:
                self.store.skip_moment(moment)
        self.store.save()
        if self.page_idx + 1 < len(self.pages):
            self._show_page(self.page_idx + 1)

    def _back(self):
        if self.dirty:
            self._save_page()
        if self.page_idx > 0:
            self._show_page(self.page_idx - 1)

    def keyPressEvent(self, event):
        key = event.key()
        if not self.tiles:
            return super().keyPressEvent(event)
        if key in KEY_LABEL:
            self._set(self.tiles[self.focus].rel, KEY_LABEL[key])
        elif key == Qt.Key_Space:
            self._click(self.tiles[self.focus].rel)
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self._next()
        elif key == Qt.Key_Backspace:
            self._back()
        elif key == Qt.Key_S:
            self._skip()
        elif key == Qt.Key_O:
            self._open(self.tiles[self.focus].rel)
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -self.cols, Qt.Key_Down: self.cols}[key]
            self.focus = max(0, min(len(self.tiles) - 1, self.focus + step))
            self._refocus()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.dirty and self.pages:
            self._save_page()
        self.worker.cancel()
        self.worker.wait(3000)
        self.pool.clear()
        super().closeEvent(event)
