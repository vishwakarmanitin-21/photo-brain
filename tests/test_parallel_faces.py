import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from app.core import faces
from app.core.models import Photo, FaceDistance
from app.core.scanner import detect_and_analyze_faces, face_worker_count


def _photo(pid: str, path: str, sha: str) -> Photo:
    return Photo(id=pid, filepath=path, filename=os.path.basename(path),
                 file_size=1, sha256=sha, sharpness=120.0, brightness=128.0)


# A deterministic stand-in for analyze_photo so tests don't need mediapipe.
_FAKE = {
    "f2.jpg": {"face_count": 2, "face_area_ratio": 0.3, "face_distance": "close",
               "subject_isolation": 1.0, "eyes_open": 0.9, "smile": 0.6,
               "expression_naturalness": 0.8, "head_pose_frontal": 0.7},
    "f0.jpg": {"face_count": 0, "face_area_ratio": 0.0, "face_distance": "none",
               "subject_isolation": 0.0, "eyes_open": 0.0, "smile": 0.0,
               "expression_naturalness": 0.0, "head_pose_frontal": 0.0},
}


def _fake_analyze(filepath: str) -> dict:
    return dict(_FAKE[os.path.basename(filepath)])


class ParallelFaceTests(unittest.TestCase):
    def _photos(self, folder):
        photos = []
        for name, sha in [("f2.jpg", "s2"), ("f0.jpg", "s0")]:
            p = os.path.join(folder, name)
            Image.new("RGB", (64, 48), (100, 100, 100)).save(p)
            photos.append(_photo(name, p, sha))
        return photos

    def test_applies_results_and_aggregates_stats(self):
        with tempfile.TemporaryDirectory() as folder:
            photos = self._photos(folder)
            with patch("app.core.scanner.analyze_photo", side_effect=_fake_analyze):
                stats = detect_and_analyze_faces(photos, workers=2)

            by_name = {p.filename: p for p in photos}
            self.assertEqual(2, by_name["f2.jpg"].face_count)
            self.assertEqual(FaceDistance.CLOSE, by_name["f2.jpg"].face_distance)
            self.assertAlmostEqual(0.9, by_name["f2.jpg"].eyes_open_score)
            self.assertEqual(0, by_name["f0.jpg"].face_count)
            # Face photo is rescored above its base (face terms add signal).
            self.assertGreater(by_name["f2.jpg"].quality_score, 0.0)

            # Stats count photos, not faces-per-photo: one face photo, one not.
            self.assertEqual(1, stats["faces_total"])
            self.assertEqual(1, stats["faces_close"])
            self.assertEqual(1, stats["faces_none"])
            self.assertEqual(1, stats["expressions_analyzed"])
            self.assertEqual(0, stats["group_shots"])   # 2 faces < 3

    def test_results_independent_of_worker_count(self):
        with tempfile.TemporaryDirectory() as folder:
            photos_a = self._photos(folder)
            photos_b = [
                Photo(id=p.id, filepath=p.filepath, filename=p.filename,
                      file_size=1, sha256=p.sha256, sharpness=120.0,
                      brightness=128.0)
                for p in photos_a
            ]
            with patch("app.core.scanner.analyze_photo", side_effect=_fake_analyze):
                detect_and_analyze_faces(photos_a, workers=1)
                detect_and_analyze_faces(photos_b, workers=4)
            for a, b in zip(photos_a, photos_b):
                self.assertAlmostEqual(a.quality_score, b.quality_score)
                self.assertEqual(a.face_count, b.face_count)

    def test_cancellation_stops_early(self):
        with tempfile.TemporaryDirectory() as folder:
            photos = self._photos(folder)
            with patch("app.core.scanner.analyze_photo", side_effect=_fake_analyze):
                stats = detect_and_analyze_faces(
                    photos, workers=2, cancel_check=lambda: True
                )
            # Cancelled before applying results to any group.
            applied = sum(1 for p in photos if p.face_count or p.subject_isolation)
            self.assertEqual(0, applied)

    def test_worker_analysis_failure_is_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            photos = self._photos(folder)

            def boom(filepath):
                if os.path.basename(filepath) == "f2.jpg":
                    raise RuntimeError("mediapipe blew up")
                return _fake_analyze(filepath)

            with patch("app.core.scanner.analyze_photo", side_effect=boom):
                stats = detect_and_analyze_faces(photos, workers=2)
            # The failing photo defaults to no-face; the other still works.
            self.assertEqual(0, {p.filename: p for p in photos}["f2.jpg"].face_count)
            self.assertEqual(2, stats["faces_none"])


class ThreadLocalDetectorTests(unittest.TestCase):
    def test_each_thread_gets_its_own_detector(self):
        seen = {}

        class FakeDetector:
            def close(self):
                pass

        import mediapipe as mp
        detector_cls = mp.tasks.vision.FaceDetector  # materialize lazy attr

        faces.cleanup()
        with patch("app.core.faces._get_model_path", return_value="x"), \
             patch.object(detector_cls, "create_from_options",
                          side_effect=lambda *a, **k: FakeDetector()):
            def grab():
                seen[threading.get_ident()] = id(faces._get_detector())

            t1 = threading.Thread(target=grab)
            t2 = threading.Thread(target=grab)
            t1.start(); t2.start(); t1.join(); t2.join()

        self.assertEqual(2, len(seen))            # two threads ran
        self.assertNotEqual(*seen.values())        # distinct instances
        self.assertEqual(2, len(faces._instances))  # both tracked for cleanup
        faces.cleanup()
        self.assertEqual(0, len(faces._instances))  # cleanup released them


if __name__ == "__main__":
    unittest.main()
