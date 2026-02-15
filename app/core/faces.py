"""Face detection using mediapipe Tasks API — multi-scale short-range model."""
import logging
import os
import tempfile
import urllib.request

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

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


def _bb_iou(bb1, bb2) -> float:
    """Compute Intersection over Union for two bounding boxes."""
    x1 = max(bb1.origin_x, bb2.origin_x)
    y1 = max(bb1.origin_y, bb2.origin_y)
    x2 = min(bb1.origin_x + bb1.width, bb2.origin_x + bb2.width)
    y2 = min(bb1.origin_y + bb1.height, bb2.origin_y + bb2.height)

    if x1 >= x2 or y1 >= y2:
        return 0.0

    intersection = (x2 - x1) * (y2 - y1)
    area1 = bb1.width * bb1.height
    area2 = bb2.width * bb2.height
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


def _merge_detections(existing, new_dets, iou_threshold=0.3):
    """Add new detections that don't overlap with existing ones."""
    merged = list(existing)
    for det in new_dets:
        overlaps = any(
            _bb_iou(det.bounding_box, e.bounding_box) > iou_threshold
            for e in merged
        )
        if not overlaps:
            merged.append(det)
    return merged


def _compute_isolation(face_areas: list[float]) -> float:
    """Compute subject isolation score from face area distribution.

    Returns 1.0 for clean compositions (single face or uniform group).
    Returns < 1.0 when small background faces are present alongside
    larger primary subjects.
    """
    if len(face_areas) <= 1:
        return 1.0

    largest = max(face_areas)
    # Faces >= 25% of the largest face are "primary" (intentional subjects)
    primary_area = sum(a for a in face_areas if a >= largest * 0.25)
    total_area = sum(face_areas)

    return round(primary_area / total_area, 4) if total_area > 0 else 1.0


def _compute_expression_naturalness(blendshapes) -> float:
    """Compute expression naturalness score (0.0-1.0) from 52 blendshapes.

    Penalizes awkward/unflattering expressions:
    - eyeSquint: squinting into sun
    - mouthFrown: sad/angry expression
    - jawOpen: mid-speech, yawning
    - mouthFunnel: "O" mouth (surprised)
    - browDown: furrowed brow (concerned)

    Returns 1.0 for natural, relaxed expressions; lower for awkward ones.
    """
    try:
        # Extract relevant blendshapes (by index)
        eye_squint_left = blendshapes[19].score if len(blendshapes) > 19 else 0.0
        eye_squint_right = blendshapes[20].score if len(blendshapes) > 20 else 0.0
        mouth_frown_left = blendshapes[30].score if len(blendshapes) > 30 else 0.0
        mouth_frown_right = blendshapes[31].score if len(blendshapes) > 31 else 0.0
        jaw_open = blendshapes[25].score if len(blendshapes) > 25 else 0.0
        mouth_funnel = blendshapes[32].score if len(blendshapes) > 32 else 0.0
        brow_down_left = blendshapes[1].score if len(blendshapes) > 1 else 0.0
        brow_down_right = blendshapes[2].score if len(blendshapes) > 2 else 0.0

        # Apply penalty formula
        naturalness = 1.0
        naturalness -= 0.08 * (eye_squint_left + eye_squint_right) / 2.0
        naturalness -= 0.10 * (mouth_frown_left + mouth_frown_right) / 2.0
        naturalness -= 0.05 * jaw_open
        naturalness -= 0.04 * mouth_funnel
        naturalness -= 0.03 * max(brow_down_left, brow_down_right)

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, naturalness))

    except (IndexError, AttributeError) as e:
        log.warning("Failed to compute expression naturalness: %s", e)
        return 0.0


def _compute_head_pose_frontal(matrix) -> float:
    """Compute head pose frontal score (0.0-1.0) from transformation matrix.

    Penalizes extreme angles:
    - yaw: left/right turn (0° ideal, -90/+90 bad)
    - pitch: up/down tilt (0° ideal, -90/+90 bad)
    - roll: head tilt (0° ideal, ±180 bad)

    Returns 1.0 for frontal faces; lower for profile/extreme angles.
    """
    try:
        # Extract 3x3 rotation matrix from 4x4 transformation matrix
        R = np.array(matrix)[:3, :3]
        rotation = Rotation.from_matrix(R)
        yaw, pitch, roll = rotation.as_euler('yxz', degrees=True)

        # Apply penalty formula
        frontal = 1.0
        frontal -= 0.015 * abs(yaw)
        frontal -= 0.010 * abs(pitch)
        frontal -= 0.012 * abs(roll)

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, frontal))

    except (ValueError, IndexError) as e:
        log.warning("Failed to compute head pose frontal: %s", e)
        return 0.0


def detect_faces(filepath: str) -> tuple[int, float, str, float]:
    """Detect faces using multi-scale short-range detection.

    Runs detection at all scales, merges overlapping detections, and
    computes a subject isolation score based on face size distribution.

    Returns:
        (face_count, face_area_ratio, face_distance, subject_isolation)
        face_distance: "close" if original-scale model found faces,
                       "far" if only a downscaled pass found faces,
                       "none" if no faces found at any scale.
        subject_isolation: 1.0 for clean compositions, < 1.0 when
                          small background faces dilute the primary subject.
                          0.0 when no faces found.
    """
    try:
        img = cv2.imread(filepath)
        if img is None:
            log.warning("Cannot read image for face detection: %s", filepath)
            return 0, 0.0, "none", 0.0

        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return 0, 0.0, "none", 0.0

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        image_area = float(h * w)
        detector = _get_detector()

        # Detect at original scale (close-up faces)
        detections = _detect_at_scale(detector, rgb, 1.0)
        face_distance = "close" if detections else "none"

        if detections:
            # Also check downscaled versions for background bystanders
            for scale in _DOWNSCALE_FACTORS:
                if w * scale < 128 or h * scale < 128:
                    continue
                extra = _detect_at_scale(detector, rgb, scale)
                if extra:
                    detections = _merge_detections(detections, extra)
        else:
            # No close-up faces — try downscaled for distant subjects
            for scale in _DOWNSCALE_FACTORS:
                if w * scale < 128 or h * scale < 128:
                    continue
                detections = _detect_at_scale(detector, rgb, scale)
                if detections:
                    face_distance = "far"
                    # Check even smaller scales for more background faces
                    remaining = [s for s in _DOWNSCALE_FACTORS if s < scale]
                    for s2 in remaining:
                        if w * s2 < 128 or h * s2 < 128:
                            continue
                        extra = _detect_at_scale(detector, rgb, s2)
                        if extra:
                            detections = _merge_detections(detections, extra)
                    break

        if not detections:
            return 0, 0.0, "none", 0.0

        face_count = len(detections)
        face_areas = [
            d.bounding_box.width * d.bounding_box.height
            for d in detections
        ]
        total_face_area = sum(face_areas)
        isolation = _compute_isolation(face_areas)

        return (
            face_count,
            round(total_face_area / image_area, 4),
            face_distance,
            isolation,
        )

    except Exception as e:
        log.warning("Face detection failed for %s: %s", filepath, e)
        return 0, 0.0, "none", 0.0


def _get_landmarker():
    """Get or create the FaceLandmarker for expression analysis."""
    global _landmarker
    if _landmarker is None:
        import mediapipe as mp
        model_path = _get_model_path("landmarker")
        opts = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
            num_faces=5,
        )
        _landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(opts)
    return _landmarker


def _extract_blendshape_scores(face_blendshapes, facial_transformation_matrixes=None) -> tuple[float, float, float, float]:
    """Extract average expression scores and head pose from blendshapes + matrices.

    Returns:
        (eyes_open, smile, expression_naturalness, head_pose_frontal)
    """
    total_eyes_open = 0.0
    total_smile = 0.0
    total_naturalness = 0.0
    total_frontal = 0.0
    num_faces = len(face_blendshapes)

    for i, face_shapes in enumerate(face_blendshapes):
        # Eyes open = 1.0 - blink (blink 0=open, 1=closed)
        blink_left = face_shapes[9].score if len(face_shapes) > 9 else 0.0
        blink_right = face_shapes[10].score if len(face_shapes) > 10 else 0.0
        eyes_open = 1.0 - (blink_left + blink_right) / 2.0
        total_eyes_open += max(0.0, eyes_open)

        # Smile = average of left and right
        smile_left = face_shapes[44].score if len(face_shapes) > 44 else 0.0
        smile_right = face_shapes[45].score if len(face_shapes) > 45 else 0.0
        total_smile += (smile_left + smile_right) / 2.0

        # Expression naturalness
        total_naturalness += _compute_expression_naturalness(face_shapes)

        # Head pose frontal (if matrices available)
        if facial_transformation_matrixes and i < len(facial_transformation_matrixes):
            total_frontal += _compute_head_pose_frontal(facial_transformation_matrixes[i])

    return (
        round(total_eyes_open / num_faces, 4),
        round(total_smile / num_faces, 4),
        round(total_naturalness / num_faces, 4),
        round(total_frontal / num_faces, 4) if facial_transformation_matrixes else 0.0,
    )


def _analyze_cropped_faces(rgb, landmarker) -> tuple[float, float, float, float]:
    """Crop each detected face, upscale, and run landmarker on each crop."""
    import mediapipe as mp

    h, w = rgb.shape[:2]
    detector = _get_detector()

    # Detect faces using multi-scale approach with merging
    detections = _detect_at_scale(detector, rgb, 1.0)
    for scale in _DOWNSCALE_FACTORS:
        if w * scale < 128 or h * scale < 128:
            continue
        extra = _detect_at_scale(detector, rgb, scale)
        if extra:
            detections = _merge_detections(detections, extra) if detections else extra

    if not detections:
        return 0.0, 0.0, 0.0, 0.0

    all_eyes = []
    all_smile = []
    all_naturalness = []
    all_frontal = []
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
            eyes, smile, natural, frontal = _extract_blendshape_scores(
                crop_result.face_blendshapes,
                crop_result.facial_transformation_matrixes
            )
            all_eyes.append(eyes)
            all_smile.append(smile)
            all_naturalness.append(natural)
            all_frontal.append(frontal)

    if not all_eyes:
        return 0.0, 0.0, 0.0, 0.0

    return (
        round(sum(all_eyes) / len(all_eyes), 4),
        round(sum(all_smile) / len(all_smile), 4),
        round(sum(all_naturalness) / len(all_naturalness), 4),
        round(sum(all_frontal) / len(all_frontal), 4),
    )


def analyze_expressions(filepath: str) -> tuple[float, float, float, float]:
    """Analyze face expressions and head pose.

    Tries the full image first. If the landmarker can't find faces
    (common with distant/small faces), crops and upscales each detected
    face region and retries.

    Returns:
        (eyes_open, smile, expression_naturalness, head_pose_frontal)
        All scores in range [0.0, 1.0], averaged across detected faces.
        Returns (0.0, 0.0, 0.0, 0.0) on error or if no faces found.
    """
    try:
        import mediapipe as mp

        img = cv2.imread(filepath)
        if img is None:
            return 0.0, 0.0, 0.0, 0.0

        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        landmarker = _get_landmarker()
        result = landmarker.detect(mp_image)

        if result.face_blendshapes:
            return _extract_blendshape_scores(
                result.face_blendshapes,
                result.facial_transformation_matrixes
            )

        # Full-image landmarker didn't find faces — crop+upscale fallback
        return _analyze_cropped_faces(rgb, landmarker)

    except Exception as e:
        log.warning("Expression analysis failed for %s: %s", filepath, e)
        return 0.0, 0.0, 0.0, 0.0


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
