import os
import tempfile
import unittest
from unittest.mock import patch

from app.core import faces


class ModelResolutionTests(unittest.TestCase):
    """ADOPT-03: models resolve bundled-first and download atomically."""

    def test_bundled_models_exist_and_are_used(self):
        # The repo ships both models; resolution must not touch the network.
        for key in ("detector", "landmarker"):
            with patch.object(
                faces.urllib.request, "urlretrieve",
                side_effect=AssertionError("network hit"),
            ):
                path = faces._get_model_path(key)
            self.assertTrue(os.path.isfile(path))
            self.assertIn(
                os.path.join("assets", "models"), path,
                f"{key} did not resolve to the bundled copy: {path}",
            )
            self.assertGreater(os.path.getsize(path), 10_000)

    def test_partial_download_never_occupies_final_path(self):
        with tempfile.TemporaryDirectory() as cache_root:
            def truncated_download(url, dest):
                with open(dest, "wb") as f:
                    f.write(b"x" * 100)  # far below the 10KB sanity floor

            with patch.object(
                faces, "_bundled_model_path", return_value=None,
            ), patch.dict(
                os.environ, {"LOCALAPPDATA": cache_root},
            ), patch.object(
                faces.urllib.request, "urlretrieve",
                side_effect=truncated_download,
            ):
                with self.assertRaises(OSError):
                    faces._get_model_path("detector")

            model_dir = os.path.join(cache_root, "PhotoBrain", "models")
            leftovers = os.listdir(model_dir) if os.path.isdir(model_dir) else []
            self.assertEqual(
                [], leftovers,
                "a partial or .part file survived a failed download",
            )

    def test_complete_download_lands_atomically_in_localappdata(self):
        with tempfile.TemporaryDirectory() as cache_root:
            def good_download(url, dest):
                with open(dest, "wb") as f:
                    f.write(b"m" * 20_000)

            with patch.object(
                faces, "_bundled_model_path", return_value=None,
            ), patch.dict(
                os.environ, {"LOCALAPPDATA": cache_root},
            ), patch.object(
                faces.urllib.request, "urlretrieve",
                side_effect=good_download,
            ):
                path = faces._get_model_path("detector")

            self.assertTrue(os.path.isfile(path))
            self.assertIn(
                os.path.join("PhotoBrain", "models"), path,
            )
            self.assertFalse(os.path.exists(f"{path}.part"))


if __name__ == "__main__":
    unittest.main()
