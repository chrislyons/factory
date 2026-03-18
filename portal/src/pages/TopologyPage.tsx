import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useAgentStatuses, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { timeAgo } from "../lib/utils";

export function TopologyPage() {
  const statuses = useAgentStatuses();
  return (
    <AppShell
      title="Factory Topology"
      description="Agent network, current state, and direct links into detail views."
      pageKey="/pages/topology.html"
      statusSlot={<LastUpdatedChip updatedAt={latestDataUpdatedAt(statuses.results)} stale={statuses.hasError} />}
    >
      <SurfaceCard title="Agent Network" subtitle="Status and detail entry points" className="surface-card--compact">
        <div className="topology-grid">
          {AGENTS.map((agent) => (
            <a
              key={agent.id}
              className="topology-node"
              href={`/pages/agents/${agent.id}.html`}
              style={{ ["--node-accent" as string]: agent.color }}
            >
              <div className="topology-node__header">
                <div className="topology-node__label">{agent.label}</div>
                <div className={`topology-node__status is-${statuses.data[agent.id]?.status ?? "waiting"}`}>
                  {statuses.data[agent.id]?.status ?? "waiting"}
                </div>
              </div>
              <div className="topology-node__meta">
                {timeAgo(statuses.data[agent.id]?.last_updated as string | undefined)}
              </div>
              <div className="topology-node__note">Open detail view</div>
            </a>
          ))}
        </div>
      </SurfaceCard>
    </AppShell>
  );
}
