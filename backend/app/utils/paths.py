from pathlib import Path


def resolve_local_path(path_value: str) -> Path:
    """Resolve a user-provided local path without modifying the target."""
    return Path(path_value).expanduser().resolve()


def relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name
