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

- Python 3.12 – 3.13 (the pinned numpy/scipy require 3.12+; developed and
  tested on 3.13). End users of the packaged .exe need no Python at all.
- Windows 10/11 (64-bit)

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
# Install build tools (one-time)
venv\Scripts\pip install -r requirements-dev.txt

# Build the application
venv\Scripts\python scripts\build.py
```

This produces:
- `dist/PhotoBrain/` — folder with `PhotoBrain.exe` and all dependencies
- `dist/PhotoBrain.zip` — zip archive (~150 MB) ready to share

**To distribute:** Send the zip file to users. They extract it and run
`PhotoBrain/PhotoBrain.exe` — no Python installation required. The face
detection models are bundled, so everything works fully offline. (The
download size is dominated by the on-device face-analysis engine — that's
what keeps your photos on your PC.)

### First run on a fresh PC

- **Windows SmartScreen** may show "Windows protected your PC" because the
  exe is not yet code-signed. Click **More info → Run anyway**. (Code
  signing is on the roadmap.)
- If the app fails to start with a DLL error, install the
  [Microsoft Visual C++ 2015–2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).

## How It Works

### 1. Select a Folder

Choose a folder containing your photos (JPEG, PNG, WEBP, HEIC/HEIF). PhotoBrain scans recursively and supports nested subdirectories.

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
9. **Suggest** — marks the best N photos per cluster as KEEP, rest as ARCHIVE. Genuinely low-quality photos (blurry, or too dark/blown-out to use) — including a whole similar group where *every* frame is junk — are left flagged as **undecided (REVIEW)** rather than auto-kept or auto-moved, so you make the final call

The scan summary shows detailed statistics including face distance breakdown (close-up, distant, no faces, group shots) and expression analysis count.

### 3. Review

Browse clusters of similar photos in a visual grid:

Each thumbnail shows its decision as a coloured border **and** a corner letter badge (colour-blind safe):

- **Green / `K`** = KEEP
- **Orange / `A`** = ARCHIVE
- **Red / `D`** = DELETE
- **Gray / `?`** = undecided (REVIEW)

**Zoom Controls:** Drag the zoom slider (120–800px) or use the `+`/`-` keys to adjust thumbnail size; `0` resets to the default. The grid reflows its column count to fit, and above the cached thumbnail size it loads high-quality images from the originals.

**Multi-select:** `Ctrl`+click toggles individual photos, `Shift`+click selects a range, or hit **Select All Shown**. A **selection bar** under the grid then shows **"N photos selected"** with one-click **Keep / Archive / Delete Selected** (and **Clear**); the `K`/`A`/`D` keys and the on-card buttons apply to the whole selection too. It all undoes as a single step.

**Hover Preview:** Hold `Alt` and hover over any thumbnail to see a full-size preview in a floating overlay — perfect for quick quality checks without opening files.

**Tooltips:** Hover any thumbnail to see detailed metrics: quality score, sharpness, brightness, face count, eyes open %, smile %, isolation %, expression naturalness %, and head pose frontal %.

**Filters:** Filter by face distance, low-quality photos (every flagged junk shot across all groups), **expression** (smiling / eyes-open / blinking / looking-away — for sorting people photos by what makes them good), **duplicate type** (exact / near / unique), or events; hide single-photo auto-keeps; search by filename. An "N of M groups reviewed" indicator tracks progress, and **Export CSV** saves the full decision list before you apply.

**Sort:** by quality (best first), date, size, or — for people photos — **most smiling / eyes-open / most natural / facing camera**.

**View — Groups vs All photos (ranked):** switch from reviewing one similar/duplicate group at a time to the whole batch laid out in a single quality order. In the all-photos view the three **"…All Shown"** buttons act on the entire filtered set — so *Low Quality* + *Delete All Shown* sweeps every flagged junk photo in one pass (reversible, undoable, count-confirmed). A near-black or blown-out photo you can't even see is scored as the junk it is and is left **flagged (undecided)** — never silently kept, never moved on its own.

**Duplicates:** the **Resolve Exact Dups** button keeps the best copy of every byte-identical group and archives the rest across the whole batch in one click.

**Best-of shortlist (O2):** **Keep Best/Event** marks the single best photo from each event as KEEP, and **Export Keepers…** copies every KEEP photo into a folder you choose — your originals stay exactly where they are.

### 4. Apply

When satisfied with your decisions, apply the changes:

| Decision | Destination |
|----------|-------------|
| KEEP | `03_KEEP/` |
| ARCHIVE (exact duplicate) | `04_ARCHIVE_DUPES/` |
| ARCHIVE (low quality / near-dup) | `05_ARCHIVE_LOW_QUALITY/` |
| DELETE | Recycle Bin (via send2trash) |

A detailed log (CSV + JSON) is written for every apply operation.

**Delete Marked Now (interim):** you don't have to finish the whole batch before reclaiming space. The red **"Delete Marked (N)"** button sends *just* the photos marked for deletion to the Recycle Bin right away — your Keep/Archive decisions stay pending — so a huge folder can be cleared gradually as you go. It confirms the count first (and warns if any is the only copy), and the recycled photos drop out of the review so they never come back as broken tiles.

### 5. Undo

Changed your mind? Click "Undo Last Apply" to restore all moved files to their original locations. (Recycle Bin deletes cannot be undone from the app.)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `K` | Mark selected photo(s) as KEEP |
| `A` | Mark selected photo(s) as ARCHIVE |
| `D` | Mark selected photo(s) as DELETE |
| `R` | Reset selected photo(s) to undecided |
| `Left` / `Right` | Previous / next photo in the group |
| `Up` / `Down` | Move up / down a row in the photo grid |
| `J` / `PageDown` / `PageUp` | Next / previous group |
| `Ctrl` / `Shift` + click | Select several photos at once |
| `C` | Compare the group side by side |
| `+` / `=` / `-` | Zoom in / out |
| `0` | Reset zoom to default |
| `Alt` + hover | Show full-size preview |
| `Ctrl+Z` | Undo your last decision |
| `Ctrl+Shift+Z` | Undo the last Apply (restore moved files) |
| `Ctrl+Enter` | Apply changes |
| `F1` / `?` | Show the shortcuts list |

## Settings

Accessible from the home screen:

| Setting | Default | Description |
|---------|---------|-------------|
| How to group photos | Similar shots | Plain-language preset for how aggressively near-duplicates are grouped: *Only near-identical* (8), *Similar shots* (17), or *Loose grouping* (24). The exact pHash Hamming-distance threshold (1–30) is available under **Advanced**. |
| Keep per group | 2 | Number of best photos to suggest keeping per group. |
| Event Gap (hours) | 4.0 | Time gap between EXIF timestamps to split into separate events. |
| Face Detection | On | Enable/disable face detection and expression analysis. |
| Face confidence | 50% | How sure the app must be before counting something as a face. Higher = fewer false faces; lower = catches fainter/distant faces. |

Window size, zoom level, the hide-single-photos toggle, and these settings are all remembered between launches. The app follows your Windows light/dark theme.

## Quality Score Formula

Every component is normalized to [0, 1] before weighting, so the score is
itself in [0, 1] and the weights mean exactly what they say:

```
score = 0.45 * sharpness_norm      # min(1, log(sharpness+1) / log(1001))
      + 0.13 * exposure            # 1 - |brightness - 128| / 128
      + 0.10 * (min(face_count, 3) / 3)
      + 0.12 * eyes_open_score
      + 0.09 * smile_score
      + 0.05 * subject_isolation
      + 0.04 * expression_naturalness
      + 0.02 * head_pose_frontal
```

| Component | Weight | Description |
|-----------|--------|-------------|
| **Sharpness** | 45% | Contrast-normalized variance of the Laplacian (focus). Normalizing by image contrast means a darker exposure of the same shot does not read as "blurrier". Log-compressed and capped at a reference of 1000 (decisively sharp). |
| **Exposure** | 13% | Peaks at mid-gray (128). Overexposed (blown-out) frames are penalized exactly like underexposed ones. |
| **Face count** | 10% | Number of detected faces, capped at 3, scaled to [0, 1]. |
| **Eyes open** | 12% | Average eyes-open score across faces (0 = closed, 1 = open). |
| **Smile** | 9% | Average smile score across faces (0 = neutral, 1 = smiling). |
| **Subject isolation** | 5% | Composition cleanliness — 1.0 for clean portraits and uniform groups, < 1.0 when small background bystanders are detected. |
| **Expression naturalness** | 4% | Penalizes awkward/unflattering expressions (squinting, frowning, mid-speech, jaw tension). 1.0 = natural/relaxed, lower = awkward. |
| **Head pose frontal** | 2% | Rewards frontal, flattering head angles. 1.0 = frontal (yaw≈0, pitch≈0, roll≈0), lower = extreme angles (profile, looking up/down). |

The upshot: between two acceptably sharp frames of the same people, the one
with open eyes and a smile wins — a blink is no longer rescued by a slightly
crisper frame, while a genuinely blurred frame still loses to a sharp one.
Photos without faces compete on sharpness and exposure only. Unreadable
files are left "undecided" for manual review instead of being auto-kept.

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
- WEBP (`.webp`)
- HEIC / HEIF (`.heic`, `.heif`) — the default iPhone format, via `pillow-heif`

## Known Limitations

- **pHash clustering is O(n^2)** — works well for ~5,000 photos but may be slow for very large collections (50,000+)
- **Single undo level** — only the most recent apply operation can be undone
- **No RAW support** — JPEG, PNG, WEBP, and HEIC/HEIF are supported; camera RAW is not
- **Flat output structure** — files moved to output folders do not preserve their original subdirectory hierarchy
- **Expression analysis on close-up faces only** — distant faces are detected but too small for reliable blendshape extraction
- **Windows only** — built and tested for Windows 10/11

## License

MIT — see [LICENSE](LICENSE). Free to use, modify, and share.
