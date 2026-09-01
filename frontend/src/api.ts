// Thin fetch wrapper for the backend API. Same-origin in production (nginx
// proxies /api and /health); proxied to :8000 by Vite during local dev.

export type Transport = "ftp" | "rsync";

export interface NasMount {
  host_path: string;
  container_path: string;
  read_only: boolean;
}

export interface RsyncEnvironment {
  rsync_available: boolean;
  rsync_version: string | null;
  rsync_protocol: number | null;
  rsync_error: string | null;
  mount_root: string;
  mounts: NasMount[];
}

export interface Health {
  status: string;
  version: string;
  database: string;
  scheduler: string;
}

export interface Settings {
  timezone: string;
  default_verification_level: number;
  default_conflict_strategy: string;
  default_transfer_mode: string;
  max_concurrent_transfers: number;
  max_bandwidth_kbps: number | null;
  log_retention_days: number;
  archive_path_template: string;
  retry_count: number;
  retry_delay_seconds: number;
  max_auto_source_deletes: number;
  max_auto_destination_deletes: number;
  max_delete_percent: number;
  require_manual_approval_for_deletes: boolean;
  preserve_timestamps: boolean;
  updated_at: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export interface Connection {
  id: number;
  name: string;
  host: string;
  protocol: "ftp" | "ftps";
  port: number;
  username: string;
  root_path: string;
  passive_mode: boolean;
  timeout_seconds: number;
  description: string | null;
  fs_root: string | null;
  rsync_enabled: boolean;
  rsync_mode: "daemon" | "ssh";
  rsync_host: string | null;
  rsync_port: number;
  rsync_module: string | null;
  rsync_username: string | null;
  rsync_ssh_port: number;
  rsync_password_set: boolean;
  last_test_status: string | null;
  last_test_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectionInput {
  name: string;
  host: string;
  protocol: "ftp" | "ftps";
  port: number;
  username: string;
  password?: string;
  root_path: string;
  passive_mode: boolean;
  timeout_seconds: number;
  description?: string | null;
  fs_root?: string | null;
  rsync_enabled?: boolean;
  rsync_mode?: "daemon" | "ssh";
  rsync_host?: string | null;
  rsync_port?: number;
  rsync_module?: string | null;
  rsync_username?: string | null;
  rsync_password?: string;
  rsync_ssh_port?: number;
}

export interface RsyncTestResult {
  ok: boolean;
  reachable: boolean;
  authenticated: boolean;
  module_found: boolean | null;
  modules: string[];
  summary: string;
  messages: string[];
}

export interface TestResult {
  ok: boolean;
  connectivity: boolean;
  authentication: boolean;
  can_list: boolean;
  can_write: boolean | null;
  can_delete: boolean | null;
  summary: string;
  messages: string[];
  /** Present only when the connection has rsync enabled. FTP and rsync are
   *  reported separately: one can work while the other is misconfigured. */
  rsync: RsyncTestResult | null;
}

export const api = {
  health: () => request<Health>("/health"),
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (patch: Partial<Settings>) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(patch) }),

  rsyncEnvironment: () => request<RsyncEnvironment>("/api/rsync/environment"),

  listConnections: () => request<Connection[]>("/api/connections"),
  createConnection: (body: ConnectionInput) =>
    request<Connection>("/api/connections", { method: "POST", body: JSON.stringify(body) }),
  updateConnection: (id: number, body: Partial<ConnectionInput>) =>
    request<Connection>(`/api/connections/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteConnection: (id: number) =>
    request<void>(`/api/connections/${id}`, { method: "DELETE" }),
  testConnection: (id: number) =>
    request<TestResult>(`/api/connections/${id}/test`, { method: "POST" }),
  testConfig: (body: ConnectionInput) =>
    request<TestResult>("/api/connections/test", { method: "POST", body: JSON.stringify(body) }),

  browse: (connId: number, path?: string, transport: Transport = "ftp") => {
    const q = new URLSearchParams({ transport });
    if (path) q.set("path", path);
    return request<BrowseResponse>(`/api/browse/${connId}?${q.toString()}`);
  },
  folderSize: (connId: number, path: string, transport: Transport = "ftp") =>
    request<FolderSize>(
      `/api/browse/${connId}/size?${new URLSearchParams({ path, transport }).toString()}`
    ),

  listJobs: () => request<Job[]>("/api/jobs"),
  getJob: (id: number) => request<Job>(`/api/jobs/${id}`),
  createJob: (body: JobInput) =>
    request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(body) }),
  updateJob: (id: number, body: Partial<JobInput>) =>
    request<Job>(`/api/jobs/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteJob: (id: number) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  enableJob: (id: number) => request<Job>(`/api/jobs/${id}/enable`, { method: "POST" }),
  disableJob: (id: number) => request<Job>(`/api/jobs/${id}/disable`, { method: "POST" }),
  previewJob: (body: JobPreviewInput) =>
    request<Plan>("/api/jobs/preview", { method: "POST", body: JSON.stringify(body) }),
  dryRun: (id: number) =>
    request<{ run: JobRun; plan: Plan }>(`/api/jobs/${id}/dry-run`, { method: "POST" }),
  runJob: (id: number) =>
    request<JobRun>(`/api/jobs/${id}/run`, { method: "POST" }),
  cancelJob: (id: number) =>
    request<{ status: string; job_id: number }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  listRuns: (id: number) => request<JobRun[]>(`/api/jobs/${id}/runs`),
  getRun: (runId: number) => request<JobRun>(`/api/jobs/runs/${runId}`),
  runItems: (runId: number) => request<RunItem[]>(`/api/jobs/runs/${runId}/items`),

  listPending: () => request<PendingDeletion[]>("/api/pending-deletions"),
  approvePending: (id: number) =>
    request<PendingDeletion>(`/api/pending-deletions/${id}/approve`, { method: "POST" }),
  rejectPending: (id: number) =>
    request<void>(`/api/pending-deletions/${id}/reject`, { method: "POST" }),

  getDashboard: () => request<Dashboard>("/api/dashboard"),
  runsLog: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return request<JobRun[]>(`/api/runs${q ? `?${q}` : ""}`);
  },
  exportBackup: () => request<unknown>("/api/backup/export", { method: "POST" }),
  importBackup: (doc: unknown) =>
    request<{ connections: number; jobs: number; settings_updated: boolean }>("/api/backup/import", {
      method: "POST",
      body: JSON.stringify(doc),
    }),
};

export interface Dashboard {
  connections_total: number;
  connections: { id: number; name: string; last_test_status: string | null }[];
  jobs_total: number;
  jobs_enabled: number;
  jobs_running: number;
  jobs_failed: number;
  pending_deletions: number;
  last_success_job: string | null;
  last_success_at: string | null;
  next_run_job: string | null;
  next_run_at: string | null;
  recent_runs: { id: number; job_name: string | null; run_type: string; status: string; started_at: string }[];
  recent_activity: { action: string; detail: string | null; created_at: string }[];
}

export interface PendingDeletion {
  id: number;
  job_id: number;
  job_run_id: number | null;
  source_path: string;
  destination_path: string | null;
  size_bytes: number;
  verification_status: string;
  approved: boolean;
  approved_at: string | null;
  deleted: boolean;
  deleted_at: string | null;
  created_at: string;
  job_name: string | null;
}

export interface RunItem {
  id: number;
  job_run_id: number;
  source_path: string | null;
  destination_path: string | null;
  action: string;
  status: string;
  size_bytes: number;
  message: string | null;
  created_at: string;
}

export type JobType = "copy" | "mirror" | "move";

export interface Job {
  id: number;
  name: string;
  description: string | null;
  job_type: JobType;
  transport: Transport;
  source_connection_id: number;
  source_path: string;
  destination_connection_id: number;
  destination_path: string;
  enabled: boolean;
  conflict_strategy: string;
  verification_level: number;
  delete_strategy: string;
  mirror_mode: string;
  archive_path: string | null;
  include_filters: string | null;
  exclude_filters: string | null;
  rsync_compress: boolean;
  rsync_bandwidth_kbps: number | null;
  schedule_type: string;
  schedule_value: string | null;
  source_connection_name: string | null;
  destination_connection_name: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobInput {
  name: string;
  description?: string | null;
  job_type: JobType;
  transport: Transport;
  source_connection_id: number;
  source_path: string;
  destination_connection_id: number;
  destination_path: string;
  enabled: boolean;
  conflict_strategy: string;
  verification_level: number;
  delete_strategy: string;
  mirror_mode: string;
  archive_path?: string | null;
  include_filters?: string | null;
  exclude_filters?: string | null;
  rsync_compress?: boolean;
  rsync_bandwidth_kbps?: number | null;
  schedule_type: string;
  schedule_value?: string | null;
}

export interface JobPreviewInput {
  job_type: JobType;
  transport: Transport;
  source_connection_id: number;
  source_path: string;
  destination_connection_id: number;
  destination_path: string;
  conflict_strategy: string;
  delete_strategy: string;
  mirror_mode: string;
  include_filters?: string | null;
  exclude_filters?: string | null;
  rsync_compress?: boolean;
  rsync_bandwidth_kbps?: number | null;
}

export interface PlanItem {
  action: string;
  source_path: string | null;
  destination_path: string | null;
  size: number;
  reason: string;
}

export interface Plan {
  items: PlanItem[];
  warnings: string[];
  copy_count: number;
  update_count: number;
  skip_count: number;
  mkdir_count: number;
  delete_count: number;
  archive_count: number;
  transfer_bytes: number;
  /** Files already identical at the destination, needing only a re-stamp. */
  inplace_count: number;
  /** What those files weigh - none of it crosses the network. */
  inplace_bytes: number;
  truncated: boolean;
  /** Exact command a run would issue, credentials removed. null for FTP. */
  command: string | null;
}

export interface JobRun {
  id: number;
  job_id: number;
  run_type: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  files_scanned: number;
  files_copied: number;
  files_updated: number;
  files_skipped: number;
  files_failed: number;
  files_deleted: number;
  bytes_transferred: number;
  files_total: number;
  bytes_total: number;
  current_item: string | null;
  transport: string | null;
  exit_code: number | null;
  safety_notes: string | null;
  summary: string | null;
  error_message: string | null;
  job_name?: string | null;
  source_label?: string | null;
  destination_label?: string | null;
}

export interface BrowseEntry {
  name: string;
  type: "dir" | "file";
  path: string;
  size: number | null;
  modify: string | null;
}

export interface BrowseResponse {
  connection_id: number;
  path: string;
  parent: string | null;
  entries: BrowseEntry[];
}

export interface FolderSize {
  connection_id: number;
  path: string;
  total_bytes: number;
  file_count: number;
  folder_count: number;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatBytes(n: number | null): string {
  if (n === null || n === undefined) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${i === 0 ? v : v.toFixed(1)} ${units[i]}`;
}
