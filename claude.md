# PhotoBrain Desktop — Workspace Context

## What is this project?

PhotoBrain Desktop is a local-first Windows GUI application for cleaning and organizing large batches of personal photos (Android phones + DSLR). It scans folders, detects exact and near duplicates, scores image quality, suggests KEEP/DELETE decisions, and lets the user review them visually before applying safe file moves.

## Tech Stack

- **Language:** Python 3.10+
- **UI:** PySide6 (Qt for Python)
- **Image processing:** opencv-python (sharpness via Laplacian), Pillow (thumbnails)
- **Similarity:** imagehash (pHash + Hamming distance)
- **Persistence:** SQLite (stdlib) with WAL mode
- **Packaging:** pip + requirements.txt + venv

## Architecture

The codebase follows strict separation between UI, core logic, and background workers:

```
app/
  main.py                     # QApplication bootstrap
  core/                       # Pure logic — no Qt dependencies except models
    models.py                 # Dataclasses: Photo, Cluster, SessionState + enums
    hashing.py                # SHA256 (exact dup) + pHash (near dup)
    clustering.py             # Union-Find clustering by hash similarity
    scoring.py                # Laplacian sharpness + brightness → quality score
    scanner.py                # Pipeline orchestrator (collect → hash → cluster → score → suggest)
    thumbnails.py             # 200x200 JPEG cache in .photobrain/thumbs/
    session_store.py          # SQLite CRUD with WAL, batch inserts, transactions
    file_ops.py               # Safe file moves, collision handling, CSV/JSON logs, undo
  ui/                         # PySide6 widgets — no processing logic
    main_window.py            # QStackedWidget (Setup→Scan→Review), owns workers + store
    setup_view.py             # Folder picker, Start Scan, Resume Session
    scan_view.py              # Progress bar, live stats, elapsed timer, Cancel
    review_view.py            # Cluster list + thumbnail grid + keyboard shortcuts
    dialogs.py                # SettingsDialog, ApplyConfirmDialog, UndoResultDialog
  workers/                    # QThread subclasses for background processing
    scan_worker.py            # Full scan pipeline with cancellation + progress signals
    thumb_worker.py           # Progressive thumbnail generation
  util/
    paths.py                  # Path constants, skip dirs, collision resolution
    logging_util.py           # Rotating file + console logging
```

## Key Design Patterns

- **QThread subclass** for workers (not moveToThread) — linear pipeline, no event loop needed
- **Signals/slots** for all worker→UI communication (progress, completion, errors)
- **Cancellation** via boolean flag checked between phases and every 50 iterations
- **SQLite WAL mode** allows concurrent reads from UI while worker writes
- **Batch inserts** via `executemany` for 5000+ photo performance
- **Union-Find** with path compression for deterministic clustering
- **Never permanently delete** — files are moved to archive folders with full undo

## Data Flow

1. User selects folder → SetupView emits `scan_requested(path)`
2. MainWindow creates SessionStore + ScanWorker → ScanWorker runs pipeline in background
3. Pipeline: collect files → SHA256 hash → pHash → quality score → Union-Find cluster → suggest verdicts
4. All results persisted to SQLite → MainWindow loads ReviewView
5. ThumbWorker generates thumbnails progressively → ReviewView displays them
6. User reviews with K/D/R shortcuts → verdicts stored in-memory on Photo objects
7. Apply: verdicts saved to SQLite → FileOperator moves files → logs written
8. Undo: reads apply_log from SQLite → reverses moves

## Session Persistence

Database at `<source_folder>/.photobrain/session.db`. Tables: session, photos, clusters, apply_log. Thumbnails cached at `.photobrain/thumbs/`. Logs at `.photobrain/logs/`.

## Output Folders (inside source folder, excluded from scanning)

- `03_KEEP` — photos marked KEEP
- `04_ARCHIVE_DUPES` — exact duplicate archives
- `05_ARCHIVE_LOW_QUALITY` — near-duplicate / low quality archives

## Running

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python run.py
```

## Current Status (v1)

- All core features implemented: scan, cluster, score, review, apply, undo, settings, session resume
- Only Assisted mode (user reviews all suggestions before apply)
- Supports JPEG + PNG only
- pHash clustering is O(n^2) — fine for ~5000 photos

## Conventions

- No cloud/API calls — everything local
- No permanent deletes — only safe moves
- Deterministic behavior — sorted inputs, tiebreakers on filepath
- Progress signals throttled every 50 items to avoid UI flooding
- Error handling: unreadable images get score 0.0, sha256/phash = None, placed in singleton clusters
