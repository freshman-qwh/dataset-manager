from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def find_frontend_directory() -> Path | None:
    configured = os.getenv("DATASET_MANAGER_FRONTEND_DIR")
    if configured:
        candidate = Path(configured).resolve()
    elif getattr(sys, "frozen", False):
        candidate = (Path(getattr(sys, "_MEIPASS")) / "frontend").resolve()
    else:
        candidate = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def install_frontend(app: FastAPI, frontend_directory: Path | None = None) -> bool:
    root = (frontend_directory or find_frontend_directory())
    if root is None:
        return False
    root = root.resolve()
    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{requested_path:path}", include_in_schema=False)
    def serve_frontend(requested_path: str):
        if requested_path == "api" or requested_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        requested = (root / requested_path).resolve()
        if root == requested or root in requested.parents:
            if requested.is_file():
                return FileResponse(requested)
        return FileResponse(root / "index.html")

    return True
