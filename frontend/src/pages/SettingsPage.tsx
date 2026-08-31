import { useEffect, useState } from "react";
import { api, ApiError, type Settings } from "../api";

const CONFLICT_OPTIONS = [
  ["skip", "Skip existing file"],
  ["overwrite_if_newer", "Overwrite if source is newer"],
  ["overwrite_if_size_differs", "Overwrite if size differs"],
  ["overwrite_if_newer_or_size_differs", "Overwrite if newer or size differs"],
  ["always_overwrite", "Always overwrite"],
  ["rename", "Rename destination copy"],
  ["keep_both", "Keep both"],
] as const;

const VERIFICATION_OPTIONS = [
  [1, "Level 1 - Exists + size"],
  [2, "Level 2 - Timestamp + size"],
  [3, "Level 3 - Checksum where available"],
  [4, "Level 4 - Download and hash"],
] as const;

const MODE_OPTIONS = [
  ["copy", "Copy"],
  ["mirror", "Mirror"],
  ["move", "Move"],
] as const;

export function SettingsPage() {
  const [form, setForm] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backupMsg, setBackupMsg] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then(setForm)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load settings"))
      .finally(() => setLoading(false));
  }, []);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const saved = await api.updateSettings(form);
      setForm(saved);
      setMessage("Settings saved.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function exportConfig() {
    setBackupMsg(null);
    try {
      const doc = await api.exportBackup();
      const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nas-sync-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setBackupMsg(err instanceof ApiError ? err.message : "Export failed");
    }
  }

  async function importConfig(file: File) {
    if (!confirm("Importing REPLACES all connections and jobs with the backup contents. Continue?")) return;
    setBackupMsg(null);
    try {
      const doc = JSON.parse(await file.text());
      const res = await api.importBackup(doc);
      setBackupMsg(`Imported ${res.connections} connections and ${res.jobs} jobs.`);
      setForm(await api.getSettings());
    } catch (err) {
      setBackupMsg(err instanceof ApiError ? err.message : "Import failed - invalid file?");
    }
  }

  if (loading) return <div className="page"><h1>Settings</h1><p className="muted">Loading…</p></div>;
  if (!form) return <div className="page"><h1>Settings</h1><p className="error-text">{error}</p></div>;

  const num = (v: string) => (v === "" ? null : Number(v));

  return (
    <div className="page">
      <h1>Settings</h1>
      <p className="muted">Global defaults. Deletion safety limits default to zero - nothing is deleted automatically.</p>

      <form onSubmit={onSave} className="form">
        <fieldset>
          <legend>General</legend>
          <label className="field">
            <span>Timezone</span>
            <input value={form.timezone} onChange={(e) => update("timezone", e.target.value)} />
          </label>
          <label className="field">
            <span>Default transfer mode</span>
            <select value={form.default_transfer_mode} onChange={(e) => update("default_transfer_mode", e.target.value)}>
              {MODE_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Default verification level</span>
            <select value={form.default_verification_level} onChange={(e) => update("default_verification_level", Number(e.target.value))}>
              {VERIFICATION_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Default conflict handling</span>
            <select value={form.default_conflict_strategy} onChange={(e) => update("default_conflict_strategy", e.target.value)}>
              {CONFLICT_OPTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field check">
            <input type="checkbox" checked={form.preserve_timestamps} onChange={(e) => update("preserve_timestamps", e.target.checked)} />
            <span>Preserve file timestamps where the FTP server allows</span>
          </label>
        </fieldset>

        <fieldset>
          <legend>Transfers</legend>
          <label className="field">
            <span>Max concurrent transfers</span>
            <input type="number" min={1} max={16} value={form.max_concurrent_transfers} onChange={(e) => update("max_concurrent_transfers", Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Max bandwidth (KB/s, blank = unlimited)</span>
            <input type="number" min={0} value={form.max_bandwidth_kbps ?? ""} onChange={(e) => update("max_bandwidth_kbps", num(e.target.value))} />
          </label>
          <label className="field">
            <span>Retry count</span>
            <input type="number" min={0} max={20} value={form.retry_count} onChange={(e) => update("retry_count", Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Retry delay (seconds)</span>
            <input type="number" min={0} max={3600} value={form.retry_delay_seconds} onChange={(e) => update("retry_delay_seconds", Number(e.target.value))} />
          </label>
        </fieldset>

        <fieldset>
          <legend>Safety</legend>
          <label className="field check">
            <input type="checkbox" checked={form.require_manual_approval_for_deletes} onChange={(e) => update("require_manual_approval_for_deletes", e.target.checked)} />
            <span>Require manual approval for all deletes</span>
          </label>
          <label className="field">
            <span>Max automatic source deletes per job</span>
            <input type="number" min={0} value={form.max_auto_source_deletes} onChange={(e) => update("max_auto_source_deletes", Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Max automatic destination deletes per job</span>
            <input type="number" min={0} value={form.max_auto_destination_deletes} onChange={(e) => update("max_auto_destination_deletes", Number(e.target.value))} />
          </label>
          <label className="field">
            <span>Max deletions as % of destination</span>
            <input
              type="number"
              min={1}
              max={100}
              value={form.max_delete_percent}
              onChange={(e) => update("max_delete_percent", Number(e.target.value))}
            />
            <span className="muted small">
              A second, proportional guard. A run that would remove more than this
              share of the destination is stopped even when the count above allows
              it - removing most of a folder is usually a wrong path, not a tidy-up.
            </span>
          </label>
          <label className="field">
            <span>Archive path template</span>
            <input value={form.archive_path_template} onChange={(e) => update("archive_path_template", e.target.value)} />
          </label>
        </fieldset>

        <fieldset>
          <legend>Logs</legend>
          <label className="field">
            <span>Log retention (days)</span>
            <input type="number" min={1} max={3650} value={form.log_retention_days} onChange={(e) => update("log_retention_days", Number(e.target.value))} />
          </label>
        </fieldset>

        <div className="form-actions">
          <button type="submit" className="btn primary" disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
          {message && <span className="ok-text">{message}</span>}
          {error && <span className="error-text">{error}</span>}
        </div>
      </form>

      <div className="form">
        <fieldset>
          <legend>Backup &amp; Restore</legend>
          <p className="muted small">
            Export settings, connections (encrypted) and jobs to a JSON file. Import replaces the
            current configuration.
          </p>
          <div className="form-actions">
            <button type="button" className="btn" onClick={exportConfig}>
              Export configuration
            </button>
            <label className="btn">
              Import…
              <input
                type="file"
                accept="application/json"
                hidden
                onChange={(e) => e.target.files?.[0] && importConfig(e.target.files[0])}
              />
            </label>
            {backupMsg && <span className="ok-text small">{backupMsg}</span>}
          </div>
        </fieldset>
      </div>
    </div>
  );
}
