import datetime as dt

from app.services.ftp_client import FtpEntry
from app.services.planner import build_plan, is_filtered


def _f(size, mtime=None):
    return FtpEntry(name="x", type="file", size=size, modify=mtime)


def test_filters_exclude_extension_and_folder():
    assert is_filtered("a/b.tmp", [], ["*.tmp"]) is True
    assert is_filtered("@Recycle/x.jpg", [], ["@Recycle/"]) is True
    assert is_filtered("a/b.jpg", [], ["*.tmp"]) is False


def test_filters_include_allowlist():
    # Only *.jpg included.
    assert is_filtered("a/photo.jpg", ["*.jpg"], []) is False
    assert is_filtered("a/notes.txt", ["*.jpg"], []) is True


def test_plan_copy_new_and_skip_unchanged():
    src = {"a.txt": _f(10), "b.txt": _f(20)}
    dst = {"a.txt": _f(10)}  # same size -> unchanged
    plan = build_plan(
        job_type="copy",
        conflict_strategy="overwrite_if_newer_or_size_differs",
        mirror_mode="safe",
        include_filters=None,
        exclude_filters=None,
        source_files=src,
        source_dirs=[],
        dest_files=dst,
        dest_dirs=[],
        dest_root="/dst",
        source_root="/src",
    )
    assert plan.copy_count == 1   # b.txt
    assert plan.skip_count == 1   # a.txt unchanged
    assert plan.transfer_bytes == 20


def test_plan_update_on_size_difference():
    src = {"a.txt": _f(30)}
    dst = {"a.txt": _f(10)}
    plan = build_plan(
        job_type="copy",
        conflict_strategy="overwrite_if_size_differs",
        mirror_mode="safe",
        include_filters=None,
        exclude_filters=None,
        source_files=src,
        source_dirs=[],
        dest_files=dst,
        dest_dirs=[],
        dest_root="/dst",
        source_root="/src",
    )
    assert plan.update_count == 1


def test_safe_mirror_warns_but_does_not_delete_dest_only():
    src = {"a.txt": _f(10)}
    dst = {"a.txt": _f(10), "orphan.txt": _f(5)}
    plan = build_plan(
        job_type="mirror",
        conflict_strategy="overwrite_if_newer_or_size_differs",
        mirror_mode="safe",
        include_filters=None,
        exclude_filters=None,
        source_files=src,
        source_dirs=[],
        dest_files=dst,
        dest_dirs=[],
        dest_root="/dst",
        source_root="/src",
    )
    assert plan.delete_count == 0
    assert any("not present in source" in w for w in plan.warnings)


def test_strict_mirror_plans_deletes():
    src = {"a.txt": _f(10)}
    dst = {"a.txt": _f(10), "orphan.txt": _f(5)}
    plan = build_plan(
        job_type="mirror",
        conflict_strategy="always_overwrite",
        mirror_mode="strict",
        include_filters=None,
        exclude_filters=None,
        source_files=src,
        source_dirs=[],
        dest_files=dst,
        dest_dirs=[],
        dest_root="/dst",
        source_root="/src",
    )
    assert plan.delete_count == 1


def test_mkdir_for_missing_dest_dirs():
    plan = build_plan(
        job_type="copy",
        conflict_strategy="skip",
        mirror_mode="safe",
        include_filters=None,
        exclude_filters=None,
        source_files={},
        source_dirs=["Movies", "Movies/2024"],
        dest_files={},
        dest_dirs=[],
        dest_root="/dst",
        source_root="/src",
    )
    assert plan.mkdir_count == 2
