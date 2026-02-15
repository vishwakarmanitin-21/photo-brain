"""Face detection using mediapipe Tasks API — multi-scale short-range model."""
import logging
import os
import tempfile
import urllib.request

import cv2
import numpy as np

log = logging.getLogger("photobrain.faces")

# Lazy-loaded singletons
_detector = None
_landmarker = None

_MODELS = {
    "detector": {
        "url": (
            "https://storage.googleapis.com/mediapipe-models/"
            "face_detector/blaze_face_short_range/float16/latest/"
            "blaze_face_short_range.tflite"
        ),
        "filename": "blaze_face_short_range.tflite",
    },
    "landmarker": {
        "url": (
            "https://storage.googleapis.com/mediapipe-models/"
            "face_landmarker/face_landmarker/float16/1/"
            "face_landmarker.task"
        ),
        "filename": "face_landmarker.task",
    },
}

# Downscale factors for multi-scale detection.
# Original image catches close-up faces; downscaled versions catch distant ones.
# Each scale halves the long edge: 50%, 25% of original.
_DOWNSCALE_FACTORS = [0.5, 0.25]


def _get_model_path(model_key: str) -> str:
    """Download the model if not cached, return local path."""
    info = _MODELS[model_key]
    cache_dir = os.path.join(tempfile.gettempdir(), "photobrain_models")
    os.makedirs(cache_dir, exist_ok=True)
    model_path = os.path.join(cache_dir, info["filename"])
    if not os.path.exists(model_path):
        log.info("Downloading %s model...", model_key)
        urllib.request.urlretrieve(info["url"], model_path)
        log.info("Model saved to %s", model_path)
    return model_path


def _get_detector():
    """Get or create the face detector singleton."""
    global _detector
    if _detector is None:
        import mediapipe as mp
        model_path = _get_model_path("detector")
        opts = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            min_detection_confidence=0.3,
        )
        _detector = mp.tasks.vision.FaceDetector.create_from_options(opts)
    return _detector


def _detect_at_scale(detector, rgb, scale: float):
    """Run face detection on a scaled version of the image.

    Returns list of detections with bounding boxes mapped back to original coords.
    """
    import mediapipe as mp

    if scale >= 1.0:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)
        return result.detections or []

    h, w = rgb.shape[:2]
    new_w = max(int(w * scale), 1)
    new_h = max(int(h * scale), 1)
    scaled = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
    scaled = np.ascontiguousarray(scaled)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=scaled)
    result = detector.detect(mp_image)

    if not result.detections:
        return []

    # Map bounding boxes back to original image coordinates
    inv_scale = 1.0 / scale
    mapped = []
    for det in result.detections:
        bb = det.bounding_box
        bb.origin_x = int(bb.origin_x * inv_scale)
        bb.origin_y = int(bb.origin_y * inv_scale)
        bb.width = int(bb.width * inv_scale)
        bb.height = int(bb.height * inv_scale)
        mapped.append(det)

    return mapped


def detect_faces(filepath: str) -> tuple[int, float, str]:
    """Detect faces using multi-scale short-range detection.

    Tries detection on the original image first. If nothing is found,
    progressively downscales the image so that distant/small faces become
    large enough for the short-range model to detect.

    Returns:
        (face_count, face_area_ratio, face_distance)
        face_distance: "close" if original-scale model found faces,
                       "far" if only a downscaled pass found faces,
                       "none" if no faces found at any scale.
    """
    try:
        img = cv2.imread(filepath)
        if img is None:
            log.warning("Cannot read image for face detection: %s", filepath)
            return 0, 0.0, "none"

        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return 0, 0.0, "none"

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        image_area = float(h * w)
        detector = _get_detector()

        # Try original scale first (close-up faces)
        detections = _detect_at_scale(detector, rgb, 1.0)
        if detections:
            face_count = len(detections)
            total_face_area = sum(
                d.bounding_box.width * d.bounding_box.height
                for d in detections
            )
            return face_count, round(total_face_area / image_area, 4), "close"

        # Try downscaled versions for distant faces
        for scale in _DOWNSCALE_FACTORS:
            # Skip if image is already small
            if w * scale < 128 or h * scale < 128:
                continue

            detections = _detect_at_scale(detector, rgb, scale)
            if detections:
                face_count = len(detections)
                total_face_area = sum(
                    d.bounding_box.width * d.bounding_box.height
                    for d in detections
                )
                return face_count, round(total_face_area / image_area, 4), "far"

        return 0, 0.0, "none"

    except Exception as e:
        log.warning("Face detection failed for %s: %s", filepath, e)
        return 0, 0.0, "none"


def _get_landmarker():
    """Get or create the FaceLandmarker for expression analysis."""
    global _landmarker
    if _landmarker is None:
        import mediapipe as mp
        model_path = _get_model_path("landmarker")
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            output_face_blendshapes=True,
            num_faces=5,
        )
        _landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def _extract_blendshape_scores(face_blendshapes) -> tuple[float, float]:
    """Extract average eyes-open and smile scores from blendshape list."""
    total_eyes_open = 0.0
    total_smile = 0.0
    num_faces = len(face_blendshapes)

    for face_shapes in face_blendshapes:
        shape_map = {s.category_name: s.score for s in face_shapes}

        # Eyes open = 1.0 - blink (blink 0=open, 1=closed)
        blink_left = shape_map.get("eyeBlinkLeft", 0.0)
        blink_right = shape_map.get("eyeBlinkRight", 0.0)
        eyes_open = 1.0 - (blink_left + blink_right) / 2.0
        total_eyes_open += max(0.0, eyes_open)

        # Smile = average of left and right
        smile_left = shape_map.get("mouthSmileLeft", 0.0)
        smile_right = shape_map.get("mouthSmileRight", 0.0)
        total_smile += (smile_left + smile_right) / 2.0

    return (
        round(total_eyes_open / num_faces, 4),
        round(total_smile / num_faces, 4),
    )


def _analyze_cropped_faces(rgb, landmarker) -> tuple[float, float]:
    """Crop each detected face, upscale, and run landmarker on each crop."""
    import mediapipe as mp

    h, w = rgb.shape[:2]
    detector = _get_detector()

    # Detect faces using multi-scale approach
    detections = _detect_at_scale(detector, rgb, 1.0)
    if not detections:
        for scale in _DOWNSCALE_FACTORS:
            if w * scale < 128 or h * scale < 128:
                continue
            detections = _detect_at_scale(detector, rgb, scale)
            if detections:
                break

    if not detections:
        return 0.0, 0.0

    all_eyes = []
    all_smile = []
    target_size = 512

    for det in detections:
        bb = det.bounding_box
        # Add 50% padding around the face for context
        pad_w = int(bb.width * 0.5)
        pad_h = int(bb.height * 0.5)
        x1 = max(0, bb.origin_x - pad_w)
        y1 = max(0, bb.origin_y - pad_h)
        x2 = min(w, bb.origin_x + bb.width + pad_w)
        y2 = min(h, bb.origin_y + bb.height + pad_h)

        crop = rgb[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        # Upscale small crops so the landmarker has enough detail
        crop_h, crop_w = crop.shape[:2]
        scale = target_size / max(crop_h, crop_w)
        if scale > 1.0:
            new_w = int(crop_w * scale)
            new_h = int(crop_h * scale)
            crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        # Ensure contiguous array for mediapipe
        crop = np.ascontiguousarray(crop)
        crop_mp = mp.Image(image_format=mp.ImageFormat.SRGB, data=crop)
        crop_result = landmarker.detect(crop_mp)

        if crop_result.face_blendshapes:
            eyes, smile = _extract_blendshape_scores(crop_result.face_blendshapes)
            all_eyes.append(eyes)
            all_smile.append(smile)

    if not all_eyes:
        return 0.0, 0.0

    return (
        round(sum(all_eyes) / len(all_eyes), 4),
        round(sum(all_smile) / len(all_smile), 4),
    )


def analyze_expressions(filepath: str) -> tuple[float, float]:
    """Analyze face expressions for eyes-open and smile scores.

    Tries the full image first. If the landmarker can't find faces
    (common with distant/small faces), crops and upscales each detected
    face region and retries.

    Returns:
        (eyes_open_score, smile_score) each in range [0.0, 1.0].
        Averaged across all detected faces.
        Returns (0.0, 0.0) on error or if no blendshapes found.
    """
    try:
        import mediapipe as mp

        img = cv2.imread(filepath)
        if img is None:
            return 0.0, 0.0

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        landmarker = _get_landmarker()
        result = landmarker.detect(mp_image)

        if result.face_blendshapes:
            return _extract_blendshape_scores(result.face_blendshapes)

        # Full-image landmarker didn't find faces — crop+upscale fallback
        return _analyze_cropped_faces(rgb, landmarker)

    except Exception as e:
        log.warning("Expression analysis failed for %s: %s", filepath, e)
        return 0.0, 0.0


def cleanup():
    """Release all model resources."""
    global _detector, _landmarker
    for resource_name, resource in [("detector", _detector), ("landmarker", _landmarker)]:
        if resource is not None:
            try:
                resource.close()
            except Exception:
                log.debug("Error closing %s (ignored)", resource_name)
    _detector = None
    _landmarker = None
