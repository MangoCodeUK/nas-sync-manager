"""Deletion guards for destructive rsync operations.

The premise of this whole feature is that NAS Sync Manager should make a
destructive rsync *safer* than running rsync by hand. Running it by hand, a
mistyped path or an unmounted source silently becomes "delete everything". These
guards exist so that cannot happen here.

Four independent checks, each able to veto on its own:

1. Manual approval      - on by default; nothing is auto-deleted at all.
2. Absolute limit       - never remove more than N files in one run.
3. Proportional limit   - never remove more than X% of the destination, which
                          catches the mistyped-path case that an absolute limit
                          sized for a big share would wave through.
4. Source plausibility  - a source reporting zero files while the destination
                          holds many means the source is probably gone, not that
                          you asked to empty the destination.

Every decision is recorded in ``SafetyReport.checks`` and written to the run, so
"what did it check before deleting?" has an answer after the fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Below this many destination files a percentage says nothing useful - on a
# five-file folder one deletion is 20% - so the proportional cap stands down
# and the absolute limit governs. Without this, the two guards conflict: a 10%
# cap forbids every deletion on a small folder however high the count limit is.
PERCENT_FLOOR = 20


@dataclass
class SafetyReport:
    """The verdict on whether a run may delete, and why."""

    deletions_planned: int = 0
    destination_files: int | None = None
    source_files: int | None = None
    allow_deletes: bool = False
    veto_reason: str | None = None
    abort: bool = False  # stop the whole run, not merely the deletions
    checks: list[str] = field(default_factory=list)

    @property
    def notes(self) -> str:
        return "\n".join(self.checks)


def evaluate(
    *,
    deletions_planned: int,
    source_files: int | None,
    destination_files: int | None,
    settings_row,
    is_destructive: bool,
) -> SafetyReport:
    """Decide whether a run may proceed, and whether it may delete.

    ``is_destructive`` is True only for a strict mirror - the one operation that
    removes destination files. A copy cannot delete anything, so it skips the
    deletion checks entirely but still gets the source plausibility check, since
    an empty source is worth reporting either way.
    """
    report = SafetyReport(
        deletions_planned=deletions_planned,
        destination_files=destination_files,
        source_files=source_files,
    )

    # --- 4. source plausibility, checked first: it can veto everything -------
    # The scenario this exists for: the source share becomes unavailable and the
    # container sees an empty directory rather than an error. Without this, a
    # strict mirror would faithfully "reflect" an empty source by wiping the
    # destination.
    if source_files == 0 and deletions_planned > 0:
        report.checks.append(
            f"ABORTED: source reported 0 files while {deletions_planned} destination "
            f"file(s) would be deleted. A source that has become unavailable must never "
            f"be read as an instruction to empty the destination."
        )
        report.abort = True
        report.veto_reason = (
            "The source appears to be empty, but the destination is not. This usually "
            "means the source share is unavailable rather than genuinely empty, so the "
            "run was stopped before anything was deleted."
        )
        return report

    if source_files is None and deletions_planned > 0:
        # Defence in depth. If we cannot establish how many files the source
        # holds, we cannot rule out the scenario above, so deletions are refused
        # rather than taken on trust.
        report.checks.append(
            "BLOCKED: the source file count could not be determined, so deletions "
            "were refused rather than assumed safe."
        )
        report.veto_reason = (
            "The number of files on the source could not be determined, so no files were "
            "deleted from the destination. The transfer itself still ran."
        )
        return report

    if source_files == 0:
        report.checks.append("Source reported 0 files; nothing to transfer.")

    if not is_destructive:
        report.checks.append("Operation cannot delete destination files; no deletion checks needed.")
        return report

    if deletions_planned == 0:
        report.checks.append("No destination files would be deleted.")
        report.allow_deletes = True
        return report

    # --- 1. manual approval --------------------------------------------------
    if settings_row.require_manual_approval_for_deletes:
        report.checks.append(
            f"BLOCKED: {deletions_planned} deletion(s) require manual approval "
            f"(Settings: require manual approval for deletes)."
        )
        report.veto_reason = (
            f"This job would delete {deletions_planned} file(s) from the destination, but "
            f"deletions require manual approval. The transfer can still run without "
            f"deleting anything - turn off manual approval in Settings to allow it."
        )
        return report

    # --- 2. absolute limit ---------------------------------------------------
    limit = settings_row.max_auto_destination_deletes
    if deletions_planned > limit:
        report.checks.append(
            f"BLOCKED: {deletions_planned} deletion(s) exceeds the limit of {limit}."
        )
        report.veto_reason = (
            f"This job would delete {deletions_planned} file(s), above the configured "
            f"limit of {limit}. Raise the limit in Settings if that is genuinely intended."
        )
        return report
    report.checks.append(f"Deletion count {deletions_planned} is within the limit of {limit}.")

    # --- 3. proportional limit ----------------------------------------------
    percent_cap = getattr(settings_row, "max_delete_percent", 100) or 100
    if destination_files and destination_files < PERCENT_FLOOR:
        # A percentage is meaningless on a small folder: with five files, any
        # single deletion is 20%, so a 10% cap would forbid every deletion no
        # matter how high the absolute limit was set - one guard silently
        # disabling the other. Below the floor the absolute limit governs, which
        # is the guard that actually says something useful at this size.
        report.checks.append(
            f"Destination holds {destination_files} file(s), below the {PERCENT_FLOOR}-file "
            f"floor where a percentage is meaningful; the {percent_cap}% cap was not "
            f"applied and the limit of {limit} governs."
        )
    elif destination_files:
        percent = deletions_planned * 100 / destination_files
        if percent > percent_cap:
            report.checks.append(
                f"BLOCKED: deletions are {percent:.1f}% of the destination "
                f"({deletions_planned} of {destination_files}), above the {percent_cap}% cap."
            )
            report.veto_reason = (
                f"This job would delete {percent:.1f}% of the destination "
                f"({deletions_planned} of {destination_files} files), above the "
                f"{percent_cap}% safety cap. That much removal usually means a wrong path "
                f"rather than an intended clean-up."
            )
            return report
        report.checks.append(
            f"Deletions are {percent:.1f}% of the destination "
            f"({deletions_planned} of {destination_files}), within the {percent_cap}% cap."
        )
    else:
        report.checks.append(
            "Destination file count unknown; proportional cap could not be applied."
        )

    report.allow_deletes = True
    report.checks.append(f"APPROVED: {deletions_planned} deletion(s) permitted.")
    return report


__all__ = ["PERCENT_FLOOR", "SafetyReport", "evaluate"]
