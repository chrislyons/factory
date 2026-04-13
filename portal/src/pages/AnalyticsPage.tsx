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

      {/* IG-88 Trading Visualizations */}
      <SurfaceCard title="IG-88 Trading Visualizations" subtitle="Backtest equity curves, Ichimoku signals, and daily summaries — Manim 0.20.1">
        <div className="ig88-viz-filters" style={{ display: "flex", gap: "0.35rem", marginBottom: "1rem", flexWrap: "wrap" }}>
          {["all", "equity", "ichimoku", "backtest", "daily"].map((f) => (
            <button
              key={f}
              className="ig88-viz-filter"
              data-filter={f}
              style={{
                fontFamily: "var(--font-body)", fontSize: "0.75rem", padding: "0.35rem 0.75rem",
                border: "1px solid var(--border-strong)", background: "var(--bg-panel)", color: "var(--text-muted)",
                borderRadius: "8px", cursor: "pointer", textTransform: "capitalize",
              }}
              onClick={(e) => {
                document.querySelectorAll(".ig88-viz-filter").forEach((b) => {
                  (b as HTMLElement).style.background = "var(--bg-panel)";
                  (b as HTMLElement).style.color = "var(--text-muted)";
                  (b as HTMLElement).style.borderColor = "var(--border-strong)";
                });
                e.currentTarget.style.background = "var(--accent)";
                e.currentTarget.style.color = "#fff";
                e.currentTarget.style.borderColor = "var(--accent)";
                document.querySelectorAll<HTMLElement>(".ig88-viz-card").forEach((card) => {
                  card.style.display = (f === "all" || card.dataset.cat === f) ? "" : "none";
                });
              }}
            >
              {f === "all" ? "All" : f}
            </button>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
          {[
            { cat: "equity", title: "Equity Curve — H3-Combined", badge: "Backtest", badgeColor: "var(--green)",
              src: "/renders/ig88/videos/equity_curve/480p15/EquityCurveScene.mp4", poster: "/renders/ig88/poster_equity_curve.png",
              stats: [["Initial", "$10,000", ""], ["Final", "$26,055", "pos"], ["Return", "+160.6%", "pos"], ["PF", "3.13", "pos"], ["WR", "57.7%", "pos"], ["Trades", "52", ""]],
              desc: "Regime overlay (green=RISK_ON, yellow=NEUTRAL, red=RISK_OFF). Trade markers: green=win, red=loss.",
              full: true },
            { cat: "ichimoku", title: "Ichimoku Cloud — H3-A", badge: "Signal", badgeColor: "var(--accent)",
              src: "/renders/ig88/videos/ichimoku_cloud/480p15/IchimokuCloudScene.mp4", poster: "/renders/ig88/poster_ichimoku_cloud.png",
              stats: [["Strategy", "H3-A", ""], ["OOS PF", "4.82", "pos"], ["WR", "57.9%", "pos"]],
              desc: "TK crossover highlighted. Cloud: green=bearish, red=bullish. Score gauge bottom-right." },
            { cat: "backtest", title: "Walk-Forward Validation", badge: "OOS", badgeColor: "var(--yellow)",
              src: "/renders/ig88/videos/backtest_comparison/480p15/BacktestComparisonScene.mp4", poster: "/renders/ig88/poster_backtest_comparison.png",
              stats: [["Train PF", "4.12", ""], ["OOS PF", "2.13", "pos"], ["Ratio", "51.7%", "pos"]],
              desc: "Split train(70%) / test(30%). Arrow shows PF decay." },
            { cat: "daily", title: "Daily Summary — Matrix GIF", badge: "Report", badgeColor: "var(--green)",
              src: "/renders/ig88/videos/daily_summary/480p15/DailySummaryScene.mp4", poster: "/renders/ig88/poster_daily_summary.png",
              stats: [["Format", "GIF", ""], ["Size", "70 KB", ""], ["Duration", "6s", ""]],
              desc: "Regime indicator, trade list + P&L, open positions, stats summary.",
              full: true },
          ].map((v) => (
            <div key={v.cat} className="ig88-viz-card" data-cat={v.cat} style={{
              gridColumn: v.full ? "1 / -1" : undefined,
              background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: "var(--radius)", overflow: "hidden",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.625rem 1rem", borderBottom: "1px solid var(--border)" }}>
                <span style={{ fontSize: "0.8125rem", fontWeight: 400 }}>{v.title}</span>
                <span style={{ fontSize: "0.5625rem", textTransform: "uppercase", letterSpacing: "0.05em", padding: "0.2rem 0.45rem", borderRadius: "4px", background: `color-mix(in srgb, ${v.badgeColor} 12%, transparent)`, color: v.badgeColor, border: `1px solid color-mix(in srgb, ${v.badgeColor} 18%, transparent)` }}>{v.badge}</span>
              </div>
              <div style={{ padding: "1rem" }}>
                <div style={{ background: "var(--bg-deep)", borderRadius: "8px", overflow: "hidden", aspectRatio: "16/9" }}>
                  <video controls preload="metadata" poster={v.poster} style={{ width: "100%", height: "100%", objectFit: "contain", display: "block" }}>
                    <source src={v.src} type="video/mp4" />
                  </video>
                </div>
                <div style={{ display: "flex", gap: 0, marginTop: "0.75rem", background: "var(--bg-deep)", border: "1px solid var(--border)", borderRadius: "8px", overflow: "hidden" }}>
                  {v.stats.map(([label, value, kind]) => (
                    <div key={label} style={{ flex: 1, padding: "0.5rem 0.75rem", textAlign: "center", borderRight: "1px solid var(--border)" }}>
                      <div style={{ fontSize: "0.5625rem", textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-muted)", marginBottom: "0.125rem" }}>{label}</div>
                      <div style={{ fontFamily: "var(--font-body)", fontSize: "0.875rem", color: kind === "pos" ? "var(--green)" : kind === "neg" ? "var(--red)" : "var(--text)" }}>{value}</div>
                    </div>
                  ))}
                </div>
                <p style={{ fontSize: "0.75rem", color: "var(--text-dim)", marginTop: "0.5rem", lineHeight: 1.5 }}>{v.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </SurfaceCard>
    </AppShell>
  );
}
