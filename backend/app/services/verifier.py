"""Post-transfer verification (FR-007/008).

Levels:
  1 Basic              - destination exists and size matches.
  2 Timestamp + Size   - size matches (timestamp preserved separately via MFMT).
  3 Checksum if avail. - try a server-side hash; fall back to Level 2.
  4 Download and Hash  - SHA-256 of the source bytes vs the re-downloaded file.
"""
from __future__ import annotations

import ftplib
import hashlib
import io

_HASH_COMMANDS = ("XSHA256", "XSHA1", "XMD5")


def verify(
    *,
    level: int,
    dest_ftp: ftplib.FTP,
    remote_path: str,
    expected_size: int,
    local_source_path: str | None = None,
) -> tuple[bool, str]:
    """Verify an uploaded file. Returns ``(ok, message)``."""
    try:
        actual_size = dest_ftp.size(remote_path)
    except ftplib.all_errors as exc:
        return False, f"verify: cannot stat destination ({exc})"

    if actual_size is None or actual_size != expected_size:
        return False, f"verify: size mismatch (expected {expected_size}, got {actual_size})"

    if level <= 2:
        return True, "verified: size"

    if level == 3:
        digest = _server_hash(dest_ftp, remote_path)
        if digest is not None and local_source_path is not None:
            local = _file_hash(local_source_path, digest[0])
            if local is not None:
                ok = local.lower() == digest[1].lower()
                return ok, f"verified: {digest[0]} {'match' if ok else 'MISMATCH'}"
        return True, "verified: size (checksum unsupported, level 3 fell back)"

    # Level 4: download the destination and compare SHA-256 with the source bytes.
    if local_source_path is None:
        return True, "verified: size (no source copy for hashing)"
    buf = io.BytesIO()
    try:
        dest_ftp.retrbinary(f"RETR {remote_path}", buf.write)
    except ftplib.all_errors as exc:
        return False, f"verify: cannot re-download destination ({exc})"
    dest_digest = hashlib.sha256(buf.getvalue()).hexdigest()
    src_digest = _file_hash(local_source_path, "sha256")
    ok = src_digest == dest_digest
    return ok, f"verified: sha256 {'match' if ok else 'MISMATCH'}"


def _server_hash(ftp: ftplib.FTP, path: str) -> tuple[str, str] | None:
    """Best-effort server-side hash. Returns (algorithm, hexdigest) or None."""
    for cmd in _HASH_COMMANDS:
        try:
            resp = ftp.sendcmd(f"{cmd} {path}")
            token = resp.strip().split()[-1]
            algo = {"XSHA256": "sha256", "XSHA1": "sha1", "XMD5": "md5"}[cmd]
            return algo, token
        except ftplib.all_errors:
            continue
    return None


def _file_hash(path: str, algo: str) -> str | None:
    try:
        h = hashlib.new(algo)
    except (ValueError, TypeError):
        return None
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
