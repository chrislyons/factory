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

  // Pattern matches
  const statusMatch = path.match(/^\/status\/(.+)\.json$/);
  if (statusMatch) return DEMO_AGENT_STATUSES[statusMatch[1]] ?? {};

  const configMatch = path.match(/^\/api\/config\/([^/]+)$/);
  if (configMatch) {
    const agent = DEMO_AGENTS.find((a) => a.id === configMatch[1]);
    if (agent) return { agent: agent.id, config: { model: { default: agent.model, provider: agent.provider }, display: {}, memory: {}, terminal: {} }, health: { reachable: true, url: null, status: 200, error: null } };
  }

  return null;
}
