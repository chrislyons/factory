/**
 * Demo mock data for Factory Portal static builds.
 *
 * When VITE_DEMO_MODE=true, all API calls return this data instead
 * of hitting the backend. Used for GitHub Pages / static previews.
 */

import type {
  AgentBudgetStatus,
  AgentConfigSummary,
  AgentStatus,
  CronJobsResponse,
  HermesSessionsResponse,
  TasksDocument,
} from "./types";

// ── Config API ────────────────────────────────────────────────────

export const DEMO_AGENTS: AgentConfigSummary[] = [
  {
    id: "agent-1",
    label: "Agent 1",
    model: "gemma-4-7b",
    provider: "local",
    toolsets: ["terminal", "file", "web", "delegation", "memory", "skills", "cronjob", "browser"],
  },
  {
    id: "agent-2",
    label: "Agent 2",
    model: "gemma-4-7b",
    provider: "local",
    toolsets: ["terminal", "file", "web", "memory", "skills"],
  },
  {
    id: "agent-3",
    label: "Agent 3",
    model: "mimo-v2",
    provider: "cloud",
    toolsets: ["terminal", "file", "web", "delegation", "memory", "skills", "cronjob", "vision", "browser"],
  },
];

export const DEMO_MEMORY_BUDGET = {
  total_gb: 32,
  available_gb: 6.4,
  used_by_inference_gb: 15.8,
  headroom_gb: 4.0,
  models: [
    { agent: "agent-1", provider: "local", port: null, model: "gemma-4-7b", loaded: true, est_gb: 7.2 },
    { agent: "agent-2", provider: "local", port: null, model: "gemma-4-7b", loaded: true, est_gb: 7.1 },
    { agent: "shared", provider: "local", port: null, model: "gemma-4-26b", loaded: true, est_gb: 1.5 },
    { agent: "agent-3", provider: "cloud", port: null, model: "mimo-v2", loaded: false, est_gb: 0 },
  ],
};

export const DEMO_BUDGET = {
  agents: [
    {
      agent_id: "agent-1",
      monthly_limit_usd: 50,
      spent_this_month_usd: 12.34,
      status: { kind: "normal" as const },
      incidents: [],
    },
    {
      agent_id: "agent-2",
      monthly_limit_usd: 50,
      spent_this_month_usd: 8.10,
      status: { kind: "normal" as const },
      incidents: [],
    },
    {
      agent_id: "agent-3",
      monthly_limit_usd: 100,
      spent_this_month_usd: 47.82,
      status: { kind: "warning" as const, pct: 47.8 },
      incidents: [],
    },
  ] as AgentBudgetStatus[],
};

// ── Jobs / Tasks ──────────────────────────────────────────────────

export const DEMO_TASKS: TasksDocument = {
  tasks: [
    { id: "job.01.001.0001", title: "Portal design overhaul", status: "done", order: 1, blocked_by: [], block: "01-Portal", assignee: "agent-1" },
    { id: "job.01.002.0001", title: "Config page — live controls", status: "in-progress", order: 2, blocked_by: [], block: "01-Portal", assignee: "agent-1" },
    { id: "job.01.003.0001", title: "Mobile responsive audit", status: "in-progress", order: 3, blocked_by: [], block: "01-Portal", assignee: "agent-1" },
    { id: "job.02.001.0001", title: "Local model serving setup", status: "done", order: 4, blocked_by: [], block: "02-Models", assignee: "agent-1" },
    { id: "job.02.002.0001", title: "Shared inference engine", status: "done", order: 5, blocked_by: [], block: "02-Models", assignee: "agent-1" },
    { id: "job.03.001.0001", title: "E2EE migration", status: "done", order: 6, blocked_by: [], block: "03-Messaging", assignee: "agent-1" },
    { id: "job.03.002.0001", title: "Cross-signing automation", status: "done", order: 7, blocked_by: [], block: "03-Messaging", assignee: "agent-1" },
    { id: "job.04.001.0001", title: "Orchestrator build and deploy", status: "done", order: 8, blocked_by: [], block: "04-Orchestration", assignee: "agent-1" },
    { id: "job.05.001.0001", title: "Trading system bootstrap", status: "in-progress", order: 9, blocked_by: [], block: "05-Domains", assignee: "agent-3" },
    { id: "job.05.002.0001", title: "Venue integration — platform A", status: "pending", order: 10, blocked_by: ["job.05.001.0001"], block: "05-Domains", assignee: "agent-3" },
    { id: "job.05.003.0001", title: "Venue integration — platform B", status: "pending", order: 11, blocked_by: ["job.05.001.0001"], block: "05-Domains", assignee: "agent-3" },
    { id: "job.06.001.0001", title: "Agent 2 documentation", status: "done", order: 12, blocked_by: [], block: "06-Agents", assignee: "agent-2" },
    { id: "job.06.002.0001", title: "Agent health monitoring", status: "pending", order: 13, blocked_by: [], block: "06-Agents", assignee: null },
    { id: "job.07.001.0001", title: "Service matrix setup", status: "done", order: 14, blocked_by: [], block: "07-Infra", assignee: "agent-1" },
    { id: "job.07.002.0001", title: "Reverse proxy config", status: "done", order: 15, blocked_by: [], block: "07-Infra", assignee: "agent-1" },
    { id: "job.08.001.0001", title: "Cron job framework", status: "done", order: 16, blocked_by: [], block: "08-Automation", assignee: "agent-1" },
    { id: "job.08.002.0001", title: "Scanner cycle", status: "in-progress", order: 17, blocked_by: [], block: "08-Automation", assignee: "agent-3" },
    { id: "job.09.001.0001", title: "Documentation vault", status: "done", order: 18, blocked_by: [], block: "09-Research", assignee: "agent-1" },
    { id: "job.09.002.0001", title: "Research server", status: "done", order: 19, blocked_by: [], block: "09-Research", assignee: "agent-1" },
    { id: "job.10.001.0001", title: "Demo deployment", status: "in-progress", order: 20, blocked_by: [], block: "10-Outreach", assignee: "agent-1" },
  ],
  blocks: {
    "01-Portal": { label: "Portal", color: "#38bdf8" },
    "02-Models": { label: "Models", color: "#a78bfa" },
    "03-Messaging": { label: "Messaging", color: "#22c55e" },
    "04-Orchestration": { label: "Orchestration", color: "#fbbf24" },
    "05-Domains": { label: "Domains", color: "#f97316" },
    "06-Agents": { label: "Agents", color: "#fb7185" },
    "07-Infra": { label: "Infra", color: "#94a3b8" },
    "08-Automation": { label: "Automation", color: "#34d399" },
    "09-Research": { label: "Research", color: "#c084fc" },
    "10-Outreach": { label: "Outreach", color: "#38bdf8" },
  },
  log: [
    { timestamp: "2026-04-19T13:00:00Z", actor: "agent-1", action: "completed", task_id: "job.03.001.0001", detail: "E2EE migration done" },
    { timestamp: "2026-04-19T12:30:00Z", actor: "agent-3", action: "started", task_id: "job.05.001.0001", detail: "Trading system bootstrap" },
    { timestamp: "2026-04-19T11:00:00Z", actor: "agent-1", action: "completed", task_id: "job.02.002.0001", detail: "Shared engine live" },
  ],
};

// ── Agent Statuses ────────────────────────────────────────────────

export const DEMO_AGENT_STATUSES: Record<string, AgentStatus> = {
  "agent-1": {
    status: "working",
    notes: "Portal config page — live controls",
    current_task: "job.01.002.0001",
    last_updated: "2026-04-19T17:30:00Z",
  },
  "agent-2": {
    status: "idle",
    notes: "Waiting for assignment",
    last_updated: "2026-04-19T17:25:00Z",
  },
  "agent-3": {
    status: "working",
    notes: "Scanner cycle",
    current_task: "job.08.002.0001",
    last_updated: "2026-04-19T17:28:00Z",
  },
};

// ── Demo index.json (docs page — factory only) ────────────────────

export const DEMO_INDEX = {
  generated_at: "2026-04-19T17:00:00Z",
  generator: "demo",
  version: "1",
  count: 1,
  repos: [
    {
      name: "factory",
      gallery: "/galleries/factory_architecture-gallery.html",
      commands: "/commands/factory_repo-commands.html",
      gallery_title: "Factory Architecture Gallery",
      commands_title: "Factory — Command Reference",
      gallery_mtime: "2026-04-19T17:00:00Z",
      commands_mtime: "2026-04-19T17:00:00Z",
    },
  ],
};

// ── Sessions ────────────────────────────────────────────────────────

export const DEMO_SESSIONS: HermesSessionsResponse = {
  active: [
    {
      id: "sess-a1c8f2d0",
      source: "cli",
      user_id: "chris",
      model: "gemma-4-7b",
      started_at: "2026-04-19T16:45:00Z",
      ended_at: null,
      message_count: 34,
      tool_call_count: 12,
      input_tokens: 18400,
      output_tokens: 9200,
      title: "Portal sessions browser build",
    },
    {
      id: "sess-b7e4a1f3",
      source: "matrix",
      user_id: "@operator:matrix.org",
      model: "gemma-4-7b",
      started_at: "2026-04-19T17:10:00Z",
      ended_at: null,
      message_count: 8,
      tool_call_count: 3,
      input_tokens: 4200,
      output_tokens: 2100,
      title: "Config page debugging",
    },
    {
      id: "sess-c3d9e5a1",
      source: "cron",
      user_id: null,
      model: "mimo-v2",
      started_at: "2026-04-19T17:00:00Z",
      ended_at: null,
      message_count: 2,
      tool_call_count: 5,
      input_tokens: 1800,
      output_tokens: 3400,
      title: "Heartbeat check",
    },
  ],
  completed: [
    {
      id: "sess-d1f2a8b4",
      source: "cli",
      user_id: "chris",
      model: "gemma-4-7b",
      started_at: "2026-04-19T14:00:00Z",
      ended_at: "2026-04-19T14:32:00Z",
      message_count: 22,
      tool_call_count: 8,
      input_tokens: 12100,
      output_tokens: 6800,
      title: "Memory bar standardization",
    },
    {
      id: "sess-e5a3c7d9",
      source: "matrix",
      user_id: "@operator:matrix.org",
      model: "gemma-4-7b",
      started_at: "2026-04-19T12:15:00Z",
      ended_at: "2026-04-19T12:48:00Z",
      message_count: 15,
      tool_call_count: 6,
      input_tokens: 8900,
      output_tokens: 4300,
      title: "Demo mode wiring",
    },
    {
      id: "sess-f8b2d6e0",
      source: "acp",
      user_id: "chris",
      model: "mimo-v2",
      started_at: "2026-04-19T10:00:00Z",
      ended_at: "2026-04-19T10:55:00Z",
      message_count: 41,
      tool_call_count: 18,
      input_tokens: 24500,
      output_tokens: 15200,
      title: "Architecture gallery update",
    },
    {
      id: "sess-a9c1e4f7",
      source: "cli",
      user_id: "chris",
      model: "gemma-4-26b",
      started_at: "2026-04-19T08:30:00Z",
      ended_at: "2026-04-19T09:15:00Z",
      message_count: 28,
      tool_call_count: 14,
      input_tokens: 16800,
      output_tokens: 9400,
      title: "Trading system bootstrap",
    },
    {
      id: "sess-b2d5f8a3",
      source: "cron",
      user_id: null,
      model: "gemma-4-7b",
      started_at: "2026-04-18T22:00:00Z",
      ended_at: "2026-04-18T22:03:00Z",
      message_count: 1,
      tool_call_count: 2,
      input_tokens: 600,
      output_tokens: 400,
      title: "Nightly health sweep",
    },
  ],
  total: 8,
  tool_distribution: {
    "terminal": 24,
    "read_file": 19,
    "patch": 14,
    "write_file": 11,
    "search_files": 8,
    "browser_navigate": 6,
    "mcp_qdrant_search": 5,
    "execute_code": 4,
    "memory": 3,
  },
};

export const DEMO_SESSION_DETAILS: Record<string, unknown> = {
  "sess-a1c8f2d0": {
    id: "sess-a1c8f2d0",
    source: "cli",
    user_id: "chris",
    model: "gemma-4-7b",
    started_at: "2026-04-19T16:45:00Z",
    ended_at: null,
    message_count: 34,
    tool_call_count: 12,
    input_tokens: 18400,
    output_tokens: 9200,
    title: "Portal sessions browser build",
    estimated_cost_usd: 0.0042,
    cost_status: "normal",
    recent_messages: [
      { id: 1, role: "user", tool_calls: null, tool_name: null, timestamp: "2026-04-19T16:45:00Z", preview: "Build a sessions browser page for the portal", tool_names: [] },
      { id: 2, role: "assistant", tool_calls: null, tool_name: null, timestamp: "2026-04-19T16:45:12Z", preview: "I'll create the SessionsPage component with filtering, sorting, and a detail panel…", tool_names: ["read_file", "search_files"] },
      { id: 3, role: "tool", tool_calls: "read_file", tool_name: "read_file", timestamp: "2026-04-19T16:45:15Z", preview: "Read 281 lines from LoopsPage.tsx", tool_names: ["read_file"] },
      { id: 4, role: "assistant", tool_calls: null, tool_name: null, timestamp: "2026-04-19T16:46:00Z", preview: "Writing the SessionsPage component…", tool_names: ["write_file"] },
      { id: 5, role: "tool", tool_calls: "write_file", tool_name: "write_file", timestamp: "2026-04-19T16:46:30Z", preview: "Wrote 380 lines to SessionsPage.tsx", tool_names: ["write_file"] },
      { id: 6, role: "assistant", tool_calls: null, tool_name: null, timestamp: "2026-04-19T16:47:00Z", preview: "Adding CSS styles for the session browser…", tool_names: ["patch"] },
    ],
  },
  "sess-b7e4a1f3": {
    id: "sess-b7e4a1f3",
    source: "matrix",
    user_id: "@operator:matrix.org",
    model: "gemma-4-7b",
    started_at: "2026-04-19T17:10:00Z",
    ended_at: null,
    message_count: 8,
    tool_call_count: 3,
    input_tokens: 4200,
    output_tokens: 2100,
    title: "Config page debugging",
    estimated_cost_usd: 0.0018,
    cost_status: "normal",
    recent_messages: [
      { id: 1, role: "user", tool_calls: null, tool_name: null, timestamp: "2026-04-19T17:10:00Z", preview: "Why are the config controls not responding?", tool_names: [] },
      { id: 2, role: "assistant", tool_calls: null, tool_name: null, timestamp: "2026-04-19T17:10:08Z", preview: "Let me check the ConfigPage component and the API endpoints…", tool_names: ["read_file"] },
      { id: 3, role: "tool", tool_calls: "read_file", tool_name: "read_file", timestamp: "2026-04-19T17:10:12Z", preview: "Read 1001 lines from ConfigPage.tsx", tool_names: ["read_file"] },
    ],
  },
};

// ── Cron Jobs ───────────────────────────────────────────────────────

export const DEMO_CRON_JOBS: CronJobsResponse = {
  jobs: [
    {
      id: "cj-001",
      name: "Nightly health sweep",
      schedule: { cron: "0 22 * * *" },
      schedule_display: "Every day at 10:00 PM",
      state: "scheduled",
      enabled: true,
      prompt: "Check all service health endpoints and report any failures.",
      skill: null,
      skills: ["systematic-debugging"],
      next_run: "2026-04-19T22:00:00Z",
      last_run: "2026-04-18T22:00:00Z",
      created_at: "2026-04-10T14:00:00Z",
      run_count: 9,
    },
    {
      id: "cj-002",
      name: "Heartbeat check",
      schedule: { interval: "10m" },
      schedule_display: "Every 10 minutes",
      state: "scheduled",
      enabled: true,
      prompt: "Ping all agent gateways and update heartbeat status.",
      skill: null,
      skills: null,
      next_run: "2026-04-19T17:20:00Z",
      last_run: "2026-04-19T17:10:00Z",
      created_at: "2026-04-08T09:00:00Z",
      run_count: 1442,
    },
    {
      id: "cj-003",
      name: "Memory pressure alert",
      schedule: { interval: "5m" },
      schedule_display: "Every 5 minutes",
      state: "scheduled",
      enabled: true,
      prompt: "Check system memory. Alert if available < 2GB.",
      skill: null,
      skills: null,
      next_run: "2026-04-19T17:15:00Z",
      last_run: "2026-04-19T17:10:00Z",
      created_at: "2026-04-12T11:00:00Z",
      run_count: 2884,
    },
    {
      id: "cj-004",
      name: "Weekly config backup",
      schedule: { cron: "0 3 * * 0" },
      schedule_display: "Every Sunday at 3:00 AM",
      state: "scheduled",
      enabled: true,
      prompt: "Backup all agent configs, portal state, and infra configs to timestamped archive.",
      skill: null,
      skills: ["github-pr-workflow"],
      next_run: "2026-04-20T03:00:00Z",
      last_run: "2026-04-13T03:00:00Z",
      created_at: "2026-03-15T10:00:00Z",
      run_count: 5,
    },
    {
      id: "cj-005",
      name: "Portal demo rebuild",
      schedule: { cron: "0 6 * * *" },
      schedule_display: "Every day at 6:00 AM",
      state: "paused",
      enabled: false,
      prompt: "Rebuild and redeploy the portal demo site.",
      skill: null,
      skills: ["github-pr-workflow"],
      next_run: null,
      last_run: "2026-04-17T06:00:00Z",
      created_at: "2026-04-15T08:00:00Z",
      run_count: 4,
    },
    {
      id: "cj-006",
      name: "Session cleanup",
      schedule: { cron: "0 4 * * *" },
      schedule_display: "Every day at 4:00 AM",
      state: "scheduled",
      enabled: true,
      prompt: "Archive completed sessions older than 7 days.",
      skill: null,
      skills: null,
      next_run: "2026-04-20T04:00:00Z",
      last_run: "2026-04-19T04:00:00Z",
      created_at: "2026-04-05T12:00:00Z",
      run_count: 14,
    },
  ],
  count: 6,
};

// ── Health ──────────────────────────────────────────────────────────

export interface ServiceHealth {
  name: string;
  url: string | null;
  status: "up" | "down" | "degraded" | "unknown";
  latency_ms: number | null;
  last_check: string;
  detail: string | null;
}

export interface SystemHealth {
  overall: "healthy" | "degraded" | "critical";
  services: ServiceHealth[];
  checked_at: string;
}

export const DEMO_SYSTEM_HEALTH: SystemHealth = {
  overall: "healthy",
  services: [
    { name: "Inference — Agent 1 (E4B)", url: "http://localhost:41961", status: "up", latency_ms: 45, last_check: "2026-04-19T17:14:00Z", detail: "30 tok/s" },
    { name: "Inference — Agent 2 (E4B)", url: "http://localhost:41962", status: "up", latency_ms: 52, last_check: "2026-04-19T17:14:00Z", detail: "28 tok/s" },
    { name: "Inference — Shared (26B)", url: "http://localhost:41966", status: "up", latency_ms: 180, last_check: "2026-04-19T17:14:00Z", detail: "5.4 tok/s SSD streaming" },
    { name: "Hermes — Agent 1", url: "http://localhost:41961", status: "up", latency_ms: 32, last_check: "2026-04-19T17:14:00Z", detail: "Gateway active, 2 sessions" },
    { name: "Hermes — Agent 2", url: "http://localhost:41962", status: "up", latency_ms: 28, last_check: "2026-04-19T17:14:00Z", detail: "Gateway active, 1 session" },
    { name: "Hermes — Agent 3", url: null, status: "up", latency_ms: 210, last_check: "2026-04-19T17:14:00Z", detail: "Cloud provider (Nous Portal)" },
    { name: "Qdrant", url: "http://localhost:41460", status: "up", latency_ms: 8, last_check: "2026-04-19T17:14:00Z", detail: "projects-vault, 12k vectors" },
    { name: "Research MCP", url: "http://localhost:41470", status: "up", latency_ms: 12, last_check: "2026-04-19T17:14:00Z", detail: "research-vault active" },
    { name: "Matrix Bridge", url: "https://matrix.org", status: "up", latency_ms: 340, last_check: "2026-04-19T17:13:00Z", detail: "E2EE connected, 4 rooms" },
    { name: "Portal (Caddy)", url: "http://localhost:8080", status: "up", latency_ms: 5, last_check: "2026-04-19T17:14:00Z", detail: "Reverse proxy active" },
    { name: "System Memory", url: null, status: "up", latency_ms: null, last_check: "2026-04-19T17:14:00Z", detail: "6.4 GB available / 32 GB total" },
    { name: "System Disk", url: null, status: "up", latency_ms: null, last_check: "2026-04-19T17:14:00Z", detail: "412 GB free / 1 TB" },
  ],
  checked_at: "2026-04-19T17:14:00Z",
};

// ── Activity Feed ───────────────────────────────────────────────────

export interface ActivityEntry {
  id: string;
  timestamp: string;
  kind: "session_start" | "session_end" | "tool_call" | "cron_run" | "task_update" | "approval" | "error" | "config_change";
  agent: string;
  summary: string;
  detail?: string;
}

export const DEMO_ACTIVITY: ActivityEntry[] = [
  { id: "act-019", timestamp: "2026-04-19T17:14:00Z", kind: "tool_call", agent: "agent-1", summary: "Read ConfigPage.tsx (1001 lines)", detail: "read_file" },
  { id: "act-018", timestamp: "2026-04-19T17:12:00Z", kind: "session_start", agent: "agent-2", summary: "Matrix session started — Config page debugging", detail: "sess-b7e4a1f3" },
  { id: "act-017", timestamp: "2026-04-19T17:10:00Z", kind: "cron_run", agent: "system", summary: "Heartbeat check completed — all services up", detail: "cj-002" },
  { id: "act-016", timestamp: "2026-04-19T17:05:00Z", kind: "tool_call", agent: "agent-1", summary: "Wrote SessionsPage.tsx (380 lines)", detail: "write_file" },
  { id: "act-015", timestamp: "2026-04-19T17:00:00Z", kind: "config_change", agent: "agent-1", summary: "Added 4 new page entries to vite.config.ts", detail: "patch" },
  { id: "act-014", timestamp: "2026-04-19T16:55:00Z", kind: "tool_call", agent: "agent-1", summary: "Updated NAV_LINKS with Sessions, Cron, Health, Activity", detail: "patch" },
  { id: "act-013", timestamp: "2026-04-19T16:45:00Z", kind: "session_start", agent: "agent-1", summary: "CLI session started — Portal sessions browser build", detail: "sess-a1c8f2d0" },
  { id: "act-012", timestamp: "2026-04-19T14:32:00Z", kind: "session_end", agent: "agent-1", summary: "Session completed — Memory bar standardization", detail: "sess-d1f2a8b4" },
  { id: "act-011", timestamp: "2026-04-19T13:00:00Z", kind: "task_update", agent: "agent-1", summary: "Completed: E2EE migration", detail: "job.03.001.0001" },
  { id: "act-010", timestamp: "2026-04-19T12:48:00Z", kind: "session_end", agent: "agent-1", summary: "Session completed — Demo mode wiring", detail: "sess-e5a3c7d9" },
  { id: "act-009", timestamp: "2026-04-19T12:30:00Z", kind: "task_update", agent: "agent-3", summary: "Started: Trading system bootstrap", detail: "job.05.001.0001" },
  { id: "act-008", timestamp: "2026-04-19T11:00:00Z", kind: "task_update", agent: "agent-1", summary: "Completed: Shared inference engine", detail: "job.02.002.0001" },
  { id: "act-007", timestamp: "2026-04-19T10:55:00Z", kind: "session_end", agent: "agent-1", summary: "Session completed — Architecture gallery update", detail: "sess-f8b2d6e0" },
  { id: "act-006", timestamp: "2026-04-19T10:00:00Z", kind: "session_start", agent: "agent-1", summary: "ACP session started — Architecture gallery update", detail: "sess-f8b2d6e0" },
  { id: "act-005", timestamp: "2026-04-19T09:15:00Z", kind: "session_end", agent: "agent-1", summary: "Session completed — Trading system bootstrap", detail: "sess-a9c1e4f7" },
  { id: "act-004", timestamp: "2026-04-19T08:30:00Z", kind: "session_start", agent: "agent-1", summary: "CLI session started — Trading system bootstrap", detail: "sess-a9c1e4f7" },
  { id: "act-003", timestamp: "2026-04-19T04:00:00Z", kind: "cron_run", agent: "system", summary: "Session cleanup completed — archived 3 old sessions", detail: "cj-006" },
  { id: "act-002", timestamp: "2026-04-18T22:00:00Z", kind: "cron_run", agent: "system", summary: "Nightly health sweep — all services green", detail: "cj-001" },
  { id: "act-001", timestamp: "2026-04-18T21:30:00Z", kind: "error", agent: "agent-3", summary: "Connection timeout to venue API — retrying", detail: "HTTP 504 after 8s" },
];

// ── URL Router ────────────────────────────────────────────────────

/**
 * Match a demo URL path to its mock response.
 * Returns null if no demo data exists for that path.
 */
export function matchDemoUrl(path: string): unknown | null {
  // Exact matches
  if (path === "/api/config") return { agents: DEMO_AGENTS };
  if (path === "/api/config/memory-budget") return DEMO_MEMORY_BUDGET;
  if (path === "/budget/status") return DEMO_BUDGET;
  if (path === "/jobs.json") return DEMO_TASKS;
  if (path === "/analytics/summary") return { period_days: 14, total_runs: 47, total_cost_usd: 68.26, avg_run_duration_s: 12.4 };
  if (path === "/api/config/sessions") return DEMO_SESSIONS;
  if (path === "/api/config/cron-jobs") return DEMO_CRON_JOBS;

  // Pattern matches
  const statusMatch = path.match(/^\/status\/(.+)\.json$/);
  if (statusMatch) return DEMO_AGENT_STATUSES[statusMatch[1]] ?? {};

  const configMatch = path.match(/^\/api\/config\/([^/]+)$/);
  if (configMatch) {
    const agent = DEMO_AGENTS.find((a) => a.id === configMatch[1]);
    if (agent) return { agent: agent.id, config: { model: { default: agent.model, provider: agent.provider }, display: {}, memory: {}, terminal: {} }, health: { reachable: true, url: null, status: 200, error: null } };
  }

  const sessionMatch = path.match(/^\/api\/config\/sessions\/([^/]+)$/);
  if (sessionMatch) return DEMO_SESSION_DETAILS[sessionMatch[1]] ?? { error: "Session not found" };

  return null;
}
