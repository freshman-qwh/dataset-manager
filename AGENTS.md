# AGENTS.md

This file provides instructions for AI coding agents working on this repository.

## Project Overview

This project is a local-first research dataset management system. It manages datasets, samples, labels, statistics, and metadata while keeping raw files on disk.

The system should start as a local Web application and may later be packaged as a desktop application.

Primary goals:

- Provide a clean UI for managing research datasets.
- Store raw data safely on the local filesystem.
- Store metadata in SQLite.
- Support cross-platform development on Windows, Debian, and Linux.
- Keep the architecture modular and extensible.

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

Do not implement the following in the first version:

- Authentication
- Multi-user permissions
- Cloud sync
- AI API integration
- Tauri / Electron desktop packaging
- Complex annotation tools
- Vector database integration
- Distributed task queues

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
- `services/`: business logic, scanning logic, statistics, export logic.
- `models/`: database models.
- `schemas/`: request and response schemas.
- `core/`: config, database session, app settings.
- `utils/`: reusable helpers such as hashing, file type detection, path handling.

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
- Store relative and absolute paths
- Register file records in the database

Not allowed unless explicitly requested:

- Delete raw files
- Move raw files
- Rename raw files
- Overwrite raw files
- Rewrite annotations

When scanning folders, handle missing permissions, broken files, and unsupported file types gracefully.

## Database Rules

Use SQLite for the MVP.

The database should store:

- Dataset metadata
- Sample metadata
- File paths
- Labels
- Dataset statistics
- Split information
- Manifest export information

The database should not store:

- Large image binaries
- Large video binaries
- Large raw dataset archives

Prefer stable models that can be migrated later to PostgreSQL.

## API Design Rules

Use REST-style endpoints under `/api`.

Required MVP endpoints:

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
- Put scanning and export logic in services.
- Handle filesystem errors explicitly.

TypeScript:

- Use typed API responses.
- Avoid `any` unless absolutely necessary.
- Keep UI components reusable but not over-engineered.
- Keep state management simple in the MVP.

## Testing Expectations

For the MVP, add basic tests when practical:

- File scanning utility tests
- Hashing utility tests
- Dataset API tests
- Manifest export tests

Do not block MVP progress with complex test infrastructure.

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
14. README updates

## Important Constraints

- Keep the first version runnable locally.
- Do not require Docker for the MVP.
- Do not require external cloud services.
- Do not require GPU dependencies.
- Do not assume a specific dataset format.
- Do not hard-code absolute paths.
- Do not commit generated databases, cache files, thumbnails, or raw datasets.
