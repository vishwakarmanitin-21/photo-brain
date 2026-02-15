# PhotoBrain Desktop — Workspace Context

## What is this project?

PhotoBrain Desktop is a local-first Windows GUI application for cleaning and organizing large batches of personal photos (Android phones + DSLR). It scans folders, detects exact and near duplicates, scores image quality, detects faces, groups photos into time-based events, suggests KEEP/ARCHIVE/DELETE decisions, and lets the user review them visually before applying safe file moves.

## Tech Stack

- **Language:** Python 3.10+
- **UI:** PySide6 (Qt for Python)
- **Image processing:** opencv-python (sharpness via Laplacian), Pillow (thumbnails + EXIF), scipy (head pose estimation)
- **Similarity:** imagehash (pHash + Hamming distance)
- **Face detection:** mediapipe (Tasks API — `mp.tasks.vision.FaceDetector` + `FaceLandmarker`)
- **File deletion:** send2trash (cross-platform Recycle Bin)
- **Persistence:** SQLite (stdlib) with WAL mode, schema version 7
- **Packaging:** pip + requirements.txt + venv

## Architecture

The codebase follows strict separation between UI, core logic, and background workers:

```
app/
  main.py                     # QApplication bootstrap
  core/                       # Pure logic — no Qt dependencies except models
    models.py                 # Dataclasses: Photo, Cluster, Event, SessionState + enums
    hashing.py                # SHA256 (exact dup) + pHash (near dup)
    clustering.py             # Union-Find clustering by hash similarity
    scoring.py                # Laplacian sharpness + brightness + face/expression/isolation → quality score
    scanner.py                # Pipeline orchestrator (collect → hash → cluster → score → faces → expressions → events → suggest)
    faces.py                  # Face detection (multi-scale) + expression analysis via mediapipe Tasks API
    events.py                 # EXIF date/time extraction + time-proximity event grouping
    thumbnails.py             # 200x200 JPEG cache in .photobrain/thumbs/
    session_store.py          # SQLite CRUD with WAL, batch inserts, schema migrations (v1→v7)
    file_ops.py               # Safe file moves, Recycle Bin delete, collision handling, CSV/JSON logs, undo
  ui/                         # PySide6 widgets — no processing logic
    main_window.py            # QStackedWidget (Setup→Scan→Review), owns workers + store
    setup_view.py             # Folder picker, Start Scan, Resume Session
    scan_view.py              # Progress bar, live stats, elapsed timer, Cancel, Continue to Review
    review_view.py            # Cluster list + thumbnail grid + keyboard shortcuts + face/event filters
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
- **Three-verdict system:** KEEP (safe move), ARCHIVE (safe move to archive), DELETE (Recycle Bin via send2trash)
- **Schema migrations** via `PRAGMA user_version` — v1→v2 adds face/event columns, v2→v3 converts old DELETE→ARCHIVE, v3→v4 adds face_distance, v4→v5 adds expression scores, v5→v6 adds subject_isolation

## Data Flow

1. User selects folder → SetupView emits `scan_requested(path)`
2. MainWindow creates SessionStore + ScanWorker → ScanWorker runs pipeline in background
3. Pipeline: collect files → SHA256 hash → pHash → quality score → face detection → expression analysis → EXIF events → Union-Find cluster → suggest verdicts
4. All results persisted to SQLite → scan summary shown → user clicks "Continue to Review"
5. ThumbWorker generates thumbnails progressively → ReviewView displays them
6. User reviews with K/A/D/R shortcuts → verdicts stored in-memory on Photo objects
7. Apply: verdicts saved to SQLite → FileOperator moves/deletes files → logs written
8. Undo: reads apply_log from SQLite → reverses moves (Recycle Bin deletes cannot be undone from app)

## Verdict System

- **KEEP** (green) — moved to `03_KEEP` folder
- **ARCHIVE** (orange) — moved to archive folders (safe, fully reversible)
- **DELETE** (red) — sent to system Recycle Bin via send2trash (not reversible from app)
- **REVIEW** (default) — undecided, skipped during apply

## Session Persistence

Database at `<source_folder>/.photobrain/session.db`. Tables: session, photos, clusters, events, apply_log. Thumbnails cached at `.photobrain/thumbs/`. Logs at `.photobrain/logs/`.

## Output Folders (inside source folder, excluded from scanning)

- `03_KEEP` — photos marked KEEP
- `04_ARCHIVE_DUPES` — exact duplicate archives
- `05_ARCHIVE_LOW_QUALITY` — near-duplicate / low quality archives

## Running

```bash
# First time setup:
python -m venv venv
venv\Scripts\pip install -r requirements.txt

# Run the application:
venv\Scripts\python run.py
```

## Current Status (v2 — Phase 2+ complete)

- All Phase 1 features: scan, cluster, score, review, apply, undo, settings, session resume
- Phase 2: face detection (mediapipe multi-scale), EXIF event grouping, face/event filters in review UI
- Expression-aware scoring: eyes-open and smile bonuses via Face Landmarker blendshapes
- Scan summary with face distance breakdown (close-up, distant, no faces, group shots, expressions analyzed)
- Three verdicts: KEEP, ARCHIVE (safe move), DELETE (Recycle Bin)
- Per-photo buttons (Keep/Archive/Delete) + cluster-level (Keep All/Archive All/Delete All)
- Double-click thumbnail to open photo in default viewer
- Scan summary with "Continue to Review" button
- Keyboard shortcuts: K (Keep), A (Archive), D (Delete), R (Review)
- Thumbnail tooltips show Eyes Open %, Smile %, and Isolation % for photos with faces
- Supports JPEG + PNG only
- pHash clustering is O(n^2) — fine for ~5000 photos

## Important Technical Notes

- **mediapipe API:** Uses `mp.tasks.vision.FaceDetector` (Tasks API), NOT the deprecated `mp.solutions` API. Multi-scale detection using `blaze_face_short_range.tflite`: runs on original image first (close-up faces), then on progressively downscaled versions (50%, 25%) to catch distant/small faces. Models auto-download to temp dir on first use. Expression analysis uses `FaceLandmarker` (`face_landmarker.task`) for blendshape-based eyes-open and smile scoring (works on close-up faces; distant faces get detection but not expressions).
- **QDialog.Accepted:** Always use `QDialog.Accepted` (class-level), never `dialog.Accepted` (instance-level) — PySide6 doesn't expose it on instances.
- **Quality score formula:** `0.45 * log(sharpness+1) + 0.13 * (brightness/255) + 0.10 * min(face_count, 3) + 0.12 * eyes_open_score + 0.09 * smile_score + 0.05 * subject_isolation + 0.04 * expression_naturalness + 0.02 * head_pose_frontal`
- **Subject isolation:** Measures composition cleanliness (1.0 = clean portrait/uniform group, < 1.0 = background bystanders). Computed via multi-scale face detection + IoU merge. Faces < 25% of the largest face area are classified as background noise.
- **Expression naturalness:** Penalizes awkward/unflattering expressions (squinting, frowning, mid-speech, jaw tension) using mediapipe blendshapes. 1.0 = natural/relaxed, lower = awkward.
- **Head pose frontal:** Rewards frontal, flattering head angles from mediapipe transformation matrix. 1.0 = frontal (yaw≈0, pitch≈0, roll≈0), lower = extreme angles (profile, looking up/down).

## Conventions

- No cloud/API calls — everything local
- ARCHIVE for safe moves, DELETE only for Recycle Bin
- Deterministic behavior — sorted inputs, tiebreakers on filepath
- Progress signals throttled every 50 items to avoid UI flooding
- Error handling: unreadable images get score 0.0, sha256/phash = None, placed in singleton clusters

---

## Vibe Code Guide

### Core Principles

When making any code changes, follow these principles in order:

#### 1. Understand Before Acting

- Fully comprehend the change request, including context and expected outcome
- Identify the root cause of issues before proposing solutions
- Understand how the change fits into the broader codebase architecture
- Consider downstream effects and integration points
- Never make assumptions about unclear requirements — ask for clarification

#### 2. Explore Better Solutions

- In the context of requested changes, identify opportunities for improvement
- Share better ideas or alternative approaches when they exist
- Don't over-engineer simple requests
- Consider technical debt vs. immediate needs
- Respect existing patterns unless there's a compelling reason to change

#### 3. Prevent Regressions

- Identify all code paths affected by the change
- Review dependencies and dependent code
- Ensure changes don't break existing functionality
- Verify backward compatibility where required
- Check for similar patterns elsewhere in the codebase that might need updates

#### 4. Verify Compilation and Functionality

- After making changes, ensure the code compiles/runs without errors
- Fix any syntax errors, type mismatches, or import issues
- Test that the change works as expected
- Verify edge cases and error conditions

#### 5. Code Review Mindset

- Does the code follow established patterns and conventions?
- Is the implementation clear and maintainable?
- Is error handling appropriate?
- No debugging code left in (console.logs, commented code, etc.)
- Performance and security implications considered

#### 6. Maintain Documentation

- Update CLAUDE.md when architecture, patterns, or conventions change
- Keep feature descriptions current with implementation
- Write for someone new to the project

### Workflow

For each change request:
1. **Clarify** — Understand the request fully, ask questions
2. **Analyze** — Assess impact, identify better approaches if they exist
3. **Plan** — Consider regression risks, integration points
4. **Implement** — Make the changes carefully
5. **Verify** — Compile, test functionality, review integration
6. **Document** — Update docs with relevant details

### When to Push Back

It's appropriate to question or suggest alternatives when:
- The requested change would introduce technical debt
- A simpler approach would achieve the same goal
- The change would break existing functionality
- Requirements are unclear or contradictory
- The change conflicts with architectural principles

### Success Criteria

A change is complete when:
- The original request is fully addressed
- No regressions introduced
- Code compiles and runs without errors
- Integration points verified
- Documentation updated with relevant details
- Code quality standards met
