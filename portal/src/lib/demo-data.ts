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
    id: "boot",
    label: "Boot",
    model: "gemma-4-e4b-it-6bit",
    provider: "mlx-vlm:41961",
    toolsets: ["terminal", "file", "web", "delegation", "memory", "session_search", "skills", "clarify", "cronjob", "browser"],
  },
  {
    id: "kelk",
    label: "Kelk",
    model: "gemma-4-e4b-it-6bit",
    provider: "mlx-vlm:41962",
    toolsets: ["terminal", "file", "web", "memory", "session_search", "skills", "clarify"],
  },
  {
    id: "ig88",
    label: "IG-88",
    model: "xiaomi/mimo-v2-pro",
    provider: "nous",
    toolsets: ["terminal", "file", "web", "delegation", "memory", "session_search", "skills", "cronjob", "vision", "browser"],
  },
];

export const DEMO_MEMORY_BUDGET = {
  total_gb: 32,
  available_gb: 6.4,
  used_by_inference_gb: 15.8,
  headroom_gb: 4.0,
  models: [
    { agent: "boot", provider: "mlx-vlm", port: 41961, model: "gemma-4-e4b-it-6bit", loaded: true, est_gb: 7.2 },
    { agent: "kelk", provider: "mlx-vlm", port: 41962, model: "gemma-4-e4b-it-6bit", loaded: true, est_gb: 7.1 },
    { agent: "aux", provider: "flash-moe", port: 41966, model: "gemma-4-26b-a4b-it-6bit", loaded: true, est_gb: 1.5 },
    { agent: "ig88", provider: "nous", port: null, model: "xiaomi/mimo-v2-pro", loaded: false, est_gb: 0 },
  ],
};

export const DEMO_BUDGET = {
  agents: [
    {
      agent_id: "boot",
      monthly_limit_usd: 50,
      spent_this_month_usd: 12.34,
      status: { kind: "normal" as const },
      incidents: [],
    },
    {
      agent_id: "kelk",
      monthly_limit_usd: 50,
      spent_this_month_usd: 8.10,
      status: { kind: "normal" as const },
      incidents: [],
    },
    {
      agent_id: "ig88",
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
    { id: "job.01.001.0001", title: "Portal v8 design overhaul", status: "done", order: 1, blocked_by: [], block: "01-Portal", assignee: "boot" },
    { id: "job.01.002.0001", title: "Config page — live agent controls", status: "in-progress", order: 2, blocked_by: [], block: "01-Portal", assignee: "boot" },
    { id: "job.01.003.0001", title: "Mobile responsive audit", status: "in-progress", order: 3, blocked_by: [], block: "01-Portal", assignee: "boot" },
    { id: "job.02.001.0001", title: "Gemma 4 E4B model serving (mlx-vlm)", status: "done", order: 4, blocked_by: [], block: "02-Models", assignee: "boot" },
    { id: "job.02.002.0001", title: "26B-A4B SSD expert streaming", status: "done", order: 5, blocked_by: [], block: "02-Models", assignee: "boot" },
    { id: "job.03.001.0001", title: "E2EE migration from Pantalaimon", status: "done", order: 6, blocked_by: [], block: "03-Matrix", assignee: "boot" },
    { id: "job.03.002.0001", title: "Cross-signing automation", status: "done", order: 7, blocked_by: [], block: "03-Matrix", assignee: "boot" },
    { id: "job.04.001.0001", title: "Coordinator-rs build and deploy", status: "done", order: 8, blocked_by: [], block: "04-Coordinator", assignee: "boot" },
    { id: "job.05.001.0001", title: "IG-88 trading system bootstrap", status: "in-progress", order: 9, blocked_by: [], block: "05-Trading", assignee: "ig88" },
    { id: "job.05.002.0001", title: "Polymarket venue setup", status: "pending", order: 10, blocked_by: ["job.05.001.0001"], block: "05-Trading", assignee: "ig88" },
    { id: "job.05.003.0001", title: "Kraken API integration", status: "pending", order: 11, blocked_by: ["job.05.001.0001"], block: "05-Trading", assignee: "ig88" },
    { id: "job.06.001.0001", title: "Kelk foundation documentation", status: "done", order: 12, blocked_by: [], block: "06-Agents", assignee: "kelk" },
    { id: "job.06.002.0001", title: "Agent health monitoring", status: "pending", order: 13, blocked_by: [], block: "06-Agents", assignee: null },
    { id: "job.07.001.0001", title: "Factory launchd service matrix", status: "done", order: 14, blocked_by: [], block: "07-Infra", assignee: "boot" },
    { id: "job.07.002.0001", title: "Caddy reverse proxy config", status: "done", order: 15, blocked_by: [], block: "07-Infra", assignee: "boot" },
    { id: "job.08.001.0001", title: "Hermes cron job framework", status: "done", order: 16, blocked_by: [], block: "08-Automation", assignee: "boot" },
    { id: "job.08.002.0001", title: "Paper trade scanner cycle", status: "in-progress", order: 17, blocked_by: [], block: "08-Automation", assignee: "ig88" },
    { id: "job.09.001.0001", title: "Qdrant vault for PREFIX docs", status: "done", order: 18, blocked_by: [], block: "09-Research", assignee: "boot" },
    { id: "job.09.002.0001", title: "Research MCP server", status: "done", order: 19, blocked_by: [], block: "09-Research", assignee: "boot" },
    { id: "job.10.001.0001", title: "Demo deployment for Nous review", status: "in-progress", order: 20, blocked_by: [], block: "10-Outreach", assignee: "boot" },
  ],
  blocks: {
    "01-Portal": { label: "Portal", color: "#38bdf8" },
    "02-Models": { label: "Models", color: "#a78bfa" },
    "03-Matrix": { label: "Matrix", color: "#22c55e" },
    "04-Coordinator": { label: "Coordinator", color: "#fbbf24" },
    "05-Trading": { label: "Trading", color: "#f97316" },
    "06-Agents": { label: "Agents", color: "#fb7185" },
    "07-Infra": { label: "Infra", color: "#94a3b8" },
    "08-Automation": { label: "Automation", color: "#34d399" },
    "09-Research": { label: "Research", color: "#c084fc" },
    "10-Outreach": { label: "Outreach", color: "#38bdf8" },
  },
  log: [
    { timestamp: "2026-04-19T13:00:00Z", actor: "boot", action: "completed", task_id: "job.03.001.0001", detail: "E2EE migration done" },
    { timestamp: "2026-04-19T12:30:00Z", actor: "ig88", action: "started", task_id: "job.05.001.0001", detail: "Trading system bootstrap" },
    { timestamp: "2026-04-19T11:00:00Z", actor: "boot", action: "completed", task_id: "job.02.002.0001", detail: "SSD expert streaming live" },
  ],
};

// ── Agent Statuses ────────────────────────────────────────────────

export const DEMO_AGENT_STATUSES: Record<string, AgentStatus> = {
  boot: {
    status: "working",
    notes: "Portal config page — live controls",
    current_task: "job.01.002.0001",
    last_updated: "2026-04-19T17:30:00Z",
  },
  kelk: {
    status: "idle",
    notes: "Waiting for assignment",
    last_updated: "2026-04-19T17:25:00Z",
  },
  ig88: {
    status: "working",
    notes: "Paper trade scanner cycle",
    current_task: "job.08.002.0001",
    last_updated: "2026-04-19T17:28:00Z",
  },
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
