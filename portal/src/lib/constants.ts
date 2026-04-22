import type { AgentId } from "./types";

export interface AgentDefinition {
  id: AgentId;
  label: string;
  shortLabel: string;
  color: string;
  accent: string;
  model: string;
  trust: string;
}

export const PORTAL_HOME = "/pages/jobs.html";

export const AGENTS: AgentDefinition[] = [
  { id: "coord", label: "Coordinator", shortLabel: "CO", color: "#22c55e", accent: "#22c55e", model: "—", trust: "L4 Coordinator" },
  { id: "boot", label: "Boot", shortLabel: "BT", color: "#38bdf8", accent: "#38bdf8", model: "Nanbeige4.1-3B-8bit", trust: "L2 Advisor" },
  { id: "kelk", label: "Kelk", shortLabel: "KE", color: "#a78bfa", accent: "#a78bfa", model: "Qwen3.5-4B-MLX-8bit", trust: "L2 Advisor" },
  { id: "nan", label: "Nan", shortLabel: "NN", color: "#fb7185", accent: "#fb7185", model: "LFM2.5-1.2B-Thinking-MLX-6bit", trust: "L1 Observer" },
  { id: "xamm", label: "Xamm", shortLabel: "XM", color: "#fbbf24", accent: "#fbbf24", model: "—", trust: "L2 Advisor" },
  { id: "ig88", label: "IG-88", shortLabel: "IG", color: "#f97316", accent: "#f97316", model: "Nanbeige4.1-3B-8bit", trust: "L3 Operator" },
];

/** Demo anonymized agents — used only when VITE_DEMO_MODE=true */
export const DEMO_AGENTS_LIST: AgentDefinition[] = [
  { id: "agent-1", label: "Agent 1", shortLabel: "A1", color: "#38bdf8", accent: "#38bdf8", model: "gemma-4-7b", trust: "L2 Advisor" },
  { id: "agent-2", label: "Agent 2", shortLabel: "A2", color: "#a78bfa", accent: "#a78bfa", model: "gemma-4-7b", trust: "L2 Advisor" },
  { id: "agent-3", label: "Agent 3", shortLabel: "A3", color: "#f97316", accent: "#f97316", model: "mimo-v2", trust: "L3 Operator" },
];

export const NAV_LINKS = [
  { href: PORTAL_HOME, label: "Jobs" },
  { href: "/pages/sessions.html", label: "Sessions" },
  { href: "/pages/loops.html", label: "Loops" },
  { href: "/pages/cron.html", label: "Cron" },
  { href: "/pages/health.html", label: "Health" },
  { href: "/pages/activity.html", label: "Activity" },
  { href: "/pages/docs.html", label: "Docs" },
  { href: "/pages/analytics.html", label: "Stats" },
  { href: "/pages/config.html", label: "Config" },
];

export const DOC_LINKS = [
  { href: "/pages/docs.html", label: "Reference Docs" },
  { href: "/pages/docs.html?tab=objects", label: "Object Index" },
];

export const POLL_INTERVAL_MS = 5_000;

export interface AssigneeDefinition {
  id: string;
  label: string;
  color: string;
}

export const ASSIGNEES: AssigneeDefinition[] = [
  ...(import.meta.env.VITE_DEMO_MODE === "true" ? DEMO_AGENTS_LIST : AGENTS).map(a => ({ id: a.id, label: a.label, color: a.color })),
  { id: "chris", label: "Chris", color: "#94a3b8" },
];
