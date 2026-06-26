import { Fragment, useEffect, useState } from "react";
import { api, ApiError, formatBytes, formatDateTime, type JobRun, type RunItem } from "../api";

const STATUS_CLASS: Record<string, string> = {
  success: "ok-text",
  failed: "error-text",
  partial: "error-text",
  skipped: "muted",
  running: "",
};

export function LogsPage() {
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [filters, setFilters] = useState({ status: "", run_type: "", error_only: false });
  const [expanded, setExpanded] = useState<number | null>(null);
  const [items, setItems] = useState<RunItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const params: Record<string, string> = {};
    if (filters.status) params.status = filters.status;
    if (filters.run_type) params.run_type = filters.run_type;
    if (filters.error_only) params.error_only = "true";
    try {
      setRuns(await api.runsLog(params));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load logs");
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  async function toggle(run: JobRun) {
    if (expanded === run.id) {
      setExpanded(null);
      return;
    }
    setExpanded(run.id);
    try {
      setItems(await api.runItems(run.id));
    } catch {
      setItems([]);
    }
  }

  return (
    <div className="page">
      <h1>Logs</h1>

      <div className="log-filters">
        <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
          <option value="">All statuses</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
          <option value="partial">Partial</option>
          <option value="skipped">Skipped</option>
        </select>
        <select value={filters.run_type} onChange={(e) => setFilters({ ...filters, run_type: e.target.value })}>
          <option value="">All types</option>
          <option value="manual">Manual</option>
          <option value="scheduled">Scheduled</option>
          <option value="dry_run">Dry-run</option>
        </select>
        <label className="field check">
          <input type="checkbox" checked={filters.error_only} onChange={(e) => setFilters({ ...filters, error_only: e.target.checked })} />
          <span>Errors only</span>
        </label>
      </div>

      {error && <p className="error-text">{error}</p>}
      {runs.length === 0 && <p className="muted">No runs match.</p>}

      {runs.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Job</th><th>Type</th><th>Status</th><th>Started</th>
              <th>Copied</th><th>Skipped</th><th>Failed</th><th>Data</th><th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <Fragment key={r.id}>
                <tr>
                  <td>{r.job_name ?? "-"}</td>
                  <td>{r.run_type}</td>
                  <td className={STATUS_CLASS[r.status] ?? ""}>{r.status}</td>
                  <td className="small">{formatDateTime(r.started_at)}</td>
                  <td>{r.files_copied + r.files_updated}</td>
                  <td>{r.files_skipped}</td>
                  <td className={r.files_failed ? "error-text" : ""}>{r.files_failed}</td>
                  <td>{formatBytes(r.bytes_transferred)}</td>
                  <td>
                    <button className="btn small-btn" onClick={() => toggle(r)}>
                      {expanded === r.id ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr>
                    <td colSpan={9}>
                      {r.summary && <p className="muted small">{r.summary}</p>}
                      {r.error_message && <p className="error-text small">{r.error_message}</p>}
                      <div className="plan-items">
                        <table>
                          <thead><tr><th>Action</th><th>Path</th><th>Status</th><th>Message</th></tr></thead>
                          <tbody>
                            {items.slice(0, 300).map((it) => (
                              <tr key={it.id} className={it.status === "failed" ? "row-delete" : ""}>
                                <td>{it.action}</td>
                                <td className="mono small">{it.destination_path ?? it.source_path}</td>
                                <td>{it.status}</td>
                                <td className="muted small">{it.message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
