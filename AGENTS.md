# AGENTS.md

This file defines the project standards and operating workflow for AI coding agents working on this repository.

中文说明：这是整个项目的“标准 + 工作流程”文档。Agent 在本仓库工作时，应优先遵守本文；当本文与用户本轮明确指令冲突时，先按用户本轮指令执行，并在必要时说明取舍。

## Project Overview

This project is a local-first research dataset management system. It manages datasets, samples, labels, annotations, statistics, and metadata while keeping raw files on disk.

The system starts as a local Web application and may later be packaged as a desktop application.

Primary goals:

- Provide a clean UI for managing research datasets.
- Store raw data safely on the local filesystem.
- Store metadata in SQLite.
- Support cross-platform development on Windows, Debian, and Linux.
- Keep the architecture modular and extensible.
- Make iterative local development easy to verify and easy to roll back.

## Current Target: MVP

Focus only on the MVP unless explicitly instructed otherwise.

MVP scope:

- Dataset creation and listing
- Local folder scanning
- Sample metadata registration
- Sample preview grid
- Sample detail panel
- Label editing
- Basic search and filtering
- Dataset statistics
- Manifest export
- Basic image geometry annotation: rectangle, polygon, point/points, object list, category editing, manual save, annotation metadata export

Do not implement the following in the MVP unless explicitly requested:

- Authentication
- Multi-user permissions
- Cloud sync
- AI API integration
- Tauri / Electron desktop packaging
- Complex annotation tools such as brush, mask, skeleton, video frame tracking, or CVAT-scale task/job workflows
- Vector database integration
- Distributed task queues

## Agent Operating Workflow

Agents should work in small, reviewable loops:

1. Establish state.
   - Run `git status --short --branch`.
   - Read `TODO.md`, `CHANGELOG.md`, and `ACCEPTANCE_TESTS.md` when the task affects workflow, behavior, or release scope.
   - Read the relevant source files before proposing or editing code.
   - Treat existing uncommitted changes as user or prior-agent work. Do not revert them unless explicitly instructed.

2. Clarify only when needed.
   - Ask the user before major scope changes, destructive operations, adding large dependencies, changing raw-data behavior, or moving work outside MVP.
   - If there is no serious ambiguity, make a conservative decision and proceed.
   - If a requested change conflicts with data safety rules, stop and ask.

3. Implement conservatively.
   - Keep edits scoped to the requested task and nearby code.
   - Prefer existing project patterns over new abstractions.
   - Keep route handlers thin; put business logic in services.
   - Keep frontend state simple and explicit.
   - Do not introduce broad refactors while fixing narrow bugs.

4. Verify.
   - Run focused checks for the changed area.
   - For frontend layout or interaction changes, run `npm run build` and use the browser to visually verify the affected page when practical.
   - For backend behavior changes, run compile checks and relevant pytest tests.
   - Always run `git diff --check` before reporting done.

5. Update docs.
   - Update `TODO.md` when task status, priority, or remaining scope changes.
   - Prepend `CHANGELOG.md` for user-visible behavior changes, feature additions, bug fixes, or workflow changes.
   - Prepend `ACCEPTANCE_TESTS.md` with concrete human validation steps when behavior changes.
   - For documentation-only changes, update only the relevant document unless the user requests release notes.

6. Report clearly.
   - Summarize what changed, where, and how it was verified.
   - Mention tests or verification that were not run.
   - Include local service URLs only if services were started.

## Version, Git, and Release Workflow

Use Git as the project history boundary.

- Small updates should be committed when they are coherent and verified.
- Larger version milestones may be pushed for remote version management, but do not push unless the user explicitly asks or approves.
- Prefer one commit per coherent unit of work:
  - bug fix
  - feature slice
  - documentation/workflow update
  - acceptance-test update tied to a behavior change
- Do not mix unrelated refactors into a feature or bug-fix commit.
- Commit messages should be short, imperative, and specific, for example:
  - `Fix annotation panel scrolling`
  - `Add labelme annotation export`
  - `Plan annotation follow-up batches`
- Before committing:
  - Ensure the working tree only contains intended changes.
  - Run appropriate verification.
  - Run `git diff --check`.
- After committing:
  - Confirm `git status --short --branch` is clean, unless the user intentionally asked to leave changes unstaged.

## TODO Workflow

`TODO.md` is the active scope and priority control document.

Keep it useful rather than archival:

- Keep current and near-future work visible.
- Delete or compress completed tasks from old versions once they no longer help current planning.
- Preserve only completed baseline items that explain current architecture or release state.
- Use priority labels:
  - `P0`: blocks usability or causes obvious incorrect behavior
  - `P1`: core workflow and review efficiency
  - `P2`: capability polish or secondary feature work
  - `P3`: engineering foundation or long-term work
- Use task attributes:
  - `Bug 修复`
  - `优化`
  - `新增`
  - `工程`
- When planning larger work, group tasks by batch or phase and state the goal of each batch.
- Do not let `TODO.md` become a full changelog; completed historical detail belongs in `CHANGELOG.md` or release notes.

## CHANGELOG Workflow

`CHANGELOG.md` records meaningful project changes.

- Always prepend the newest entry at the top.
- Use the current date.
- Keep entries concise and user-facing.
- For small updates, add a short entry only when behavior, workflow, UI, API, data model, or verification scope changes.
- For larger versions, merge and compress older detailed entries into higher-signal summaries when the file becomes too long.
- Avoid duplicating every low-level implementation detail already visible in Git history.

## ACCEPTANCE_TESTS Workflow

`ACCEPTANCE_TESTS.md` records human validation steps.

- Always prepend the newest acceptance scope at the top.
- Write concrete steps and pass criteria.
- Keep old acceptance tests only while they remain useful regression coverage.
- Delete or merge overly old sections into a compact core regression checklist.
- Every user-visible workflow change should have at least one manual validation path.

## Tech Stack

Backend:

- Python
- FastAPI
- SQLModel or SQLAlchemy
- SQLite
- Pydantic
- Pillow / OpenCV when needed

Frontend:

- React
- TypeScript
- Vite
- Tailwind CSS
- Axios
- React Router
- Lucide Icons

Storage:

- Raw files stay on disk.
- Database stores metadata only.
- Do not store large binary files directly in SQLite.

## Architecture Rules

Use a clean modular structure.

Backend should follow this pattern:

```text
backend/app/
├── main.py
├── core/
├── models/
├── schemas/
├── services/
├── api/
└── utils/
```

Responsibilities:

- `api/`: FastAPI routes only. Keep route handlers thin.
- `services/`: business logic, scanning logic, statistics, annotation logic, export logic.
- `models/`: database models.
- `schemas/`: request and response schemas.
- `core/`: config, database session, app settings.
- `utils/`: reusable helpers such as hashing, file type detection, image size reading, path handling.

Frontend should follow this pattern:

```text
frontend/src/
├── pages/
├── components/
├── api/
├── hooks/
├── types/
└── styles/
```

Responsibilities:

- `pages/`: route-level views.
- `components/`: reusable UI components.
- `components/annotation/`: annotation-specific canvas, toolbar, object list, and history helpers.
- `api/`: API client functions.
- `hooks/`: reusable React hooks.
- `types/`: shared TypeScript types.
- `styles/`: global styles.

## Data Safety Rules

The application must not silently modify, move, rename, or delete user data files.

Allowed by default:

- Read file metadata
- Generate hashes
- Generate thumbnails
- Read image dimensions
- Store relative and absolute paths
- Register file records in the database
- Store labels, annotations, splits, review status, and other metadata in SQLite

Not allowed unless explicitly requested:

- Delete raw files
- Move raw files
- Rename raw files
- Overwrite raw files
- Rewrite source annotations next to raw data files
- Generate sidecar files in raw dataset directories

When scanning folders, handle missing permissions, broken files, and unsupported file types gracefully.

Annotation saves are metadata-only operations. They may replace rows in the SQLite `annotations` table for a sample, but must not write back to the original image.

## Database Rules

Use SQLite for the MVP.

The database should store:

- Dataset metadata
- Sample metadata
- File paths
- Labels
- Annotation metadata
- Dataset statistics
- Split information
- Manifest export information

The database should not store:

- Large image binaries
- Large video binaries
- Large raw dataset archives

Prefer stable models that can be migrated later to PostgreSQL.

For SQLite model additions, add lightweight startup column/table backfill in `backend/app/core/database.py` unless a real migration system is introduced.

## API Design Rules

Use REST-style endpoints under `/api`.

Core MVP endpoints:

```text
GET    /api/datasets
POST   /api/datasets
GET    /api/datasets/{id}
PATCH  /api/datasets/{id}
DELETE /api/datasets/{id}
POST   /api/datasets/{id}/scan
GET    /api/datasets/{id}/samples
GET    /api/samples/{id}
PATCH  /api/samples/{id}
GET    /api/stats/datasets/{id}
GET    /api/datasets/{id}/export-manifest
```

Annotation endpoints:

```text
GET    /api/samples/{id}/annotations
PUT    /api/samples/{id}/annotations
POST   /api/samples/{id}/annotations/export-labelme
```

Use clear response objects. Do not return raw ORM objects directly if schemas are available.

## UI Style Rules

The UI should feel clean, white, modern, and premium.

Design references:

- ChatGPT Web layout style
- iOS white minimal interface
- Rounded cards
- Soft shadows
- Light borders
- Clear spacing
- Minimal visual noise

Avoid:

- Overly colorful dashboards
- Dense enterprise-style tables as the only view
- Dark UI as the default
- Complex animations in the MVP

Recommended main views:

- Dataset list page
- Dataset detail page
- Sample grid
- Sample detail side panel
- Statistics cards
- Search and filter bar
- Image annotation workspace

Annotation UI rules:

- Keep the canvas, object list, and save state visually stable.
- Object lists must scroll internally and must not resize the image canvas.
- Save status must be explicit when edits are dirty.
- Switching samples while dirty must require a clear save/discard/cancel path.

## Coding Standards

General:

- Keep code simple and readable.
- Prefer explicit names over clever abstractions.
- Add concise comments for non-obvious logic.
- Avoid premature optimization.
- Do not introduce large dependencies without a clear reason.

Python:

- Use type hints.
- Use Pydantic / SQLModel schemas where appropriate.
- Keep API route functions thin.
- Put scanning, annotation, statistics, and export logic in services.
- Handle filesystem errors explicitly.

TypeScript:

- Use typed API responses.
- Avoid `any` unless absolutely necessary.
- Keep UI components reusable but not over-engineered.
- Keep state management simple in the MVP.
- Use stable layout constraints for card grids, toolbars, canvases, and side panels to avoid overlap or resize loops.

## Testing Expectations

For the MVP, add focused tests when practical:

- File scanning utility tests
- Hashing utility tests
- Dataset API tests
- Annotation API tests
- Manifest export tests
- Metadata import/export tests

Do not block MVP progress with complex test infrastructure.

Verification guidance:

- Backend syntax check:

```bash
cd backend
python -m compileall app tests
```

- Backend tests:

```bash
cd backend
python -m pytest
```

- Frontend build:

```bash
cd frontend
npm run build
```

Run the smallest reliable subset first, then broaden when touching shared behavior.

## Development Commands

Backend example:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend example:

```bash
cd frontend
npm install
npm run dev
```

Default local URLs:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173`

## Implementation Priority

When implementing from scratch, follow this order:

1. Backend project skeleton
2. Config and database setup
3. Dataset and Sample models
4. Dataset CRUD API
5. Folder scanning service
6. Sample listing API
7. Manifest export API
8. Frontend project skeleton
9. Dataset list page
10. Dataset detail page
11. Sample grid and filters
12. Sample detail panel
13. Basic statistics cards
14. Basic image annotation workflow
15. README and workflow document updates

For current development, use `TODO.md` as the active priority source instead of this historical bootstrap order.

## Important Constraints

- Keep the first version runnable locally.
- Do not require Docker for the MVP.
- Do not require external cloud services.
- Do not require GPU dependencies.
- Do not assume a specific dataset format.
- Do not hard-code absolute paths.
- Do not commit generated databases, cache files, thumbnails, raw datasets, or local logs.
- Do not push to a remote repository unless the user explicitly requests or approves it.
