import { agentDefinition } from "../../lib/utils";
import { StatusDot } from "./StatusDot";

export function AgentBadge({
  agentId,
  fallback,
  status = "idle"
}: {
  agentId?: string | null;
  fallback?: string;
  status?: "active" | "idle" | "paused" | "error";
}) {
  const agent = agentDefinition(agentId);
  return (
    <span className="agent-badge">
      <StatusDot status={status} />
      <span style={{ color: agent?.color }}>{agent?.label ?? fallback ?? agentId ?? "Unknown"}</span>
    </span>
  );
}
