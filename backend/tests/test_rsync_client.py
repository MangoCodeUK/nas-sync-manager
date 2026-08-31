"""rsync capability probe tests.

The VERSION_LINES below are verbatim first lines of ``rsync --version`` captured
from all three rsync installations in this estate. They are here because the
original parser took "the token after 'version'", which silently returned None
for the protocol on every one of them - "version" appears twice per line, and
the token after "protocol" is "version", not the number.

That bug reached the NAS because the only assertion covering it was inside an
``if rsync_available:`` branch, and rsync is not installed on the dev box, so it
never ran. These tests parse fixed strings and therefore run everywhere.
"""
from __future__ import annotations

import pytest

from app.services import rsync_client

# (first line of `rsync --version`, expected release, expected protocol)
VERSION_LINES = [
    ("rsync  version 3.4.1  protocol version 32", "3.4.1", 32),  # backend container
    ("rsync  version 3.2.3  protocol version 31", "3.2.3", 31),  # new NAS host
    ("rsync  version 3.1.2  protocol version 31", "3.1.2", 31),  # old NAS
]


@pytest.mark.parametrize(("line", "version", "protocol"), VERSION_LINES)
def test_parses_real_version_lines(line, version, protocol):
    assert rsync_client.parse_version(line) == version
    assert rsync_client.parse_protocol(line) == protocol


def test_protocol_is_not_confused_by_the_release_number():
    # The failure mode that shipped: returning "version" (or the release) where
    # the protocol belongs. The protocol must be the number after
    # "protocol version", never the one after the first "version".
    line = "rsync  version 3.4.1  protocol version 32"
    assert rsync_client.parse_protocol(line) == 32
    assert rsync_client.parse_protocol(line) != 3


def test_parsing_survives_junk_without_raising():
    for junk in ("", "not rsync output", "rsync\n"):
        assert rsync_client.parse_version(junk) is None or isinstance(
            rsync_client.parse_version(junk), str
        )
        assert rsync_client.parse_protocol(junk) is None


def test_probe_reports_missing_rsync_instead_of_raising(monkeypatch):
    monkeypatch.setattr(rsync_client.shutil, "which", lambda _: None)
    capability = rsync_client.probe()
    assert capability.available is False
    assert "not installed" in capability.error


def test_probe_reports_a_broken_rsync_instead_of_raising(monkeypatch):
    def explode(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(rsync_client.shutil, "which", lambda _: "/usr/bin/rsync")
    monkeypatch.setattr(rsync_client.subprocess, "run", explode)
    capability = rsync_client.probe()
    assert capability.available is False
    assert "permission denied" in capability.error


def test_available_rsync_always_reports_version_and_protocol(monkeypatch):
    """Guards the invariant the endpoint test could only check conditionally."""

    class Result:
        returncode = 0
        stdout = "rsync  version 3.4.1  protocol version 32\nCopyright (C) 1996-2024\n"

    monkeypatch.setattr(rsync_client.shutil, "which", lambda _: "/usr/bin/rsync")
    monkeypatch.setattr(rsync_client.subprocess, "run", lambda *a, **k: Result())
    capability = rsync_client.probe()
    assert capability.available is True
    assert capability.version == "3.4.1"
    assert capability.protocol == 32
    assert capability.error is None
