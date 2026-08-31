"""rsync endpoint building, argv construction, and dry-run parsing.

None of these tests need rsync installed or a NAS reachable: argv is built as a
list and output is parsed from fixed strings. The DRY_RUN_OUTPUT fixture matches
the shape our own --out-format produces (%i|%l|%n) against the real test folders
- RsyncSourceTest holding Test1.txt/TestNEW.txt/FolderA/FolderB, and RsyncTest
additionally holding Test2.txt and Destination-Only.txt.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import providers, rsync_client
from app.services.mounts import Mount
from app.services.rsync_client import RsyncError

LOCAL_MOUNT = [Mount("/Volume1/RsyncTest", "/nas/Volume1/RsyncTest", False)]
READ_ONLY_MOUNT = [Mount("/Volume1/Films", "/nas/Volume1/Films", True)]


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


def job(**overrides):
    base = dict(
        job_type="copy",
        transport="rsync",
        conflict_strategy="overwrite_if_newer_or_size_differs",
        mirror_mode="safe",
        include_filters=None,
        exclude_filters=None,
        rsync_compress=False,
        rsync_bandwidth_kbps=None,
        source_path="/mnt/md0/RsyncSourceTest",
        destination_path="/Volume1/RsyncTest",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- endpoints --------------------------------------------------------------
def test_a_mounted_path_is_used_locally_even_when_rsync_is_configured():
    # A local path beats any network transport: it is faster, and rsync refuses a
    # transfer with two remote ends.
    conn = connection(name="NAS 5", fs_root="/Volume1", rsync_module="RsyncTest")
    endpoint = rsync_client.build_endpoint(
        conn, "/Volume1/RsyncTest", write=True, available=LOCAL_MOUNT
    )
    assert endpoint.is_local is True
    assert endpoint.spec == "/nas/Volume1/RsyncTest"


def test_daemon_endpoint_is_expressed_relative_to_the_module():
    endpoint = rsync_client.build_endpoint(
        connection(), "/mnt/md0/RsyncSourceTest/FolderA", write=False, available=[]
    )
    assert endpoint.is_local is False
    assert endpoint.spec == "nassync@192.168.50.189::RsyncSourceTest/FolderA"


def test_daemon_endpoint_at_the_module_root_has_no_subpath():
    endpoint = rsync_client.build_endpoint(
        connection(), "/mnt/md0/RsyncSourceTest", write=False, available=[]
    )
    assert endpoint.spec == "nassync@192.168.50.189::RsyncSourceTest"


def test_the_module_comes_from_the_path_so_several_can_be_used():
    # A device can publish more than one module, and which applies depends on
    # where the job points - not on one field set once on the connection.
    endpoint = rsync_client.build_endpoint(
        connection(), "/mnt/md0/public/Films", write=False, available=[]
    )
    assert endpoint.spec == "nassync@192.168.50.189::public/Films"


def test_a_path_outside_the_devices_filesystem_root_is_refused():
    with pytest.raises(RsyncError, match="not under"):
        rsync_client.build_endpoint(
            connection(), "/somewhere/else", write=False, available=[]
        )


def test_the_filesystem_root_itself_cannot_be_addressed():
    # A daemon exposes named modules, never the whole device.
    with pytest.raises(RsyncError, match="cannot address"):
        rsync_client.build_endpoint(connection(), "/mnt/md0", write=False, available=[])


def test_ssh_endpoint_uses_the_real_filesystem_path():
    endpoint = rsync_client.build_endpoint(
        connection(rsync_mode="ssh", rsync_username="Admin"),
        "/mnt/md0/RsyncSourceTest",
        write=False,
        available=[],
    )
    assert endpoint.spec == "Admin@192.168.50.189:/mnt/md0/RsyncSourceTest"
    assert endpoint.ssh_port == 9222


def test_unreachable_connection_explains_both_ways_to_fix_it():
    conn = connection(rsync_enabled=False, fs_root="/mnt/md0")
    with pytest.raises(RsyncError) as exc:
        rsync_client.build_endpoint(conn, "/mnt/md0/Films", write=False, available=[])
    assert "docker-compose" in str(exc.value)
    assert "rsync settings" in str(exc.value)


def test_read_only_share_works_as_a_source_but_not_a_destination():
    conn = connection(name="NAS 5", fs_root="/Volume1", rsync_enabled=False)
    assert rsync_client.build_endpoint(
        conn, "/Volume1/Films", write=False, available=READ_ONLY_MOUNT
    ).is_local
    with pytest.raises(Exception, match="read-only"):
        rsync_client.build_endpoint(conn, "/Volume1/Films", write=True, available=READ_ONLY_MOUNT)


# --- argv -------------------------------------------------------------------
def _argv(**job_overrides):
    source = rsync_client.build_endpoint(
        connection(), "/mnt/md0/RsyncSourceTest", write=False, available=[]
    )
    destination = rsync_client.build_endpoint(
        connection(name="NAS 5", fs_root="/Volume1"),
        "/Volume1/RsyncTest",
        write=True,
        available=LOCAL_MOUNT,
    )
    return rsync_client.build_argv(
        source=source, destination=destination, job=job(**job_overrides), dry_run=True
    )


def test_source_always_gets_a_trailing_slash():
    # The proven TerraMaster semantic: the CONTENTS of the source land in the
    # destination, never destination/source-name. Made explicit rather than left
    # to whether someone typed a slash.
    argv = _argv()
    assert argv[-2] == "nassync@192.168.50.189::RsyncSourceTest/"
    assert argv[-1] == "/nas/Volume1/RsyncTest/"


def test_argv_never_contains_a_credential():
    # The password goes via RSYNC_PASSWORD; argv is readable from /proc.
    argv = _argv()
    assert not any("secret" in a or ":" in a.split("@")[0] for a in argv if "@" in a)


def test_protect_args_is_always_set():
    # Shares here have spaces ("TV Shows"); without this the far end re-splits
    # the path and the transfer targets the wrong directory.
    assert "--protect-args" in _argv()


def test_delete_only_appears_for_a_strict_mirror():
    assert "--delete" not in _argv(job_type="copy")
    assert "--delete" not in _argv(job_type="mirror", mirror_mode="safe")
    assert "--delete" in _argv(job_type="mirror", mirror_mode="strict")


def test_dry_run_flag_is_present_for_previews():
    assert "--dry-run" in _argv()


@pytest.mark.parametrize(
    ("strategy", "flag"),
    [
        ("skip", "--ignore-existing"),
        ("overwrite_if_newer", "--update"),
        ("overwrite_if_size_differs", "--size-only"),
        ("always_overwrite", "--ignore-times"),
    ],
)
def test_conflict_strategies_map_onto_rsync_flags(strategy, flag):
    assert flag in _argv(conflict_strategy=strategy)


def test_default_conflict_strategy_adds_no_flag():
    # rsync's own quick check (size or mtime differs) already is this strategy.
    argv = _argv(conflict_strategy="overwrite_if_newer_or_size_differs")
    for flag in ("--ignore-existing", "--update", "--size-only", "--ignore-times"):
        assert flag not in argv


def test_excludes_and_includes_become_filters_in_the_right_order():
    argv = _argv(include_filters="*.mkv", exclude_filters="@Recycle/\n*.tmp")
    assert "--exclude=@Recycle/" in argv
    assert "--exclude=*.tmp" in argv
    # '--include=*/' must precede the allowlist or rsync prunes directories
    # before their contents can match.
    assert argv.index("--include=*/") < argv.index("--include=*.mkv")
    assert argv.index("--include=*.mkv") < argv.index("--exclude=*")


def test_compression_is_off_unless_asked_for():
    assert "-z" not in _argv()
    assert "-z" in _argv(rsync_compress=True)


def test_bandwidth_limit_is_passed_through():
    assert "--bwlimit=2000" in _argv(rsync_bandwidth_kbps=2000)


def test_two_remote_ends_are_refused_with_an_explanation():
    remote = rsync_client.build_endpoint(
        connection(), "/mnt/md0/RsyncSourceTest", write=False, available=[]
    )
    with pytest.raises(RsyncError, match="two remote devices"):
        rsync_client.build_argv(
            source=remote, destination=remote, job=job(), dry_run=True
        )


def test_redacted_command_strips_a_password_that_reached_argv_anyway():
    command = rsync_client.redacted_command(["rsync", "nassync:hunter2@host::Module/"])
    assert "hunter2" not in command
    assert "nassync@host::Module/" in command


# --- dry-run output ---------------------------------------------------------
DRY_RUN_OUTPUT = """\
cd+++++++++|0|FolderA
cd+++++++++|0|FolderB
>f+++++++++|11|Test1.txt
>f+++++++++|0|TestNEW.txt
>f.st......|2048|Existing.mkv
*deleting  |0|Destination-Only.txt
*deleting  |0|Test2.txt

Number of files: 8 (reg: 6, dir: 2)
Number of created files: 4 (reg: 2, dir: 2)
Total file size: 2,059 bytes
"""


def _plan():
    return rsync_client.parse_itemized(
        DRY_RUN_OUTPUT,
        source_root="/mnt/md0/RsyncSourceTest",
        dest_root="/Volume1/RsyncTest",
    )


def test_itemized_output_maps_onto_the_existing_plan_vocabulary():
    plan = _plan()
    assert plan.copy_count == 2  # Test1.txt, TestNEW.txt
    assert plan.update_count == 1  # Existing.mkv
    assert plan.mkdir_count == 2  # FolderA, FolderB
    assert plan.delete_count == 2  # Destination-Only.txt, Test2.txt


def test_sizes_and_paths_are_absolute_on_both_sides():
    copies = [i for i in _plan().items if i.action == "copy"]
    first = next(i for i in copies if i.source_path.endswith("Test1.txt"))
    assert first.source_path == "/mnt/md0/RsyncSourceTest/Test1.txt"
    assert first.destination_path == "/Volume1/RsyncTest/Test1.txt"
    assert first.size == 11


def test_transfer_bytes_counts_only_what_moves():
    # Deletions and folder creations are not transferred bytes.
    assert _plan().transfer_bytes == 11 + 0 + 2048


def test_update_reason_names_the_attributes_that_differ():
    update = next(i for i in _plan().items if i.action == "update")
    assert "size" in update.reason and "time" in update.reason


def test_unchanged_count_is_derived_from_stats_not_invented():
    plan = _plan()
    providers._annotate(plan, DRY_RUN_OUTPUT, job())
    # --stats reports 6 regular files; 3 of them change, so 3 are left alone.
    assert plan.unchanged == 3
    assert plan.skip_count == 3


def test_unchanged_stays_unknown_when_stats_are_absent():
    plan = rsync_client.parse_itemized(
        ">f+++++++++|10|a.txt\n", source_root="/s", dest_root="/d"
    )
    providers._annotate(plan, ">f+++++++++|10|a.txt\n", job())
    assert plan.unchanged is None  # not guessed at
    assert plan.skip_count == 0


def test_deletions_are_warned_about_loudly_and_first():
    plan = _plan()
    providers._annotate(plan, DRY_RUN_OUTPUT, job(job_type="mirror", mirror_mode="strict"))
    assert "DELETE 2 file(s)" in plan.warnings[0]


# --- provider dispatch ------------------------------------------------------
def test_transport_selects_the_provider_and_defaults_to_ftp():
    assert providers.get("rsync").name == "rsync"
    assert providers.get("ftp").name == "ftp"
    assert providers.get(None).name == "ftp"  # pre-rsync jobs
    with pytest.raises(ValueError):
        providers.get("carrier-pigeon")


def test_exit_codes_are_translated_into_something_readable():
    result = SimpleNamespace(returncode=5, stderr="@ERROR: auth failed on module")
    message = providers._explain(result)
    assert "username or password" in message
    result = SimpleNamespace(returncode=10, stderr="Connection refused")
    assert "Could not connect" in providers._explain(result)


# --- against genuinely real rsync output ------------------------------------
# Captured from rsync 3.2.3 on the NAS, mirroring /Volume1/RsyncTest into a
# scratch directory rigged to produce one of each outcome. Kept verbatim: the
# hand-written fixture above missed that rsync emits a "./" line for the
# transfer root and a trailing slash on directory names, and it was this real
# output that caught --contimeout being rejected outside daemon mode.
REAL_OUTPUT = """\
.d..t......|142|./
*deleting  |0|ScratchOnly.txt
>f.st......|11|Test1.txt
>f+++++++++|0|TestNEW.txt
cd+++++++++|0|FolderA/

Number of files: 18 (reg: 12, dir: 6)
Number of created files: 2 (reg: 1, dir: 1)
Number of deleted files: 1 (reg: 1)
Number of regular files transferred: 2
Total file size: 355 bytes
"""


def test_real_rsync_output_parses_to_the_expected_actions():
    plan = rsync_client.parse_itemized(
        REAL_OUTPUT, source_root="/Volume1/RsyncTest", dest_root="/tmp/dest"
    )
    assert (plan.copy_count, plan.update_count, plan.mkdir_count, plan.delete_count) == (1, 1, 1, 1)
    assert plan.transfer_bytes == 11


def test_the_transfer_root_line_is_not_mistaken_for_a_new_folder():
    # ".d..t......|142|./" means the destination root's mtime differs. Counting
    # it as a folder to create would inflate every preview by one.
    plan = rsync_client.parse_itemized(
        REAL_OUTPUT, source_root="/Volume1/RsyncTest", dest_root="/tmp/dest"
    )
    assert all(i.destination_path != "/tmp/dest/." for i in plan.items)
    assert plan.mkdir_count == 1  # FolderA only


def test_directory_names_lose_their_trailing_slash():
    plan = rsync_client.parse_itemized(
        REAL_OUTPUT, source_root="/Volume1/RsyncTest", dest_root="/tmp/dest"
    )
    folder = next(i for i in plan.items if i.action == "mkdir")
    assert folder.destination_path == "/tmp/dest/FolderA"


def test_contimeout_is_only_sent_to_a_daemon():
    """rsync 3.2.3 exits 1: "--contimeout ... may only be used when connecting
    to an rsync daemon". Caught by running the generated argv for real."""
    local = rsync_client.Endpoint(spec="/nas/Volume1/RsyncTest", is_local=True)
    daemon = rsync_client.build_endpoint(
        connection(), "/mnt/md0/RsyncSourceTest", write=False, available=[]
    )
    ssh = rsync_client.build_endpoint(
        connection(rsync_mode="ssh"), "/mnt/md0/RsyncSourceTest", write=False, available=[]
    )
    assert "--contimeout=30" not in rsync_client.build_argv(
        source=local, destination=local, job=job(), dry_run=True
    )
    assert "--contimeout=30" not in rsync_client.build_argv(
        source=ssh, destination=local, job=job(), dry_run=True
    )
    assert "--contimeout=30" in rsync_client.build_argv(
        source=daemon, destination=local, job=job(), dry_run=True
    )


# --- verification level must mean something, or not be offered --------------
def test_verification_levels_1_and_2_use_rsyncs_quick_check():
    for level in (1, 2):
        assert "--checksum" not in _argv(verification_level=level)


def test_verification_levels_3_and_4_add_a_real_checksum():
    # Previously the control was shown on rsync jobs and did nothing at all.
    for level in (3, 4):
        assert "--checksum" in _argv(verification_level=level)


def test_a_job_without_a_verification_level_still_builds():
    # Duck-typed preview configs may not carry every field.
    source = rsync_client.Endpoint(spec="/nas/a", is_local=True)
    bare = SimpleNamespace(
        job_type="copy",
        mirror_mode="safe",
        conflict_strategy="overwrite_if_newer_or_size_differs",
        include_filters=None,
        exclude_filters=None,
        rsync_compress=False,
        rsync_bandwidth_kbps=None,
    )
    assert "--checksum" not in rsync_client.build_argv(
        source=source, destination=source, job=bare, dry_run=True
    )


# --- live progress ----------------------------------------------------------
def test_progress_only_appears_on_real_runs():
    # A dry run transfers nothing, so progress output would be noise.
    assert "--info=progress2" not in _argv()
    source = rsync_client.Endpoint(spec="/nas/a", is_local=True)
    real = rsync_client.build_argv(
        source=source, destination=source, job=job(), dry_run=False
    )
    assert "--info=progress2" in real
    assert "--dry-run" not in real


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("     1,234,567  45%   12.34MB/s    0:00:05", (1234567, 45)),
        ("        32,768   1%    0.00kB/s    0:00:00", (32768, 1)),
        (">f+++++++++|11|Test1.txt", None),
        ("Number of files: 6 (reg: 5, dir: 1)", None),
        ("", None),
    ],
)
def test_progress_lines_are_recognised_without_false_positives(line, expected):
    assert rsync_client.parse_progress(line) == expected


def test_progress_output_is_split_on_carriage_returns():
    """--info=progress2 redraws one line with \r and emits no newline until it
    finishes, so line-based reading would withhold every update until the end."""
    import re as _re

    chunk = "  1,000  10%  1MB/s  0:00:01\r  2,000  20%  1MB/s  0:00:02\rdone\n"
    parts = [p for p in _re.split(r"[\r\n]", chunk) if p]
    assert len(parts) == 3
    assert rsync_client.parse_progress(parts[1]) == (2000, 20)
