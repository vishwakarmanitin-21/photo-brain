"""Persistent application preferences (UX-13).

A thin, typed wrapper over QSettings so window geometry, scan defaults, and
review preferences survive across launches instead of resetting every time.
QSettings resolves to the registry on Windows using the org/app names set in
app.main, so no file path handling is needed here.
"""
from PySide6.QtCore import QSettings


def _to_bool(value, default: bool) -> bool:
    # QSettings may hand back a real bool or the strings "true"/"false".
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AppSettings:
    # Keys
    K_GEOMETRY = "window/geometry"
    K_THRESHOLD = "scan/threshold"
    K_KEEP = "scan/keep_per_cluster"
    K_EVENT_GAP = "scan/event_gap_hours"
    K_FACES = "scan/face_detection"
    K_ZOOM = "review/zoom"
    K_HIDE_SINGLETONS = "review/hide_singletons"

    def __init__(self, settings: QSettings | None = None):
        self._s = settings or QSettings()

    # ── Window geometry ──
    def save_geometry(self, data) -> None:
        self._s.setValue(self.K_GEOMETRY, data)

    def geometry(self):
        return self._s.value(self.K_GEOMETRY)

    # ── Scan defaults ──
    def threshold(self, default: int) -> int:
        return _to_int(self._s.value(self.K_THRESHOLD), default)

    def keep_per_cluster(self, default: int) -> int:
        return _to_int(self._s.value(self.K_KEEP), default)

    def event_gap_hours(self, default: float) -> float:
        return _to_float(self._s.value(self.K_EVENT_GAP), default)

    def face_detection(self, default: bool) -> bool:
        return _to_bool(self._s.value(self.K_FACES), default)

    def save_scan_defaults(self, threshold: int, keep: int,
                           event_gap: float, faces: bool) -> None:
        self._s.setValue(self.K_THRESHOLD, int(threshold))
        self._s.setValue(self.K_KEEP, int(keep))
        self._s.setValue(self.K_EVENT_GAP, float(event_gap))
        self._s.setValue(self.K_FACES, bool(faces))

    # ── Review preferences ──
    def zoom(self, default: int) -> int:
        return _to_int(self._s.value(self.K_ZOOM), default)

    def save_zoom(self, value: int) -> None:
        self._s.setValue(self.K_ZOOM, int(value))

    def hide_singletons(self, default: bool) -> bool:
        return _to_bool(self._s.value(self.K_HIDE_SINGLETONS), default)

    def save_hide_singletons(self, value: bool) -> None:
        self._s.setValue(self.K_HIDE_SINGLETONS, bool(value))
