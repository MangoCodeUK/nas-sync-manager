"""Folder browsing over either transport.

The FTP browser walks an FTP-relative tree (``/public/Films``). rsync works in
the device's real filesystem namespace (``/Volume1/public/Films``,
``/mnt/md0/...``), so the same device browsed two ways shows two different path
vocabularies. That is not a bug to paper over - a job's paths must match its
transport - so the transport is chosen explicitly and the paths returned are
always the ones that transport actually uses.

Two ways to see an rsync device, picked automatically:

* **Bind-mounted** - read the directory directly. No network, no daemon, and
  fast enough that folder sizes stop needing to be an opt-in scan.
* **Remote** - ``rsync --list-only``, which returns a listing and transfers no
  file data.

What the *root* of a device shows differs from a plain filesystem listing, and
deliberately so: it lists what is actually reachable. For a mounted device that
is the set of bind-mounted shares; for a daemon it is the set of published
modules. Showing a full filesystem root would offer folders that no rsync job
could then address.
"""
from __future__ import annotations

import datetime as dt
import os
import re

from app.services import mounts, rsync_client
from app.services.rsync_client import Endpoint, RsyncError

# "drwxrwxrwx          4,096 2026/08/31 18:14:00 FolderA"
_LISTING_RE = re.compile(
    r"^(?P<perms>[-dlspcb][rwxstST-]{9})\s+"
    r"(?P<size>[\d,]+)\s+"
    r"(?P<date>\d{4}/\d{2}/\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<name>.+)$"
)


class Entry:
    """One row in a listing, in the shape the browse API already returns."""

    def __init__(self, name: str, is_dir: bool, size: int | None, modify: dt.datetime | None):
        self.name = name
        self.type = "dir" if is_dir else "file"
        self.size = None if is_dir else size
        self.modify = modify


def fs_root(conn) -> str:
    return mounts._norm(conn.fs_root or "/")


def browse(conn, path: str | None, password: str | None = None) -> tuple[str, list[Entry]]:
    """List one directory of a device in its rsync (filesystem) namespace.

    Returns ``(normalised path, entries)``.
    """
    root = fs_root(conn)
    target = mounts._norm(path) if path else root

    # At the device root, show what is actually reachable rather than the whole
    # filesystem - see the module docstring.
    if target == root:
        entries = _reachable_shares(conn, root, password)
        if entries:
            return target, entries

    mount = mounts.find(target)
    if mount is not None:
        return target, _browse_local(mounts.to_container_path(target))

    if not conn.rsync_enabled:
        raise RsyncError(
            f"'{target}' on {conn.name} cannot be browsed over rsync: it is not "
            f"bind-mounted into the container, and rsync is not configured for this "
            f"connection."
        )
    endpoint = rsync_client.build_endpoint(conn, target, write=False)
    return target, _browse_remote(endpoint, password)


def _reachable_shares(conn, root: str, password: str | None) -> list[Entry]:
    """The device root: mounted shares, or published rsync modules."""
    found = [
        Entry(m.host_path[len(root.rstrip("/")) + 1 :] or m.host_path, True, None, None)
        for m in mounts.list_mounts()
        if m.host_path != root and mounts._within(m.host_path, root)
    ]
    if found:
        return sorted(found, key=lambda e: e.name.lower())

    if conn.rsync_enabled and conn.rsync_mode == "daemon":
        return [Entry(name, True, None, None) for name in _modules(conn, password)]
    return []


def _modules(conn, password: str | None) -> list[str]:
    """Modules a daemon publishes. Empty if it will not say.

    Listing needs credentials whenever the daemon sets ``auth users``, which both
    of these devices do, so this quietly returns nothing rather than erroring
    when no password is stored yet.
    """
    host = (conn.rsync_host or conn.host).strip()
    user = (conn.rsync_username or "").strip()
    target = f"{user}@{host}::" if user else f"{host}::"
    try:
        result = rsync_client.run(["rsync", "--list-only", target], password=password, timeout=30)
    except RsyncError:
        return []
    if result.returncode != 0:
        return []
    names = []
    for line in result.stdout.splitlines():
        # "ModuleName<tab>optional comment"
        name = line.split("\t")[0].strip()
        if name and not name.startswith("@"):
            names.append(name)
    return sorted(names)


def _browse_local(container_path: str) -> list[Entry]:
    """Read a bind-mounted directory directly."""
    try:
        with os.scandir(container_path) as scan:
            rows = list(scan)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise RsyncError(f"Cannot read '{container_path}' ({exc}).") from exc

    entries: list[Entry] = []
    for row in rows:
        try:
            is_dir = row.is_dir()
            stat = row.stat()
            size, modified = stat.st_size, dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc)
        except OSError:
            is_dir, size, modified = False, None, None
        entries.append(Entry(row.name, is_dir, size, modified))
    return sorted(entries, key=lambda e: (e.type != "dir", e.name.lower()))


def _browse_remote(endpoint: Endpoint, password: str | None) -> list[Entry]:
    """List one level of a remote path with --list-only (no data transferred)."""
    argv = ["rsync", "--list-only", "--protect-args", endpoint.spec.rstrip("/") + "/"]
    if endpoint.ssh_port:
        argv[1:1] = ["-e", f"ssh -p {endpoint.ssh_port} -o BatchMode=yes"]
    result = rsync_client.run(argv, password=password, timeout=60)
    if result.returncode != 0:
        raise RsyncError(_listing_error(result))

    entries: list[Entry] = []
    for line in result.stdout.splitlines():
        match = _LISTING_RE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        if name in (".", "..", ""):
            continue  # the directory itself, which rsync always lists first
        is_dir = match.group("perms").startswith("d")
        try:
            size = int(match.group("size").replace(",", ""))
        except ValueError:
            size = None
        try:
            modified = dt.datetime.strptime(
                f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M:%S"
            ).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            modified = None
        entries.append(Entry(name, is_dir, size, modified))
    return sorted(entries, key=lambda e: (e.type != "dir", e.name.lower()))


def _listing_error(result) -> str:
    tail = (result.stderr or "").strip().splitlines()
    detail = tail[-1] if tail else ""
    if result.returncode == 5:
        return (
            "The rsync server refused the connection - check the username, password and "
            f"module name. ({detail})"
        )
    if result.returncode == 10:
        return f"Could not reach the rsync server. ({detail})"
    return f"rsync could not list that folder (exit {result.returncode}). {detail}".strip()


__all__ = ["Entry", "browse", "fs_root"]
