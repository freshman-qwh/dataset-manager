from pydantic import BaseModel


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListResponse(BaseModel):
    current_path: str | None
    parent_path: str | None
    entries: list[DirectoryEntry]
