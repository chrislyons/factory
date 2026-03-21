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
  { id: "boot", label: "Boot", shortLabel: "BT", color: "#38bdf8", accent: "#38bdf8", model: "Nanbeige4.1-3B", trust: "L2 Advisor" },
  { id: "ig88", label: "IG-88", shortLabel: "IG", color: "#f97316", accent: "#f97316", model: "Nanbeige4.1-3B", trust: "L3 Operator" },
  { id: "kelk", label: "Kelk", shortLabel: "KE", color: "#a78bfa", accent: "#a78bfa", model: "Qwen3.5-4B", trust: "L2 Advisor" },
  { id: "nan", label: "Nan", shortLabel: "NN", color: "#fb7185", accent: "#fb7185", model: "LFM2.5-1.2B", trust: "L1 Observer" }
];

export const NAV_LINKS = [
  { href: PORTAL_HOME, label: "Jobs" },
  { href: "/pages/loops.html", label: "Loops" },
  { href: "/pages/object-index.html", label: "Objects" },
  { href: "/pages/analytics.html", label: "Analytics" },
  { href: "/pages/topology.html", label: "System" },
];

export const DOC_LINKS = [
  { href: "/pages/explainers-v4.html", label: "Repo Explorer" },
  { href: "/pages/architecture-gallery.html", label: "Architecture Gallery" },
  { href: "/pages/credential-rotation-guide.html", label: "Credential Rotation" },
  { href: "/pages/local-inference-guide.html", label: "Local Inference" },
  { href: "/pages/repo-commands.html", label: "Command Reference" }
];

export const POLL_INTERVAL_MS = 5_000;
