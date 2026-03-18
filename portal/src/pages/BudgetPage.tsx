import { AppShell, SurfaceCard } from "../components/AppShell";
import { AgentBadge } from "../components/primitives/AgentBadge";
import { BudgetBar } from "../components/primitives/BudgetBar";
import { EmptyState } from "../components/primitives/EmptyState";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { MetricCard } from "../components/primitives/MetricCard";
import { useBudgetOverride, useBudgetStatus } from "../hooks/usePortalQueries";
import type { AgentId } from "../lib/types";
import { budgetStatusKind, formatUsd, relativeTimestamp } from "../lib/utils";

export function BudgetPage() {
  const budget = useBudgetStatus();
  const override = useBudgetOverride();
  const agents = budget.data?.agents ?? [];
  const totalSpend = agents.reduce((sum, agent) => sum + agent.spent_this_month_usd, 0);
  const totalLimit = agents.reduce((sum, agent) => sum + agent.monthly_limit_usd, 0);
  const pausedCount = agents.filter((agent) => budgetStatusKind(agent.status) === "paused").length;
  const incidents = agents.flatMap((agent) => agent.incidents);

  return (
    <AppShell
      title="Budget"
      description="Per-agent budget enforcement, incidents, and override surfaces."
      pageKey="/pages/budget.html"
      statusSlot={<LastUpdatedChip updatedAt={budget.dataUpdatedAt} stale={Boolean(budget.error)} />}
    >
      <div className="metric-grid">
        <MetricCard label="Month Spend" value={formatUsd(totalSpend)} detail={totalLimit > 0 ? `of ${formatUsd(totalLimit)}` : "No company cap"} />
        <MetricCard label="Tracked Agents" value={agents.length} />
        <MetricCard label="Paused Agents" value={pausedCount} danger={pausedCount > 0} />
        <MetricCard label="Active Incidents" value={incidents.filter((incident) => incident.status === "open").length} danger={incidents.some((incident) => incident.status === "open")} />
      </div>

      <SurfaceCard title="Budget Policies" subtitle="Company and agent status">
        {agents.length === 0 ? (
          <EmptyState title="Waiting for coordinator budget status" detail="No budget data yet." />
        ) : (
          <div className="budget-grid">
            {agents.map((agent) => {
              const statusKind = budgetStatusKind(agent.status);
              return (
                <article key={agent.agent_id} className="budget-card-ui">
                  <div className="budget-card-ui__header">
                    <div>
                      <AgentBadge agentId={agent.agent_id} fallback={agent.agent_id} status={statusKind === "paused" ? "paused" : "idle"} />
                      <div className="budget-card-ui__meta">{formatUsd(agent.monthly_limit_usd)} monthly cap</div>
                    </div>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={override.isPending}
                      onClick={() => override.mutate(agent.agent_id as AgentId)}
                    >
                      Request Override
                    </button>
                  </div>

                  {statusKind === "paused" ? (
                    <div className="alert-banner is-danger">Budget exhausted — agent paused</div>
                  ) : null}

                  <BudgetBar spent={agent.spent_this_month_usd} limit={agent.monthly_limit_usd} />

                  <div className="budget-incident-list">
                    {agent.incidents.length === 0 ? (
                      <div className="placeholder-copy">No active incidents.</div>
                    ) : (
                      agent.incidents.map((incident) => (
                        <div key={incident.id} className="budget-incident">
                          <strong>{incident.threshold_type}</strong>
                          <span>{formatUsd(incident.amount_observed)} observed</span>
                          <span>{relativeTimestamp(incident.created_at)}</span>
                        </div>
                      ))
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </SurfaceCard>
    </AppShell>
  );
}
