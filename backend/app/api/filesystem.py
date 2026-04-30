import string
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.filesystem import DirectoryEntry, DirectoryListResponse
from app.utils.paths import resolve_local_path

router = APIRouter(prefix="/api/filesystem", tags=["filesystem"])


@router.get("/directories", response_model=DirectoryListResponse)
def list_directories(path: str | None = Query(default=None)) -> DirectoryListResponse:
    """List local directories without reading or modifying user files."""
    if not path:
        return DirectoryListResponse(current_path=None, parent_path=None, entries=_root_entries())

    root = resolve_local_path(path)
    if not root.exists() or not root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory does not exist: {root}",
        )

    entries: list[DirectoryEntry] = []
    try:
        for child in root.iterdir():
            if child.is_dir():
                entries.append(DirectoryEntry(name=child.name, path=str(child.resolve())))
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Directory is not readable: {exc}",
        ) from exc

    entries.sort(key=lambda item: item.name.casefold())
    parent = root.parent if root.parent != root else None
    return DirectoryListResponse(
        current_path=str(root),
        parent_path=str(parent) if parent else None,
        entries=entries,
    )


def _root_entries() -> list[DirectoryEntry]:
    entries: list[DirectoryEntry] = []
    if "\\" in str(Path.cwd()) or ":" in str(Path.cwd()):
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                entries.append(DirectoryEntry(name=f"{letter}:\\", path=str(drive)))
        return entries

    return [DirectoryEntry(name="/", path="/")]
