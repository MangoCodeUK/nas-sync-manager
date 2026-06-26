import { NavLink, Route, Routes } from "react-router-dom";
import { HealthBadge } from "./components/HealthBadge";
import { Placeholder } from "./components/Placeholder";
import { BrowsePage } from "./pages/BrowsePage";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { JobsPage } from "./pages/JobsPage";
import { LogsPage } from "./pages/LogsPage";
import { PendingDeletionsPage } from "./pages/PendingDeletionsPage";
import { SettingsPage } from "./pages/SettingsPage";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/connections", label: "Connections" },
  { to: "/browse", label: "Browse" },
  { to: "/jobs", label: "Jobs" },
  { to: "/pending-deletions", label: "Pending Deletions" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">⇄</span>
          <span className="brand-name">NAS Sync</span>
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <HealthBadge />
        </div>
      </aside>

      <main className="content">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route
            path="/pending-deletions"
            element={<PendingDeletionsPage />}
          />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Placeholder title="Not found" stage={0} />} />
        </Routes>
      </main>
    </div>
  );
}
