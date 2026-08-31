import { useEffect, useState } from "react";
import { api, ApiError, type Connection, type ConnectionInput, type TestResult } from "../api";

const EMPTY: ConnectionInput = {
  name: "",
  host: "",
  protocol: "ftp",
  port: 21,
  username: "",
  password: "",
  root_path: "/",
  passive_mode: true,
  timeout_seconds: 30,
  description: "",
  fs_root: "",
  rsync_enabled: false,
  rsync_mode: "daemon",
  rsync_host: "",
  rsync_port: 873,
  rsync_module: "",
  rsync_username: "",
  rsync_password: "",
  rsync_ssh_port: 22,
};

export function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [editing, setEditing] = useState<ConnectionInput | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The saved record behind the form, so the password field can say whether one
  // is already stored without the API ever returning the secret itself.
  const current = editingId ? connections.find((c) => c.id === editingId) : undefined;

  async function refresh() {
    try {
      setConnections(await api.listConnections());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load connections");
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  function startAdd() {
    setEditing({ ...EMPTY });
    setEditingId(null);
    setTest(null);
    setError(null);
  }
  function startEdit(c: Connection) {
    setEditing({ ...c, password: "" }); // blank = keep existing password
    setEditingId(c.id);
    setTest(null);
    setError(null);
  }
  function cancel() {
    setEditing(null);
    setEditingId(null);
    setTest(null);
  }

  function set<K extends keyof ConnectionInput>(k: K, v: ConnectionInput[K]) {
    setEditing((e) => (e ? { ...e, [k]: v } : e));
  }

  async function onTest() {
    if (!editing) return;
    setBusy(true);
    setTest(null);
    setError(null);
    try {
      // Test the saved row when editing without a new password; else test the form.
      const result =
        editingId && !editing.password
          ? await api.testConnection(editingId)
          : await api.testConfig(editing);
      setTest(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Test failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      if (editingId) {
        const patch: Partial<ConnectionInput> = { ...editing };
        if (!editing.password) delete patch.password; // don't overwrite with blank
        await api.updateConnection(editingId, patch);
      } else {
        await api.createConnection(editing);
      }
      await refresh();
      cancel();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(c: Connection) {
    if (!confirm(`Delete connection "${c.name}"?`)) return;
    try {
      await api.deleteConnection(c.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Delete failed");
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Connections</h1>
        {!editing && (
          <button className="btn primary" onClick={startAdd}>
            Add connection
          </button>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      {!editing && (
        <div className="card-list">
          {connections.length === 0 && <p className="muted">No NAS connections yet.</p>}
          {connections.map((c) => (
            <div key={c.id} className="card">
              <div className="card-main">
                <div className="card-title">
                  {c.name} <span className="tag">{c.protocol.toUpperCase()}</span>
                </div>
                <div className="muted small">
                  {c.username}@{c.host}:{c.port} &nbsp;root {c.root_path}
                </div>
                {c.last_test_status && (
                  <div className={c.last_test_status.startsWith("OK") ? "ok-text small" : "error-text small"}>
                    {c.last_test_status}
                  </div>
                )}
              </div>
              <div className="card-actions">
                <button className="btn" onClick={() => startEdit(c)}>
                  Edit
                </button>
                <button className="btn" onClick={() => onDelete(c)}>
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <form onSubmit={onSave} className="form">
          <fieldset>
            <legend>{editingId ? "Edit connection" : "New connection"}</legend>
            <label className="field">
              <span>Display name</span>
              <input value={editing.name} onChange={(e) => set("name", e.target.value)} required />
            </label>
            <div className="field-row">
              <label className="field">
                <span>Host / IP</span>
                <input value={editing.host} onChange={(e) => set("host", e.target.value)} required />
              </label>
              <label className="field narrow">
                <span>Protocol</span>
                <select value={editing.protocol} onChange={(e) => set("protocol", e.target.value as "ftp" | "ftps")}>
                  <option value="ftp">FTP</option>
                  <option value="ftps">FTPS</option>
                </select>
              </label>
              <label className="field narrow">
                <span>Port</span>
                <input type="number" min={1} max={65535} value={editing.port} onChange={(e) => set("port", Number(e.target.value))} />
              </label>
            </div>
            <div className="field-row">
              <label className="field">
                <span>Username</span>
                <input value={editing.username} onChange={(e) => set("username", e.target.value)} required />
              </label>
              <label className="field">
                <span>{editingId ? "Password (blank = unchanged)" : "Password"}</span>
                <input type="password" value={editing.password ?? ""} onChange={(e) => set("password", e.target.value)} />
              </label>
            </div>
            <div className="field-row">
              <label className="field">
                <span>Root path</span>
                <input value={editing.root_path} onChange={(e) => set("root_path", e.target.value)} />
              </label>
              <label className="field narrow">
                <span>Timeout (s)</span>
                <input type="number" min={1} max={600} value={editing.timeout_seconds} onChange={(e) => set("timeout_seconds", Number(e.target.value))} />
              </label>
            </div>
            <label className="field check">
              <input type="checkbox" checked={editing.passive_mode} onChange={(e) => set("passive_mode", e.target.checked)} />
              <span>Passive mode</span>
            </label>
            <label className="field">
              <span>Description (optional)</span>
              <input value={editing.description ?? ""} onChange={(e) => set("description", e.target.value)} />
            </label>
          </fieldset>

          <fieldset>
            <legend>rsync (optional)</legend>
            <label className="field">
              <span>Filesystem root on this device</span>
              <input
                placeholder="/Volume1 or /mnt/md0"
                value={editing.fs_root ?? ""}
                onChange={(e) => set("fs_root", e.target.value)}
              />
            </label>
            <p className="muted small">
              The device's real path, which is not the same as the FTP root above.
              The 14&nbsp;TB device uses <code>/Volume1</code>; the 8&nbsp;TB one uses{" "}
              <code>/mnt/md0</code>.
            </p>
            <label className="field check">
              <input
                type="checkbox"
                checked={editing.rsync_enabled ?? false}
                onChange={(e) => set("rsync_enabled", e.target.checked)}
              />
              <span>This device runs an rsync server</span>
            </label>
            {editing.rsync_enabled && (
              <>
                <label className="field">
                  <span>Mode</span>
                  <select
                    value={editing.rsync_mode ?? "daemon"}
                    onChange={(e) => set("rsync_mode", e.target.value as "daemon" | "ssh")}
                  >
                    <option value="daemon">Daemon - the device's rsync service (port 873)</option>
                    <option value="ssh">SSH - tunnel rsync over SSH</option>
                  </select>
                </label>
                <div className="field-row">
                  <label className="field">
                    <span>rsync host (blank = same as above)</span>
                    <input
                      value={editing.rsync_host ?? ""}
                      onChange={(e) => set("rsync_host", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>{editing.rsync_mode === "ssh" ? "SSH port" : "rsync port"}</span>
                    <input
                      type="number"
                      min={1}
                      max={65535}
                      value={
                        editing.rsync_mode === "ssh"
                          ? editing.rsync_ssh_port ?? 22
                          : editing.rsync_port ?? 873
                      }
                      onChange={(e) =>
                        set(
                          editing.rsync_mode === "ssh" ? "rsync_ssh_port" : "rsync_port",
                          Number(e.target.value)
                        )
                      }
                    />
                  </label>
                </div>
                {editing.rsync_mode === "daemon" && (
                  <label className="field">
                    <span>Module</span>
                    <input
                      placeholder="RsyncSourceTest"
                      value={editing.rsync_module ?? ""}
                      onChange={(e) => set("rsync_module", e.target.value)}
                    />
                  </label>
                )}
                <div className="field-row">
                  <label className="field">
                    <span>rsync username</span>
                    <input
                      placeholder="nassync"
                      value={editing.rsync_username ?? ""}
                      onChange={(e) => set("rsync_username", e.target.value)}
                    />
                  </label>
                  <label className="field">
                    <span>
                      rsync password
                      {editingId && current?.rsync_password_set ? " (saved - leave blank to keep)" : ""}
                    </span>
                    <input
                      type="password"
                      value={editing.rsync_password ?? ""}
                      onChange={(e) => set("rsync_password", e.target.value)}
                    />
                  </label>
                </div>
                <p className="muted small">
                  Stored encrypted, and never sent back to this page. It is passed to
                  rsync out of band, so it never appears in a command or a log.
                </p>
              </>
            )}
          </fieldset>

          {test && (
            <div className={test.ok ? "test-result ok" : "test-result bad"}>
              <strong>{test.summary}</strong>
              <ul className="test-checks">
                <li>Connectivity: {test.connectivity ? "yes" : "no"}</li>
                <li>Authentication: {test.authentication ? "yes" : "no"}</li>
                <li>List root: {test.can_list ? "yes" : "no"}</li>
                <li>Write access: {test.can_write === null ? "n/a" : test.can_write ? "yes" : "no"}</li>
                <li>Delete access: {test.can_delete === null ? "n/a" : test.can_delete ? "yes" : "no"}</li>
              </ul>
            </div>
          )}

          <div className="form-actions">
            <button type="submit" className="btn primary" disabled={busy}>
              {editingId ? "Save changes" : "Create"}
            </button>
            <button type="button" className="btn" onClick={onTest} disabled={busy}>
              {busy ? "Testing…" : "Test connection"}
            </button>
            <button type="button" className="btn" onClick={cancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
