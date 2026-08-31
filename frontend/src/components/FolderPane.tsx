import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  formatBytes,
  type BrowseEntry,
  type Connection,
  type FolderSize,
  type Transport,
} from "../api";

export interface PaneSelection {
  connId: number | null;
  path: string;
}

export function FolderPane({
  title,
  connections,
  selection,
  onChange,
  transport,
}: {
  title: string;
  connections: Connection[];
  selection: PaneSelection;
  onChange: (s: PaneSelection) => void;
  transport: Transport;
}) {
  const [entries, setEntries] = useState<BrowseEntry[]>([]);
  const [parent, setParent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState<FolderSize | null>(null);
  const [sizing, setSizing] = useState(false);

  const { connId, path } = selection;

  useEffect(() => {
    if (connId === null) {
      setEntries([]);
      setParent(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    setSize(null);
    api
      .browse(connId, path, transport)
      .then((r) => {
        if (!active) return;
        setEntries(r.entries);
        setParent(r.parent);
      })
      .catch((e) => active && setError(e instanceof ApiError ? e.message : "Browse failed"))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [connId, path, transport]);

  function selectConnection(id: number) {
    const conn = connections.find((c) => c.id === id);
    // Each transport has its own path vocabulary, so the starting folder differs:
    // FTP begins at the FTP root, rsync at the device's real filesystem root.
    onChange({ connId: id, path: rootFor(conn, transport) });
  }

  async function computeSize() {
    if (connId === null) return;
    setSizing(true);
    try {
      setSize(await api.folderSize(connId, path, transport));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Size calc failed");
    } finally {
      setSizing(false);
    }
  }

  return (
    <div className="pane">
      <div className="pane-head">
        <span className="pane-title">{title}</span>
        <select
          value={connId ?? ""}
          onChange={(e) => selectConnection(Number(e.target.value))}
        >
          <option value="" disabled>
            Select NAS…
          </option>
          {connections.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {connId === null ? (
        <p className="muted pane-empty">Choose a NAS to browse.</p>
      ) : (
        <>
          <div className="pane-path">
            <code>{path}</code>
          </div>
          {error && <p className="error-text small">{error}</p>}
          <div className="pane-list">
            {parent !== null && (
              <button className="entry up" onClick={() => onChange({ connId, path: parent })}>
                <span className="entry-icon">↰</span> ..
              </button>
            )}
            {loading && <div className="muted small entry-loading">Loading…</div>}
            {!loading &&
              entries.map((e) =>
                e.type === "dir" ? (
                  <button
                    key={e.path}
                    className="entry dir"
                    onClick={() => onChange({ connId, path: e.path })}
                    title={e.path}
                  >
                    <span className="entry-icon">📁</span>
                    <span className="entry-name">{e.name}</span>
                  </button>
                ) : (
                  <div key={e.path} className="entry file" title={e.path}>
                    <span className="entry-icon">📄</span>
                    <span className="entry-name">{e.name}</span>
                    <span className="entry-size">{formatBytes(e.size)}</span>
                  </div>
                )
              )}
            {!loading && entries.length === 0 && parent === null && (
              <div className="muted small entry-loading">Empty folder.</div>
            )}
          </div>
          <div className="pane-foot">
            <button className="btn small-btn" onClick={computeSize} disabled={sizing}>
              {sizing ? "Calculating…" : "Folder size"}
            </button>
            {size && (
              <span className="muted small">
                {formatBytes(size.total_bytes)} · {size.file_count} files · {size.folder_count} folders
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}


/** Where a pane should start for a given transport. */
export function rootFor(conn: Connection | undefined, transport: Transport): string {
  if (!conn) return "/";
  return transport === "rsync" ? conn.fs_root || "/" : conn.root_path || "/";
}
