# PhotoBrain Desktop

A local-first Windows desktop application for cleaning and organizing large batches of personal photos. PhotoBrain scans your photo folders, detects duplicates, scores image quality, detects faces, groups photos into events, and helps you decide what to keep — all without uploading anything to the cloud.

## Features

- **Duplicate Detection** — finds exact duplicates (SHA256) and near-duplicates (perceptual hash)
- **Quality Scoring** — ranks photos by sharpness, brightness, face presence, expressions, composition, and head pose
- **Face Detection** — multi-scale face detection catches both close-up and distant faces
- **Expression Analysis** — scores eyes-open, smile, expression naturalness, and head pose via Face Landmarker blendshapes and transformation matrix
- **Subject Isolation** — penalizes photos with random background bystanders (group photos are not penalized)
- **Event Grouping** — groups photos into time-based events using EXIF date/time
- **Smart Suggestions** — automatically suggests which photos to keep and which to archive
- **Visual Review** — browse clusters of similar photos with color-coded thumbnails
- **Keyboard-Driven** — fast review workflow with single-key shortcuts (K/A/D/R)
- **Three Verdicts** — KEEP (organized folder), ARCHIVE (safe move), DELETE (Recycle Bin)
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

## Building a Standalone Executable

Create a distributable package that runs without Python installed:

```bash
# Install PyInstaller (one-time)
venv\Scripts\pip install pyinstaller

# Build the application
venv\Scripts\python scripts\build.py
```

This produces:
- `dist/PhotoBrain/` — folder with `PhotoBrain.exe` and all dependencies
- `dist/PhotoBrain.zip` — zip archive (~120 MB) ready to share

**To distribute:** Send the zip file to users. They extract it and run `PhotoBrain/PhotoBrain.exe` — no Python installation required. The mediapipe face detection models are downloaded automatically on first use (~5 MB).

## How It Works

### 1. Select a Folder

Choose a folder containing your photos (JPEG, PNG). PhotoBrain scans recursively and supports nested subdirectories.

### 2. Scan

The scan pipeline runs in the background with live progress:

1. **Collect** — finds all `.jpg`, `.jpeg`, `.png` files
2. **Hash** — computes SHA256 for exact duplicate detection
3. **Perceptual Hash** — computes pHash for near-duplicate detection
4. **Score** — measures sharpness and brightness for each photo
5. **Face Detection** — multi-scale detection (original + downscaled) for close-up and distant faces
6. **Expression Analysis** — eyes-open and smile scoring for photos with faces
7. **EXIF Events** — groups photos by time proximity using EXIF timestamps
8. **Cluster** — groups similar photos using Union-Find on hash similarity
9. **Suggest** — marks the best N photos per cluster as KEEP, rest as ARCHIVE

The scan summary shows detailed statistics including face distance breakdown (close-up, distant, no faces, group shots) and expression analysis count.

### 3. Review

Browse clusters of similar photos in a visual grid:

- **Green border** = KEEP
- **Orange border** = ARCHIVE
- **Red border** = DELETE
- **Gray border** = undecided (REVIEW)

Hover any thumbnail to see detailed metrics: quality score, sharpness, brightness, face count, eyes open %, smile %, isolation %, expression naturalness %, and head pose frontal %. Filter by face distance, events, or group shots.

### 4. Apply

When satisfied with your decisions, apply the changes:

| Decision | Destination |
|----------|-------------|
| KEEP | `03_KEEP/` |
| ARCHIVE (exact duplicate) | `04_ARCHIVE_DUPES/` |
| ARCHIVE (low quality / near-dup) | `05_ARCHIVE_LOW_QUALITY/` |
| DELETE | Recycle Bin (via send2trash) |

A detailed log (CSV + JSON) is written for every apply operation.

### 5. Undo

Changed your mind? Click "Undo Last Apply" to restore all moved files to their original locations. (Recycle Bin deletes cannot be undone from the app.)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `K` | Mark selected photo as KEEP |
| `A` | Mark selected photo as ARCHIVE |
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
| Event Gap (hours) | 4.0 | Time gap between EXIF timestamps to split into separate events. |
| Face Detection | On | Enable/disable face detection and expression analysis. |

## Quality Score Formula

```
score = 0.45 * log(sharpness + 1)
      + 0.13 * (brightness / 255)
      + 0.10 * min(face_count, 3)
      + 0.12 * eyes_open_score
      + 0.09 * smile_score
      + 0.05 * subject_isolation
      + 0.04 * expression_naturalness
      + 0.02 * head_pose_frontal
```

| Component | Weight | Description |
|-----------|--------|-------------|
| **Sharpness** | 45% | Variance of the Laplacian (measures edge contrast / focus). Log-compressed. |
| **Brightness** | 13% | Mean pixel luminance normalized to [0, 1]. |
| **Face count** | 10% | Number of detected faces, capped at 3. |
| **Eyes open** | 12% | Average eyes-open score across faces (0 = closed, 1 = open). |
| **Smile** | 9% | Average smile score across faces (0 = neutral, 1 = smiling). |
| **Subject isolation** | 5% | Composition cleanliness — 1.0 for clean portraits and uniform groups, < 1.0 when small background bystanders are detected. |
| **Expression naturalness** | 4% | Penalizes awkward/unflattering expressions (squinting, frowning, mid-speech, jaw tension). 1.0 = natural/relaxed, lower = awkward. |
| **Head pose frontal** | 2% | Rewards frontal, flattering head angles. 1.0 = frontal (yaw≈0, pitch≈0, roll≈0), lower = extreme angles (profile, looking up/down). |

Photos without faces compete on sharpness and brightness only (face/expression/isolation/naturalness/pose terms are 0).

## Project Structure

```
photo-brain/
  requirements.txt              # PySide6, opencv-python, Pillow, imagehash, mediapipe, send2trash, scipy
  run.py                        # Entry point
  assets/
    photobrain.ico              # Application icon
    photobrain_256.png          # 256x256 icon image
  app/
    main.py                     # QApplication bootstrap
    core/
      models.py                 # Data models (Photo, Cluster, Event, SessionState + enums)
      hashing.py                # SHA256 + perceptual hash computation
      clustering.py             # Union-Find clustering algorithm
      scoring.py                # Image quality scoring (sharpness + brightness + faces + isolation)
      scanner.py                # Scan pipeline orchestrator
      faces.py                  # Multi-scale face detection + expression analysis (mediapipe)
      events.py                 # EXIF date/time extraction + event grouping
      thumbnails.py             # Thumbnail cache management
      session_store.py          # SQLite persistence layer (schema v7)
      file_ops.py               # File move operations + undo
    ui/
      main_window.py            # Main window with screen navigation
      setup_view.py             # Home screen / folder selection
      scan_view.py              # Scan progress screen with live stats
      review_view.py            # Photo review screen with filters
      dialogs.py                # Settings, confirmation, and result dialogs
    workers/
      scan_worker.py            # Background scan thread
      thumb_worker.py           # Background thumbnail generation thread
    util/
      paths.py                  # Path utilities and constants
      logging_util.py           # Logging configuration
```

## Data Storage

PhotoBrain stores all session data locally in a `.photobrain` folder inside your selected source folder:

```
your-photos/
  .photobrain/
    session.db          # SQLite database (session state, photo metadata, clusters, events)
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
- **Expression analysis on close-up faces only** — distant faces are detected but too small for reliable blendshape extraction
- **Windows only** — built and tested for Windows 10/11

## License

Private project. All rights reserved.
