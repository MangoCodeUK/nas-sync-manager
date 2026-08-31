"""Registry of NAS shares bind-mounted into the container (rsync transport).

Why this exists
---------------
rsync cannot copy remote->remote: one end of every transfer must be a real path
belonging to the process running rsync. The app runs in a container on the new
NAS, so that local end is a bind mount of the NAS's own storage. FTP has no such
need - it streams between two sockets - which is why this module is only used by
the rsync provider.

The convention
--------------
A host path ``/X`` is mounted in the container at ``<mount_root>/X``::

    /Volume1/RsyncTest   ->   /nas/Volume1/RsyncTest

so the container path always *encodes* the host path and translation is a prefix
add. Nothing here is hardcoded to a particular share: exposing another one is a
line in ``docker-compose.prod.yml`` plus a redeploy, with no code change and no
migration. That was an explicit requirement - shares get added one at a time as
trust in the destructive operations grows.

Why ``/proc/self/mountinfo`` is only used to *verify*
-----------------------------------------------------
It tells us a mount really exists and whether it is read-only, but it cannot tell
us the host path. Measured on this NAS, a bind mount of ``/Volume1/RsyncTest``
reports its root as ``/RsyncTest`` - because ``/Volume1`` is a btrfs subvolume,
the field is relative to the source filesystem, not to the host's root. Deriving
host paths from it would therefore be silently wrong, so we don't.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass

from app.settings import get_settings

MOUNTINFO = "/proc/self/mountinfo"

# mountinfo escapes these characters in path fields.
_UNESCAPE = (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\"))


class MountError(Exception):
    """Base class for mount problems - always carries an actionable message."""


class MountNotAvailable(MountError):
    """The path is not inside any share exposed to the container."""


class MountReadOnly(MountError):
    """The path is inside a share mounted read-only, but a write was requested."""


@dataclass(frozen=True)
class Mount:
    """One NAS share visible to the container."""

    host_path: str  # e.g. /Volume1/RsyncTest  (what TOS calls it)
    container_path: str  # e.g. /nas/Volume1/RsyncTest
    read_only: bool

    @property
    def mode(self) -> str:
        return "ro" if self.read_only else "rw"


# --- path helpers -----------------------------------------------------------
def _norm(path: str) -> str:
    """Absolute, normalised, no trailing slash (except root)."""
    p = posixpath.normpath(path or "/")
    if not p.startswith("/"):
        p = "/" + p
    return p


def _within(path: str, root: str) -> bool:
    """True if ``path`` is ``root`` or sits underneath it.

    Compares whole segments, so ``/Volume1/RsyncTestOther`` is *not* inside
    ``/Volume1/RsyncTest``.
    """
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


def _unescape(field: str) -> str:
    for token, char in _UNESCAPE:
        field = field.replace(token, char)
    return field


def mount_root() -> str:
    return _norm(get_settings().mount_root)


def to_container_path(host_path: str, root: str | None = None) -> str:
    """Translate a NAS filesystem path to its path inside this container."""
    root = _norm(root) if root else mount_root()
    return _norm(root + _norm(host_path))


def to_host_path(container_path: str, root: str | None = None) -> str | None:
    """Inverse of :func:`to_container_path`; None if outside the mount root."""
    root = _norm(root) if root else mount_root()
    container_path = _norm(container_path)
    if not _within(container_path, root):
        return None
    return _norm(container_path[len(root.rstrip("/")):] or "/")


# --- discovery --------------------------------------------------------------
def list_mounts(mountinfo_path: str = MOUNTINFO, root: str | None = None) -> list[Mount]:
    """Every share currently bind-mounted under the mount root.

    Returns an empty list when there is no mountinfo to read (local development
    outside a container), so callers degrade to "no shares available" with a
    useful message rather than crashing.
    """
    root = _norm(root) if root else mount_root()
    try:
        with open(mountinfo_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    found: list[Mount] = []
    for line in lines:
        # Format: id parent major:minor root mountpoint options [optional...] - fstype ...
        # Only the fixed head matters; optional fields before the "-" vary in count.
        fields = line.split(" ")
        if len(fields) < 6:
            continue
        container_path = _norm(_unescape(fields[4]))
        options = fields[5].split(",")
        if not _within(container_path, root) or container_path == root:
            continue
        host_path = to_host_path(container_path, root)
        if host_path is None:
            continue
        found.append(
            Mount(
                host_path=host_path,
                container_path=container_path,
                read_only="ro" in options,
            )
        )
    # Longest container path first, so find() picks the most specific share when
    # one share is nested inside another.
    found.sort(key=lambda m: len(m.container_path), reverse=True)
    return found


def find(host_path: str, mounts: list[Mount] | None = None) -> Mount | None:
    """The mounted share containing ``host_path``, or None."""
    for mount in list_mounts() if mounts is None else mounts:
        if _within(host_path, mount.host_path):
            return mount
    return None


def compose_line(host_path: str, read_only: bool = False) -> str:
    """The exact docker-compose volume line that would expose ``host_path``."""
    host_path = _norm(host_path)
    suffix = ":ro" if read_only else ""
    return f"- {host_path}:{to_container_path(host_path)}{suffix}"


def resolve(host_path: str, *, write: bool, mounts: list[Mount] | None = None) -> str:
    """Container path for a NAS path, or raise with an actionable message.

    ``write=True`` additionally requires the share to be writable. Called before
    an rsync job runs so a missing share is reported up front by name, rather
    than surfacing later as a confusing rsync error.
    """
    host_path = _norm(host_path)
    available = list_mounts() if mounts is None else mounts
    mount = find(host_path, available)

    if mount is None:
        if available:
            current = ", ".join(f"{m.host_path} ({m.mode})" for m in available)
        else:
            current = "none - no NAS shares are bind-mounted into the container"
        raise MountNotAvailable(
            f"'{host_path}' is not available to rsync jobs. Add this line to the "
            f"backend service's volumes in docker-compose.prod.yml, then redeploy:\n"
            f"    {compose_line(host_path)}\n"
            f"Currently mounted: {current}."
        )

    if write and mount.read_only:
        raise MountReadOnly(
            f"'{host_path}' is inside the share {mount.host_path}, which is "
            f"mounted read-only. Remove the ':ro' suffix from its line in "
            f"docker-compose.prod.yml and redeploy to allow writes."
        )

    return to_container_path(host_path)


__all__ = [
    "Mount",
    "MountError",
    "MountNotAvailable",
    "MountReadOnly",
    "compose_line",
    "find",
    "list_mounts",
    "mount_root",
    "resolve",
    "to_container_path",
    "to_host_path",
]
