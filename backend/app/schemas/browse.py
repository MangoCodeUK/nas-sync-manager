"""Schemas for the dual-pane folder browser (FR-004/005/006)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class BrowseEntry(BaseModel):
    name: str
    type: str  # "dir" | "file"
    path: str
    size: int | None = None
    modify: dt.datetime | None = None


class BrowseResponse(BaseModel):
    connection_id: int
    path: str
    parent: str | None
    entries: list[BrowseEntry]


class FolderSize(BaseModel):
    connection_id: int
    path: str
    total_bytes: int
    file_count: int
    folder_count: int
