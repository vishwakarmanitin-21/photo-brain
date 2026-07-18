"""Path utilities for PhotoBrain."""
import errno
import os
import shutil

PHOTOBRAIN_DIR = ".photobrain"
THUMBS_DIR = "thumbs"
PREVIEWS_DIR = "previews"
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

# .heic/.heif decode via pillow-heif; .webp is native to Pillow (FEAT-02).
SUPPORTED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif",
})


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


def get_preview_dir(source_folder: str) -> str:
    path = os.path.join(get_photobrain_dir(source_folder), PREVIEWS_DIR)
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


def extended_path(path: str) -> str:
    r"""Return a Windows extended-length path (\\?\ prefix).

    Lifts the ~260-character MAX_PATH limit for os-level calls, which
    otherwise fail on deep photo trees even though the files are fine.
    Returns the path unchanged on other platforms or when already prefixed.
    Use only at OS-call boundaries — stored and displayed paths stay plain.
    """
    if os.name != "nt":
        return path
    p = os.path.normpath(os.path.abspath(path))
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC" + p[1:]
    return "\\\\?\\" + p


def move_no_overwrite(src: str, dest_path: str) -> str:
    """Move src to dest_path without ever overwriting an existing file.

    Windows os.rename refuses to replace an existing destination, which
    closes the plan-then-move race where two same-named photos could
    silently clobber each other (shutil.move's copy fallback overwrites).
    Returns the destination actually used — suffixed _1, _2, ... when the
    planned name was taken after planning. Cross-drive moves fall back to
    exclusive-create + copy, preserving the no-overwrite guarantee.
    """
    stem, ext = os.path.splitext(dest_path)
    counter = 0
    candidate = dest_path
    while True:
        try:
            os.rename(extended_path(src), extended_path(candidate))
            return candidate
        except FileExistsError:
            pass  # name taken since planning — try the next suffix
        except OSError as error:
            cross_device = (
                error.errno == errno.EXDEV
                or getattr(error, "winerror", None) == 17
            )
            if not cross_device:
                raise
            # Different drive or network share: claim the name exclusively,
            # then copy onto our own placeholder and remove the source.
            try:
                with open(extended_path(candidate), "xb"):
                    pass
            except FileExistsError:
                counter += 1
                candidate = f"{stem}_{counter}{ext}"
                continue
            shutil.copy2(extended_path(src), extended_path(candidate))
            os.remove(extended_path(src))
            return candidate
        counter += 1
        candidate = f"{stem}_{counter}{ext}"


def copy_no_overwrite(src: str, dest_path: str) -> str:
    """Copy src to dest_path without ever overwriting an existing file.

    Unlike move_no_overwrite this leaves the source in place — used to export
    a copy of the keepers to a folder the user picks, so their originals are
    untouched. Returns the destination actually used (suffixed _1, _2, ... on
    a name clash)."""
    candidate = resolve_collision(dest_path)
    shutil.copy2(extended_path(src), extended_path(candidate))
    return candidate
