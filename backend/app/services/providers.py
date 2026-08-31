"""Transfer providers: one interface, two transports.

A job has two independent axes - the OPERATION (copy / mirror / move, which
already existed) and the TRANSPORT (how bytes actually move). This module is the
seam between them, so adding SFTP or SMB later means adding a class here rather
than touching the job model, the scheduler, the planner or the UI.

Deliberately narrow. The FTP provider delegates wholesale to the existing
transfer engine: no FTP behaviour moves, so the code that survived months of
real transfers against a temperamental SmbFTPD keeps running exactly as it did.
"""
from __future__ import annotations

from typing import Protocol

from app.services.planner import Plan
from app.services.rsync_client import RsyncError

# rsync exit codes worth translating. rsync's own wording ("error in socket IO")
# does not tell you which of the plausible causes you actually hit.
_EXIT_CODES = {
    1: "rsync rejected the command line (internal error - please report this).",
    2: "The two rsync versions are incompatible.",
    5: (
        "The rsync server refused the connection - usually a wrong username or password, "
        "or a module name that does not exist on that device."
    ),
    10: (
        "Could not connect to the rsync server. Check the device is on, that its rsync "
        "service is enabled, and that the port is right."
    ),
    12: "The connection to the rsync server broke mid-conversation.",
    13: "rsync could not read the requested files (permission denied on the far end).",
    23: "Some files could not be transferred (permissions, or they vanished mid-run).",
    24: "Some files vanished during the run - usually harmless.",
    30: "The transfer timed out.",
    35: "Timed out waiting for the rsync server to respond.",
}


class TransferProvider(Protocol):
    """What every transport must be able to do."""

    name: str

    def plan(self, db, job) -> Plan:
        """Work out what a run would do, changing nothing."""

    def execute(self, db, run, job) -> None:
        """Actually move the data, recording progress on ``run``."""


class FtpProvider:
    """The original transport. Delegates entirely to the existing engine."""

    name = "ftp"

    def plan(self, db, job) -> Plan:
        # Imported here rather than at module scope: jobs_runner and
        # transfer_engine import each other's neighbours, and a top-level import
        # would close the cycle.
        from app.services import jobs_runner

        return jobs_runner.plan_for_job(db, job)

    def execute(self, db, run, job) -> None:
        from app.services import transfer_engine

        transfer_engine._do_work(db, run, job)


class RsyncProvider:
    """rsync over the daemon protocol or SSH, with one end bind-mounted."""

    name = "rsync"

    def plan(self, db, job) -> Plan:
        from app.services import rsync_client

        source_conn, dest_conn = _connections(db, job)
        available = _available_mounts()

        # The source is only ever read; the destination is written to. Passing
        # that through means a read-only share is refused for a destination but
        # remains perfectly usable as a source.
        source = rsync_client.build_endpoint(
            source_conn, job.source_path, write=False, available=available
        )
        destination = rsync_client.build_endpoint(
            dest_conn, job.destination_path, write=True, available=available
        )

        argv = rsync_client.build_argv(
            source=source, destination=destination, job=job, dry_run=True
        )
        result = rsync_client.run(
            argv,
            password=_password(source, destination, source_conn, dest_conn),
            timeout=600,
        )
        if result.returncode != 0:
            raise RsyncError(_explain(result))

        plan = rsync_client.parse_itemized(
            result.stdout,
            source_root=job.source_path,
            dest_root=job.destination_path,
        )
        plan.command = rsync_client.redacted_command(argv)
        _annotate(plan, result.stdout, job)
        return plan

    def execute(self, db, run, job) -> None:
        """Run for real, but only after a dry-run has proved it is safe to.

        The order matters and is the whole point of the feature: every run
        rehearses itself first, the guards judge the rehearsal, and only then
        does anything actually move or get deleted.
        """
        from app.models import utcnow
        from app.services import rsync_client, rsync_safety, settings_service, transfer_engine

        settings_row = settings_service.get_settings_row(db)
        source_conn, dest_conn = _connections(db, job)
        available = _available_mounts()

        source = rsync_client.build_endpoint(
            source_conn, job.source_path, write=False, available=available
        )
        destination = rsync_client.build_endpoint(
            dest_conn, job.destination_path, write=True, available=available
        )
        password = _password(source, destination, source_conn, dest_conn)
        is_destructive = job.job_type == "mirror" and job.mirror_mode == "strict"

        run.transport = "rsync"
        db.commit()

        # --- 1. rehearse --------------------------------------------------
        rehearsal = rsync_client.run(
            rsync_client.build_argv(
                source=source, destination=destination, job=job, dry_run=True
            ),
            password=password,
            timeout=1800,
        )
        if rehearsal.returncode != 0:
            raise RsyncError(_explain(rehearsal))

        planned = rsync_client.parse_itemized(
            rehearsal.stdout,
            source_root=job.source_path,
            dest_root=job.destination_path,
        )

        # --- 2. judge the rehearsal ---------------------------------------
        report = rsync_safety.evaluate(
            deletions_planned=planned.delete_count,
            source_files=rsync_client.parse_regular_file_count(rehearsal.stdout),
            destination_files=(
                _managed_file_count(destination, password, job) if is_destructive else None
            ),
            settings_row=settings_row,
            is_destructive=is_destructive,
        )
        run.safety_notes = report.notes
        db.commit()

        if report.abort:
            run.status = "failed"
            run.error_message = report.veto_reason
            run.completed_at = utcnow()
            db.commit()
            raise RsyncError(report.veto_reason or "Aborted by a safety check.")

        if report.veto_reason:
            # The transfer is still worth doing; only the deletions are refused.
            planned.warnings.insert(0, report.veto_reason)

        # --- 3. run it ----------------------------------------------------
        run.files_total = planned.copy_count + planned.update_count
        run.bytes_total = planned.transfer_bytes
        db.commit()

        argv = rsync_client.build_argv(
            source=source,
            destination=destination,
            job=_without_deletes(job) if not report.allow_deletes else job,
            dry_run=False,
            max_delete=report.deletions_planned if report.allow_deletes else None,
        )

        progress = _Progress(db, run)
        try:
            result = rsync_client.run_streaming(
                argv,
                password=password,
                on_line=progress.saw,
                should_cancel=lambda: transfer_engine.is_cancelled(job.id),
            )
        except rsync_client.Cancelled:
            run.status = "cancelled"
            run.summary = "Cancelled part-way through."
            run.completed_at = utcnow()
            db.commit()
            return

        run.exit_code = result.returncode
        actual = rsync_client.parse_itemized(
            result.stdout, source_root=job.source_path, dest_root=job.destination_path
        )
        _record_items(db, run, actual)

        run.files_copied = actual.copy_count
        run.files_updated = actual.update_count
        run.files_deleted = actual.delete_count
        run.files_skipped = planned.skip_count
        run.files_scanned = actual.copy_count + actual.update_count + planned.skip_count
        run.bytes_transferred = actual.transfer_bytes
        run.current_item = None

        if result.returncode != 0:
            run.status = "failed"
            run.error_message = _explain(result)
        elif report.veto_reason:
            # The transfer worked, but the job did not do everything it was asked
            # to. Reporting that as plain "success" with a quiet 0-deleted count
            # is how a refused deletion looks like a broken feature: the reason
            # was recorded but never shown. It is an outcome, so it is surfaced
            # like one.
            run.status = "partial"
            run.error_message = report.veto_reason
        else:
            run.status = "success"

        # --- 4. move: only ever after a clean, verified run ----------------
        if job.job_type == "move" and result.returncode == 0:
            self._queue_source_deletions(db, run, job, source, destination, password)

        run.summary = (
            f"rsync ({job.job_type}): {run.files_copied} copied, {run.files_updated} updated, "
            f"{run.files_deleted} deleted, {run.files_skipped} unchanged"
            + (
                f" - {report.deletions_planned} deletion(s) refused by a safety check"
                if report.veto_reason and report.deletions_planned
                else ""
            )
        )
        run.completed_at = utcnow()
        db.commit()

    def _queue_source_deletions(self, db, run, job, source, destination, password) -> None:
        """Queue source files for deletion, but only once proved redundant.

        A second dry-run is the verification: if it reports nothing left to copy
        or update, then every source file is present and identical at the
        destination. Anything less than that and the source is left completely
        alone - a move must never delete on a partial success.
        """
        from app.models import PendingDeletion
        from app.services import rsync_client

        verify = rsync_client.run(
            rsync_client.build_argv(
                source=source, destination=destination, job=job, dry_run=True
            ),
            password=password,
            timeout=1800,
        )
        remaining = rsync_client.parse_itemized(
            verify.stdout, source_root=job.source_path, dest_root=job.destination_path
        )
        outstanding = remaining.copy_count + remaining.update_count
        if verify.returncode != 0 or outstanding:
            run.status = "partial"
            run.error_message = (
                f"Move verification failed: {outstanding} file(s) are still not identical at "
                f"the destination, so nothing was queued for deletion from the source."
            )
            db.commit()
            return

        listed = rsync_client.list_files(source, password)
        if listed is None:
            run.error_message = (
                "Transfer verified, but the source could not be listed, so no files were "
                "queued for deletion. Nothing was removed."
            )
            db.commit()
            return

        for relative, size in listed:
            db.add(
                PendingDeletion(
                    job_id=job.id,
                    job_run_id=run.id,
                    source_path=f"{job.source_path.rstrip('/')}/{relative}",
                    destination_path=f"{job.destination_path.rstrip('/')}/{relative}",
                    size_bytes=size,
                    verification_status="verified",
                    approved=False,
                )
            )
        db.commit()


_PROVIDERS: dict[str, TransferProvider] = {
    FtpProvider.name: FtpProvider(),
    RsyncProvider.name: RsyncProvider(),
}


def get(transport: str | None) -> TransferProvider:
    """The provider for a transport, defaulting to FTP for pre-rsync jobs."""
    provider = _PROVIDERS.get((transport or "ftp").lower())
    if provider is None:
        raise ValueError(f"Unknown transport '{transport}'")
    return provider


def plan_for_job(db, job) -> Plan:
    return get(getattr(job, "transport", "ftp")).plan(db, job)


# --- helpers ----------------------------------------------------------------
def _available_mounts():
    from app.services import mounts

    return mounts.list_mounts()


def _connections(db, job):
    from fastapi import HTTPException

    from app.models import NasConnection

    source = db.get(NasConnection, job.source_connection_id)
    destination = db.get(NasConnection, job.destination_connection_id)
    for conn, label in ((source, "Source"), (destination, "Destination")):
        if conn is None:
            raise HTTPException(status_code=400, detail=f"{label} connection does not exist")
    return source, destination


def _password(source, destination, source_conn, dest_conn) -> str | None:
    """Decrypt the daemon password for whichever end is remote.

    Only one end can be remote (rsync refuses remote-to-remote), so at most one
    password is ever in play.
    """
    from app.services import crypto

    for endpoint, conn in ((source, source_conn), (destination, dest_conn)):
        if endpoint.needs_password and conn.rsync_encrypted_password:
            return crypto.decrypt(conn.rsync_encrypted_password)
    return None


def _explain(result) -> str:
    """Turn an rsync failure into something worth showing a person."""
    known = _EXIT_CODES.get(result.returncode)
    detail = (result.stderr or "").strip().splitlines()
    tail = detail[-1] if detail else ""
    if known:
        return f"{known} (rsync exit code {result.returncode}: {tail})" if tail else known
    return f"rsync failed with exit code {result.returncode}. {tail}".strip()


def _annotate(plan: Plan, stdout: str, job) -> None:
    """Add the counts and warnings a preview needs to be honest."""
    from app.services import rsync_client

    # rsync only itemises what changes, so unchanged files are total minus
    # changed - arithmetic on a number rsync reported, not an invention. When
    # --stats is missing the count stays unknown rather than being guessed at.
    total = rsync_client.parse_regular_file_count(stdout)
    if total is not None:
        changed = plan.copy_count + plan.update_count
        plan.unchanged = max(total - changed, 0)

    if plan.delete_count:
        plan.warnings.insert(
            0,
            f"Strict mirror will DELETE {plan.delete_count} file(s) from the destination.",
        )
    if not plan.items:
        plan.warnings.append("Nothing to do - the destination already matches the source.")
    if job.job_type == "move":
        plan.warnings.append(
            "Move job: source files are only removed after a verified transfer and "
            "manual approval."
        )


class _Progress:
    """Turns rsync's per-file output into live run progress.

    rsync prints one --out-format line per file as it goes, so the file currently
    in flight is simply the last line seen. Counts come from those lines too;
    nothing here is estimated, so the UI never shows a number rsync did not
    actually report.
    """

    FLUSH_SECONDS = 2.0

    def __init__(self, db, run) -> None:
        self._db = db
        self._run = run
        self._done = 0
        self._bytes = 0
        self._current: str | None = None
        self._last_flush = 0.0

    def _flush(self, now: float, force: bool = False) -> None:
        """Persist progress, throttled so many small files do not commit per file."""
        if not force and now - self._last_flush < self.FLUSH_SECONDS:
            return
        self._run.current_item = self._current
        self._run.files_copied = self._done
        self._run.bytes_transferred = self._bytes
        self._db.commit()
        self._last_flush = now

    def saw(self, line: str) -> None:
        import time

        from app.services.rsync_client import parse_progress

        # --info=progress2 gives cumulative bytes for the whole transfer. The UI
        # already derives percentage and rate from bytes_transferred against the
        # plan's bytes_total, so feeding this straight in is all live progress
        # needs - and every figure shown is one rsync actually reported.
        progress = parse_progress(line)
        if progress is not None:
            transferred, _percent = progress
            self._bytes = transferred
            self._flush(time.monotonic())
            return

        if "|" not in line:
            return
        flags, _, rest = line.partition("|")
        _size, _, name = rest.partition("|")
        name = name.strip().rstrip("/")
        if not name or name == "." or flags.strip().startswith("*deleting"):
            return

        self._done += 1
        self._current = name
        self._flush(time.monotonic())


def _without_deletes(job):
    """A copy of the job with deletion turned off, for a vetoed strict mirror.

    The transfer itself is still worth running - only the removals were refused -
    so the job is downgraded to a safe mirror rather than abandoned.
    """
    from types import SimpleNamespace

    fields = {
        name: getattr(job, name)
        for name in (
            "job_type",
            "mirror_mode",
            "conflict_strategy",
            "include_filters",
            "exclude_filters",
            "rsync_compress",
            "rsync_bandwidth_kbps",
        )
    }
    fields["mirror_mode"] = "safe"
    return SimpleNamespace(**fields)


def _record_items(db, run, plan) -> None:
    """Write one job_run_items row per action, matching what FTP runs record."""
    from app.models import JobRunItem

    for item in plan.items:
        db.add(
            JobRunItem(
                job_run_id=run.id,
                source_path=item.source_path,
                destination_path=item.destination_path,
                action=item.action,
                status="ok",
                size_bytes=item.size or 0,
                message=item.reason,
            )
        )
    db.commit()


def _managed_file_count(endpoint, password, job) -> int | None:
    """How many destination files this job actually manages.

    Counting everything present would include files the job's own filters
    exclude - a #recycle folder, say - which inflates the denominator and makes
    the proportional guard fire on a percentage that was never real.
    """
    from app.services.planner import is_filtered, parse_filters
    from app.services.rsync_client import list_files

    listed = list_files(endpoint, password)
    if listed is None:
        return None
    includes = parse_filters(getattr(job, "include_filters", None))
    excludes = parse_filters(getattr(job, "exclude_filters", None))
    if not includes and not excludes:
        return len(listed)
    return sum(1 for relative, _size in listed if not is_filtered(relative, includes, excludes))
