import { AppShell, SurfaceCard } from "../components/AppShell";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { AGENTS, PORTAL_HOME } from "../lib/constants";
import { useAgentStatuses, useBudgetStatus, usePendingApprovals, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { budgetStatusKind, formatUsd } from "../lib/utils";

const cards = [
  {
    href: "/pages/dashboard-v4.html",
    title: "Mission Control",
    description: "Task operations, live agents, and operator metrics",
    note: "Dispatch, live state, and work routing",
    key: "mission",
    priority: "primary"
  },
  {
    href: "/pages/approvals.html",
    title: "Approvals",
    description: "Typed gate inbox with optimistic decisions and history",
    note: "Gate decisions, countdowns, and outcomes",
    key: "approvals",
    priority: "primary"
  },
  {
    href: "/pages/budget.html",
    title: "Budget",
    description: "Per-agent spend, incidents, and override surfaces",
    note: "Spend guardrails and override posture",
    key: "budget",
    priority: "primary"
  },
  {
    href: "/pages/loops.html",
    title: "Loops",
    description: "Active loop console, iteration history, and operator controls",
    note: "Iteration oversight and abort controls",
    key: "loops",
    priority: "secondary"
  },
  {
    href: "/pages/analytics.html",
    title: "Analytics",
    description: "14-day activity and approval performance charts",
    note: "Trend signals and performance context",
    key: "analytics",
    priority: "secondary"
  },
  {
    href: "/pages/topology.html",
    title: "Topology",
    description: "System map and direct links into agent detail views",
    note: "Agent identity, status, and detail entry points",
    key: "topology",
    priority: "secondary"
  }
];

export function PortalPage() {
  const statuses = useAgentStatuses();
  const approvals = usePendingApprovals();
  const budget = useBudgetStatus();
  const statusFeedsLoaded = AGENTS.some((agent) => Boolean(statuses.data[agent.id]));
  const approvalsLoaded = Array.isArray(approvals.data);
  const budgetLoaded = Boolean(budget.data);

  const activeAgents = AGENTS.filter((agent) => {
    const status = statuses.data[agent.id];
    return status && status.status !== "paused" && status.status !== "error";
  }).length;
  const loopFeedsEnabled = AGENTS.some((agent) => Array.isArray(statuses.data[agent.id]?.active_loops));
  const activeLoopCount = AGENTS.reduce((sum, agent) => {
    return sum + (statuses.data[agent.id]?.active_loops?.length ?? 0);
  }, 0);

  const pendingApprovals = approvals.data?.length ?? 0;
  const pausedBudgets = (budget.data?.agents ?? []).filter(
    (entry) => budgetStatusKind(entry.status) === "paused"
  ).length;
  const totalSpend = (budget.data?.agents ?? []).reduce(
    (sum, agent) => sum + agent.spent_this_month_usd,
    0
  );
  const lastUpdatedAt = latestDataUpdatedAt([
    approvals,
    budget,
    ...statuses.results
  ]);

  return (
    <AppShell
      title="Factory Operator Control Plane"
      description="A consolidated React surface for approvals, budgets, live runs, metrics, and operator controls."
      pageKey={PORTAL_HOME}
      statusSlot={
        <LastUpdatedChip
          updatedAt={lastUpdatedAt}
          stale={Boolean(approvals.error || budget.error || statuses.hasError)}
        />
      }
    >
      <div className="landing-grid">
        {cards.map((card) => (
          <a key={card.href} className={`landing-card is-${card.priority}`} href={card.href}>
            <div className="landing-card__topline">
              <span className="landing-card__eyebrow">
                {card.priority === "primary" ? "Primary Surface" : "Operator Surface"}
              </span>
              {card.key === "mission" && statusFeedsLoaded ? (
                <span className="landing-card__badge">{activeAgents} active agents</span>
              ) : null}
              {card.key === "loops" && loopFeedsEnabled ? (
                <span className={activeLoopCount > 0 ? "landing-card__badge is-alert" : "landing-card__badge"}>
                  {activeLoopCount} active
                </span>
              ) : null}
              {card.key === "approvals" && approvalsLoaded && pendingApprovals > 0 ? (
                <span className="landing-card__badge is-alert">{pendingApprovals} pending</span>
              ) : null}
              {card.key === "budget" && budgetLoaded ? (
                <span className={pausedBudgets > 0 ? "landing-card__badge is-alert" : "landing-card__badge"}>
                  {pausedBudgets > 0 ? `${pausedBudgets} paused` : formatUsd(totalSpend)}
                </span>
              ) : null}
            </div>
            <h2>{card.title}</h2>
            <p>{card.description}</p>
            <span className="landing-card__note">{card.note}</span>
          </a>
        ))}
      </div>

      <div className="portal-columns">
        <SurfaceCard title="Operator Flow" subtitle="Where each surface earns its keep" className="surface-card--compact">
          <ul className="compact-list">
            <li>Open Mission Control first for dispatch, task handling, and live operator context.</li>
            <li>Use Approvals for decision pressure, Budget for guardrails, and Loops for active iteration control.</li>
            <li>Topology is the shortest path into agent-specific detail when a surface needs more context.</li>
            <li>Analytics stays as the long-view companion once work is already in motion.</li>
          </ul>
        </SurfaceCard>
        <SurfaceCard title="Shared Signals" subtitle="Conventions that carry across every page" className="surface-card--compact">
          <ul className="compact-list">
            <li>Agent color is consistent between topology, task rails, and detail entry points.</li>
            <li>Selected navigation and urgent incidents are the only places that should glow brightly.</li>
            <li>Every page keeps working in a useful degraded state when coordinator routes are unavailable.</li>
            <li>`Cmd/Ctrl + K` is global, so navigation does not depend on visual scanning alone.</li>
          </ul>
        </SurfaceCard>
      </div>
    </AppShell>
  );
}
