# CLAUDE.md — PhotoBrain Desktop

Local-first Windows GUI for cleaning and organizing large photo batches. Python 3.10+ + PySide6 + SQLite + mediapipe + imagehash.

## Shared Nitin second brain

The shared cross-tool context lives in the Obsidian vault at `D:\Wealducate Ecosystem`. For non-trivial work for Nitin, read `D:\Wealducate Ecosystem\00-Maps\Home.md` plus the small notes in `D:\Wealducate Ecosystem\Context\` (`profile.md`, `governance.md`, `glossary.md`, `decisions.md`) before acting.

Follow the vault governance: durable knowledge, decisions, research, and non-code tasks live in the vault; code and app backlog stay in this repo. Do not duplicate repo backlog into the vault. At the end of any substantive session, append a short Daily log in the vault and route durable outcomes to the canonical files there.

## OpenClaw Project Memory

For full project history, decisions, and current state, read `C:/Users/Nitin/.openclaw/workspace/memory/projects/photo-brain.md` at the start of non-trivial sessions. That file is the canonical durable record maintained by OpenClaw agents. Local Claude Code memory (auto-managed) captures codebase patterns and conventions — complementary, not competing.

### Reverse Bridge: Direct Session → OpenClaw Memory
When this session makes significant decisions (architecture changes, config fixes, workflow changes), write a handoff note to `C:/Users/Nitin/.openclaw/workspace/memory/handoff.md` so OpenClaw's midnight tracker can incorporate it. Format: date, decisions, config changes, memory updates, Lobster action needed.

## Running

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python run.py
```

## Architecture (see .claude/rules/architecture.md for full detail)

Strict separation:
- `app/core/` — pure logic, NO Qt imports
- `app/ui/` — PySide6 widgets ONLY, no processing
- `app/workers/` — QThread subclasses (scan + thumbnail generation)

## Current Status

- Schema version: **8** (v7→v8 adds `applied` column to clusters for per-cluster apply)
- Phase 1+2 complete: scan, cluster, score, review, apply, undo, face detection, EXIF events
- Verdicts: KEEP (move to 03_KEEP), ARCHIVE (move to archive folders), DELETE (Recycle Bin — NOT reversible)

## Key Technical Rules

- mediapipe: use `mp.tasks.vision.FaceDetector` — NOT deprecated `mp.solutions`
- `QDialog.Accepted` — class-level only, never instance-level
- All inputs sorted deterministically, filepath as tiebreaker
- pHash clustering is O(n²) — suitable up to ~5000 photos
- No cloud/API calls — everything local

## Quality Score

`0.45 * log(sharpness+1) + 0.13 * (brightness/255) + 0.10 * min(face_count,3) + 0.12 * eyes_open + 0.09 * smile + 0.05 * isolation + 0.04 * expression + 0.02 * frontal`

## Post-Change Checklist

- [ ] Code runs without errors (`venv\Scripts\python run.py`)
- [ ] Schema version incremented if DB columns changed
- [ ] Separation respected — no Qt in core/, no processing in ui/
- [ ] No cloud/API calls introduced
