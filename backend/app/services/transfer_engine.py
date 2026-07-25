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
import hashlib
import posixpath
import threading
import time

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import JobRun, JobRunItem, PendingDeletion, SyncJob, utcnow
from app.services import jobs_runner, settings_service, verifier
from app.services.planner import ARCHIVE, COPY, DELETE, MKDIR, SKIP, UPDATE

TMP_SUFFIX = ".__nas_sync_tmp"

# ftplib transfers in 8 KB blocks by default, which badly caps throughput over a
# LAN. 1 MiB blocks speed up copies substantially with no safety trade-off.
BLOCKSIZE = 1024 * 1024

# How often (seconds) to persist live run progress so the UI shows movement
# mid-run; without this the run counters only update when the whole job finishes.
PROGRESS_FLUSH_SECONDS = 2.0

_FTP_ERRORS = ftplib.all_errors
_RETRYABLE = (OSError,) + _FTP_ERRORS


class AlreadyRunning(Exception):
    """Raised when a run is requested for a job that is already running."""


class TransferError(Exception):
    """A single-file transfer failed (verification or transfer)."""


class Cancelled(Exception):
    """Raised to abort a run when the user has requested cancellation."""


# --- overlap guard (FR-011) + cooperative cancellation ----------------------
_running: set[int] = set()
_cancel: set[int] = set()
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


def request_cancel(job_id: int) -> bool:
    """Ask a running job to stop - at the next file boundary, or mid-file for the
    file currently streaming. Returns True if the job was actually running."""
    with _lock:
        if job_id in _running:
            _cancel.add(job_id)
            return True
        return False


def is_cancelled(job_id: int) -> bool:
    with _lock:
        return job_id in _cancel


def _clear_cancel(job_id: int) -> None:
    with _lock:
        _cancel.discard(job_id)


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
    session: "_Session",
    src_abs: str,
    dst_abs: str,
    level: int,
    preserve_ts: bool,
    source_mtime,
    cancel_check=None,
    on_bytes=None,
) -> tuple[int, str]:
    dest_ftp = session.dftp
    ensure_dir(dest_ftp, posixpath.dirname(dst_abs))
    tmp_remote = dst_abs + TMP_SUFFIX

    # Stream the source straight to the destination, with both data channels live
    # at once. The old code spooled the whole file to a local temp first, which
    # (a) left the destination connection idle for the entire download - large
    # files then died with "broken pipe" when the server dropped the idle socket -
    # and (b) wrote every byte through the app host's disk. Streaming removes both
    # and roughly halves per-file time. We still STOR to a temp name, verify, then
    # rename into place, so a partial transfer never exposes a corrupt final file.
    hasher = hashlib.sha256() if level >= 3 else None
    size = 0

    def _pump(chunk: bytes) -> None:
        nonlocal size
        if cancel_check is not None and cancel_check():
            raise Cancelled()
        conn.sendall(chunk)
        size += len(chunk)
        if hasher is not None:
            hasher.update(chunk)
        if on_bytes is not None:
            on_bytes(size)

    dest_ftp.voidcmd("TYPE I")
    conn = dest_ftp.transfercmd(f"STOR {tmp_remote}")
    try:
        session.sftp.retrbinary(f"RETR {src_abs}", _pump, BLOCKSIZE)
    except Exception:
        conn.close()
        try:
            dest_ftp.voidresp()  # drain the aborted STOR so the connection stays usable
        except _FTP_ERRORS:
            pass
        raise
    conn.close()
    dest_ftp.voidresp()  # surfaces destination-side STOR errors (e.g. quota)

    # The upload is committed on the server now (226 received). Some FTP servers -
    # e.g. SmbFTPD on older TerraMaster units - drop the control connection the
    # moment a STOR finishes (and again after a handful of commands), so EVERY
    # post-upload command (SIZE, MFMT, rename) must run on a freshly reconnected
    # destination connection. Reconnecting is cheap on a LAN and harmless for
    # well-behaved servers, so we always do it.
    session.reconnect_dest()
    verify_ftp = session.dftp
    verify_ftp.voidcmd("TYPE I")  # a fresh connection defaults to ASCII; SIZE/RETR need binary
    ok, msg = verifier.verify(
        level=level,
        dest_ftp=verify_ftp,
        remote_path=tmp_remote,
        expected_size=size,
        source_sha256=hasher.hexdigest() if hasher is not None else None,
    )
    if not ok:
        session.reconnect_dest()
        _safe_delete(session.dftp, tmp_remote)
        raise TransferError(msg)

    if preserve_ts and source_mtime is not None:
        try:
            verify_ftp.sendcmd(f"MFMT {source_mtime.strftime('%Y%m%d%H%M%S')} {tmp_remote}")
        except _FTP_ERRORS:
            pass  # server doesn't support MFMT (or dropped us); not fatal

    # Atomically replace the final file. A fresh connection with the rename as its
    # first operations stays well inside servers that drop the control connection
    # after only a few commands.
    session.reconnect_dest()
    _safe_delete(session.dftp, dst_abs)
    session.dftp.rename(tmp_remote, dst_abs)
    return size, msg


class _Session:
    """Holds the source + destination connections for a run and reconnects on
    demand.

    Consumer NAS FTP servers (and the NAT between containers) routinely drop the
    control connection after a large transfer, so reusing a single connection for
    the whole run made every file after the first fail with "broken pipe". We
    check liveness before each file and reconnect if needed, so a drop costs one
    reconnect instead of the rest of the queue.
    """

    def __init__(self, source_client, dest_client) -> None:
        self._source_client = source_client
        self._dest_client = dest_client
        self.sftp: ftplib.FTP | None = None
        self.dftp: ftplib.FTP | None = None

    def open(self) -> None:
        self.sftp = self._source_client.connect()
        self.dftp = self._dest_client.connect()

    def close(self) -> None:
        for ftp in (self.sftp, self.dftp):
            if ftp is None:
                continue
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001 - best-effort teardown
                try:
                    ftp.close()
                except Exception:  # noqa: BLE001
                    pass
        self.sftp = self.dftp = None

    def reconnect(self) -> None:
        self.close()
        self.open()

    def reconnect_dest(self) -> None:
        """Rebuild only the destination connection. Used after every upload for
        servers that drop the control connection once a STOR completes."""
        if self.dftp is not None:
            try:
                self.dftp.quit()
            except Exception:  # noqa: BLE001 - best-effort teardown
                try:
                    self.dftp.close()
                except Exception:  # noqa: BLE001
                    pass
        self.dftp = self._dest_client.connect()

    def ensure_alive(self) -> None:
        """Cheap liveness probe; reconnect (with a few retries) if either side is
        dead. Raises only if reconnection keeps failing (server truly down)."""
        try:
            self.sftp.voidcmd("NOOP")
            self.dftp.voidcmd("NOOP")
            return
        except Exception:  # noqa: BLE001 - connection is stale; rebuild it
            pass
        last: Exception | None = None
        for _ in range(3):
            try:
                self.reconnect()
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1)
        raise last if last else RuntimeError("cannot reconnect to FTP server")


def _with_retry(fn, retry_count: int, retry_delay: int, session: "_Session | None" = None):
    last: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            return fn()
        except (TransferError, *_RETRYABLE) as exc:
            last = exc
            if attempt < retry_count:
                # A connection-level failure poisons the held connection for every
                # later file, so rebuild it before retrying.
                if session is not None:
                    try:
                        session.reconnect()
                    except Exception:  # noqa: BLE001 - retry loop will surface it
                        pass
                if retry_delay:
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
    bytes_transferred = 0  # bytes of fully-completed files
    inflight = 0  # bytes of the file currently streaming (for a live progress bar)
    scanned = 0
    current: str | None = None
    cancelled = False
    # Source files confirmed at the destination (safe to delete for move jobs).
    verified: list[tuple[str, str, int]] = []  # (abs_path, rel_path, size)

    last_flush = time.monotonic()

    def flush_progress(force: bool = False) -> None:
        """Persist live counters so a polling UI (separate session) sees progress.

        Time-throttled so a job of many small files does not commit per file.
        """
        nonlocal last_flush
        now = time.monotonic()
        if not force and now - last_flush < PROGRESS_FLUSH_SECONDS:
            return
        run.files_scanned = scanned
        run.files_copied = copied
        run.files_updated = updated
        run.files_skipped = skipped
        run.files_failed = failed
        run.files_deleted = deleted
        run.bytes_transferred = bytes_transferred + inflight
        run.current_item = current
        db.commit()
        last_flush = now

    try:
        ctx = jobs_runner.prepare_for_job(db, job)
        plan = ctx.plan
        delete_total = plan.delete_count
        allow_deletes = _deletes_allowed(settings_row, delete_total)

        # Persist plan totals up-front so the UI can show "X of Y" immediately.
        run.files_total = plan.copy_count + plan.update_count
        run.bytes_total = plan.transfer_bytes
        db.commit()

        session = _Session(ctx.source_client, ctx.dest_client)
        session.open()
        try:
            ensure_dir(session.dftp, ctx.dest_path)

            for item in plan.items:
                if is_cancelled(job.id):
                    cancelled = True
                    break

                if item.action == MKDIR:
                    session.ensure_alive()
                    ensure_dir(session.dftp, item.destination_path)
                    _log_item(db, run, action=MKDIR, status="ok", destination=item.destination_path)

                elif item.action in (COPY, UPDATE):
                    scanned += 1
                    rel = posixpath.relpath(item.source_path, ctx.source_path)
                    entry = ctx.source_files.get(rel)
                    mtime = entry.modify if entry else None
                    current = rel
                    inflight = 0
                    flush_progress(force=True)  # show the file the moment it starts

                    def _tick(n: int) -> None:
                        nonlocal inflight
                        inflight = n
                        flush_progress()  # throttled: live bytes during a big file

                    try:
                        # Make sure we start the file on a live connection - the
                        # server may have dropped us after the previous transfer.
                        session.ensure_alive()
                        size, msg = _with_retry(
                            lambda i=item, m=mtime: _transfer_one(
                                session, i.source_path, i.destination_path, level, preserve, m,
                                cancel_check=lambda: is_cancelled(job.id),
                                on_bytes=_tick,
                            ),
                            retry_count,
                            retry_delay,
                            session,
                        )
                        bytes_transferred += size
                        inflight = 0
                        if item.action == COPY:
                            copied += 1
                        else:
                            updated += 1
                        verified.append((item.source_path, rel, size))
                        _log_item(db, run, action=item.action, status="ok",
                                  source=item.source_path, destination=item.destination_path,
                                  size=size, message=msg)
                    except Cancelled:
                        inflight = 0
                        cancelled = True
                        break
                    except Exception as exc:  # noqa: BLE001 - record and continue
                        inflight = 0
                        failed += 1
                        _log_item(db, run, action=item.action, status="failed",
                                  source=item.source_path, destination=item.destination_path,
                                  size=item.size, message=str(exc))
                        # The connection is likely poisoned; rebuild it so the next
                        # file does not fail against a dead socket too.
                        try:
                            session.reconnect()
                        except Exception:  # noqa: BLE001 - next file's ensure_alive retries
                            pass

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
                        session.ensure_alive()
                        _safe_delete(session.dftp, item.destination_path)
                        deleted += 1
                        _log_item(db, run, action=DELETE, status="ok",
                                  destination=item.destination_path, size=item.size,
                                  message="destination-only removed")
                    else:
                        _log_item(db, run, action=DELETE, status="pending",
                                  destination=item.destination_path, size=item.size,
                                  message="blocked by safety settings (manual approval / limit)")

                flush_progress()

            # Move workflow: queue or perform source deletion for verified files
            # (skip it when the run was cancelled - the picture is incomplete).
            if job.job_type == "move" and not cancelled:
                session.ensure_alive()
                deleted += _handle_move(db, run, job, session.sftp, verified, settings_row)
        finally:
            session.close()

        if cancelled:
            run.status = "cancelled"
        elif failed and not (copied or updated):
            run.status = "failed"
        elif failed:
            run.status = "partial"
        else:
            run.status = "success"
        run.summary = (
            f"{copied} copied, {updated} updated, {skipped} skipped, "
            f"{deleted} deleted, {failed} failed"
            + (" (cancelled)" if cancelled else "")
        )
    except Exception as exc:  # noqa: BLE001 - whole-run failure
        run.status = "failed"
        run.error_message = str(exc)

    inflight = 0
    current = None
    run.files_scanned = scanned
    run.files_copied = copied
    run.files_updated = updated
    run.files_skipped = skipped
    run.files_failed = failed
    run.files_deleted = deleted
    run.bytes_transferred = bytes_transferred
    run.current_item = None
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
        _clear_cancel(job.id)


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
            _clear_cancel(job_id)

    threading.Thread(target=_thread, daemon=True).start()
