"""Deletion guards.

The point of the feature is that a destructive rsync through this app is safer
than the same rsync typed by hand. Each guard below can veto on its own, and the
most important one is the last: a source that reports zero files is treated as a
source that has gone away, never as an instruction to empty the destination.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import rsync_safety


def settings(**overrides):
    base = dict(
        require_manual_approval_for_deletes=False,
        max_auto_destination_deletes=50,
        max_auto_source_deletes=0,
        max_delete_percent=10,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def evaluate(**overrides):
    base = dict(
        deletions_planned=2,
        source_files=100,
        destination_files=100,
        settings_row=settings(),
        is_destructive=True,
    )
    base.update(overrides)
    return rsync_safety.evaluate(**base)


# --- the one that matters most ----------------------------------------------
def test_an_empty_source_never_authorises_deleting_the_destination():
    # The disconnected-share scenario: the source mount goes away, the container
    # sees an empty directory, and a strict mirror would faithfully "reflect"
    # that by wiping the destination. This must abort the whole run.
    report = evaluate(source_files=0, deletions_planned=500, destination_files=500)
    assert report.abort is True
    assert report.allow_deletes is False
    assert "unavailable" in report.veto_reason
    assert any("ABORTED" in c for c in report.checks)


def test_an_empty_source_with_nothing_to_delete_is_merely_noted():
    # Genuinely empty source, empty destination: nothing to do, but no danger.
    report = evaluate(source_files=0, deletions_planned=0, destination_files=0)
    assert report.abort is False
    assert any("0 files" in c for c in report.checks)


def test_a_copy_job_skips_deletion_checks_but_still_runs():
    report = evaluate(is_destructive=False, deletions_planned=0)
    assert report.abort is False
    assert any("cannot delete" in c for c in report.checks)


# --- the graded limits ------------------------------------------------------
def test_manual_approval_blocks_deletions_by_default():
    report = evaluate(settings_row=settings(require_manual_approval_for_deletes=True))
    assert report.allow_deletes is False
    assert report.abort is False  # the transfer may still proceed
    assert "manual approval" in report.veto_reason


def test_deletions_within_every_limit_are_approved():
    report = evaluate(deletions_planned=2, destination_files=100)
    assert report.allow_deletes is True
    assert any("APPROVED" in c for c in report.checks)


def test_the_absolute_limit_blocks_a_large_removal():
    report = evaluate(deletions_planned=80, settings_row=settings(max_auto_destination_deletes=50))
    assert report.allow_deletes is False
    assert "limit of 50" in report.veto_reason


def test_the_proportional_limit_catches_what_an_absolute_limit_waves_through():
    # 30 deletions is under an absolute limit of 50, but it is 60% of a small
    # destination - the signature of a mistyped path rather than a tidy-up.
    report = evaluate(
        deletions_planned=30,
        destination_files=50,
        settings_row=settings(max_auto_destination_deletes=50, max_delete_percent=10),
    )
    assert report.allow_deletes is False
    assert "60.0%" in report.veto_reason


def test_an_unknown_destination_size_disables_the_percentage_check_but_says_so():
    report = evaluate(destination_files=None, deletions_planned=2)
    assert report.allow_deletes is True
    assert any("could not be applied" in c for c in report.checks)


def test_no_deletions_needs_no_permission():
    report = evaluate(deletions_planned=0)
    assert report.allow_deletes is True


# --- the audit trail --------------------------------------------------------
def test_every_decision_is_written_down():
    # "What did it check before deleting?" must have an answer after the fact.
    report = evaluate(deletions_planned=2, destination_files=100)
    assert len(report.checks) >= 2
    assert report.notes  # persisted onto the run as safety_notes


@pytest.mark.parametrize("planned", [1, 5, 50])
def test_the_sanctioned_count_is_carried_forward_for_max_delete(planned):
    # Whatever the guards approve becomes rsync's own --max-delete ceiling, so a
    # destination that changed between preview and run cannot exceed it.
    report = evaluate(deletions_planned=planned, destination_files=1000)
    assert report.allow_deletes is True
    assert report.deletions_planned == planned


def test_a_vetoed_mirror_is_downgraded_to_safe_rather_than_abandoned():
    from app.services.providers import _without_deletes

    downgraded = _without_deletes(
        SimpleNamespace(
            job_type="mirror",
            mirror_mode="strict",
            conflict_strategy="always_overwrite",
            include_filters=None,
            exclude_filters=None,
            rsync_compress=False,
            rsync_bandwidth_kbps=None,
        )
    )
    assert downgraded.mirror_mode == "safe"
    assert downgraded.job_type == "mirror"
    assert downgraded.conflict_strategy == "always_overwrite"  # everything else intact


# --- the zero-vs-unknown distinction ----------------------------------------
# Captured from rsync 3.2.3 on the NAS. When there are no regular files, rsync
# omits the "reg:" group ENTIRELY rather than printing "reg: 0". Reading that as
# "unknown" instead of "zero" silently disarms the empty-source abort - the one
# check standing between an unavailable source and a wiped destination. It did
# exactly that until a real run against an empty directory exposed it.
STATS_EMPTY_SOURCE = "Number of files: 1 (dir: 1)"
STATS_HEALTHY_SOURCE = "Number of files: 6 (reg: 5, dir: 1)"


def test_zero_regular_files_reads_as_zero_not_unknown():
    from app.services import rsync_client

    assert rsync_client.parse_regular_file_count(STATS_EMPTY_SOURCE) == 0
    assert rsync_client.parse_regular_file_count(STATS_HEALTHY_SOURCE) == 5
    # No --stats at all is the genuinely-unknown case, and stays None.
    assert rsync_client.parse_regular_file_count(">f+++++++++|10|a.txt") is None


def test_the_reg_count_comes_from_the_right_stats_line():
    from app.services import rsync_client

    # "Number of created files" carries its own reg: group and must not be read
    # in place of the file-list count.
    stdout = "Number of files: 1 (dir: 1)\nNumber of created files: 9 (reg: 9)\n"
    assert rsync_client.parse_regular_file_count(stdout) == 0


def test_end_to_end_an_empty_source_aborts_a_strict_mirror():
    from app.services import rsync_client

    report = rsync_safety.evaluate(
        deletions_planned=5,  # rsync listed all five destination files for deletion
        source_files=rsync_client.parse_regular_file_count(STATS_EMPTY_SOURCE),
        destination_files=5,
        settings_row=settings(max_auto_destination_deletes=100, max_delete_percent=100),
        is_destructive=True,
    )
    assert report.abort is True
    assert report.allow_deletes is False


def test_end_to_end_a_healthy_source_still_permits_a_sanctioned_deletion():
    from app.services import rsync_client

    report = rsync_safety.evaluate(
        deletions_planned=1,
        source_files=rsync_client.parse_regular_file_count(STATS_HEALTHY_SOURCE),
        destination_files=6,
        settings_row=settings(max_auto_destination_deletes=100, max_delete_percent=100),
        is_destructive=True,
    )
    assert report.abort is False
    assert report.allow_deletes is True


def test_an_undeterminable_source_count_refuses_deletions():
    report = evaluate(source_files=None, deletions_planned=3)
    assert report.abort is False  # the transfer may proceed
    assert report.allow_deletes is False
    assert "could not be determined" in report.veto_reason


# --- the two guards must not disable each other -----------------------------
def test_a_small_destination_is_governed_by_the_count_not_the_percentage():
    """The real-world failure this fixes.

    A five-file folder with a 10% cap: every possible deletion is at least 20%,
    so the percentage forbade what the raised absolute limit was meant to allow.
    Raising the limit appeared to do nothing, and the run still said "success".
    """
    report = evaluate(
        deletions_planned=2,
        destination_files=5,
        settings_row=settings(max_auto_destination_deletes=5, max_delete_percent=10),
    )
    assert report.allow_deletes is True
    assert any("floor" in c for c in report.checks)


def test_the_percentage_still_applies_once_the_destination_is_large_enough():
    # Above the floor the proportional guard is meaningful again, and still bites.
    report = evaluate(
        deletions_planned=25,
        destination_files=100,
        settings_row=settings(max_auto_destination_deletes=1000, max_delete_percent=10),
    )
    assert report.allow_deletes is False
    assert "25.0%" in report.veto_reason


def test_the_absolute_limit_still_bites_below_the_floor():
    # Standing the percentage down must not leave a small folder unguarded.
    report = evaluate(
        deletions_planned=9,
        destination_files=10,
        settings_row=settings(max_auto_destination_deletes=5, max_delete_percent=100),
    )
    assert report.allow_deletes is False
    assert "limit of 5" in report.veto_reason


def test_excluded_files_do_not_inflate_the_destination_count():
    """#recycle held 8 of 13 files, making 2 deletions look like 15.4% not 40%."""
    from types import SimpleNamespace as NS

    from app.services import providers, rsync_client

    listing = [(f"#recycle/junk{i}.txt", 10) for i in range(8)] + [
        ("Test1.txt", 11),
        ("Test2.txt", 0),
        ("TestNEW.txt", 0),
        ("Destination-Only.txt", 0),
        ("Test3NASManager.txt", 0),
    ]
    original = rsync_client.list_files
    rsync_client.list_files = lambda *a, **k: listing
    try:
        job_with = NS(include_filters=None, exclude_filters="#recycle/")
        job_without = NS(include_filters=None, exclude_filters=None)
        assert providers._managed_file_count(None, None, job_with) == 5
        assert providers._managed_file_count(None, None, job_without) == 13
    finally:
        rsync_client.list_files = original
