import { useMemo } from "react";
import type { ChartConfiguration } from "chart.js";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { ChartCanvas } from "../components/charts/ChartCanvas";
import { EmptyState } from "../components/primitives/EmptyState";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useAnalytics } from "../hooks/usePortalQueries";

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
          ticks: { color: "#c7bcad" },
          grid: { color: "rgba(255,255,255,0.08)" }
        },
        y: {
          stacked: !horizontal,
          ticks: { color: "#c7bcad" },
          grid: { color: "rgba(255,255,255,0.08)" }
        }
      },
      plugins: {
        legend: {
          labels: { color: "#ebe4d8" }
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
        { label: "Succeeded", data: data.run_activity.map((point) => point.succeeded ?? 0), backgroundColor: "#58d8a6" },
        { label: "Failed", data: data.run_activity.map((point) => point.failed ?? 0), backgroundColor: "#f08a74" },
        { label: "Other", data: data.run_activity.map((point) => point.other ?? 0), backgroundColor: "#8b8174" }
      ]
    });
  }, [data]);

  const tasksByStatusConfig = useMemo<ChartConfiguration<"bar"> | null>(() => {
    if (!data) return null;
    return barConfig({
      labels: data.tasks_by_status.map((point) => point.label),
      datasets: [
        { label: "Todo", data: data.tasks_by_status.map((point) => point.todo ?? 0), backgroundColor: "#74b6f6" },
        { label: "In Progress", data: data.tasks_by_status.map((point) => point.in_progress ?? 0), backgroundColor: "#2dd4bf" },
        { label: "Done", data: data.tasks_by_status.map((point) => point.done ?? 0), backgroundColor: "#58d8a6" },
        { label: "Blocked", data: data.tasks_by_status.map((point) => point.blocked ?? 0), backgroundColor: "#b79af8" }
      ]
    });
  }, [data]);

  const tasksByAssigneeConfig = useMemo<ChartConfiguration<"bar"> | null>(() => {
    if (!data) return null;
    return barConfig({
      labels: data.tasks_by_assignee.map((point) => point.label),
      datasets: [
        { label: "Tasks", data: data.tasks_by_assignee.map((point) => point.value), backgroundColor: "#74b6f6" }
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
            backgroundColor: ["#58d8a6", "#f08a74", "#f2c86f"]
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#ebe4d8" } }
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
      {!data ? (
        <SurfaceCard title="Analytics" subtitle="Waiting for coordinator">
          <EmptyState title="Waiting for analytics summary" detail="`/analytics/summary?days=14` is not returning data yet." />
        </SurfaceCard>
      ) : (
        <div className="chart-grid">
          {runActivityConfig ? (
            <SurfaceCard title="Run Activity" subtitle="Succeeded vs failed vs other">
              <div className="chart-wrap"><ChartCanvas config={runActivityConfig} /></div>
            </SurfaceCard>
          ) : null}
          {tasksByStatusConfig ? (
            <SurfaceCard title="Tasks by Status" subtitle="Last 14 days">
              <div className="chart-wrap"><ChartCanvas config={tasksByStatusConfig} /></div>
            </SurfaceCard>
          ) : null}
          {tasksByAssigneeConfig ? (
            <SurfaceCard title="Tasks by Assignee" subtitle="Current allocation">
              <div className="chart-wrap"><ChartCanvas config={tasksByAssigneeConfig} /></div>
            </SurfaceCard>
          ) : null}
          {approvalRateConfig ? (
            <SurfaceCard title="Approval Rate" subtitle="Approved vs rejected vs timed out">
              <div className="chart-wrap"><ChartCanvas config={approvalRateConfig} /></div>
            </SurfaceCard>
          ) : null}
        </div>
      )}
    </AppShell>
  );
}
