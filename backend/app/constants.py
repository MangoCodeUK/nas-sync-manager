"""Shared vocabulary for job/transfer options (kept in one place)."""
from __future__ import annotations

from typing import Literal

JobType = Literal["copy", "mirror", "move"]
MirrorMode = Literal["safe", "strict"]

ConflictStrategy = Literal[
    "skip",
    "overwrite_if_newer",
    "overwrite_if_size_differs",
    "overwrite_if_newer_or_size_differs",
    "always_overwrite",
    "rename",
    "keep_both",
]

DeleteStrategy = Literal[
    "manual_approval",
    "auto_delete_after_verification",
    "archive",
    "never",
]

ScheduleType = Literal["manual", "interval", "hourly", "daily", "weekly", "monthly", "cron"]

Protocol = Literal["ftp", "ftps"]

# How bytes actually move, kept separate from JobType (what the job does).
Transport = Literal["ftp", "rsync"]

# daemon = rsync://user@host:873/module (no encryption, no key management)
# ssh    = rsync -e "ssh -p N" user@host:/path
RsyncMode = Literal["daemon", "ssh"]

VerificationLevel = Literal[1, 2, 3, 4]
