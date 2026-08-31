"""Pydantic schemas for NAS connection profiles (FR-001/002).

Passwords are write-only: accepted on create/update, never returned.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.constants import Protocol, RsyncMode


class ConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=255)
    protocol: Protocol = "ftp"
    port: int = Field(default=21, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    root_path: str = "/"
    passive_mode: bool = True
    timeout_seconds: int = Field(default=30, ge=1, le=600)
    description: str | None = None

    # --- rsync (optional) ---------------------------------------------------
    # fs_root is the device's REAL filesystem root (/Volume1, /mnt/md0), which is
    # a different namespace from the FTP-relative root_path above.
    fs_root: str | None = None
    rsync_enabled: bool = False
    rsync_mode: RsyncMode = "daemon"
    rsync_host: str | None = None  # defaults to `host` when blank
    rsync_port: int = Field(default=873, ge=1, le=65535)
    rsync_module: str | None = None
    rsync_username: str | None = None
    rsync_ssh_port: int = Field(default=22, ge=1, le=65535)


class ConnectionCreate(ConnectionBase):
    password: str = Field(min_length=1)
    # Write-only, like `password`. Never returned by any endpoint.
    rsync_password: str | None = Field(default=None, min_length=1)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    protocol: Protocol | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1)  # only if changing
    root_path: str | None = None
    passive_mode: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    description: str | None = None
    fs_root: str | None = None
    rsync_enabled: bool | None = None
    rsync_mode: RsyncMode | None = None
    rsync_host: str | None = None
    rsync_port: int | None = Field(default=None, ge=1, le=65535)
    rsync_module: str | None = None
    rsync_username: str | None = None
    rsync_password: str | None = Field(default=None, min_length=1)  # only if changing
    rsync_ssh_port: int | None = Field(default=None, ge=1, le=65535)


class ConnectionRead(ConnectionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # So the UI can show "password saved" without ever returning it.
    rsync_password_set: bool = False
    last_test_status: str | None = None
    last_test_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ConnectionTestRequest(ConnectionCreate):
    """Body for testing an unsaved connection (includes the password)."""


class ConnectionTestResponse(BaseModel):
    ok: bool
    connectivity: bool
    authentication: bool
    can_list: bool
    can_write: bool | None
    can_delete: bool | None
    summary: str
    messages: list[str]
