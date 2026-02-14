"""Path utilities for PhotoBrain."""
import os

PHOTOBRAIN_DIR = ".photobrain"
THUMBS_DIR = "thumbs"
LOGS_DIR = "logs"
DB_FILENAME = "session.db"

KEEP_FOLDER = "03_KEEP"
ARCHIVE_DUPES_FOLDER = "04_ARCHIVE_DUPES"
ARCHIVE_LOW_QUALITY_FOLDER = "05_ARCHIVE_LOW_QUALITY"

SKIP_DIRS = frozenset({
    PHOTOBRAIN_DIR,
    KEEP_FOLDER,
    ARCHIVE_DUPES_FOLDER,
    ARCHIVE_LOW_QUALITY_FOLDER,
})

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})


def get_photobrain_dir(source_folder: str) -> str:
    path = os.path.join(source_folder, PHOTOBRAIN_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_db_path(source_folder: str) -> str:
    return os.path.join(get_photobrain_dir(source_folder), DB_FILENAME)


def get_thumb_dir(source_folder: str) -> str:
    path = os.path.join(get_photobrain_dir(source_folder), THUMBS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_log_dir(source_folder: str) -> str:
    path = os.path.join(get_photobrain_dir(source_folder), LOGS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def get_output_dir(source_folder: str, folder_name: str) -> str:
    path = os.path.join(source_folder, folder_name)
    os.makedirs(path, exist_ok=True)
    return path


def has_existing_session(source_folder: str) -> bool:
    db_path = os.path.join(source_folder, PHOTOBRAIN_DIR, DB_FILENAME)
    return os.path.isfile(db_path)


def resolve_collision(dest_path: str) -> str:
    if not os.path.exists(dest_path):
        return dest_path
    stem, ext = os.path.splitext(dest_path)
    counter = 1
    while True:
        candidate = f"{stem}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1
