import { useMemo } from "react";
import type { ChartConfiguration } from "chart.js";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { ChartCanvas } from "../components/charts/ChartCanvas";
import { AgentBadge } from "../components/primitives/AgentBadge";
import { BudgetBar } from "../components/primitives/BudgetBar";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import { useAnalytics, useBudgetOverride, useBudgetStatus } from "../hooks/usePortalQueries";
import type { AgentId } from "../lib/types";
import { budgetStatusKind, formatUsd, relativeTimestamp } from "../lib/utils";

function ChartPlaceholder({
  detail,
  legend
}: {
  detail: string;
  legend: string[];
}) {
  const bars = [42, 68, 56, 84, 63, 91];
  return (
    <div className="chart-placeholder">
      <div className="chart-placeholder__bars" aria-hidden="true">
        {bars.map((height, index) => (
          <span key={`${height}-${index}`} className="chart-placeholder__bar" style={{ height: `${height}%` }} />
        ))}
      </div>
      <div className="chart-placeholder__detail">{detail}</div>
      <div className="chart-placeholder__legend">
        {legend.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </div>
  );
}

function barConfig({
  labels,
  datasets,
  horizontal = false
}: {
  labels: string[];
  datasets: ChartConfiguration<"bar">["data"]["datasets"];
  horizontal?: boolean;
}): ChartConfiguration<"bar"> {
  return {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      scales: {
        x: {
          stacked: !horizontal,
          ticks: { color: "#94a3b8" },
          grid: { color: "rgba(255,255,255,0.08)" }
        },
        y: {
          stacked: !horizontal,
          ticks: { color: "#94a3b8" },
          grid: { color: "rgba(255,255,255,0.08)" }
        }
      },
      plugins: {
        legend: {
          labels: { color: "#e4eaf1" }
        }
      }
    }
  };
}

export function AnalyticsPage() {
  const analytics = useAnalytics();
  const budget = useBudgetStatus();
  const override = useBudgetOverride();
  const agents = budget.data?.agents ?? [];
  const data = analytics.data;

  const runActivityConfig = useMemo<ChartConfiguration<"bar"> | null>(() => {
    if (!data) return null;
    return barConfig({
      labels: data.run_activity.map((point) => point.label),
      datasets: [
        { label: "Succeeded", data: data.run_activity.map((point) => point.succeeded ?? 0), backgroundColor: "#34d399" },
        { label: "Failed", data: data.run_activity.map((point) => point.failed ?? 0), backgroundColor: "#f87171" },
        { label: "Other", data: data.run_activity.map((point) => point.other ?? 0), backgroundColor: "#fbbf24" }
      ]
    });
  }, [data]);

  const tasksByStatusConfig = useMemo<ChartConfiguration<"bar"> | null>(() => {
    if (!data) return null;
    return barConfig({
      labels: data.tasks_by_status.map((point) => point.label),
      datasets: [
        { label: "Todo", data: data.tasks_by_status.map((point) => point.todo ?? 0), backgroundColor: "#60a5fa" },
        { label: "In Progress", data: data.tasks_by_status.map((point) => point.in_progress ?? 0), backgroundColor: "#6366f1" },
        { label: "Done", data: data.tasks_by_status.map((point) => point.done ?? 0), backgroundColor: "#34d399" },
        { label: "Blocked", data: data.tasks_by_status.map((point) => point.blocked ?? 0), backgroundColor: "#a78bfa" }
      ]
    });
  }, [data]);

  const tasksByAssigneeConfig = useMemo<ChartConfiguration<"bar"> | null>(() => {
    if (!data) return null;
    return barConfig({
      labels: data.tasks_by_assignee.map((point) => point.label),
      datasets: [
        { label: "Tasks", data: data.tasks_by_assignee.map((point) => point.value), backgroundColor: "#60a5fa" }
      ],
      horizontal: true
    });
  }, [data]);

  const approvalRateConfig = useMemo<ChartConfiguration<"doughnut"> | null>(() => {
    if (!data) return null;
    return {
      type: "doughnut",
      data: {
        labels: ["Approved", "Rejected", "Timed Out"],
        datasets: [
          {
            data: [data.approval_rate.approved, data.approval_rate.rejected, data.approval_rate.timed_out],
            backgroundColor: ["#34d399", "#f87171", "#fbbf24"]
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#e4eaf1" } }
        }
      }
    };
  }, [data]);

  return (
    <AppShell
      title="Statistics"
      description="Run, task, and approval activity over the last 14 days."
      pageKey="/pages/analytics.html"
      statusSlot={<SyncClock updatedAt={Math.max(analytics.dataUpdatedAt || 0, budget.dataUpdatedAt || 0)} stale={Boolean(analytics.error || budget.error)} />}
    >
      {/* Budget Policies */}
      <SurfaceCard title="Budget Policies" subtitle="Company and per-agent guardrails">
        {agents.length === 0 ? (
          <EmptyState compact title="Waiting for coordinator budget status" detail="No budget data yet." />
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

      <div className="chart-grid">
        <SurfaceCard title="Run Activity" subtitle="Succeeded vs failed vs other">
          {runActivityConfig ? (
            <div className="chart-wrap"><ChartCanvas config={runActivityConfig} /></div>
          ) : (
            <ChartPlaceholder detail="Run activity appears here when analytics summary is available." legend={["Succeeded", "Failed", "Other"]} />
          )}
        </SurfaceCard>
        <SurfaceCard title="Tasks by Status" subtitle="Last 14 days">
          {tasksByStatusConfig ? (
            <div className="chart-wrap"><ChartCanvas config={tasksByStatusConfig} /></div>
          ) : (
            <ChartPlaceholder detail="Task status movement will render here once the coordinator summary is live." legend={["Todo", "In Progress", "Done", "Blocked"]} />
          )}
        </SurfaceCard>
        <SurfaceCard title="Tasks by Assignee" subtitle="Current allocation">
          {tasksByAssigneeConfig ? (
            <div className="chart-wrap"><ChartCanvas config={tasksByAssigneeConfig} /></div>
          ) : (
            <ChartPlaceholder detail="Assignee distribution will render here when current workload data is available." legend={["Boot", "IG-88", "Kelk", "Nan"]} />
          )}
        </SurfaceCard>
        <SurfaceCard title="Approval Rate" subtitle="Approved vs rejected vs timed out">
          {approvalRateConfig ? (
            <div className="chart-wrap"><ChartCanvas config={approvalRateConfig} /></div>
          ) : (
            <ChartPlaceholder detail="Approval outcomes will render here once the decision summary endpoint is available." legend={["Approved", "Rejected", "Timed Out"]} />
          )}
        </SurfaceCard>
      </div>
    </AppShell>
  );
}
