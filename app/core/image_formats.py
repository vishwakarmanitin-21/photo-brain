"""Register extra image formats with Pillow (FEAT-02).

Importing this module registers the HEIF/HEIC opener so that iPhone photos
decode through the normal Pillow paths (hashing, thumbnails, scoring,
integrity checks). WEBP is already handled natively by Pillow, so it needs
no registration — only the scanner's extension list. Registration is
idempotent and safe to call from any entry point.
"""
import logging

log = logging.getLogger("photobrain.image_formats")

_registered = False


def register_image_formats() -> None:
    global _registered
    if _registered:
        return
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
        log.info("Registered HEIF/HEIC opener")
    except Exception as error:  # pragma: no cover - optional dependency
        # HEIC simply stays unsupported if the wheel is unavailable; the app
        # continues to work for JPEG/PNG/WEBP.
        log.warning("HEIF/HEIC support unavailable: %s", error)
    _registered = True


# Register on first import so any decode path picks it up.
register_image_formats()
