import { formatBytes, type JobRun } from "../api";

const STATUS_CLASS: Record<string, string> = {
  running: "chip",
  success: "chip chip-copy",
  partial: "chip chip-update",
  failed: "chip chip-delete",
  cancelled: "chip chip-warn",
};

// Bytes/sec: use the recorded duration once finished, otherwise wall-clock since
// the run started (it updates each poll, so the live figure is an average so far).
function transferRate(run: JobRun): number | null {
  if (run.bytes_transferred <= 0) return null;
  const elapsed =
    run.duration_seconds ??
    Math.max((Date.now() - new Date(run.started_at).getTime()) / 1000, 0.001);
  if (!elapsed || elapsed <= 0) return null;
  return run.bytes_transferred / elapsed;
}

// Fraction done, preferring bytes (smooth during big files) then file counts.
function progressPct(run: JobRun): number | null {
  if (run.bytes_total > 0) return Math.min(100, (run.bytes_transferred / run.bytes_total) * 100);
  if (run.files_total > 0)
    return Math.min(100, ((run.files_copied + run.files_updated + run.files_failed) / run.files_total) * 100);
  return null;
}

export function RunStatus({
  name,
  run,
  onCancel,
  cancelling,
}: {
  name: string;
  run: JobRun;
  onCancel?: () => void;
  cancelling?: boolean;
}) {
  const running = run.status === "running";
  const rate = transferRate(run);
  const pct = progressPct(run);
  const done = run.files_copied + run.files_updated + run.files_failed;
  // "Found" = everything the plan looked at: transfers + already-in-sync skips.
  const found = run.files_total + run.files_skipped;

  return (
    <div className="plan run-status">
      <div className="run-head-row">
        <h3 className="plan-title" style={{ margin: 0 }}>
          {running ? "Running" : "Finished"}: {name}{" "}
          <span className={STATUS_CLASS[run.status] ?? "chip"}>{run.status}</span>
        </h3>
        {running && onCancel && (
          <button className="btn small-btn" onClick={onCancel} disabled={cancelling}>
            {cancelling ? "Cancelling…" : "Cancel"}
          </button>
        )}
      </div>

      {running && (
        <div className="progress">
          <div
            className={`progress-fill${pct == null ? " indeterminate" : ""}`}
            style={pct == null ? undefined : { width: `${pct}%` }}
          />
        </div>
      )}

      {run.files_total > 0 && (
        <p className="muted small" style={{ margin: "2px 0" }}>
          {found} files found · {done} of {run.files_total} to transfer
          {pct != null ? ` · ${Math.floor(pct)}%` : ""} ·{" "}
          {formatBytes(run.bytes_transferred)}
          {run.bytes_total > 0 ? ` / ${formatBytes(run.bytes_total)}` : ""}
        </p>
      )}

      {running && run.current_item && (
        <p className="run-current">
          <span className="mono">Transferring:</span> {run.current_item}
        </p>
      )}

      <div className="plan-counts">
        <span className="chip chip-copy">{run.files_copied} copied</span>
        <span className="chip chip-update">{run.files_updated} updated</span>
        <span className="chip chip-skip">{run.files_skipped} skipped</span>
        {run.files_deleted > 0 && <span className="chip chip-delete">{run.files_deleted} deleted</span>}
        {run.files_failed > 0 && <span className="chip chip-delete">{run.files_failed} failed</span>}
        <span className="chip">{formatBytes(run.bytes_transferred)} transferred</span>
        {rate != null && <span className="chip">{formatBytes(rate)}/s</span>}
        {run.duration_seconds != null && <span className="chip">{run.duration_seconds}s</span>}
      </div>

      {run.summary && !running && <p className="muted small">{run.summary}</p>}
      {run.error_message && <p className="error-text small">{run.error_message}</p>}
    </div>
  );
}
