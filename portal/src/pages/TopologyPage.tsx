import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useAgentStatuses, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { timeAgo } from "../lib/utils";

const AGENT_CSS_COLORS: Record<string, string> = {
  boot: "var(--agent-boot)",
  ig88: "var(--agent-ig88)",
  kelk: "var(--agent-kelk)",
  nan: "var(--agent-nan)",
};

export function TopologyPage() {
  const statuses = useAgentStatuses();

  const activeAgentCount = AGENTS.filter((agent) => {
    const s = statuses.data[agent.id];
    return s && s.status !== "paused" && s.status !== "waiting";
  }).length;

  const totalActiveLoops = AGENTS.reduce((sum, agent) => {
    return sum + (statuses.data[agent.id]?.active_loops?.length ?? 0);
  }, 0);

  const activeRunCount = AGENTS.filter((agent) => {
    return statuses.data[agent.id]?.current_run != null;
  }).length;

  return (
    <AppShell
      title="Factory Topology"
      description="Agent network, infrastructure layers, and system overview."
      pageKey="/pages/topology.html"
      statusSlot={<LastUpdatedChip updatedAt={latestDataUpdatedAt(statuses.results)} stale={statuses.hasError} />}
    >
      {/* Summary Stats */}
      <div className="topology-summary-row">
        <div className="topology-summary-card">
          <div className="topology-summary-card__value">{AGENTS.length}</div>
          <div className="topology-summary-card__label">Total Agents</div>
        </div>
        <div className="topology-summary-card">
          <div className="topology-summary-card__value">{activeAgentCount}</div>
          <div className="topology-summary-card__label">Active Agents</div>
        </div>
        <div className="topology-summary-card">
          <div className="topology-summary-card__value">{totalActiveLoops}</div>
          <div className="topology-summary-card__label">Active Loops</div>
        </div>
        <div className="topology-summary-card">
          <div className="topology-summary-card__value">{activeRunCount}</div>
          <div className="topology-summary-card__label">Active Runs</div>
        </div>
      </div>

      {/* Agent Network */}
      <SurfaceCard title="Agent Network" subtitle="Status and detail entry points" className="surface-card--compact">
        <div className="topology-grid">
          {AGENTS.map((agent) => {
            const status = statuses.data[agent.id];
            const loopCount = status?.active_loops?.length ?? 0;
            const currentTask = status?.current_task as string | undefined;
            return (
              <a
                key={agent.id}
                className="topology-node"
                href={`/pages/agents/${agent.id}.html`}
                style={{ ["--node-accent" as string]: AGENT_CSS_COLORS[agent.id] ?? agent.color }}
              >
                <div className="topology-node__header">
                  <div className="topology-node__label">{agent.label}</div>
                  <div className={`topology-node__status is-${status?.status ?? "waiting"}`}>
                    {status?.status ?? "waiting"}
                  </div>
                </div>
                <div className="topology-stat-row">
                  <div className="topology-stat">
                    <span className="topology-stat__value">{loopCount}</span>
                    <span className="topology-stat__label">loops</span>
                  </div>
                  {currentTask ? (
                    <div className="topology-stat">
                      <span className="topology-stat__label">{currentTask.length > 40 ? `${currentTask.slice(0, 40)}...` : currentTask}</span>
                    </div>
                  ) : null}
                </div>
                <div className="topology-node__meta">
                  {timeAgo(status?.last_updated as string | undefined)}
                </div>
              </a>
            );
          })}
        </div>
      </SurfaceCard>

      {/* System Infrastructure */}
      <SurfaceCard title="System Infrastructure" subtitle="Core services and hardware" className="surface-card--compact">
        <h4 className="topology-layer-title">Services</h4>
        <div className="topology-mini-grid">
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Coordinator</div>
            <div className="topology-mini-node__meta">Rust, Matrix E2EE</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Memory Service</div>
            <div className="topology-mini-node__meta">Graphiti + Qdrant</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">LLM Layer</div>
            <div className="topology-mini-node__meta">MLX local + OpenRouter fallback</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Hardware</div>
            <div className="topology-mini-node__meta">Blackbox RP5 / Cloudkicker M2</div>
          </div>
        </div>
      </SurfaceCard>

      {/* Escalation Chain */}
      <SurfaceCard title="Escalation Chain" subtitle="Approval flow tiers" className="surface-card--compact">
        <div className="topology-mini-grid">
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Auto-approve</div>
            <div className="topology-mini-node__meta">Low risk actions</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Propose-then-execute</div>
            <div className="topology-mini-node__meta">Medium risk actions</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Human approval required</div>
            <div className="topology-mini-node__meta">High risk actions</div>
          </div>
        </div>
      </SurfaceCard>

      {/* Autonomous Loops */}
      <SurfaceCard title="Autonomous Loops" subtitle="Per-agent loop capacity" className="surface-card--compact">
        <div className="topology-mini-grid">
          {AGENTS.map((agent) => {
            const loopCount = statuses.data[agent.id]?.active_loops?.length ?? 0;
            return (
              <div key={agent.id} className="topology-mini-node" style={{ ["--node-accent" as string]: AGENT_CSS_COLORS[agent.id] ?? agent.color }}>
                <div className="topology-mini-node__label">{agent.label}</div>
                <div className="topology-mini-node__meta">{loopCount} active loop{loopCount !== 1 ? "s" : ""}</div>
              </div>
            );
          })}
        </div>
      </SurfaceCard>
    </AppShell>
  );
}
