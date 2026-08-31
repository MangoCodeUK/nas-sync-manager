"""rsync execution service.

Currently holds the capability probe only; the argv builder, runner and output
parsing land here as the provider is built out. Kept separate from
``mounts.py`` because that module answers "where can we write?" while this one
answers "what can rsync do here?".
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

# rsync is well-behaved about --version, but a hung binary must not hang a page
# load, so every probe is bounded.
_PROBE_TIMEOUT = 5


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
        version=_first_match(result.stdout, "version"),
        protocol=_protocol(result.stdout),
        path=path,
    )


def _first_match(output: str, keyword: str) -> str | None:
    """Pull the token after ``keyword`` on the first line ("rsync  version 3.4.1  ...")."""
    head = output.splitlines()[0] if output else ""
    tokens = head.split()
    for i, token in enumerate(tokens):
        if token == keyword and i + 1 < len(tokens):
            return tokens[i + 1]
    return None


def _protocol(output: str) -> int | None:
    raw = _first_match(output, "protocol")
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


__all__ = ["RsyncCapability", "probe"]
