import { AppShell, SurfaceCard } from "../components/AppShell";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { AGENTS } from "../lib/constants";
import { useAgentStatuses, useBudgetStatus, usePendingApprovals, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { budgetStatusKind, formatUsd } from "../lib/utils";

const cards = [
  {
    href: "/pages/dashboard-v4.html",
    title: "Mission Control",
    description: "Task operations, live agents, and operator metrics",
    key: "mission"
  },
  {
    href: "/pages/loops.html",
    title: "Loops",
    description: "Active loop console, iteration history, and operator controls",
    key: "loops"
  },
  {
    href: "/pages/approvals.html",
    title: "Approvals",
    description: "Typed gate inbox with optimistic decisions and history",
    key: "approvals"
  },
  {
    href: "/pages/budget.html",
    title: "Budget",
    description: "Per-agent spend, incidents, and override surfaces",
    key: "budget"
  },
  {
    href: "/pages/analytics.html",
    title: "Analytics",
    description: "14-day activity and approval performance charts",
    key: "analytics"
  },
  {
    href: "/pages/topology.html",
    title: "Topology",
    description: "System map and direct links into agent detail views",
    key: "topology"
  }
];

export function PortalPage() {
  const statuses = useAgentStatuses();
  const approvals = usePendingApprovals();
  const budget = useBudgetStatus();

  const activeAgents = AGENTS.filter((agent) => {
    const status = statuses.data[agent.id];
    return status?.status !== "paused" && status?.status !== "error";
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
      pageKey="/"
      statusSlot={
        <LastUpdatedChip
          updatedAt={lastUpdatedAt}
          stale={Boolean(approvals.error || budget.error || statuses.hasError)}
        />
      }
    >
      <div className="card-grid">
        {cards.map((card) => (
          <a key={card.href} className="landing-card" href={card.href}>
            <span className="landing-card__eyebrow">Operator Surface</span>
            {card.key === "mission" ? (
              <span className="landing-card__badge">{activeAgents} active agents</span>
            ) : null}
            {card.key === "loops" && loopFeedsEnabled ? (
              <span className={activeLoopCount > 0 ? "landing-card__badge is-alert" : "landing-card__badge"}>
                {activeLoopCount} active
              </span>
            ) : null}
            {card.key === "approvals" && pendingApprovals > 0 ? (
              <span className="landing-card__badge is-alert">{pendingApprovals} pending</span>
            ) : null}
            {card.key === "budget" ? (
              <span className={pausedBudgets > 0 ? "landing-card__badge is-alert" : "landing-card__badge"}>
                {pausedBudgets > 0 ? `${pausedBudgets} paused` : formatUsd(totalSpend)}
              </span>
            ) : null}
            <h2>{card.title}</h2>
            <p>{card.description}</p>
          </a>
        ))}
      </div>

      <div className="portal-columns">
        <SurfaceCard title="Why React here" subtitle="Dense stateful UI is no longer incidental">
          <ul className="compact-list">
            <li>Approval inbox state and countdown timers need stable derived state.</li>
            <li>Budget and live-run surfaces need shared components and stale-data retention.</li>
            <li>Loop governance now adds a dedicated console rather than hiding behind generic run cards.</li>
            <li>Paperclip’s dashboard patterns map to the current Factory operator needs.</li>
          </ul>
        </SurfaceCard>
        <SurfaceCard title="Build Status" subtitle="Scaffold milestone">
          <ul className="compact-list">
            <li>React build is live and emitting the preserved portal URLs into `dist/`.</li>
            <li>Static docs remain outside the React app and are copied into `dist/` post-build.</li>
            <li>Current live metrics already feed the landing-card badges above.</li>
            <li>Loop surfaces degrade to waiting states until `/loops` and `active_loops` are present.</li>
          </ul>
        </SurfaceCard>
      </div>
    </AppShell>
  );
}
