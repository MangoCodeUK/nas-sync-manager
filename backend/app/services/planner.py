"""Transfer planner: compare source vs destination trees and decide actions.

Pure and side-effect free, so it powers both dry-run previews (Stage 4) and the
real transfer engine (Stage 5). Operates on already-walked tree indexes.
"""
from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass, field

from app.services.ftp_client import FtpEntry

# Action vocabulary used in plans and in job_run_items.
COPY = "copy"
UPDATE = "update"
SKIP = "skip"
MKDIR = "mkdir"
DELETE = "delete"
ARCHIVE = "archive"


@dataclass
class PlanItem:
    action: str
    source_path: str | None
    destination_path: str | None
    size: int = 0
    reason: str = ""


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Files deliberately left alone, when that number cannot be counted from
    # ``items``. The FTP planner walks both trees and emits a SKIP item per
    # unchanged file, so it leaves this None. rsync only reports what changes, so
    # its provider derives the figure from --stats instead of fabricating items.
    unchanged: int | None = None
    # The exact command this plan would issue, with credentials removed.
    # Only transports that shell out set it; the FTP planner leaves it None.
    command: str | None = None

    def _count(self, action: str) -> int:
        return sum(1 for i in self.items if i.action == action)

    @property
    def copy_count(self) -> int:
        return self._count(COPY)

    @property
    def update_count(self) -> int:
        return self._count(UPDATE)

    @property
    def skip_count(self) -> int:
        return self.unchanged if self.unchanged is not None else self._count(SKIP)

    @property
    def mkdir_count(self) -> int:
        return self._count(MKDIR)

    @property
    def delete_count(self) -> int:
        return self._count(DELETE)

    @property
    def archive_count(self) -> int:
        return self._count(ARCHIVE)

    @property
    def transfer_bytes(self) -> int:
        return sum(i.size for i in self.items if i.action in (COPY, UPDATE))


def parse_filters(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _matches(rel_path: str, pattern: str) -> bool:
    """Match a glob pattern against a relative path.

    Trailing-slash patterns (e.g. ``@Recycle/``) match any path segment. Patterns
    with a slash match the whole relative path; otherwise the basename.
    """
    name = posixpath.basename(rel_path)
    if pattern.endswith("/"):
        seg = pattern.rstrip("/")
        return seg in rel_path.split("/")
    if "/" in pattern:
        return fnmatch.fnmatch(rel_path, pattern)
    return fnmatch.fnmatch(name, pattern)


def is_filtered(rel_path: str, includes: list[str], excludes: list[str]) -> bool:
    """True if the file should be excluded from the transfer."""
    if any(_matches(rel_path, p) for p in excludes):
        return True
    if includes and not any(_matches(rel_path, p) for p in includes):
        return True
    return False


def _needs_update(strategy: str, src: FtpEntry, dst: FtpEntry) -> bool:
    if strategy == "skip":
        return False
    if strategy == "always_overwrite":
        return True
    newer = bool(src.modify and dst.modify and src.modify > dst.modify)
    size_differs = src.size is not None and dst.size is not None and src.size != dst.size
    if strategy == "overwrite_if_newer":
        return newer
    if strategy == "overwrite_if_size_differs":
        return size_differs
    if strategy == "overwrite_if_newer_or_size_differs":
        return newer or size_differs
    # rename / keep_both are handled by the caller (treated as new copies).
    return False


def build_plan(
    *,
    job_type: str,
    conflict_strategy: str,
    mirror_mode: str,
    include_filters: str | None,
    exclude_filters: str | None,
    source_files: dict[str, FtpEntry],
    source_dirs: list[str],
    dest_files: dict[str, FtpEntry],
    dest_dirs: list[str],
    dest_root: str,
    source_root: str,
) -> Plan:
    plan = Plan()
    includes = parse_filters(include_filters)
    excludes = parse_filters(exclude_filters)
    dest_dirset = set(dest_dirs)

    # Folders to create on the destination.
    for rel in sorted(source_dirs):
        if any(_matches(rel + "/", p) or _matches(rel, p) for p in excludes):
            continue
        if rel not in dest_dirset:
            plan.items.append(
                PlanItem(MKDIR, None, posixpath.join(dest_root, rel), reason="create folder")
            )

    # Files.
    for rel in sorted(source_files):
        src = source_files[rel]
        src_abs = posixpath.join(source_root, rel)
        dst_abs = posixpath.join(dest_root, rel)
        if is_filtered(rel, includes, excludes):
            plan.items.append(PlanItem(SKIP, src_abs, dst_abs, src.size or 0, "filtered"))
            continue
        if rel not in dest_files:
            plan.items.append(PlanItem(COPY, src_abs, dst_abs, src.size or 0, "new file"))
            continue
        dst = dest_files[rel]
        if conflict_strategy in ("rename", "keep_both"):
            renamed = _renamed(dst_abs)
            plan.items.append(PlanItem(COPY, src_abs, renamed, src.size or 0, "keep both"))
        elif _needs_update(conflict_strategy, src, dst):
            plan.items.append(PlanItem(UPDATE, src_abs, dst_abs, src.size or 0, "changed"))
        else:
            plan.items.append(PlanItem(SKIP, src_abs, dst_abs, src.size or 0, "unchanged"))

    # Destination-only files: warn, and for strict mirror, plan deletes.
    dest_only = [r for r in dest_files if r not in source_files and not is_filtered(r, includes, excludes)]
    if dest_only:
        if job_type == "mirror" and mirror_mode == "strict":
            for rel in sorted(dest_only):
                plan.items.append(
                    PlanItem(DELETE, None, posixpath.join(dest_root, rel), dest_files[rel].size or 0,
                             "destination-only (strict mirror)")
                )
            plan.warnings.append(
                f"Strict mirror will delete {len(dest_only)} destination-only file(s)."
            )
        else:
            plan.warnings.append(
                f"Destination has {len(dest_only)} file(s) not present in source (left untouched)."
            )

    # Move: source files will be queued for deletion after verification (Stage 7).
    if job_type == "move":
        movable = [r for r in source_files if not is_filtered(r, includes, excludes)]
        if movable:
            plan.warnings.append(
                f"Move job: {len(movable)} source file(s) will be queued for deletion "
                "after verification (manual approval required by default)."
            )

    return plan


def _renamed(path: str) -> str:
    base, ext = posixpath.splitext(path)
    return f"{base} (copy){ext}"
