"""Face detection using mediapipe Tasks API."""
import logging
import os
import tempfile
import urllib.request
from typing import Optional

import cv2

log = logging.getLogger("photobrain.faces")

# Lazy-loaded detector singleton
_detector = None

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_detector/blaze_face_short_range/float16/latest/"
    "blaze_face_short_range.tflite"
)
_MODEL_FILENAME = "blaze_face_short_range.tflite"


def _get_model_path() -> str:
    """Download the face detection model if not cached, return local path."""
    cache_dir = os.path.join(tempfile.gettempdir(), "photobrain_models")
    os.makedirs(cache_dir, exist_ok=True)
    model_path = os.path.join(cache_dir, _MODEL_FILENAME)
    if not os.path.exists(model_path):
        log.info("Downloading face detection model...")
        urllib.request.urlretrieve(_MODEL_URL, model_path)
        log.info("Model saved to %s", model_path)
    return model_path


def _get_detector():
    global _detector
    if _detector is None:
        import mediapipe as mp
        model_path = _get_model_path()
        opts = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            min_detection_confidence=0.3,
        )
        _detector = mp.tasks.vision.FaceDetector.create_from_options(opts)
    return _detector


def detect_faces(filepath: str) -> tuple[int, float]:
    """Detect faces in an image.

    Returns:
        (face_count, face_area_ratio)
        face_area_ratio = sum of face bounding box areas / total image area
    """
    try:
        import mediapipe as mp

        img = cv2.imread(filepath)
        if img is None:
            log.warning("Cannot read image for face detection: %s", filepath)
            return 0, 0.0

        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return 0, 0.0

        # mediapipe expects RGB
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        detector = _get_detector()
        results = detector.detect(mp_image)

        if not results.detections:
            return 0, 0.0

        face_count = len(results.detections)
        total_face_area = 0.0
        image_area = float(h * w)

        for detection in results.detections:
            bbox = detection.bounding_box
            # bounding_box has origin_x, origin_y, width, height in pixels
            total_face_area += bbox.width * bbox.height

        face_area_ratio = total_face_area / image_area
        return face_count, round(face_area_ratio, 4)

    except Exception as e:
        log.warning("Face detection failed for %s: %s", filepath, e)
        return 0, 0.0


def cleanup():
    """Release the detector resources."""
    global _detector
    if _detector is not None:
        _detector.close()
        _detector = None
