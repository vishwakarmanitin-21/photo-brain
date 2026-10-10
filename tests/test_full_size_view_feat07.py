"""FEAT-07: full-size viewer (fit / 100% / zoom / pan, ←/→, K/A/D, Ctrl+Z),
the shared zoom-pan panel, Compare's linked zoom, and Ctrl+wheel tile size."""
import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.models import Cluster, Photo, Verdict
from app.ui.compare_dialog import CompareDialog
from app.ui.photo_viewer import PhotoViewer
from app.ui.review_view import ReviewView
from app.ui.zoom_pan_view import ZoomPanView


def _app():
    return QApplication.instance() or QApplication([])


def _wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end and not cond():
        QApplication.processEvents()
        time.sleep(0.02)
    return cond()


def _image(w, h, color=(30, 120, 200)):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(*color))
    return img


def _jpeg(folder, name, w=1600, h=1200, color=(90, 120, 150)):
    path = os.path.join(folder, name)
    Image.new("RGB", (w, h), color).save(path, quality=90)
    return path


def _photo(path, pid, cid="c1", score=0.5):
    return Photo(id=pid, filepath=path, filename=os.path.basename(path), file_size=1,
                 sharpness=100.0, brightness=120.0, quality_score=score,
                 verdict=Verdict.REVIEW, cluster_id=cid)


class ZoomPanViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _view(self, natural=QSize(4000, 3000), loaded=(1000, 750)):
        v = ZoomPanView()
        self.addCleanup(v.deleteLater)
        v.resize(800, 600)
        v.set_image(_image(*loaded), natural)
        return v

    def test_starts_at_fit_and_goes_to_100_percent(self):
        v = self._view()
        self.assertTrue(v.is_fit())
        self.assertEqual(20, v.zoom_percent())           # 4000 px into 800 px
        v.actual_size()
        self.assertEqual(100, v.zoom_percent())
        v.toggle_fit_actual()
        self.assertTrue(v.is_fit())

    def test_zoom_keeps_the_point_under_the_cursor(self):
        v = self._view()
        anchor = QPointF(600, 150)
        before = v._photo_point(anchor)
        v.zoom_by(3.0, anchor)
        after = v._photo_point(anchor)
        self.assertAlmostEqual(before[0], after[0], places=3)
        self.assertAlmostEqual(before[1], after[1], places=3)

    def test_pan_is_clamped_to_the_photo(self):
        v = self._view()
        v.actual_size()
        v._cx, v._cy = 5.0, -5.0
        v._clamp_centre()
        rect = v._target_rect()
        self.assertLessEqual(rect.left(), 0)
        self.assertGreaterEqual(rect.right(), v.width())
        self.assertLessEqual(rect.top(), 0)

    def test_swapping_in_full_resolution_keeps_the_view(self):
        v = self._view()
        v.zoom_by(4.0, QPointF(200, 200))
        state = (v.zoom(), v._cx, v._cy)
        v.set_image(_image(4000, 3000), QSize(4000, 3000), keep_view=True)
        self.assertEqual(state, (v.zoom(), v._cx, v._cy))
        self.assertTrue(v.loaded_is_full_resolution())

    def test_asks_for_full_resolution_only_when_needed(self):
        v = self._view()
        asked = []
        v.wants_full_resolution.connect(lambda: asked.append(True))
        v.zoom_by(1.1)                       # 22% of 4000 px: the 1000-px copy still suffices
        self.assertEqual([], asked)
        v.actual_size()                      # 100% needs the real pixels
        self.assertEqual([True], asked)
        v.zoom_by(2.0)
        self.assertEqual([True], asked)      # once

    def test_user_changes_announce_programmatic_ones_do_not(self):
        v = self._view()
        seen = []
        v.view_changed.connect(lambda *a: seen.append(a))
        v.set_view(3.0, 0.3, 0.4)
        self.assertEqual([], seen)
        v.zoom_by(2.0)
        self.assertEqual(1, len(seen))

    def test_small_photo_is_never_enlarged_to_fit(self):
        v = self._view(natural=QSize(400, 300), loaded=(400, 300))   # smaller than the 800x600 panel
        self.assertEqual(100, v.zoom_percent())
        self.assertTrue(v.is_fit())
        v.zoom_by(0.5)                                           # cannot shrink below true size either
        self.assertEqual(100, v.zoom_percent())

    def test_wheel_zooms(self):
        v = self._view()
        ev = QWheelEvent(QPointF(400, 300), QPointF(400, 300), QPoint(0, 0), QPoint(0, 120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        v.wheelEvent(ev)
        self.assertGreater(v.zoom_percent(), 20)


class PhotoViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_navigate_decide_undo_and_zoom(self):
        with tempfile.TemporaryDirectory() as d:
            photos = [_photo(_jpeg(d, f"{i}.jpg", color=(40 * i, 90, 90)), f"p{i}") for i in range(3)]
            decided, undone = [], []
            viewer = PhotoViewer(photos, 1, on_verdict=lambda p, v: decided.append((p.id, v)),
                                 on_undo=lambda: undone.append(True))
            self.addCleanup(viewer.deleteLater)
            viewer.resize(1000, 700)
            self.assertTrue(_wait(viewer._view.has_image))
            self.assertIn("2 of 3", viewer._title.text())
            QTest.keyClick(viewer, Qt.Key_Right)
            self.assertEqual("p2", viewer.current_photo().id)
            QTest.keyClick(viewer, Qt.Key_Right)                 # stops at the end
            self.assertEqual("p2", viewer.current_photo().id)
            QTest.keyClick(viewer, Qt.Key_K)
            self.assertEqual([("p2", Verdict.KEEP)], decided)
            QTest.keyClick(viewer, Qt.Key_Z, Qt.ControlModifier)
            self.assertEqual([True], undone)
            self.assertTrue(_wait(viewer._view.has_image))
            QTest.keyClick(viewer, Qt.Key_Space)                 # fit -> 100%
            self.assertEqual(100, viewer._view.zoom_percent())
            # 100% of a 1600-px photo needs the full decode, swapped in place
            self.assertTrue(_wait(viewer._view.loaded_is_full_resolution))
            self.assertEqual(100, viewer._view.zoom_percent())
            QTest.keyClick(viewer, Qt.Key_Left)
            self.assertEqual("p1", viewer.current_photo().id)


class ReviewIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def _view(self, folder):
        rv = ReviewView()
        self.addCleanup(rv.deleteLater)
        photos = [_photo(_jpeg(folder, f"{i}.jpg"), f"p{i}", score=0.9 - i / 10) for i in range(3)]
        rv.load_data([Cluster(id="c1", label="c1", member_count=3)], {"c1": photos},
                     has_undo=False, events=[])
        rv.set_hide_singletons(False)
        return rv, photos

    def test_double_click_opens_the_viewer_on_that_photo(self):
        with tempfile.TemporaryDirectory() as d:
            rv, photos = self._view(d)
            opened = []

            class FakeViewer:
                def __init__(self, ps, index, **kw):
                    opened.append(ps[index].id)
                    self._p = ps[index]

                def exec(self):
                    return 0

                def current_photo(self):
                    return self._p

            with patch("app.ui.review_view.PhotoViewer", FakeViewer):
                rv._thumb_widgets["p2"].open_requested.emit("p2")
            self.assertEqual(["p2"], opened)
            self.assertEqual("p2", rv._selected_photo_id)      # grid follows the viewer

    def test_viewer_decision_counts_and_undoes_like_a_tile_decision(self):
        with tempfile.TemporaryDirectory() as d:
            rv, photos = self._view(d)
            rv._reset_verdict_history()
            rv._viewer_set_verdict(photos[1], Verdict.DELETE)
            self.assertEqual(Verdict.DELETE, photos[1].verdict)
            self.assertTrue(photos[1].user_override)
            rv._viewer_undo()
            self.assertEqual(Verdict.REVIEW, photos[1].verdict)

    def test_ctrl_wheel_on_the_grid_changes_tile_size(self):
        with tempfile.TemporaryDirectory() as d:
            rv, _ = self._view(d)
            before = rv._zoom_slider.value()
            ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                             Qt.NoButton, Qt.ControlModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(rv._scroll.viewport(), ev)
            self.assertGreater(rv._zoom_slider.value(), before)

    def test_space_in_the_search_box_types_instead_of_opening(self):
        with tempfile.TemporaryDirectory() as d:
            rv, _ = self._view(d)
            rv.resize(1800, 800)
            rv.show()
            self.addCleanup(rv.close)
            QApplication.processEvents()
            rv._search_box.setFocus()
            QApplication.processEvents()
            with patch.object(ReviewView, "_open_viewer") as open_viewer:
                QTest.keyClick(rv._search_box, Qt.Key_Space)
            open_viewer.assert_not_called()
            self.assertEqual(" ", rv._search_box.text())


class CompareLinkedZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_zooming_one_photo_zooms_the_others_and_fetches_full_size(self):
        with tempfile.TemporaryDirectory() as d:
            photos = [_photo(_jpeg(d, f"{i}.jpg"), f"p{i}") for i in range(3)]
            dlg = CompareDialog(photos, image_px=300)
            self.addCleanup(dlg.deleteLater)
            self.assertTrue(_wait(lambda: all(p.view.has_image() for p in dlg._panels)))
            first, others = dlg._panels[0].view, [p.view for p in dlg._panels[1:]]
            first.zoom_by(3.0, QPointF(250, 80))
            for v in others:
                self.assertAlmostEqual(first.zoom() / first.fit_zoom(), v.zoom() / v.fit_zoom(), places=3)
                self.assertAlmostEqual(first._cx, v._cx, places=3)
            self.assertTrue(_wait(lambda: all(p.view.loaded_is_full_resolution() for p in dlg._panels)))

    def test_close_button_is_present(self):
        from PySide6.QtWidgets import QDialogButtonBox
        with tempfile.TemporaryDirectory() as d:
            dlg = CompareDialog([_photo(_jpeg(d, "a.jpg"), "a"), _photo(_jpeg(d, "b.jpg"), "b")], image_px=200)
            self.addCleanup(dlg.deleteLater)
            boxes = dlg.findChildren(QDialogButtonBox)
            self.assertEqual(1, len(boxes))
            self.assertIsNotNone(boxes[0].button(QDialogButtonBox.Close))


if __name__ == "__main__":
    unittest.main()
