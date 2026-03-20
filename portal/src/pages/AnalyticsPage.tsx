import { useMemo } from "react";
import type { ChartConfiguration } from "chart.js";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { ChartCanvas } from "../components/charts/ChartCanvas";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useAnalytics } from "../hooks/usePortalQueries";

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
      title="Analytics"
      description="Run, task, and approval activity over the last 14 days."
      pageKey="/pages/analytics.html"
      statusSlot={<LastUpdatedChip updatedAt={analytics.dataUpdatedAt} stale={Boolean(analytics.error)} />}
    >
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
