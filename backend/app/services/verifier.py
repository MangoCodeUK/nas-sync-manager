"""Post-transfer verification (FR-007/008).

Files are streamed source -> destination with no local copy, so verification
compares against ``source_sha256`` (the digest computed from the source bytes as
they streamed) rather than re-hashing a local file.

Levels:
  1 Basic              - destination exists and size matches.
  2 Timestamp + Size   - size matches (timestamp preserved separately via MFMT).
  3 Checksum if avail. - compare a server-side SHA-256 of the destination to the
                         streamed source SHA-256; fall back to size if the server
                         has no SHA-256 command.
  4 Download and Hash  - re-download the destination and compare its SHA-256 to
                         the streamed source SHA-256.
"""
from __future__ import annotations

import ftplib
import hashlib

_BLOCKSIZE = 1024 * 1024


def verify(
    *,
    level: int,
    dest_ftp: ftplib.FTP,
    remote_path: str,
    expected_size: int,
    source_sha256: str | None = None,
) -> tuple[bool, str]:
    """Verify an uploaded file. Returns ``(ok, message)``.

    ``source_sha256`` is the digest of the source bytes computed while streaming
    (present for levels >= 3); there is no local copy of the file to re-hash.
    """
    try:
        actual_size = dest_ftp.size(remote_path)
    except ftplib.all_errors as exc:
        return False, f"verify: cannot stat destination ({exc})"

    if actual_size is None or actual_size != expected_size:
        return False, f"verify: size mismatch (expected {expected_size}, got {actual_size})"

    if level <= 2:
        return True, "verified: size"

    if level == 3:
        dest_digest = _server_sha256(dest_ftp, remote_path)
        if dest_digest is not None and source_sha256 is not None:
            ok = dest_digest.lower() == source_sha256.lower()
            return ok, f"verified: sha256 {'match' if ok else 'MISMATCH'}"
        return True, "verified: size (server checksum unavailable, level 3 fell back)"

    # Level 4: re-download the destination and compare SHA-256 with the source.
    if source_sha256 is None:
        return True, "verified: size (no source hash)"
    h = hashlib.sha256()
    try:
        dest_ftp.retrbinary(f"RETR {remote_path}", h.update, _BLOCKSIZE)
    except ftplib.all_errors as exc:
        return False, f"verify: cannot re-download destination ({exc})"
    ok = h.hexdigest() == source_sha256
    return ok, f"verified: sha256 {'match' if ok else 'MISMATCH'}"


def _server_sha256(ftp: ftplib.FTP, path: str) -> str | None:
    """Best-effort server-side SHA-256 (XSHA256). Returns the hexdigest or None."""
    try:
        resp = ftp.sendcmd(f"XSHA256 {path}")
    except ftplib.all_errors:
        return None
    return resp.strip().split()[-1]
