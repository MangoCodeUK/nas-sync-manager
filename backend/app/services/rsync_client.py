"""rsync execution service.

Currently holds the capability probe only; the argv builder, runner and output
parsing land here as the provider is built out. Kept separate from
``mounts.py`` because that module answers "where can we write?" while this one
answers "what can rsync do here?".
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

# rsync is well-behaved about --version, but a hung binary must not hang a page
# load, so every probe is bounded.
_PROBE_TIMEOUT = 5

# First line is "rsync  version 3.4.1  protocol version 32". Note "version"
# appears twice, so the release number cannot be read by simply taking the token
# after the first "version" without also mis-reading "protocol version" as the
# protocol number - which is exactly the bug these two patterns replaced.
_VERSION_RE = re.compile(r"\bversion\s+(\S+)")
_PROTOCOL_RE = re.compile(r"\bprotocol\s+version\s+(\d+)")


@dataclass(frozen=True)
class RsyncCapability:
    available: bool
    version: str | None = None  # e.g. "3.4.1"
    protocol: int | None = None  # daemon wire protocol, e.g. 31
    path: str | None = None
    error: str | None = None


def probe() -> RsyncCapability:
    """Report whether rsync is usable in this container, and which version.

    Never raises: a missing or broken rsync is a state the UI reports, not a
    crash. Protocol version matters because it - not the release number - decides
    whether two ends can talk (measured: this NAS ships 3.2.3 and the older one
    3.1.2, both protocol 31, so they interoperate).
    """
    path = shutil.which("rsync")
    if path is None:
        return RsyncCapability(
            available=False,
            error="rsync is not installed in the backend container image.",
        )

    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RsyncCapability(available=False, path=path, error=f"cannot run rsync ({exc})")

    if result.returncode != 0:
        return RsyncCapability(
            available=False,
            path=path,
            error=f"rsync --version exited {result.returncode}",
        )

    return RsyncCapability(
        available=True,
        version=parse_version(result.stdout),
        protocol=parse_protocol(result.stdout),
        path=path,
    )


def parse_version(output: str) -> str | None:
    """Release number from rsync --version output, e.g. "3.4.1"."""
    match = _VERSION_RE.search(_head(output))
    return match.group(1) if match else None


def parse_protocol(output: str) -> int | None:
    """Daemon wire protocol from rsync --version output, e.g. 32.

    This, not the release number, decides whether two ends can talk. Measured
    across the estate: the container ships 3.4.1/protocol 32, the new NAS
    3.2.3/protocol 31 and the old NAS 3.1.2/protocol 31. rsync negotiates down to
    the lower of the two, so the mismatch is fine - but it is worth surfacing.
    """
    match = _PROTOCOL_RE.search(_head(output))
    return int(match.group(1)) if match else None


def _head(output: str) -> str:
    return output.splitlines()[0] if output else ""


__all__ = ["RsyncCapability", "parse_protocol", "parse_version", "probe"]
