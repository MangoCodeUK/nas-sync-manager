import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type Connection } from "../api";
import { FolderPane, type PaneSelection } from "../components/FolderPane";

export function BrowsePage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<PaneSelection>({ connId: null, path: "/" });
  const [dest, setDest] = useState<PaneSelection>({ connId: null, path: "/" });
  const navigate = useNavigate();

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
      <div className="browse-panes">
        <FolderPane title="Source" connections={connections} selection={source} onChange={setSource} />
        <FolderPane title="Destination" connections={connections} selection={dest} onChange={setDest} />
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
