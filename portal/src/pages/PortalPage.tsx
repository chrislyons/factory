import { AppShell, SurfaceCard } from "../components/AppShell";
import { SyncClock } from "../components/primitives/SyncClock";
import { AGENTS, PORTAL_HOME } from "../lib/constants";
import { useAgentStatuses, useBudgetStatus, usePendingApprovals, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { budgetStatusKind, formatUsd } from "../lib/utils";

const cards = [
  {
    href: "/pages/jobs.html",
    title: "Jobs",
    description: "Task operations, live agents, and operator metrics",
    note: "Dispatch, live state, and work routing",
    key: "mission",
    priority: "primary"
  },
  {
    href: "/pages/loops.html",
    title: "Loops",
    description: "Active loop console, approvals queue, and iteration controls",
    note: "Iteration oversight, gate decisions, and abort controls",
    key: "loops",
    priority: "primary"
  },
  {
    href: "/pages/analytics.html",
    title: "Analytics",
    description: "14-day activity charts, budget policies, and approval performance",
    note: "Trend signals, spend guardrails, and performance context",
    key: "analytics",
    priority: "primary"
  },
  {
    href: "/pages/object-index.html",
    title: "Objects",
    description: "Searchable index of all factory objects and entities",
    note: "Entity lookup and cross-reference",
    key: "objectindex",
    priority: "secondary"
  },
  {
    href: "/pages/topology.html",
    title: "System",
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
        <SyncClock
          updatedAt={lastUpdatedAt}
          stale={Boolean(approvals.error || budget.error || statuses.hasError)}
        />
      }
    >
      <div className="landing-grid">
        {cards.map((card) => (
          <a key={card.href} className={`landing-card is-${card.priority}`} href={card.href}>
            <div className="landing-card__topline">
              <div className="landing-card__eyebrow-wrap">
                <span className="landing-card__eyebrow">
                  {card.priority === "primary" ? "Primary Surface" : "Operator Surface"}
                </span>
              </div>
              {card.key === "mission" && statusFeedsLoaded ? (
                <span className="landing-card__badge">{activeAgents} active agents</span>
              ) : null}
              {card.key === "loops" && approvalsLoaded && pendingApprovals > 0 ? (
                <span className="landing-card__badge is-alert">{pendingApprovals} pending</span>
              ) : card.key === "loops" && loopFeedsEnabled ? (
                <span className={activeLoopCount > 0 ? "landing-card__badge is-alert" : "landing-card__badge"}>
                  {activeLoopCount} active
                </span>
              ) : null}
              {card.key === "analytics" && budgetLoaded ? (
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
    </AppShell>
  );
}
