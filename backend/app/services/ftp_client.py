"""FTP / FTPS client wrapper built on the stdlib ``ftplib``.

Supports plain FTP and FTPS (explicit TLS), passive mode, configurable port and
timeout. Used for connection testing (Stage 2), browsing (Stage 3) and the
transfer engine (Stage 5+).
"""
from __future__ import annotations

import datetime as dt
import ftplib
import io
import posixpath
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

WRITE_PROBE_NAME = ".nas_sync_write_test"


class FtpError(Exception):
    """Raised for connection/auth/transfer problems with a readable message."""


@dataclass
class FtpEntry:
    name: str
    type: str  # "dir" | "file"
    size: int | None = None
    modify: dt.datetime | None = None

    @property
    def is_dir(self) -> bool:
        return self.type == "dir"


@dataclass
class ConnectionTestResult:
    connectivity: bool = False
    authentication: bool = False
    can_list: bool = False
    can_write: bool | None = None
    can_delete: bool | None = None
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.connectivity and self.authentication and self.can_list

    def summary(self) -> str:
        if self.ok:
            bits = ["connected", "listed"]
            if self.can_write:
                bits.append("writable")
            if self.can_delete:
                bits.append("deletable")
            return "OK: " + ", ".join(bits)
        return "FAILED: " + "; ".join(self.messages or ["unknown error"])


@dataclass
class FtpClient:
    host: str
    port: int = 21
    username: str = "anonymous"
    password: str = ""
    protocol: str = "ftp"  # "ftp" | "ftps"
    passive_mode: bool = True
    timeout_seconds: int = 30
    root_path: str = "/"

    def _open(self) -> ftplib.FTP:
        try:
            if self.protocol == "ftps":
                ftp: ftplib.FTP = ftplib.FTP_TLS(timeout=self.timeout_seconds)
            else:
                ftp = ftplib.FTP(timeout=self.timeout_seconds)
            ftp.connect(self.host, self.port)
        except ftplib.all_errors as exc:  # all_errors already includes OSError
            raise FtpError(f"Cannot reach {self.host}:{self.port} ({exc})") from exc

        try:
            ftp.login(self.username, self.password)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.prot_p()  # encrypt the data channel too
        except ftplib.all_errors as exc:
            try:
                ftp.close()
            finally:
                raise FtpError(f"Login failed for '{self.username}' ({exc})") from exc

        ftp.set_pasv(self.passive_mode)
        return ftp

    def connect(self) -> ftplib.FTP:
        """Open and log in, returning a connection the caller is responsible for
        closing. Used by the transfer engine, which reconnects on demand."""
        return self._open()

    @contextmanager
    def connection(self) -> Iterator[ftplib.FTP]:
        ftp = self._open()
        try:
            yield ftp
        finally:
            try:
                ftp.quit()
            except ftplib.all_errors:
                try:
                    ftp.close()
                except ftplib.all_errors:
                    pass

    # --- listing -------------------------------------------------------------
    def list_dir(self, path: str | None = None) -> list[FtpEntry]:
        target = path or self.root_path
        with self.connection() as ftp:
            return self._list(ftp, target)

    @staticmethod
    def _list(ftp: ftplib.FTP, path: str) -> list[FtpEntry]:
        entries: list[FtpEntry] = []
        # Prefer MLSD (structured: type/size/modify). Fall back to NLST (names).
        try:
            for name, facts in ftp.mlsd(path):
                if name in (".", ".."):
                    continue
                ftype = facts.get("type", "")
                if ftype in ("cdir", "pdir"):
                    continue
                kind = "dir" if ftype in ("dir",) else "file"
                size = int(facts["size"]) if facts.get("size", "").isdigit() else None
                entries.append(FtpEntry(name=name, type=kind, size=size, modify=_parse_mdtm(facts.get("modify"))))
            return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
        except ftplib.all_errors:
            pass

        # NLST fallback: names only; probe each for dir-ness via CWD.
        try:
            names = ftp.nlst(path)
        except ftplib.all_errors as exc:
            raise FtpError(f"Cannot list '{path}' ({exc})") from exc
        for full in names:
            name = posixpath.basename(full.rstrip("/")) or full
            if name in (".", ".."):
                continue
            kind = "file"
            try:
                ftp.cwd(posixpath.join(path, name))
                kind = "dir"
                ftp.cwd(path)
            except ftplib.all_errors:
                kind = "file"
            entries.append(FtpEntry(name=name, type=kind))
        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))

    def walk_tree(self, root: str | None = None) -> tuple[dict[str, "FtpEntry"], list[str]]:
        """Recursively index a tree under ``root``.

        Returns ``(files, dirs)`` keyed/listed by path relative to ``root`` (POSIX,
        no leading slash). A missing ``root`` yields empty results (so a not-yet-
        created destination plans cleanly). File sizes are filled via SIZE when the
        listing omits them.
        """
        base = root or self.root_path
        files: dict[str, FtpEntry] = {}
        dirs: list[str] = []
        with self.connection() as ftp:
            stack: list[tuple[str, str]] = [("", base)]
            while stack:
                rel, absdir = stack.pop()
                try:
                    entries = self._list(ftp, absdir)
                except FtpError:
                    continue
                for entry in entries:
                    child_rel = f"{rel}/{entry.name}" if rel else entry.name
                    child_abs = posixpath.join(absdir, entry.name)
                    if entry.is_dir:
                        dirs.append(child_rel)
                        stack.append((child_rel, child_abs))
                    else:
                        if entry.size is None:
                            try:
                                entry.size = ftp.size(child_abs) or 0
                            except ftplib.all_errors:
                                entry.size = 0
                        files[child_rel] = entry
        return files, dirs

    def walk_size(self, path: str | None = None) -> tuple[int, int, int]:
        """Recursively total bytes / file count / folder count under ``path``.

        Opt-in (FR-005): recursive FTP scans can be slow on large trees.
        """
        target = path or self.root_path
        total = 0
        files = 0
        folders = 0
        with self.connection() as ftp:
            stack = [target]
            while stack:
                current = stack.pop()
                try:
                    entries = self._list(ftp, current)
                except FtpError:
                    continue
                for entry in entries:
                    child = posixpath.join(current, entry.name)
                    if entry.is_dir:
                        folders += 1
                        stack.append(child)
                    else:
                        files += 1
                        size = entry.size
                        if size is None:
                            try:
                                size = ftp.size(child) or 0
                            except ftplib.all_errors:
                                size = 0
                        total += size
        return total, files, folders

    # --- connection test (FR-002) -------------------------------------------
    def test_connection(self) -> ConnectionTestResult:
        result = ConnectionTestResult()
        try:
            ftp = self._open()
        except FtpError as exc:
            result.messages.append(str(exc))
            # Distinguish reachability from auth where we can.
            if "Login failed" in str(exc):
                result.connectivity = True
            return result

        result.connectivity = True
        result.authentication = True
        try:
            try:
                self._list(ftp, self.root_path)
                result.can_list = True
            except FtpError as exc:
                result.messages.append(str(exc))

            if result.can_list:
                probe = posixpath.join(self.root_path, WRITE_PROBE_NAME)
                try:
                    ftp.storbinary(f"STOR {probe}", io.BytesIO(b"nas-sync write test"))
                    result.can_write = True
                except ftplib.all_errors:
                    result.can_write = False
                    result.messages.append("No write access to root path")
                if result.can_write:
                    try:
                        ftp.delete(probe)
                        result.can_delete = True
                    except ftplib.all_errors:
                        result.can_delete = False
                        result.messages.append("Wrote test file but could not delete it")
        finally:
            try:
                ftp.quit()
            except ftplib.all_errors:
                try:
                    ftp.close()
                except ftplib.all_errors:
                    pass
        return result


def _parse_mdtm(value: str | None) -> dt.datetime | None:
    """Parse an MLSD/MDTM timestamp like '20240131235959(.fff)'."""
    if not value:
        return None
    value = value.split(".")[0]
    try:
        return dt.datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
