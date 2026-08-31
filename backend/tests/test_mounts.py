"""Mount registry tests.

The MOUNTINFO fixture below is not invented - it is the real output measured
inside a container on the NAS, with unrelated lines kept so the filtering is
exercised against realistic noise. Note line 455: field 5 says ``ro`` while the
superblock options at the end of the same line say ``rw``. Reading the wrong one
would let a job write to a share the kernel has made read-only, so that
distinction is asserted explicitly.
"""
from __future__ import annotations

import pytest

from app.services import mounts
from app.services.mounts import Mount, MountNotAvailable, MountReadOnly

MOUNTINFO = """\
430 429 0:26 / / rw,relatime - overlay overlay rw,lowerdir=/x,upperdir=/y
431 430 0:29 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
440 430 0:27 /nassync_data /data rw,noatime - btrfs /dev/mapper/vg0-lv0 rw,subvol=/nassync_data
454 430 0:27 /RsyncTest /nas/Volume1/RsyncTest rw,noatime - btrfs /dev/mapper/vg0-lv0 rw,space_cache=v2,subvolid=727,subvol=/RsyncTest
455 430 0:27 /public /nas/Volume1/public ro,noatime - btrfs /dev/mapper/vg0-lv0 rw,space_cache=v2,subvolid=256,subvol=/public
"""


@pytest.fixture()
def mountinfo(tmp_path):
    path = tmp_path / "mountinfo"
    path.write_text(MOUNTINFO)
    return str(path)


def test_lists_only_shares_under_the_mount_root(mountinfo):
    found = mounts.list_mounts(mountinfo, root="/nas")
    assert {m.host_path for m in found} == {"/Volume1/RsyncTest", "/Volume1/public"}
    # /, /proc and the /data volume are not NAS shares and must not appear.


def test_read_only_comes_from_the_mount_options_not_the_superblock(mountinfo):
    by_path = {m.host_path: m for m in mounts.list_mounts(mountinfo, root="/nas")}
    assert by_path["/Volume1/RsyncTest"].read_only is False
    # The tail of this line says rw; the mount itself is ro. The kernel enforces
    # the mount, so that is the one that counts.
    assert by_path["/Volume1/public"].read_only is True


def test_container_paths_encode_the_host_path(mountinfo):
    by_path = {m.host_path: m for m in mounts.list_mounts(mountinfo, root="/nas")}
    assert by_path["/Volume1/RsyncTest"].container_path == "/nas/Volume1/RsyncTest"


def test_translation_round_trips():
    assert mounts.to_container_path("/Volume1/RsyncTest") == "/nas/Volume1/RsyncTest"
    assert mounts.to_host_path("/nas/Volume1/RsyncTest") == "/Volume1/RsyncTest"
    # Trailing slashes and doubled separators normalise away.
    assert mounts.to_container_path("/Volume1//RsyncTest/") == "/nas/Volume1/RsyncTest"
    # Outside the mount root there is no host path.
    assert mounts.to_host_path("/etc/passwd") is None


def test_missing_mountinfo_degrades_to_empty(tmp_path):
    # Local development outside a container: no crash, just nothing available.
    assert mounts.list_mounts(str(tmp_path / "absent"), root="/nas") == []


def test_paths_are_matched_by_whole_segments():
    share = [Mount("/Volume1/RsyncTest", "/nas/Volume1/RsyncTest", False)]
    assert mounts.find("/Volume1/RsyncTest", share) is not None
    assert mounts.find("/Volume1/RsyncTest/FolderA/x.mkv", share) is not None
    # A sibling share whose name merely starts the same must NOT match.
    assert mounts.find("/Volume1/RsyncTestOther", share) is None


def test_resolve_allows_a_destination_that_does_not_exist_yet():
    share = [Mount("/Volume1/RsyncTest", "/nas/Volume1/RsyncTest", False)]
    # rsync creates missing destination folders; resolution must not require them.
    resolved = mounts.resolve("/Volume1/RsyncTest/NewFolder", write=True, mounts=share)
    assert resolved == "/nas/Volume1/RsyncTest/NewFolder"


def test_unmounted_path_is_refused_with_the_line_needed_to_fix_it():
    share = [Mount("/Volume1/RsyncTest", "/nas/Volume1/RsyncTest", False)]
    with pytest.raises(MountNotAvailable) as exc:
        mounts.resolve("/Volume1/public/Films", write=False, mounts=share)
    message = str(exc.value)
    # The message must be actionable: the exact compose line, and what is mounted.
    assert "- /Volume1/public/Films:/nas/Volume1/public/Films" in message
    assert "/Volume1/RsyncTest (rw)" in message


def test_write_to_a_read_only_share_is_refused_but_reading_is_fine():
    share = [Mount("/Volume1/public", "/nas/Volume1/public", True)]
    assert mounts.resolve("/Volume1/public/a.mkv", write=False, mounts=share)
    with pytest.raises(MountReadOnly):
        mounts.resolve("/Volume1/public/a.mkv", write=True, mounts=share)


def test_escaped_spaces_in_share_names_are_decoded(tmp_path):
    path = tmp_path / "mountinfo"
    path.write_text(
        "500 430 0:27 /tv /nas/Volume1/public/TV\\040Shows rw,noatime - btrfs /dev/x rw\n"
    )
    found = mounts.list_mounts(str(path), root="/nas")
    assert found[0].host_path == "/Volume1/public/TV Shows"


def test_nested_shares_resolve_to_the_most_specific(tmp_path):
    path = tmp_path / "mountinfo"
    path.write_text(
        "501 430 0:27 /p /nas/Volume1/public rw,noatime - btrfs /dev/x rw\n"
        "502 430 0:27 /f /nas/Volume1/public/Films ro,noatime - btrfs /dev/x rw\n"
    )
    found = mounts.list_mounts(str(path), root="/nas")
    # A file under Films belongs to the Films share (read-only), not the parent.
    match = mounts.find("/Volume1/public/Films/a.mkv", found)
    assert match is not None and match.host_path == "/Volume1/public/Films"
    assert match.read_only is True


def test_compose_line_renders_both_modes():
    assert mounts.compose_line("/Volume1/X") == "- /Volume1/X:/nas/Volume1/X"
    assert mounts.compose_line("/Volume1/X", read_only=True) == "- /Volume1/X:/nas/Volume1/X:ro"


# --- environment endpoint ---------------------------------------------------
def test_environment_endpoint_reports_rsync_and_shares(client):
    body = client.get("/api/rsync/environment").json()
    assert body["mount_root"] == "/nas"
    assert isinstance(body["mounts"], list)
    # rsync is absent on the dev box and present in the image; either is valid,
    # but the pair must be self-consistent so the UI never shows "available" with
    # no version, or "unavailable" with no reason.
    if body["rsync_available"]:
        assert body["rsync_version"] and body["rsync_protocol"]
    else:
        assert body["rsync_error"]
