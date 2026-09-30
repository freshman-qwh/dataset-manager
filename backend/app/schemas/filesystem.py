from typing import Literal

from pydantic import BaseModel


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListResponse(BaseModel):
    current_path: str | None
    parent_path: str | None
    entries: list[DirectoryEntry]


class FilesystemEntry(DirectoryEntry):
    kind: Literal["directory", "file"]


class FilesystemListResponse(BaseModel):
    current_path: str | None
    parent_path: str | None
    entries: list[FilesystemEntry]
