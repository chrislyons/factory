import type { AgentId } from "./types";

export interface AgentDefinition {
  id: AgentId;
  label: string;
  shortLabel: string;
  color: string;
  accent: string;
}

export const PORTAL_HOME = "/portal.html";

export const AGENTS: AgentDefinition[] = [
  { id: "boot", label: "Boot", shortLabel: "BT", color: "#38bdf8", accent: "#38bdf8" },
  { id: "ig88", label: "IG-88", shortLabel: "IG", color: "#f97316", accent: "#f97316" },
  { id: "kelk", label: "Kelk", shortLabel: "KE", color: "#a78bfa", accent: "#a78bfa" },
  { id: "nan", label: "Nan", shortLabel: "NN", color: "#fb7185", accent: "#fb7185" }
];

export const NAV_LINKS = [
  { href: PORTAL_HOME, label: "Portal" },
  { href: "/pages/dashboard-v4.html", label: "Mission Control" },
  { href: "/pages/loops.html", label: "Loops" },
  { href: "/pages/approvals.html", label: "Approvals" },
  { href: "/pages/budget.html", label: "Budget" },
  { href: "/pages/analytics.html", label: "Analytics" },
  { href: "/pages/topology.html", label: "Topology" }
];

export const DOC_LINKS = [
  { href: "/pages/explainers-v4.html", label: "Repo Explorer" },
  { href: "/pages/architecture-gallery.html", label: "Architecture Gallery" },
  { href: "/pages/credential-rotation-guide.html", label: "Credential Rotation" },
  { href: "/pages/local-inference-guide.html", label: "Local Inference" },
  { href: "/pages/repo-commands.html", label: "Command Reference" }
];

export const POLL_INTERVAL_MS = 5_000;
