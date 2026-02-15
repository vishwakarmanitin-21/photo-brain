"""Data models for PhotoBrain."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Verdict(Enum):
    KEEP = "KEEP"
    ARCHIVE = "ARCHIVE"
    DELETE = "DELETE"
    REVIEW = "REVIEW"


class DupType(Enum):
    NONE = "none"
    EXACT = "exact"
    NEAR = "near"


class FaceDistance(Enum):
    NONE = "none"       # no faces detected
    CLOSE = "close"     # faces detected by short-range model (within ~2m)
    FAR = "far"         # faces detected only by full-range model (distant)


class SessionStatus(Enum):
    NEW = "NEW"
    SCANNING = "SCANNING"
    SCANNED = "SCANNED"
    REVIEWING = "REVIEWING"
    APPLIED = "APPLIED"


@dataclass
class Photo:
    id: str
    filepath: str
    filename: str
    file_size: int
    sha256: Optional[str] = None
    phash: Optional[str] = None
    sharpness: float = 0.0
    brightness: float = 0.0
    quality_score: float = 0.0
    cluster_id: Optional[str] = None
    verdict: Verdict = Verdict.REVIEW
    dup_type: DupType = DupType.NONE
    user_override: bool = False
    thumb_path: Optional[str] = None
    scan_order: int = 0
    face_count: int = 0
    face_area_ratio: float = 0.0
    face_distance: FaceDistance = FaceDistance.NONE
    eyes_open_score: float = 0.0
    smile_score: float = 0.0
    subject_isolation: float = 0.0
    expression_naturalness: float = 0.0
    head_pose_frontal: float = 0.0
    exif_datetime: Optional[str] = None
    event_id: Optional[str] = None


@dataclass
class Cluster:
    id: str
    label: str
    representative_photo_id: Optional[str] = None
    member_count: int = 0
    keep_count: int = 0
    delete_count: int = 0
    is_exact_dup_group: bool = False
    reviewed: bool = False


@dataclass
class SessionState:
    id: str
    source_folder: str
    status: SessionStatus = SessionStatus.NEW
    created_at: str = ""
    updated_at: str = ""
    total_files: int = 0
    scanned_files: int = 0
    phash_threshold: int = 8
    keep_per_cluster: int = 2
    last_apply_log: Optional[str] = None
    event_gap_hours: float = 4.0
    face_detection_enabled: bool = True


@dataclass
class Event:
    id: str
    label: str
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    photo_count: int = 0


@dataclass
class ApplyLogEntry:
    photo_id: str
    original_path: str
    destination_path: str
    verdict: str
    dup_type: str
    destination_folder: str
    cluster_id: str
    timestamp: str
