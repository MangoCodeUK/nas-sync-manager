import { useEffect, useState } from "react";
import { api, ApiError, formatBytes, type PendingDeletion } from "../api";

export function PendingDeletionsPage() {
  const [pending, setPending] = useState<PendingDeletion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setPending(await api.listPending());
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  async function approve(p: PendingDeletion) {
    if (!confirm(`Permanently delete the source file?\n\n${p.source_path}`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.approvePending(p.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Approve failed");
    } finally {
      setBusy(false);
    }
  }

  async function reject(p: PendingDeletion) {
    setBusy(true);
    setError(null);
    try {
      await api.rejectPending(p.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Reject failed");
    } finally {
      setBusy(false);
    }
  }

  async function approveAll() {
    if (
      !confirm(
        `Permanently delete ${pending.length} source file(s) that have been verified at the destination?`
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      for (const p of pending) await api.approvePending(p.id);
      await refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Bulk approve failed");
    } finally {
      setBusy(false);
    }
  }

  const totalBytes = pending.reduce((s, p) => s + p.size_bytes, 0);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Pending Deletions</h1>
        {pending.length > 0 && (
          <button className="btn primary" onClick={approveAll} disabled={busy}>
            Approve all ({pending.length})
          </button>
        )}
      </div>
      <p className="muted">
        Source files from move jobs that are verified at the destination and waiting for your
        approval before deletion. Nothing here is deleted automatically.
      </p>

      {error && <p className="error-text">{error}</p>}
      {loading && <p className="muted">Loading…</p>}

      {!loading && pending.length === 0 && <p className="muted">Nothing pending. 🎉</p>}

      {pending.length > 0 && (
        <>
          <p className="muted small">
            {pending.length} file(s), {formatBytes(totalBytes)} total.
          </p>
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Source file</th>
                <th>Size</th>
                <th>Verification</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pending.map((p) => (
                <tr key={p.id}>
                  <td>{p.job_name ?? p.job_id}</td>
                  <td className="mono small">{p.source_path}</td>
                  <td>{formatBytes(p.size_bytes)}</td>
                  <td className="ok-text small">{p.verification_status}</td>
                  <td className="job-actions">
                    <button className="btn small-btn" onClick={() => approve(p)} disabled={busy}>
                      Approve delete
                    </button>
                    <button className="btn small-btn" onClick={() => reject(p)} disabled={busy}>
                      Keep (reject)
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
