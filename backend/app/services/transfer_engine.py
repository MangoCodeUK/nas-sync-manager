"""The transfer engine: execute a plan against the FTP servers (FR-017/026/027).

Safety-first design:
  * Each file is written to a temporary name, verified, then renamed into place,
    so a failed/partial transfer never leaves a corrupt destination file.
  * Failed files are retried (count/delay from settings) and logged; the run
    continues so one bad file does not abort everything.
  * Destination deletes (strict mirror) are gated by the global safety limits and
    blocked by default. Move-source deletion is handled via pending deletions
    (Stage 7), never here.

Runs are sequential (one source + one destination connection held open) - data
safety is prioritised over speed (NFR-002).
"""
from __future__ import annotations

import ftplib
import os
import posixpath
import tempfile
import threading
import time

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import JobRun, JobRunItem, PendingDeletion, SyncJob, utcnow
from app.services import jobs_runner, settings_service, verifier
from app.services.planner import ARCHIVE, COPY, DELETE, MKDIR, SKIP, UPDATE

TMP_SUFFIX = ".__nas_sync_tmp"

_FTP_ERRORS = ftplib.all_errors
_RETRYABLE = (OSError,) + _FTP_ERRORS


class AlreadyRunning(Exception):
    """Raised when a run is requested for a job that is already running."""


class TransferError(Exception):
    """A single-file transfer failed (verification or transfer)."""


# --- overlap guard (FR-011) -------------------------------------------------
_running: set[int] = set()
_lock = threading.Lock()


def is_running(job_id: int) -> bool:
    with _lock:
        return job_id in _running


def _mark(job_id: int) -> None:
    with _lock:
        _running.add(job_id)


def _unmark(job_id: int) -> None:
    with _lock:
        _running.discard(job_id)


# --- low-level FTP helpers --------------------------------------------------
def ensure_dir(ftp: ftplib.FTP, path: str) -> None:
    if not path or path == "/":
        return
    cur = ""
    for part in [p for p in path.split("/") if p]:
        cur = f"{cur}/{part}"
        try:
            ftp.mkd(cur)
        except _FTP_ERRORS:
            pass  # already exists or no permission (a later STOR will surface it)


def _safe_delete(ftp: ftplib.FTP, path: str) -> None:
    try:
        ftp.delete(path)
    except _FTP_ERRORS:
        pass


def _transfer_one(
    source_ftp: ftplib.FTP,
    dest_ftp: ftplib.FTP,
    src_abs: str,
    dst_abs: str,
    level: int,
    preserve_ts: bool,
    source_mtime,
) -> tuple[int, str]:
    ensure_dir(dest_ftp, posixpath.dirname(dst_abs))
    tmp_remote = dst_abs + TMP_SUFFIX

    fd, local = tempfile.mkstemp(prefix="nassync_")
    os.close(fd)
    try:
        with open(local, "wb") as fh:
            source_ftp.retrbinary(f"RETR {src_abs}", fh.write)
        size = os.path.getsize(local)

        with open(local, "rb") as fh:
            dest_ftp.storbinary(f"STOR {tmp_remote}", fh)

        ok, msg = verifier.verify(
            level=level,
            dest_ftp=dest_ftp,
            remote_path=tmp_remote,
            expected_size=size,
            local_source_path=local,
        )
        if not ok:
            _safe_delete(dest_ftp, tmp_remote)
            raise TransferError(msg)

        if preserve_ts and source_mtime is not None:
            try:
                dest_ftp.sendcmd(f"MFMT {source_mtime.strftime('%Y%m%d%H%M%S')} {tmp_remote}")
            except _FTP_ERRORS:
                pass  # server doesn't support MFMT; not fatal

        # Atomically replace the final file.
        _safe_delete(dest_ftp, dst_abs)
        dest_ftp.rename(tmp_remote, dst_abs)
        return size, msg
    finally:
        try:
            os.remove(local)
        except OSError:
            pass


def _with_retry(fn, retry_count: int, retry_delay: int):
    last: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            return fn()
        except (TransferError, *_RETRYABLE) as exc:
            last = exc
            if attempt < retry_count:
                time.sleep(retry_delay)
    raise last if last else RuntimeError("transfer failed")


# --- run lifecycle ----------------------------------------------------------
def create_run(db: Session, job: SyncJob, run_type: str) -> JobRun:
    run = JobRun(job_id=job.id, run_type=run_type, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _log_item(db: Session, run: JobRun, *, action, status, source=None, destination=None, size=0, message=None):
    db.add(
        JobRunItem(
            job_run_id=run.id,
            source_path=source,
            destination_path=destination,
            action=action,
            status=status,
            size_bytes=size or 0,
            message=message,
        )
    )


def _deletes_allowed(settings_row, total_deletes: int) -> bool:
    if settings_row.require_manual_approval_for_deletes:
        return False
    return total_deletes <= settings_row.max_auto_destination_deletes


def _do_work(db: Session, run: JobRun, job: SyncJob) -> None:
    started = time.monotonic()
    settings_row = settings_service.get_settings_row(db)
    retry_count = settings_row.retry_count
    retry_delay = settings_row.retry_delay_seconds
    preserve = settings_row.preserve_timestamps
    level = job.verification_level

    copied = updated = skipped = failed = deleted = 0
    bytes_transferred = 0
    scanned = 0
    # Source files confirmed at the destination (safe to delete for move jobs).
    verified: list[tuple[str, str, int]] = []  # (abs_path, rel_path, size)

    try:
        ctx = jobs_runner.prepare_for_job(db, job)
        plan = ctx.plan
        delete_total = plan.delete_count
        allow_deletes = _deletes_allowed(settings_row, delete_total)

        with ctx.source_client.connection() as sftp, ctx.dest_client.connection() as dftp:
            ensure_dir(dftp, ctx.dest_path)

            for item in plan.items:
                if item.action == MKDIR:
                    ensure_dir(dftp, item.destination_path)
                    _log_item(db, run, action=MKDIR, status="ok", destination=item.destination_path)

                elif item.action in (COPY, UPDATE):
                    scanned += 1
                    rel = posixpath.relpath(item.source_path, ctx.source_path)
                    entry = ctx.source_files.get(rel)
                    mtime = entry.modify if entry else None
                    try:
                        size, msg = _with_retry(
                            lambda i=item, m=mtime: _transfer_one(
                                sftp, dftp, i.source_path, i.destination_path, level, preserve, m
                            ),
                            retry_count,
                            retry_delay,
                        )
                        bytes_transferred += size
                        if item.action == COPY:
                            copied += 1
                        else:
                            updated += 1
                        verified.append((item.source_path, rel, size))
                        _log_item(db, run, action=item.action, status="ok",
                                  source=item.source_path, destination=item.destination_path,
                                  size=size, message=msg)
                    except Exception as exc:  # noqa: BLE001 - record and continue
                        failed += 1
                        _log_item(db, run, action=item.action, status="failed",
                                  source=item.source_path, destination=item.destination_path,
                                  size=item.size, message=str(exc))

                elif item.action == SKIP:
                    skipped += 1
                    # An "unchanged" file is already verified at the destination, so
                    # for a move it is safe to delete from source. "filtered" is not.
                    if item.reason == "unchanged":
                        rel = posixpath.relpath(item.source_path, ctx.source_path)
                        verified.append((item.source_path, rel, item.size))
                    _log_item(db, run, action=SKIP, status="ok",
                              source=item.source_path, destination=item.destination_path,
                              size=item.size, message=item.reason)

                elif item.action == DELETE:
                    if allow_deletes:
                        _safe_delete(dftp, item.destination_path)
                        deleted += 1
                        _log_item(db, run, action=DELETE, status="ok",
                                  destination=item.destination_path, size=item.size,
                                  message="destination-only removed")
                    else:
                        _log_item(db, run, action=DELETE, status="pending",
                                  destination=item.destination_path, size=item.size,
                                  message="blocked by safety settings (manual approval / limit)")

            # Move workflow: queue or perform source deletion for verified files.
            if job.job_type == "move":
                deleted += _handle_move(db, run, job, sftp, verified, settings_row)

        run.status = "failed" if (failed and not (copied or updated)) else ("partial" if failed else "success")
        run.summary = (
            f"{copied} copied, {updated} updated, {skipped} skipped, "
            f"{deleted} deleted, {failed} failed"
        )
    except Exception as exc:  # noqa: BLE001 - whole-run failure
        run.status = "failed"
        run.error_message = str(exc)

    run.files_scanned = scanned
    run.files_copied = copied
    run.files_updated = updated
    run.files_skipped = skipped
    run.files_failed = failed
    run.files_deleted = deleted
    run.bytes_transferred = bytes_transferred
    run.completed_at = utcnow()
    run.duration_seconds = round(time.monotonic() - started, 3)

    job.last_run_at = utcnow()
    job.last_status = run.status
    db.commit()
    db.refresh(run)


def _queue_pending(db, run, job, verified) -> None:
    for abs_path, _rel, size in verified:
        db.add(
            PendingDeletion(
                job_id=job.id,
                job_run_id=run.id,
                source_path=abs_path,
                size_bytes=size,
                verification_status="verified",
                approved=False,
            )
        )


def _handle_move(db, run, job, sftp, verified, settings_row) -> int:
    """Apply the move job's delete strategy to verified source files.

    Returns the number of source files actually deleted now (0 for the safe
    manual-approval / never / archive paths).
    """
    strategy = job.delete_strategy
    if not verified or strategy == "never":
        return 0

    if strategy == "manual_approval":
        _queue_pending(db, run, job, verified)
        return 0

    if strategy == "auto_delete_after_verification":
        allowed = (
            not settings_row.require_manual_approval_for_deletes
            and len(verified) <= settings_row.max_auto_source_deletes
        )
        if not allowed:
            _queue_pending(db, run, job, verified)  # safety fallback
            return 0
        n = 0
        for abs_path, _rel, size in verified:
            try:
                sftp.delete(abs_path)
                _log_item(db, run, action=DELETE, status="ok", source=abs_path, size=size,
                          message="source deleted after verification")
                n += 1
            except _FTP_ERRORS as exc:
                _log_item(db, run, action=DELETE, status="failed", source=abs_path, size=size,
                          message=str(exc))
        return n

    if strategy == "archive":
        template = job.archive_path or settings_row.archive_path_template
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        safe_name = job.name.replace("/", "_")
        archive_root = template.format(job=safe_name, datetime=stamp).rstrip("/")
        for abs_path, rel, size in verified:
            dest = posixpath.join(archive_root, rel)
            ensure_dir(sftp, posixpath.dirname(dest))
            try:
                sftp.rename(abs_path, dest)
                _log_item(db, run, action=ARCHIVE, status="ok", source=abs_path,
                          destination=dest, size=size, message="archived")
            except _FTP_ERRORS as exc:
                _log_item(db, run, action=ARCHIVE, status="failed", source=abs_path, size=size,
                          message=str(exc))
        return 0

    return 0


def run_sync(db: Session, job: SyncJob, run_type: str = "manual") -> JobRun:
    """Run a job synchronously (used by tests and the scheduler)."""
    if is_running(job.id):
        raise AlreadyRunning(f"Job {job.id} is already running")
    _mark(job.id)
    try:
        run = create_run(db, job, run_type)
        _do_work(db, run, job)
        return run
    finally:
        _unmark(job.id)


def begin(db: Session, job: SyncJob, run_type: str = "manual") -> JobRun:
    """Create a running JobRun and mark the job busy (caller starts execution)."""
    if is_running(job.id):
        raise AlreadyRunning(f"Job {job.id} is already running")
    _mark(job.id)
    run = create_run(db, job, run_type)
    return run


def execute_async(run_id: int, job_id: int) -> None:
    """Run the prepared JobRun in a background thread with its own DB session."""

    def _thread() -> None:
        try:
            with SessionLocal() as db:
                run = db.get(JobRun, run_id)
                job = db.get(SyncJob, job_id)
                if run and job:
                    _do_work(db, run, job)
        finally:
            _unmark(job_id)

    threading.Thread(target=_thread, daemon=True).start()
