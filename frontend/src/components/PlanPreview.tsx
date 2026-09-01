import { formatBytes, type Plan } from "../api";

const ACTION_LABEL: Record<string, string> = {
  copy: "Copy",
  update: "Update",
  skip: "Skip",
  mkdir: "Create folder",
  delete: "Delete",
  archive: "Archive",
};

export function PlanPreview({ plan, title }: { plan: Plan; title?: string }) {
  return (
    <div className="plan">
      {title && <h3 className="plan-title">{title}</h3>}
      <div className="plan-counts">
        <span className="chip chip-copy">{plan.copy_count} new</span>
        <span className="chip chip-update">{plan.update_count} updated</span>
        <span className="chip chip-skip">{plan.skip_count} skipped</span>
        <span className="chip chip-mkdir">{plan.mkdir_count} folders</span>
        {plan.delete_count > 0 && <span className="chip chip-delete">{plan.delete_count} delete</span>}
        <span className="chip">{formatBytes(plan.transfer_bytes)} to transfer</span>
        {plan.inplace_count > 0 && (
          <span className="chip">
            {plan.inplace_count} fixed in place ({formatBytes(plan.inplace_bytes)})
          </span>
        )}
      </div>
      {plan.inplace_count > 0 && (
        <p className="muted small">
          "Fixed in place" files already match at the destination byte for byte - rsync only
          re-stamps their permissions or timestamps, so their {formatBytes(plan.inplace_bytes)}{" "}
          does not cross the network and costs almost no time.
        </p>
      )}

      {plan.warnings.length > 0 && (
        <ul className="plan-warnings">
          {plan.warnings.map((w, i) => (
            <li key={i}>⚠ {w}</li>
          ))}
        </ul>
      )}

      {plan.command && (
        <details className="plan-command">
          <summary>Show the command this job runs</summary>
          {/* Safe to display: the password travels in the environment, never in
              the command line, so there is nothing here to redact away. */}
          <pre className="mono">{plan.command}</pre>
          <p className="muted small">Credentials are never included in the command.</p>
        </details>
      )}

      <div className="plan-items">
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Path</th>
              <th>Size</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {plan.items.slice(0, 500).map((it, i) => (
              <tr key={i} className={`row-${it.action}`}>
                <td>{ACTION_LABEL[it.action] ?? it.action}</td>
                <td className="mono">{it.destination_path ?? it.source_path}</td>
                <td>{it.action === "mkdir" ? "-" : formatBytes(it.size)}</td>
                <td className="muted">{it.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(plan.truncated || plan.items.length > 500) && (
          <p className="muted small">Showing first 500 actions.</p>
        )}
        {plan.items.length === 0 && <p className="muted small">No actions - nothing to do.</p>}
      </div>
    </div>
  );
}
