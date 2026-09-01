import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Connection, type Transport } from "../api";
import { FolderPane, type PaneSelection } from "../components/FolderPane";
import { rootFor } from "../paths";

export function BrowsePage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<PaneSelection>({ connId: null, path: "/" });
  const [dest, setDest] = useState<PaneSelection>({ connId: null, path: "/" });
  const [transport, setTransport] = useState<Transport>("ftp");
  const navigate = useNavigate();

  // Switching transport re-roots both panes: FTP and rsync describe the same
  // files with different paths, so a path carried across would be meaningless.
  function switchTransport(next: Transport) {
    setTransport(next);
    setSource((s) => ({ ...s, path: rootFor(connections.find((c) => c.id === s.connId), next) }));
    setDest((d) => ({ ...d, path: rootFor(connections.find((c) => c.id === d.connId), next) }));
  }

  useEffect(() => {
    api
      .listConnections()
      .then((c) => {
        setConnections(c);
        if (c.length >= 1) setSource({ connId: c[0].id, path: c[0].root_path || "/" });
        if (c.length >= 2) setDest({ connId: c[1].id, path: c[1].root_path || "/" });
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load connections"));
  }, []);

  const canCreate = source.connId !== null && dest.connId !== null;

  function createJob() {
    if (!canCreate) return;
    const q = new URLSearchParams({
      new: "1",
      transport,
      src_conn: String(source.connId),
      src_path: source.path,
      dst_conn: String(dest.connId),
      dst_path: dest.path,
    });
    navigate(`/jobs?${q.toString()}`);
  }

  if (connections.length < 2) {
    return (
      <div className="page">
        <h1>Browse</h1>
        {error && <p className="error-text">{error}</p>}
        <p className="muted">
          Add at least two NAS connections to browse them side by side.{" "}
          <a href="/connections">Go to Connections</a>.
        </p>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Browse</h1>
      {error && <p className="error-text">{error}</p>}

      <div className="browse-transport">
        <label className="field">
          <span>Browse over</span>
          <select value={transport} onChange={(e) => switchTransport(e.target.value as Transport)}>
            <option value="ftp">FTP - shows FTP paths (/public/...)</option>
            <option value="rsync">rsync - shows filesystem paths (/Volume1/..., /mnt/md0/...)</option>
          </select>
        </label>
        <p className="muted small">
          {transport === "rsync"
            ? "Folders here are addressed the way rsync jobs address them. A device shows the shares actually reachable - bind-mounted shares, or the modules its rsync server publishes - rather than its whole filesystem."
            : "Folders here are addressed the way FTP jobs address them, relative to each connection's FTP root."}
        </p>
      </div>

      <div className="browse-panes">
        <FolderPane title="Source" connections={connections} selection={source} onChange={setSource} transport={transport} />
        <FolderPane title="Destination" connections={connections} selection={dest} onChange={setDest} transport={transport} />
      </div>
      <div className="browse-bar">
        <div className="muted small">
          <strong>Source:</strong> {source.path} &nbsp; <strong>Destination:</strong> {dest.path}
        </div>
        <button className="btn primary" disabled={!canCreate} onClick={createJob}>
          Create job from selection
        </button>
      </div>
    </div>
  );
}
