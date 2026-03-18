import type { AgentId } from "./types";

export interface AgentDefinition {
  id: AgentId;
  label: string;
  shortLabel: string;
  color: string;
  accent: string;
}

export const AGENTS: AgentDefinition[] = [
  { id: "boot", label: "Boot", shortLabel: "BT", color: "#74b6f6", accent: "#74b6f6" },
  { id: "ig88", label: "IG-88", shortLabel: "IG", color: "#f2c86f", accent: "#f2c86f" },
  { id: "kelk", label: "Kelk", shortLabel: "KE", color: "#58d8a6", accent: "#58d8a6" },
  { id: "nan", label: "Nan", shortLabel: "NN", color: "#c7bcad", accent: "#c7bcad" }
];

export const NAV_LINKS = [
  { href: "/", label: "Portal" },
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
