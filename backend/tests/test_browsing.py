"""Browsing a device in its rsync (filesystem) namespace.

LISTING is verbatim ``rsync --list-only`` output captured from the NAS, so the
parser is tested against the real column layout rather than an assumed one -
including the two cases that break naive splitting: names containing spaces, and
sizes rendered with thousands separators.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import browsing, mounts
from app.services.browsing import _LISTING_RE, Entry
from app.services.mounts import Mount

LISTING = """\
drwxrwxrwx            194 2026/08/31 21:41:58 .
-rw-rw----              0 2026/08/31 18:20:22 Destination-Only.txt
-rwxrwxrwx             11 2026/08/31 18:15:33 Test1.txt
drwxrwxrwx            138 2026/08/31 18:17:48 #recycle
drwxrwx---              0 2026/08/31 21:41:41 FolderC
-rw-r--r--              3 2026/08/31 21:51:58 a file.txt
drwxr-xr-x             40 2026/08/31 21:51:58 TV Shows
-rw-r--r--          1,234 2026/08/31 21:51:58 comma sized.mkv
"""


def connection(**overrides):
    base = dict(
        name="NAS 4.1 (8TB)",
        host="192.168.50.189",
        fs_root="/mnt/md0",
        rsync_enabled=True,
        rsync_mode="daemon",
        rsync_host=None,
        rsync_port=873,
        rsync_module="RsyncSourceTest",
        rsync_username="nassync",
        rsync_encrypted_password=None,
        rsync_ssh_port=9222,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- the listing parser -----------------------------------------------------
@pytest.mark.parametrize(
    ("line", "name", "is_dir"),
    [
        ("-rwxrwxrwx             11 2026/08/31 18:15:33 Test1.txt", "Test1.txt", False),
        ("drwxrwx---              0 2026/08/31 21:41:41 FolderC", "FolderC", True),
        ("drwxr-xr-x             40 2026/08/31 21:51:58 TV Shows", "TV Shows", True),
        ("-rw-r--r--              3 2026/08/31 21:51:58 a file.txt", "a file.txt", False),
        ("drwxrwxrwx            138 2026/08/31 18:17:48 #recycle", "#recycle", True),
    ],
)
def test_real_listing_lines_parse(line, name, is_dir):
    match = _LISTING_RE.match(line)
    assert match is not None
    assert match.group("name") == name
    assert match.group("perms").startswith("d") is is_dir


def test_a_size_with_thousands_separators_is_read():
    match = _LISTING_RE.match("-rw-r--r--          1,234 2026/08/31 21:51:58 comma sized.mkv")
    assert int(match.group("size").replace(",", "")) == 1234


def test_remote_listing_drops_the_directory_itself(monkeypatch):
    # rsync always lists "." first - the folder being listed. Including it would
    # show a phantom child in every folder.
    monkeypatch.setattr(
        browsing.rsync_client,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=LISTING, stderr="", argv=[]),
    )
    entries = browsing._browse_remote(
        browsing.Endpoint(spec="nassync@host::Module", is_local=False), None
    )
    assert "." not in [e.name for e in entries]
    assert len(entries) == 7


def test_listing_sorts_folders_before_files(monkeypatch):
    monkeypatch.setattr(
        browsing.rsync_client,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=LISTING, stderr="", argv=[]),
    )
    entries = browsing._browse_remote(
        browsing.Endpoint(spec="nassync@host::Module", is_local=False), None
    )
    kinds = [e.type for e in entries]
    assert kinds == sorted(kinds, key=lambda k: k != "dir")


def test_directories_report_no_size():
    # A directory's "size" from a listing is its inode size, which would be
    # meaningless - and misleading - shown as a folder's contents.
    entry = Entry("FolderA", True, 4096, None)
    assert entry.size is None


def test_a_refused_login_is_explained_rather_than_echoed(monkeypatch):
    monkeypatch.setattr(
        browsing.rsync_client,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=5, stdout="", stderr="@ERROR: auth failed on module", argv=[]
        ),
    )
    with pytest.raises(browsing.RsyncError, match="username, password and module"):
        browsing._browse_remote(
            browsing.Endpoint(spec="nassync@host::Module", is_local=False), None
        )


# --- local (bind-mounted) browsing ------------------------------------------
def test_a_mounted_folder_is_read_directly(tmp_path, monkeypatch):
    (tmp_path / "FolderA").mkdir()
    (tmp_path / "movie.mkv").write_text("x" * 40)
    entries = browsing._browse_local(str(tmp_path))
    assert [e.name for e in entries] == ["FolderA", "movie.mkv"]  # folders first
    assert entries[1].size == 40
    assert entries[1].modify is not None


def test_a_missing_local_folder_lists_empty_rather_than_erroring(tmp_path):
    # A destination that does not exist yet is normal, not a failure.
    assert browsing._browse_local(str(tmp_path / "not-there")) == []


# --- what the device root shows ---------------------------------------------
def test_the_root_of_a_mounted_device_lists_its_mounted_shares(monkeypatch):
    monkeypatch.setattr(
        mounts,
        "list_mounts",
        lambda *a, **k: [Mount("/Volume1/RsyncTest", "/nas/Volume1/RsyncTest", False)],
    )
    conn = connection(name="NAS 5", fs_root="/Volume1", rsync_enabled=False)
    path, entries = browsing.browse(conn, None)
    assert path == "/Volume1"
    # Only what a job could actually address, not the whole filesystem root.
    assert [e.name for e in entries] == ["RsyncTest"]
    assert entries[0].type == "dir"


def test_the_root_of_a_daemon_device_lists_its_published_modules(monkeypatch):
    monkeypatch.setattr(mounts, "list_mounts", lambda *a, **k: [])
    monkeypatch.setattr(
        browsing.rsync_client,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="RsyncSourceTest\tthe test share\nMedia\n",
            stderr="",
            argv=[],
        ),
    )
    path, entries = browsing.browse(connection(), None)
    assert path == "/mnt/md0"
    assert [e.name for e in entries] == ["Media", "RsyncSourceTest"]


def test_a_daemon_that_will_not_list_modules_yields_nothing_rather_than_erroring(monkeypatch):
    # Listing needs credentials whenever the daemon sets auth users, which both
    # devices do. Before a password is saved this must degrade quietly.
    monkeypatch.setattr(mounts, "list_mounts", lambda *a, **k: [])
    monkeypatch.setattr(
        browsing.rsync_client,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=5, stdout="", stderr="auth failed", argv=[]),
    )
    assert browsing._modules(connection(), None) == []


def test_an_unreachable_path_says_why(monkeypatch):
    monkeypatch.setattr(mounts, "list_mounts", lambda *a, **k: [])
    monkeypatch.setattr(mounts, "find", lambda *a, **k: None)
    conn = connection(name="NAS 5", fs_root="/Volume1", rsync_enabled=False)
    with pytest.raises(browsing.RsyncError, match="not bind-mounted"):
        browsing.browse(conn, "/Volume1/Films")
