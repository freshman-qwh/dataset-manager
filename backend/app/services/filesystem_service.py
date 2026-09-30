from pathlib import Path
import string

from fastapi import HTTPException, status

from app.schemas.filesystem import FilesystemEntry, FilesystemListResponse
from app.utils.paths import resolve_local_path


def browse_local_files(path: str | None, extensions: str) -> FilesystemListResponse:
    """Browse one level, including only files with the requested extensions."""
    suffixes = {f".{value.strip().lower().lstrip('.')}" for value in extensions.split(",") if value.strip()}
    if not path:
        roots = [Path(f"{letter}:\\") for letter in string.ascii_uppercase] if Path.cwd().drive else [Path("/")]
        return FilesystemListResponse(
            current_path=None,
            parent_path=None,
            entries=[FilesystemEntry(name=str(root), path=str(root), kind="directory") for root in roots if root.exists()],
        )
    root = resolve_local_path(path)
    try:
        if root.is_file():
            root = root.parent
        if not root.is_dir():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Directory does not exist: {root}")
        entries = []
        for child in root.iterdir():
            if child.is_dir():
                entries.append(FilesystemEntry(name=child.name, path=str(child.resolve()), kind="directory"))
            elif child.is_file() and child.suffix.lower() in suffixes:
                entries.append(FilesystemEntry(name=child.name, path=str(child.resolve()), kind="file"))
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Directory is not readable: {exc}") from exc
    entries.sort(key=lambda item: (item.kind != "directory", item.name.casefold()))
    return FilesystemListResponse(
        current_path=str(root),
        parent_path=str(root.parent) if root.parent != root else None,
        entries=entries,
    )
