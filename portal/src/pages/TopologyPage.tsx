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
      description="The topology view is now part of the shared React shell and links directly into agent detail pages."
      pageKey="/pages/topology.html"
      statusSlot={<LastUpdatedChip updatedAt={latestDataUpdatedAt(statuses.results)} stale={statuses.hasError} />}
    >
      <SurfaceCard title="Agent Network" subtitle="Current v1 React migration">
        <div className="topology-grid">
          {AGENTS.map((agent) => (
            <a
              key={agent.id}
              className="topology-node"
              href={`/pages/agents/${agent.id}.html`}
              style={{ ["--node-accent" as string]: agent.color }}
            >
              <div className="topology-node__label">{agent.label}</div>
              <div className="topology-node__meta">
                {statuses.data[agent.id]?.status ?? "waiting"} · {timeAgo(statuses.data[agent.id]?.last_updated as string | undefined)}
              </div>
            </a>
          ))}
        </div>
      </SurfaceCard>
    </AppShell>
  );
}
