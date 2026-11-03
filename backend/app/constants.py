"""Shared vocabulary for job/transfer options (kept in one place)."""
from __future__ import annotations

import re
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

# The host and user a remote spec is built from (user@host:path, user@host::module).
# Both reach ssh and rsync as arguments, so a value starting with "-" would be read
# as an option (-oProxyCommand=... runs a command) and a space or "@" would split
# the spec. Only names a device can really have: a host name, an IPv4 address, or
# an IPv6 address in brackets; a user name of letters, digits, ".", "_" and "-".
HOST_PATTERN = re.compile(r"^(?:[A-Za-z0-9_](?:[A-Za-z0-9._-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])$")
USER_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")

VerificationLevel = Literal[1, 2, 3, 4]
