import os
import tempfile
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from app.core.models import Photo
from app.core.thumbnails import PreviewCache
from app.workers.preview_worker import PreviewWorker


class RecordingPreviewCache(PreviewCache):
    def __init__(self, cache_dir):
        super().__init__(cache_dir)
        self.thread_ids = []

    def generate_preview(self, photo, display_size):
        self.thread_ids.append(threading.get_ident())
        return super().generate_preview(photo, display_size)


class PreviewWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_original_decode_and_resize_run_on_worker_thread(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "large.jpg")
            Image.new("RGB", (1200, 800), (30, 100, 180)).save(image_path)
            photo = Photo(
                id="photo-1",
                filepath=image_path,
                filename="large.jpg",
                file_size=os.path.getsize(image_path),
            )
            cache = RecordingPreviewCache(os.path.join(temp_dir, "previews"))
            worker = PreviewWorker([photo], 400, cache)
            ready = QSignalSpy(worker.preview_ready)
            finished = QSignalSpy(worker.all_finished)
            main_thread_id = threading.get_ident()

            worker.start()
            self.assertTrue(worker.wait(5000))
            QApplication.processEvents()

            self.assertEqual(1, ready.count())
            self.assertEqual(1, finished.count())
            self.assertEqual(1, len(cache.thread_ids))
            self.assertNotEqual(main_thread_id, cache.thread_ids[0])
            emitted = ready.at(0)
            self.assertEqual("photo-1", emitted[0])
            self.assertEqual(400, emitted[1])
            image = emitted[2]
            self.assertLessEqual(image.width(), 400)
            self.assertLessEqual(image.height(), 400)
            self.assertTrue(os.path.isfile(cache.get_preview_path("photo-1", 400)))


if __name__ == "__main__":
    unittest.main()
