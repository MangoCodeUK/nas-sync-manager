import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  type Connection,
  type JobInput,
  type Plan,
  type RsyncEnvironment,
} from "../api";
import { PlanPreview } from "./PlanPreview";

const JOB_TYPES = [
  ["copy", "Copy - add new files, never delete"],
  ["mirror", "Mirror - keep destination aligned with source"],
  ["move", "Move - copy, verify, then delete source (with approval)"],
] as const;

// What the job does and how bytes move are separate choices.
const TRANSPORTS = [
  ["ftp", "FTP - works with any share, no setup"],
  ["rsync", "rsync - faster, only transfers what changed"],
] as const;

const CONFLICTS = [
  ["skip", "Skip existing file"],
  ["overwrite_if_newer", "Overwrite if source is newer"],
  ["overwrite_if_size_differs", "Overwrite if size differs"],
  ["overwrite_if_newer_or_size_differs", "Overwrite if newer or size differs"],
  ["always_overwrite", "Always overwrite"],
  ["rename", "Rename destination copy"],
  ["keep_both", "Keep both"],
] as const;

const VERIFICATION = [
  [1, "Level 1 - Exists + size"],
  [2, "Level 2 - Timestamp + size"],
  [3, "Level 3 - Checksum where available"],
  [4, "Level 4 - Download and hash"],
] as const;

const DELETE_STRATEGIES = [
  ["manual_approval", "Manual approval (recommended)"],
  ["auto_delete_after_verification", "Auto-delete after verification"],
  ["archive", "Archive instead of delete"],
  ["never", "Never delete"],
] as const;

const SCHEDULES = [
  ["manual", "Manual only"],
  ["interval", "Every X minutes"],
  ["hourly", "Hourly"],
  ["daily", "Daily"],
  ["weekly", "Weekly"],
  ["monthly", "Monthly"],
  ["cron", "Custom cron"],
] as const;

const SCHEDULE_HINT: Record<string, string> = {
  interval: "Value = number of minutes (e.g. 30)",
  daily: "Value = time HH:MM (e.g. 02:30)",
  weekly: "Value = DOW HH:MM (e.g. SUN 02:30)",
  monthly: "Value = DOM HH:MM (e.g. 1 02:30)",
  cron: "Value = cron expression (e.g. 0 2 * * *)",
};

export function JobEditor({
  connections,
  initial,
  jobId,
  onSaved,
  onCancel,
}: {
  connections: Connection[];
  initial: JobInput;
  jobId: number | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<JobInput>(initial);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof JobInput>(k: K, v: JobInput[K]) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function preview() {
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      setPlan(
        await api.previewJob({
          job_type: form.job_type,
          transport: form.transport,
          source_connection_id: form.source_connection_id,
          source_path: form.source_path,
          destination_connection_id: form.destination_connection_id,
          destination_path: form.destination_path,
          conflict_strategy: form.conflict_strategy,
          delete_strategy: form.delete_strategy,
          mirror_mode: form.mirror_mode,
          include_filters: form.include_filters,
          exclude_filters: form.exclude_filters,
          rsync_compress: form.rsync_compress,
          rsync_bandwidth_kbps: form.rsync_bandwidth_kbps,
        })
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (jobId) await api.updateJob(jobId, form);
      else await api.createJob(form);
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form" onSubmit={save}>
      <fieldset>
        <legend>{jobId ? "Edit job" : "New job"}</legend>
        <label className="field">
          <span>Job name</span>
          <input value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <label className="field">
          <span>Job type</span>
          <select value={form.job_type} onChange={(e) => set("job_type", e.target.value as JobInput["job_type"])}>
            {JOB_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Transport</span>
          <select
            value={form.transport}
            onChange={(e) => set("transport", e.target.value as JobInput["transport"])}
          >
            {TRANSPORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {form.transport === "rsync" && <RsyncNotice />}
        <label className="field">
          <span>Description (optional)</span>
          <input value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
        </label>
      </fieldset>

      <fieldset>
        <legend>Source &rarr; Destination</legend>
        <div className="field-row">
          <label className="field">
            <span>Source NAS</span>
            <select value={form.source_connection_id} onChange={(e) => set("source_connection_id", Number(e.target.value))}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Source path</span>
            <input value={form.source_path} onChange={(e) => set("source_path", e.target.value)} required />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span>Destination NAS</span>
            <select value={form.destination_connection_id} onChange={(e) => set("destination_connection_id", Number(e.target.value))}>
              {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Destination path</span>
            <input value={form.destination_path} onChange={(e) => set("destination_path", e.target.value)} required />
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Behaviour</legend>
        <label className="field">
          <span>Conflict handling</span>
          <select value={form.conflict_strategy} onChange={(e) => set("conflict_strategy", e.target.value)}>
            {CONFLICTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Verification level</span>
          <select value={form.verification_level} onChange={(e) => set("verification_level", Number(e.target.value))}>
            {VERIFICATION.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        {form.job_type === "mirror" && (
          <label className="field">
            <span>Mirror mode</span>
            <select value={form.mirror_mode} onChange={(e) => set("mirror_mode", e.target.value)}>
              <option value="safe">Safe - never delete destination-only files</option>
              <option value="strict">Strict - delete destination-only files</option>
            </select>
          </label>
        )}
        {form.job_type === "move" && (
          <label className="field">
            <span>Delete strategy</span>
            <select value={form.delete_strategy} onChange={(e) => set("delete_strategy", e.target.value)}>
              {DELETE_STRATEGIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
        <div className="field-row">
          <label className="field">
            <span>Include filters (one per line)</span>
            <textarea rows={3} value={form.include_filters ?? ""} onChange={(e) => set("include_filters", e.target.value)} />
          </label>
          <label className="field">
            <span>Exclude filters (one per line)</span>
            <textarea rows={3} value={form.exclude_filters ?? ""} onChange={(e) => set("exclude_filters", e.target.value)} />
          </label>
        </div>
      </fieldset>

      {form.transport === "rsync" && (
        <fieldset>
          <legend>rsync options</legend>
          <label className="field check">
            <input
              type="checkbox"
              checked={form.rsync_compress ?? false}
              onChange={(e) => set("rsync_compress", e.target.checked)}
            />
            <span>Compress during transfer</span>
          </label>
          <p className="muted small">
            Leave off for media on a local network - compressing already-compressed
            files costs CPU on both devices and saves almost nothing.
          </p>
          <label className="field">
            <span>Bandwidth limit (KB/s, blank = unlimited)</span>
            <input
              type="number"
              min={1}
              value={form.rsync_bandwidth_kbps ?? ""}
              onChange={(e) =>
                set("rsync_bandwidth_kbps", e.target.value ? Number(e.target.value) : null)
              }
            />
          </label>
        </fieldset>
      )}

      <fieldset>
        <legend>Schedule</legend>
        <div className="field-row">
          <label className="field">
            <span>When</span>
            <select value={form.schedule_type} onChange={(e) => set("schedule_type", e.target.value)}>
              {SCHEDULES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          {form.schedule_type !== "manual" && form.schedule_type !== "hourly" && (
            <label className="field">
              <span>Value</span>
              <input value={form.schedule_value ?? ""} onChange={(e) => set("schedule_value", e.target.value)} />
            </label>
          )}
        </div>
        {SCHEDULE_HINT[form.schedule_type] && <p className="muted small">{SCHEDULE_HINT[form.schedule_type]}</p>}
        <label className="field check">
          <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          <span>Enabled</span>
        </label>
      </fieldset>

      {error && <p className="error-text">{error}</p>}
      {plan && <PlanPreview plan={plan} title="Preview (no changes made)" />}

      <div className="form-actions">
        <button type="submit" className="btn primary" disabled={busy}>
          {jobId ? "Save changes" : "Create job"}
        </button>
        <button type="button" className="btn" onClick={preview} disabled={busy}>
          {busy ? "Working…" : "Preview"}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
}


/**
 * What rsync can actually reach right now.
 *
 * Shown the moment rsync is selected, because the commonest failure is picking a
 * path whose share is not bind-mounted into the container - far better to say so
 * here than to let the job fail later with a raw rsync error.
 */
function RsyncNotice() {
  const [env, setEnv] = useState<RsyncEnvironment | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api.rsyncEnvironment().then(setEnv).catch(() => setFailed(true));
  }, []);

  if (failed) return <p className="muted small">Could not check the rsync environment.</p>;
  if (!env) return <p className="muted small">Checking rsync…</p>;

  if (!env.rsync_available) {
    return (
      <p className="error-text">
        rsync is not available in this container{env.rsync_error ? `: ${env.rsync_error}` : "."}
      </p>
    );
  }

  return (
    <div className="muted small">
      <p>
        rsync {env.rsync_version} (protocol {env.rsync_protocol}).{" "}
        {env.mounts.length === 0
          ? "No NAS shares are mounted, so rsync jobs have nowhere local to read or write."
          : "Shares available to rsync on this device:"}
      </p>
      {env.mounts.length > 0 && (
        <ul className="plan-warnings">
          {env.mounts.map((m) => (
            <li key={m.container_path}>
              <code>{m.host_path}</code> {m.read_only ? "(read-only - source only)" : "(read/write)"}
            </li>
          ))}
        </ul>
      )}
      <p>
        A path on the other device is reached over rsync instead, using that
        connection's rsync settings.
      </p>
    </div>
  );
}
