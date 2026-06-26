import { formatBytes, type JobRun } from "../api";

const STATUS_CLASS: Record<string, string> = {
  running: "chip",
  success: "chip chip-copy",
  partial: "chip chip-update",
  failed: "chip chip-delete",
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

export function RunStatus({ name, run }: { name: string; run: JobRun }) {
  const running = run.status === "running";
  const rate = transferRate(run);
  return (
    <div className="plan run-status">
      <h3 className="plan-title">
        {running ? "Running" : "Finished"}: {name}{" "}
        <span className={STATUS_CLASS[run.status] ?? "chip"}>{run.status}</span>
      </h3>
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
      {running && (
        <p className="muted small">
          Working… {rate != null ? `${formatBytes(rate)}/s` : "starting transfer"} (updates every couple of seconds)
        </p>
      )}
      {run.summary && !running && <p className="muted small">{run.summary}</p>}
      {run.error_message && <p className="error-text small">{run.error_message}</p>}
    </div>
  );
}
