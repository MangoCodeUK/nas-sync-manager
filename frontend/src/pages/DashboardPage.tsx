import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, formatDateTime, type Dashboard } from "../api";

const STATUS_CLASS: Record<string, string> = {
  success: "ok-text",
  failed: "error-text",
  partial: "error-text",
  running: "",
  skipped: "muted",
};

export function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () =>
      api
        .getDashboard()
        .then(setData)
        .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load"));
    load();
    const id = setInterval(load, 8000);
    return () => clearInterval(id);
  }, []);

  if (error) return <div className="page"><h1>Dashboard</h1><p className="error-text">{error}</p></div>;
  if (!data) return <div className="page"><h1>Dashboard</h1><p className="muted">Loading…</p></div>;

  return (
    <div className="page">
      <h1>Dashboard</h1>

      <div className="stat-grid">
        <Stat label="Connections" value={data.connections_total} to="/connections" />
        <Stat label="Jobs" value={data.jobs_total} sub={`${data.jobs_enabled} enabled`} to="/jobs" />
        <Stat label="Running" value={data.jobs_running} />
        <Stat label="Failed" value={data.jobs_failed} bad={data.jobs_failed > 0} to="/logs" />
        <Stat
          label="Pending deletions"
          value={data.pending_deletions}
          bad={data.pending_deletions > 0}
          to="/pending-deletions"
        />
      </div>

      <div className="dash-cols">
        <div className="dash-card">
          <h3>Schedule</h3>
          <p className="muted small">
            Last success:{" "}
            {data.last_success_job
              ? `${data.last_success_job} · ${formatDateTime(data.last_success_at)}`
              : "none yet"}
          </p>
          <p className="muted small">
            Next run:{" "}
            {data.next_run_job
              ? `${data.next_run_job} · ${formatDateTime(data.next_run_at)}`
              : "no scheduled jobs"}
          </p>
        </div>

        <div className="dash-card">
          <h3>Connection status</h3>
          {data.connections.length === 0 && <p className="muted small">No connections.</p>}
          {data.connections.map((c) => (
            <p key={c.id} className="small">
              <span className={c.last_test_status?.startsWith("OK") ? "dot dot-ok" : "dot dot-bad"} />{" "}
              {c.name} <span className="muted">{c.last_test_status ?? "untested"}</span>
            </p>
          ))}
        </div>
      </div>

      <h3 className="section-title">Recent activity</h3>
      {data.recent_runs.length === 0 ? (
        <p className="muted">No runs yet. <Link to="/jobs">Create a job</Link>.</p>
      ) : (
        <table>
          <thead>
            <tr><th>Job</th><th>Type</th><th>Status</th><th>When</th></tr>
          </thead>
          <tbody>
            {data.recent_runs.map((r) => (
              <tr key={r.id}>
                <td>{r.job_name ?? "-"}</td>
                <td>{r.run_type}</td>
                <td className={STATUS_CLASS[r.status] ?? ""}>{r.status}</td>
                <td className="small">{formatDateTime(r.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, value, sub, bad, to }: { label: string; value: number; sub?: string; bad?: boolean; to?: string }) {
  const body = (
    <div className={`stat ${bad ? "stat-bad" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub muted">{sub}</div>}
    </div>
  );
  return to ? <Link to={to} className="stat-link">{body}</Link> : body;
}
