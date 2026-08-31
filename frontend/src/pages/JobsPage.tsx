import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, formatDateTime, type Connection, type Job, type JobInput, type JobRun, type Plan } from "../api";
import { JobEditor } from "../components/JobEditor";
import { PlanPreview } from "../components/PlanPreview";
import { RunStatus } from "../components/RunStatus";

function emptyJob(connections: Connection[], over?: Partial<JobInput>): JobInput {
  const first = connections[0]?.id ?? 0;
  const second = connections[1]?.id ?? first;
  return {
    name: "",
    description: "",
    job_type: "copy",
    transport: "ftp",
    source_connection_id: first,
    source_path: "/",
    destination_connection_id: second,
    destination_path: "/",
    enabled: true,
    conflict_strategy: "overwrite_if_newer_or_size_differs",
    verification_level: 2,
    delete_strategy: "manual_approval",
    mirror_mode: "safe",
    archive_path: null,
    include_filters: "",
    exclude_filters: "",
    rsync_compress: false,
    rsync_bandwidth_kbps: null,
    schedule_type: "manual",
    schedule_value: "",
    ...over,
  };
}

export function JobsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [editor, setEditor] = useState<{ initial: JobInput; jobId: number | null } | null>(null);
  const [dryRun, setDryRun] = useState<{ name: string; plan: Plan } | null>(null);
  const [running, setRunning] = useState<{ name: string; run: JobRun } | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();

  // Poll a running job's status until it finishes.
  useEffect(() => {
    if (!running || running.run.status !== "running") return;
    const id = setTimeout(async () => {
      try {
        const run = await api.getRun(running.run.id);
        setRunning({ name: running.name, run });
        if (run.status !== "running") refresh();
      } catch {
        /* keep last state; will retry on next tick if still running */
      }
    }, 1500);
    return () => clearTimeout(id);
  }, [running]);

  // Surface ANY in-progress run - one started in another tab, a scheduled run, or
  // still going after a page refresh - so its progress bar shows without needing to
  // have clicked "Run now" in this tab. Idle-only; the poll above owns the active run.
  useEffect(() => {
    if (running && running.run.status === "running") return;
    let stop = false;
    const check = async () => {
      try {
        const rs = await api.runsLog({ status: "running" });
        if (!stop && rs.length > 0) {
          setRunning({ name: rs[0].job_name ?? "job", run: rs[0] });
        }
      } catch {
        /* ignore */
      }
    };
    check();
    const id = setInterval(check, 4000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [running]);

  async function refresh() {
    const [conns, jobList] = await Promise.all([api.listConnections(), api.listJobs()]);
    setConnections(conns);
    setJobs(jobList);
    return conns;
  }

  useEffect(() => {
    refresh()
      .then((conns) => {
        // Open a prefilled editor when arriving from Browse "create job from selection".
        if (params.get("new") === "1") {
          const over: Partial<JobInput> = {
            // Paths from Browse only make sense with the transport they were
            // browsed over, so it comes across with them.
            transport: params.get("transport") === "rsync" ? "rsync" : "ftp",
            source_connection_id: Number(params.get("src_conn")) || conns[0]?.id,
            source_path: params.get("src_path") || "/",
            destination_connection_id: Number(params.get("dst_conn")) || conns[1]?.id,
            destination_path: params.get("dst_path") || "/",
          };
          setEditor({ initial: emptyJob(conns, over), jobId: null });
          setParams({}, { replace: true });
        }
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startNew() {
    setDryRun(null);
    setEditor({ initial: emptyJob(connections), jobId: null });
  }
  function startEdit(j: Job) {
    setDryRun(null);
    setEditor({ initial: { ...(j as unknown as JobInput) }, jobId: j.id });
  }

  async function onSaved() {
    setEditor(null);
    await refresh();
  }

  async function doRun(j: Job) {
    setError(null);
    setDryRun(null);
    setCancelling(false);
    try {
      const run = await api.runJob(j.id);
      setRunning({ name: j.name, run });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Run failed to start");
    }
  }

  async function doCancel() {
    if (!running) return;
    setCancelling(true);
    try {
      await api.cancelJob(running.run.job_id);
    } catch (e) {
      setCancelling(false);
      setError(e instanceof ApiError ? e.message : "Cancel failed");
    }
  }

  async function doDryRun(j: Job) {
    setBusy(true);
    setError(null);
    setDryRun(null);
    try {
      const res = await api.dryRun(j.id);
      setDryRun({ name: j.name, plan: res.plan });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Dry-run failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEnabled(j: Job) {
    try {
      if (j.enabled) await api.disableJob(j.id);
      else await api.enableJob(j.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed");
    }
  }

  async function remove(j: Job) {
    if (!confirm(`Delete job "${j.name}"?`)) return;
    try {
      await api.deleteJob(j.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Delete failed");
    }
  }

  if (connections.length < 2 && !editor) {
    return (
      <div className="page">
        <h1>Jobs</h1>
        <p className="muted">
          Add at least two NAS connections before creating jobs. <a href="/connections">Connections</a>.
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Jobs</h1>
        {!editor && (
          <button className="btn primary" onClick={startNew}>
            New job
          </button>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      {running && (
        <RunStatus
          name={running.name}
          run={running.run}
          onCancel={doCancel}
          cancelling={cancelling}
        />
      )}

      {editor ? (
        <JobEditor
          connections={connections}
          initial={editor.initial}
          jobId={editor.jobId}
          onSaved={onSaved}
          onCancel={() => setEditor(null)}
        />
      ) : (
        <>
          {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
          {jobs.length > 0 && (
            <table className="jobs-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Via</th>
                  <th>Source &rarr; Destination</th>
                  <th>Schedule</th>
                  <th>Last run</th>
                  <th>Next run</th>
                  <th>Last result</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id} className={j.enabled ? "" : "disabled-row"}>
                    <td>
                      <strong>{j.name}</strong>
                      {!j.enabled && <span className="tag">disabled</span>}
                    </td>
                    <td>{j.job_type}</td>
                    <td>
                      <span className="tag">{j.transport}</span>
                    </td>
                    <td className="mono small">
                      {j.source_connection_name}:{j.source_path}
                      <br />→ {j.destination_connection_name}:{j.destination_path}
                    </td>
                    <td>{j.schedule_type}{j.schedule_value ? ` (${j.schedule_value})` : ""}</td>
                    <td className="small">{formatDateTime(j.last_run_at)}</td>
                    <td className="small">{j.enabled ? formatDateTime(j.next_run_at) : "-"}</td>
                    <td className={j.last_status === "failed" ? "error-text small" : "small"}>
                      {j.last_status ?? "-"}
                    </td>
                    <td className="job-actions">
                      <button
                        className="btn small-btn primary"
                        onClick={() => doRun(j)}
                        disabled={running?.run.status === "running" && running.name === j.name}
                      >
                        Run now
                      </button>
                      <button className="btn small-btn" onClick={() => doDryRun(j)} disabled={busy}>
                        Dry-run
                      </button>
                      <button className="btn small-btn" onClick={() => startEdit(j)}>
                        Edit
                      </button>
                      <button className="btn small-btn" onClick={() => toggleEnabled(j)}>
                        {j.enabled ? "Disable" : "Enable"}
                      </button>
                      <button className="btn small-btn" onClick={() => remove(j)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {dryRun && (
            <div className="dryrun-panel">
              <PlanPreview plan={dryRun.plan} title={`Dry-run: ${dryRun.name}`} />
            </div>
          )}
        </>
      )}
    </div>
  );
}
