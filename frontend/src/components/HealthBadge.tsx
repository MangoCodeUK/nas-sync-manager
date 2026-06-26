import { useEffect, useState } from "react";
import { api, type Health } from "../api";

// Polls /health and shows backend connectivity in the sidebar footer.
export function HealthBadge() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const h = await api.health();
        if (active) {
          setHealth(h);
          setError(false);
        }
      } catch {
        if (active) setError(true);
      }
    };
    poll();
    const id = setInterval(poll, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const ok = !error && health?.status === "ok";
  return (
    <div className="health-badge" title={error ? "Backend unreachable" : "Backend healthy"}>
      <span className={ok ? "dot dot-ok" : "dot dot-bad"} />
      <span className="health-text">
        {error ? "Backend offline" : health ? `Backend v${health.version}` : "Checking…"}
      </span>
    </div>
  );
}
