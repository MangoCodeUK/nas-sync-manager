"""rsync execution service: capability probe, argv construction, dry-run parsing.

Separation of concerns: ``mounts.py`` answers "where can we write?", this module
answers "what exactly do we run, and what did it say?".

Credentials never appear in argv. A daemon password goes through the
``RSYNC_PASSWORD`` environment variable, because everything in argv is readable
via ``/proc/<pid>/cmdline`` - so a command preview shown in the UI is safe by
construction rather than by remembering to redact it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

from app.services import mounts
from app.services.planner import COPY, DELETE, MKDIR, UPDATE, Plan, PlanItem, parse_filters

# rsync is well-behaved about --version, but a hung binary must not hang a page
# load, so every probe is bounded.
_PROBE_TIMEOUT = 5

# First line is "rsync  version 3.4.1  protocol version 32". Note "version"
# appears twice, so the release number cannot be read by simply taking the token
# after the first "version" without also mis-reading "protocol version" as the
# protocol number - which is exactly the bug these two patterns replaced.
_VERSION_RE = re.compile(r"\bversion\s+(\S+)")
_PROTOCOL_RE = re.compile(r"\bprotocol\s+version\s+(\d+)")

# --stats prints "Number of files: 6 (reg: 4, dir: 2)"
_REG_FILES_RE = re.compile(r"Number of files:.*?\breg:\s*([\d,]+)")

# Our own --out-format, chosen so parsing never has to guess column widths.
# --info=progress2 redraws a line like:
#   "     1,234,567  45%   12.34MB/s    0:00:05"
# The leading number is cumulative bytes for the WHOLE transfer, which is what
# makes it usable as overall progress (plain --progress is per-file).
PROGRESS_RE = re.compile(
    r"^\s*([\d,]+)\s+(\d+)%\s+(\S+)\s+(\d+:\d{2}:\d{2})"
)

OUT_FORMAT = "%i|%l|%n"
_SEPARATOR = "|"


class RsyncError(Exception):
    """rsync could not be run, or the configuration for it is unusable."""


class Cancelled(Exception):
    """The user asked for the run to stop."""


@dataclass(frozen=True)
class RsyncCapability:
    available: bool
    version: str | None = None  # e.g. "3.4.1"
    protocol: int | None = None  # daemon wire protocol, e.g. 31
    path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Endpoint:
    """One side of a transfer, as rsync needs to see it."""

    spec: str  # what goes on the command line
    is_local: bool
    needs_password: bool = False
    ssh_port: int | None = None  # set when this end is reached over SSH
    is_daemon: bool = False  # set when this end is an rsync:// daemon module


@dataclass
class RsyncResult:
    returncode: int
    stdout: str
    stderr: str
    argv: list[str] = field(default_factory=list)


# --- capability -------------------------------------------------------------
def probe() -> RsyncCapability:
    """Report whether rsync is usable in this container, and which version.

    Never raises: a missing or broken rsync is a state the UI reports, not a
    crash.
    """
    path = shutil.which("rsync")
    if path is None:
        return RsyncCapability(
            available=False,
            error="rsync is not installed in the backend container image.",
        )

    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RsyncCapability(available=False, path=path, error=f"cannot run rsync ({exc})")

    if result.returncode != 0:
        return RsyncCapability(
            available=False,
            path=path,
            error=f"rsync --version exited {result.returncode}",
        )

    return RsyncCapability(
        available=True,
        version=parse_version(result.stdout),
        protocol=parse_protocol(result.stdout),
        path=path,
    )


def parse_version(output: str) -> str | None:
    """Release number from rsync --version output, e.g. "3.4.1"."""
    match = _VERSION_RE.search(_head(output))
    return match.group(1) if match else None


def parse_protocol(output: str) -> int | None:
    """Daemon wire protocol from rsync --version output, e.g. 32.

    This, not the release number, decides whether two ends can talk. Measured
    across the estate: the container ships 3.4.1/protocol 32, the new NAS
    3.2.3/protocol 31 and the old NAS 3.1.2/protocol 31. rsync negotiates down to
    the lower of the two, so the mismatch is fine - but it is worth surfacing.
    """
    match = _PROTOCOL_RE.search(_head(output))
    return int(match.group(1)) if match else None


def _head(output: str) -> str:
    return output.splitlines()[0] if output else ""


# --- endpoints --------------------------------------------------------------
def build_endpoint(conn, path: str, *, write: bool, available=None) -> Endpoint:
    """Resolve one side of a transfer to something rsync can address.

    Preference order is deliberate: a bind-mounted path is always used when one
    exists, because a local path is faster than any network transport and because
    rsync refuses a transfer with two remote ends. Only when the path is not
    mounted do we fall back to reaching the device over the network.
    """
    fs_root = (conn.fs_root or "").strip()
    if fs_root and mounts.find(path, available) is not None:
        return Endpoint(spec=mounts.resolve(path, write=write, mounts=available), is_local=True)

    if not conn.rsync_enabled:
        raise RsyncError(
            f"'{path}' on {conn.name} is not reachable for rsync: it is not bind-mounted "
            f"into the container, and rsync is not configured for this connection. Either "
            f"add the share to docker-compose.prod.yml, or fill in the rsync settings for "
            f"{conn.name}."
        )

    host = (conn.rsync_host or conn.host).strip()
    user = (conn.rsync_username or "").strip()

    if conn.rsync_mode == "ssh":
        # user@host:/absolute/path - the device's real filesystem path.
        prefix = f"{user}@{host}" if user else host
        return Endpoint(spec=f"{prefix}:{path}", is_local=False, ssh_port=conn.rsync_ssh_port or 22)

    # Daemon mode: user@host::module/subpath. A module is a named root on the
    # remote device, so the job's path is re-expressed relative to it.
    module, relative = _module_for(path, conn)
    prefix = f"{user}@{host}" if user else host
    spec = f"{prefix}::{module}"
    if relative:
        spec = f"{spec}/{relative}"
    return Endpoint(spec=spec, is_local=False, needs_password=bool(user), is_daemon=True)


def _module_for(path: str, conn) -> tuple[str, str]:
    """Split a device path into ``(module, subpath)``.

    The module is taken from the path itself - the first segment below fs_root -
    rather than from the connection's single configured module. A device can
    publish several modules, and which one applies depends on where the job is
    pointing, not on one field set once.

    This relies on a module being named after the top-level folder it exposes
    (module ``public`` rooted at ``/mnt/md0/public``), which is how TOS names them
    by default. Where that does not hold, Test Connection lists what the device
    actually publishes so the mismatch is visible rather than mysterious.
    """
    fs_root = normalise(conn.fs_root or "/")
    target = normalise(path)
    if not (target == fs_root or target.startswith(fs_root.rstrip("/") + "/")):
        raise RsyncError(
            f"'{path}' is not under {conn.name}'s filesystem root ({fs_root}). Check the "
            f"path, or the Filesystem root set on that connection."
        )

    relative = target[len(fs_root.rstrip("/")) :].lstrip("/")
    if not relative:
        raise RsyncError(
            f"'{path}' is {conn.name}'s filesystem root itself, which rsync cannot address "
            f"directly - a daemon exposes named modules, not the whole device. Point the "
            f"job at a share below it."
        )

    module, _, subpath = relative.partition("/")
    return module, subpath


def normalise(path: str) -> str:
    return mounts._norm(path)


# --- argv -------------------------------------------------------------------
def build_argv(
    *,
    source: Endpoint,
    destination: Endpoint,
    job,
    dry_run: bool,
    timeout_seconds: int = 600,
    max_delete: int | None = None,
) -> list[str]:
    """Construct the rsync command line for a job. Carries no credentials."""
    if not source.is_local and not destination.is_local:
        raise RsyncError(
            "rsync cannot copy directly between two remote devices. One side must be "
            "bind-mounted into the container - add that share to docker-compose.prod.yml."
        )

    argv: list[str] = ["rsync"]

    # -r recurse, -l keep symlinks as symlinks, -t preserve mtimes (which is also
    # what makes the next run's quick-check meaningful). Deliberately NOT -a:
    # that implies -o/-g (owner/group), which fail or lie between devices with
    # different account databases.
    argv += ["-rlt"]

    # Destination modes are set explicitly, never inherited. With --perms off,
    # rsync gives a NEW file the source's mode masked by the receiver's umask -
    # and the TOS shares here are ACL-based with no "other" bits at all
    # (0770 dirs, 0760 files, owned by a single account). Masked by the
    # receiving daemon's umask of 022 that lands as 0750/0740 root:root on the
    # far device, which is unreadable to Plex: it cannot even descend into the
    # folders, so a scan reports the films as missing rather than as denied.
    # Measured on the 2026 Films run of 2026-08-31 - 89 files, every one of them
    # invisible, while the files already there from the old FTP jobs were fine
    # because the FTP server had applied its own permissive default.
    #
    # D777,F666 matches what the rest of the destination library already is, so
    # rsync-copied media behaves exactly like FTP-copied media. --perms is what
    # makes the setting authoritative: without it these modes would themselves
    # be masked by the receiver's umask, and files already on the destination
    # would keep whatever broken mode they were given. With it, re-running a job
    # repairs earlier copies in place - no re-transfer, since the data matches.
    argv += ["--perms", "--chmod=D777,F666"]

    # Spaces are common in these shares ("TV Shows"). Without this, the remote
    # end re-splits the path and the transfer silently targets somewhere else.
    argv += ["--protect-args"]

    # Resume rather than restart after an interruption.
    argv += ["--partial"]

    argv += [f"--timeout={timeout_seconds}"]
    # --contimeout is rejected outright ("may only be used when connecting to an
    # rsync daemon") for local and SSH transfers, so it is added only when one
    # end really is a daemon. Verified against rsync 3.2.3 on the NAS.
    if source.is_daemon or destination.is_daemon:
        argv += ["--contimeout=30"]

    if job.rsync_compress:
        argv += ["-z"]
    if job.rsync_bandwidth_kbps:
        argv += [f"--bwlimit={int(job.rsync_bandwidth_kbps)}"]

    # Verification, mapped onto what rsync actually offers. Levels 1-2 use
    # rsync's default quick check (size and mtime), which is what makes
    # incremental runs fast. Levels 3-4 add --checksum: every file is read in
    # full on BOTH ends and hashed, which is genuinely stronger and genuinely
    # expensive - on these devices it is I/O-bound and can take far longer
    # than the transfer it is checking.
    if int(getattr(job, 'verification_level', 2) or 2) >= 3:
        argv += ['--checksum']

    argv += _conflict_flags(job.conflict_strategy)
    argv += _filter_flags(job.include_filters, job.exclude_filters)

    # A preview must show deletions or it is lying about what a real run would
    # do. Real runs only reach here through the safety gate.
    if job.job_type == "mirror" and job.mirror_mode == "strict":
        argv += ["--delete"]
        # Belt and braces. The app has already decided how many deletions are
        # acceptable; this makes rsync itself refuse to exceed that number, so
        # a destination that changed between the preview and the run cannot
        # quietly delete more than was sanctioned.
        if max_delete is not None:
            argv += [f"--max-delete={max_delete}"]

    if dry_run:
        argv += ["--dry-run"]
    else:
        # Cumulative byte progress for the whole transfer. The UI already
        # derives percentage and rate from bytes, so feeding this in is all
        # that live progress needs - no invented numbers.
        argv += ["--info=progress2"]
    argv += ["--itemize-changes", f"--out-format={OUT_FORMAT}", "--stats"]

    ssh_port = source.ssh_port or destination.ssh_port
    if ssh_port:
        argv += ["-e", f"ssh -p {ssh_port} -o BatchMode=yes -o StrictHostKeyChecking=accept-new"]

    # A trailing slash on the source means "the CONTENTS of this directory",
    # which is the behaviour proven against the TerraMaster jobs: the contents of
    # RsyncSourceTest land in RsyncTest, not in RsyncTest/RsyncSourceTest. Set
    # explicitly here rather than left to whether someone typed a slash.
    argv += [source.spec.rstrip("/") + "/", destination.spec.rstrip("/") + "/"]
    return argv


def _conflict_flags(strategy: str) -> list[str]:
    """Map the app's existing conflict vocabulary onto rsync's flags."""
    if strategy == "skip":
        return ["--ignore-existing"]
    if strategy == "overwrite_if_newer":
        return ["--update"]
    if strategy == "overwrite_if_size_differs":
        return ["--size-only"]
    if strategy == "always_overwrite":
        return ["--ignore-times"]
    # overwrite_if_newer_or_size_differs is rsync's default quick check (transfer
    # when size or mtime differs), so it needs no flag. rename / keep_both have no
    # rsync equivalent and fall back to that same default.
    return []


def _filter_flags(include_filters: str | None, exclude_filters: str | None) -> list[str]:
    """Translate the app's include/exclude lists into rsync filters.

    Excludes always win. Includes act as an allowlist, which in rsync means:
    descend into every directory, allow the named patterns, exclude everything
    else. The leading '--include=*/' is what stops the allowlist pruning
    directories before their contents get a chance to match.
    """
    flags: list[str] = []
    for pattern in parse_filters(exclude_filters):
        flags += [f"--exclude={pattern}"]

    includes = parse_filters(include_filters)
    if includes:
        flags += ["--include=*/"]
        for pattern in includes:
            flags += [f"--include={pattern}"]
        flags += ["--exclude=*"]
    return flags


def redacted_command(argv: list[str]) -> str:
    """A copy-pasteable command for the UI, with any credential removed.

    argv already carries no password, so this mainly guards against a secret
    reaching us by another route - someone typing one into a path, say.
    """
    safe: list[str] = []
    for arg in argv:
        arg = re.sub(r"(?<=//)([^/:@\s]+):([^/@\s]+)(?=@)", r"\1", arg)  # scheme://u:p@host
        arg = re.sub(r"\b([\w.-]+):([^@\s/]+)(?=@[\w.-]+::)", r"\1", arg)  # u:p@host::module
        safe.append(f"'{arg}'" if " " in arg else arg)
    return " ".join(safe)


# --- execution --------------------------------------------------------------
def run(argv: list[str], *, password: str | None = None, timeout: int | None = None) -> RsyncResult:
    """Run rsync, passing any daemon password out-of-band via the environment."""
    env = dict(os.environ)
    if password:
        # Read by rsync itself for daemon auth. Not argv, so it never appears in
        # /proc/<pid>/cmdline, in a log, or in a command preview.
        env["RSYNC_PASSWORD"] = password

    try:
        completed = subprocess.run(  # noqa: S603 - argv built here, never a shell
            argv,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RsyncError("rsync is not installed in this container.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RsyncError(f"rsync timed out after {timeout}s.") from exc
    except OSError as exc:
        raise RsyncError(f"cannot run rsync ({exc}).") from exc

    return RsyncResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        argv=list(argv),
    )


def run_streaming(
    argv: list[str],
    *,
    password: str | None = None,
    on_line=None,
    should_cancel=None,
    poll_seconds: float = 0.25,
) -> RsyncResult:
    """Run rsync, streaming stdout so the run can be cancelled part-way.

    subprocess.run() would block until rsync finished, leaving the Cancel button
    a lie for exactly the long transfers where it matters. Cancellation is
    cooperative: rsync is asked to terminate, then killed if it ignores that.
    """
    env = dict(os.environ)
    if password:
        env["RSYNC_PASSWORD"] = password

    try:
        process = subprocess.Popen(  # noqa: S603 - argv built here, never a shell
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise RsyncError("rsync is not installed in this container.") from exc
    except OSError as exc:
        raise RsyncError(f"cannot run rsync ({exc}).") from exc

    lines: list[str] = []
    cancelled = False
    assert process.stdout is not None

    # Read in chunks and split on BOTH separators. --info=progress2 redraws one
    # line using carriage returns and never emits a newline until it finishes, so
    # iterating the pipe line-by-line would hold every progress update hostage
    # until the transfer ended - which is precisely when progress stops mattering.
    buffer = ""
    while True:
        chunk = process.stdout.read(1024)
        if not chunk:
            break
        buffer += chunk
        parts = re.split(r"[\r\n]", buffer)
        buffer = parts.pop()  # trailing fragment: an unfinished line
        for part in parts:
            if not part:
                continue
            lines.append(part + "\n")
            if on_line is not None:
                on_line(part)
        if should_cancel is not None and should_cancel():
            cancelled = True
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            break
    if buffer and not cancelled:
        lines.append(buffer + "\n")
        if on_line is not None:
            on_line(buffer)

    stderr = process.stderr.read() if process.stderr else ""
    process.wait()
    if cancelled:
        raise Cancelled()

    return RsyncResult(
        returncode=process.returncode,
        stdout="".join(lines),
        stderr=stderr or "",
        argv=list(argv),
    )


def list_files(endpoint: "Endpoint", password: str | None = None) -> list[tuple[str, int]] | None:
    """Every regular file under an endpoint as ``(relative path, size)``.

    None means "could not be determined", which callers must treat as a reason to
    do nothing rather than as an empty directory - the difference matters when
    the answer is about to authorise deletions.

    A local path is walked directly. A remote one is listed with --list-only,
    which transfers no file data.
    """
    if endpoint.is_local:
        root = endpoint.spec.rstrip("/")
        if not os.path.isdir(root):
            return None
        found: list[tuple[str, int]] = []
        for directory, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(directory, name)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                found.append((os.path.relpath(full, root).replace(os.sep, "/"), size))
        return found

    argv = ["rsync", "--list-only", "--recursive", "--protect-args", endpoint.spec.rstrip("/") + "/"]
    if endpoint.ssh_port:
        argv[1:1] = ["-e", f"ssh -p {endpoint.ssh_port} -o BatchMode=yes"]
    try:
        result = run(argv, password=password, timeout=300)
    except RsyncError:
        return None
    if result.returncode != 0:
        return None

    # Lines look like "-rw-r--r--  1,234 2026/08/31 18:15:00 Some Name.txt".
    # Directories start with 'd'. Split on the first four fields only, so names
    # containing spaces survive intact.
    entries: list[tuple[str, int]] = []
    for line in result.stdout.splitlines():
        if line[:1] != "-":
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            size = int(parts[1].replace(",", ""))
        except ValueError:
            size = 0
        name = parts[4].strip()
        if name and name != ".":
            entries.append((name, size))
    return entries


def count_files(endpoint: "Endpoint", password: str | None = None) -> int | None:
    """How many regular files an endpoint holds, or None if it cannot be told.

    Needed for the proportional deletion guard: "would remove 90% of the
    destination" cannot be judged without knowing the destination's size.
    """
    listed = list_files(endpoint, password)
    return None if listed is None else len(listed)


# --- output parsing ---------------------------------------------------------
def parse_itemized(stdout: str, *, source_root: str, dest_root: str) -> Plan:
    """Turn --itemize-changes output into the app's existing Plan shape.

    Reusing Plan/PlanItem is what lets the current PlanPreview component render
    an rsync preview with no frontend change at all.

    The itemized flag string is "YXcstpoguax": Y is the update type (> received,
    c created, * a message such as deleting), X the entry type (f file, d dir,
    L symlink). A brand-new file shows every attribute as '+'; an updated one
    shows which attributes differ, e.g. '>f.st......'.
    """
    plan = Plan()
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if _SEPARATOR not in line:
            continue
        flags, _, rest = line.partition(_SEPARATOR)
        size_text, _, name = rest.partition(_SEPARATOR)
        flags = flags.strip()
        # rsync reports directories with a trailing slash ("FolderA/") and the
        # transfer root as "./". Strip both so paths read consistently.
        name = name.strip().rstrip("/")
        if not name or name == "." or not flags:
            continue
        try:
            size = int(size_text.strip().replace(",", ""))
        except ValueError:
            size = 0

        source_path = f"{source_root.rstrip('/')}/{name}"
        dest_path = f"{dest_root.rstrip('/')}/{name}"

        if flags.startswith("*deleting"):
            plan.items.append(
                PlanItem(DELETE, None, dest_path, size, "destination-only (strict mirror)")
            )
            continue

        entry_type = flags[1] if len(flags) > 1 else ""
        if entry_type == "d":
            # Only *new* directories are worth previewing; an existing one whose
            # mtime merely differs is noise.
            if flags[0] == "c" or "+" in flags:
                plan.items.append(PlanItem(MKDIR, None, dest_path, 0, "create folder"))
            continue
        if entry_type not in ("f", "L"):
            continue

        if flags.endswith("+++++++++"):
            plan.items.append(PlanItem(COPY, source_path, dest_path, size, "new file"))
        else:
            plan.items.append(PlanItem(UPDATE, source_path, dest_path, size, _why(flags)))
    return plan


def _why(flags: str) -> str:
    """Human-readable reason from the itemize attribute flags."""
    attributes = flags[2:]
    reasons = []
    if "c" in attributes:
        reasons.append("checksum")
    if "s" in attributes:
        reasons.append("size")
    if "t" in attributes:
        reasons.append("time")
    if "p" in attributes:
        reasons.append("permissions")
    return "changed: " + ", ".join(reasons) if reasons else "changed"


def parse_progress(line: str) -> tuple[int, int] | None:
    """``(bytes so far, percent)`` from an --info=progress2 line, or None."""
    match = PROGRESS_RE.match(line)
    if not match:
        return None
    return int(match.group(1).replace(",", "")), int(match.group(2))


def parse_regular_file_count(stdout: str) -> int | None:
    """Regular files rsync considered, from --stats. None only when unknowable.

    Two distinct answers that must never be confused:

      0    - rsync looked and found no regular files.
      None - rsync did not report, so we do not know.

    This matters more than it looks. When the count is zero rsync writes
    "Number of files: 1 (dir: 1)" and omits the "reg:" group *entirely*. Reading
    that as "unknown" instead of "zero" disarms the empty-source guard, which is
    the single check standing between an unavailable source and a wiped
    destination. Verified against rsync 3.2.3 on the NAS with a genuinely empty
    source directory.

    Only the "Number of files:" line is examined, because later lines
    ("Number of created files: 2 (reg: 2)") carry a reg: group of their own.
    """
    for line in stdout.splitlines():
        if not line.startswith("Number of files:"):
            continue
        match = _REG_FILES_RE.search(line)
        return int(match.group(1).replace(",", "")) if match else 0
    return None


__all__ = [
    "OUT_FORMAT",
    "Cancelled",
    "Endpoint",
    "RsyncCapability",
    "RsyncError",
    "RsyncResult",
    "RsyncTestResult",
    "build_argv",
    "build_endpoint",
    "count_files",
    "list_files",
    "normalise",
    "parse_itemized",
    "parse_progress",
    "parse_protocol",
    "parse_regular_file_count",
    "parse_version",
    "probe",
    "redacted_command",
    "run",
    "run_streaming",
    "test_connection",
]


# --- connection testing -----------------------------------------------------
@dataclass
class RsyncTestResult:
    """What we could actually establish about a device's rsync service."""

    reachable: bool = False
    authenticated: bool = False
    module_found: bool | None = None
    modules: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.reachable and self.authenticated and self.module_found is not False

    def summary(self) -> str:
        if not self.reachable:
            return "rsync: unreachable"
        if not self.authenticated:
            return "rsync: reachable, login refused"
        if self.module_found is False:
            return "rsync: logged in, module not found"
        return "rsync: OK"


def test_connection(conn, password: str | None = None) -> RsyncTestResult:
    """Check a device's rsync service the way a job would use it.

    Deliberately separate from the FTP test: the same device can have a working
    FTP login and a broken rsync one, and finding that out when a job runs is far
    worse than finding out here.
    """
    import socket

    result = RsyncTestResult()
    host = (conn.rsync_host or conn.host).strip()

    if conn.rsync_mode == "ssh":
        # Ask the far end for its rsync version over SSH: proves the transport,
        # the login and that rsync exists there, in one round trip.
        port = conn.rsync_ssh_port or 22
        user = (conn.rsync_username or "").strip()
        target = f"{user}@{host}" if user else host
        probe = run(
            [
                "ssh", "-p", str(port),
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=10",
                target, "rsync --version",
            ],
            timeout=30,
        )
        result.reachable = probe.returncode != 255 or "refused" not in (probe.stderr or "").lower()
        result.authenticated = probe.returncode == 0
        if probe.returncode == 0:
            version = parse_version(probe.stdout)
            result.messages.append(f"SSH login OK; remote rsync {version or 'present'}")
        else:
            detail = (probe.stderr or "").strip().splitlines()
            result.messages.append(detail[-1] if detail else "SSH login failed")
        return result

    # Daemon mode. Step one is a plain socket: it separates "device is off or the
    # service is disabled" from "credentials are wrong", which the rsync exit
    # code alone does not.
    port = conn.rsync_port or 873
    sock = socket.socket()
    sock.settimeout(10)
    try:
        sock.connect((host, port))
        greeting = sock.recv(128).decode(errors="replace")
        result.reachable = greeting.startswith("@RSYNCD")
        if result.reachable:
            result.messages.append(f"Daemon responded: {greeting.strip()}")
        else:
            result.messages.append(f"Something is listening on {port} but it is not rsync.")
    except OSError as exc:
        result.messages.append(f"Cannot reach {host}:{port} ({exc})")
        return result
    finally:
        sock.close()

    if not result.reachable:
        return result

    user = (conn.rsync_username or "").strip()
    target = f"{user}@{host}::" if user else f"{host}::"
    listing = run(["rsync", "--list-only", target], password=password, timeout=30)
    if listing.returncode != 0:
        detail = (listing.stderr or "").strip().splitlines()
        result.messages.append(
            "Login refused - check the rsync username and password. "
            + (detail[-1] if detail else "")
        )
        return result

    result.authenticated = True
    result.modules = sorted(
        line.split("\t")[0].strip()
        for line in listing.stdout.splitlines()
        if line.strip() and not line.startswith("@")
    )
    result.messages.append(f"Modules available: {', '.join(result.modules) or 'none'}")

    wanted = (conn.rsync_module or "").strip().strip("/")
    if wanted:
        result.module_found = wanted in result.modules
        if not result.module_found:
            result.messages.append(
                f"Module '{wanted}' is not published by this device. "
                f"Check the module name in its rsync server settings."
            )
    return result
