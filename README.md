# PhotoBrain Desktop

A local-first Windows desktop application for cleaning and organizing large batches of personal photos. PhotoBrain scans your photo folders, detects duplicates, scores image quality, and helps you decide what to keep — all without uploading anything to the cloud.

## Features

- **Duplicate Detection** — finds exact duplicates (SHA256) and near-duplicates (perceptual hash)
- **Quality Scoring** — ranks photos by sharpness (Laplacian variance) and brightness
- **Smart Suggestions** — automatically suggests which photos to keep and which to archive
- **Visual Review** — browse clusters of similar photos with color-coded thumbnails
- **Keyboard-Driven** — fast review workflow with single-key shortcuts
- **Safe File Operations** — never permanently deletes; moves files to organized archive folders
- **Full Undo** — reverse the last apply operation with one click
- **Session Persistence** — close the app and resume your review session later
- **Performance** — handles 5,000+ photos without freezing the UI (background workers)

## Requirements

- Python 3.10 or higher
- Windows 10/11

## Installation

```bash
# Clone or download the repository
cd photo-brain

# Create a virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Running

```bash
venv\Scripts\python run.py
```

Or with the virtual environment activated:

```bash
python run.py
```

## How It Works

### 1. Select a Folder

Choose a folder containing your photos (JPEG, PNG). PhotoBrain scans recursively and supports nested subdirectories.

### 2. Scan

The scan pipeline runs in the background:

1. **Collect** — finds all `.jpg`, `.jpeg`, `.png` files
2. **Hash** — computes SHA256 for exact duplicate detection
3. **Perceptual Hash** — computes pHash for near-duplicate detection
4. **Score** — measures sharpness and brightness for each photo
5. **Cluster** — groups similar photos using Union-Find on hash similarity
6. **Suggest** — marks the best N photos per cluster as KEEP, rest as DELETE

### 3. Review

Browse clusters of similar photos in a visual grid:

- **Green border** = suggested KEEP
- **Red border** = suggested DELETE
- **Gray border** = undecided

Override any suggestion with keyboard shortcuts or mouse clicks.

### 4. Apply

When satisfied with your decisions, apply the changes. Photos are moved (not deleted) to organized folders:

| Decision | Destination |
|----------|-------------|
| KEEP | `03_KEEP/` |
| DELETE (exact duplicate) | `04_ARCHIVE_DUPES/` |
| DELETE (low quality / near-dup) | `05_ARCHIVE_LOW_QUALITY/` |

A detailed log (CSV + JSON) is written for every apply operation.

### 5. Undo

Changed your mind? Click "Undo Last Apply" to restore all files to their original locations.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `K` | Mark selected photo as KEEP |
| `D` | Mark selected photo as DELETE |
| `R` | Reset selected photo to undecided |
| `J` / `Down` | Next cluster |
| `Up` | Previous cluster |
| `Left` / `Right` | Navigate photos within a cluster |
| `Ctrl+Enter` | Apply changes |
| `Ctrl+Z` | Undo last apply |

## Settings

Accessible from the home screen:

| Setting | Default | Description |
|---------|---------|-------------|
| pHash Threshold | 8 | Hamming distance threshold for near-duplicate matching. Lower = stricter. |
| Keep per Cluster | 2 | Number of best photos to suggest keeping per cluster. |

## Project Structure

```
photo-brain/
  requirements.txt              # PySide6, opencv-python, Pillow, imagehash
  run.py                        # Entry point
  app/
    main.py                     # QApplication bootstrap
    core/
      models.py                 # Data models (Photo, Cluster, SessionState)
      hashing.py                # SHA256 + perceptual hash computation
      clustering.py             # Union-Find clustering algorithm
      scoring.py                # Image quality scoring
      scanner.py                # Scan pipeline orchestrator
      thumbnails.py             # Thumbnail cache management
      session_store.py          # SQLite persistence layer
      file_ops.py               # File move operations + undo
    ui/
      main_window.py            # Main window with screen navigation
      setup_view.py             # Home screen / folder selection
      scan_view.py              # Scan progress screen
      review_view.py            # Photo review screen
      dialogs.py                # Settings, confirmation, and result dialogs
    workers/
      scan_worker.py            # Background scan thread
      thumb_worker.py           # Background thumbnail generation thread
    util/
      paths.py                  # Path utilities and constants
      logging_util.py           # Logging configuration
```

## Quality Score Formula

```
score = 0.75 * log(sharpness + 1) + 0.25 * (brightness / 255)
```

- **Sharpness**: variance of the Laplacian (measures edge contrast / focus)
- **Brightness**: mean pixel luminance (0-255)
- The log compresses the large range of sharpness values into a manageable scale
- Sharpness is weighted 3x more than brightness

## Data Storage

PhotoBrain stores all session data locally in a `.photobrain` folder inside your selected source folder:

```
your-photos/
  .photobrain/
    session.db          # SQLite database (session state, photo metadata, clusters)
    thumbs/             # Cached 200x200 thumbnails
    logs/               # Apply operation logs (CSV + JSON)
  03_KEEP/              # Output: kept photos
  04_ARCHIVE_DUPES/     # Output: exact duplicate archives
  05_ARCHIVE_LOW_QUALITY/  # Output: low quality / near-dup archives
```

## Supported Formats

- JPEG (`.jpg`, `.jpeg`)
- PNG (`.png`)

## Known Limitations

- **pHash clustering is O(n^2)** — works well for ~5,000 photos but may be slow for very large collections (50,000+)
- **Single undo level** — only the most recent apply operation can be undone
- **No HEIC or RAW support** — only JPEG and PNG in the current version
- **Flat output structure** — files moved to output folders do not preserve their original subdirectory hierarchy
- **Assisted mode only** — all suggestions must be reviewed before applying (no auto-apply mode yet)
- **No EXIF metadata analysis** — does not use date, camera model, or GPS data for grouping

## License

Private project. All rights reserved.
