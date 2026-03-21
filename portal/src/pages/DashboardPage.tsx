import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { LoopStatusPill } from "../components/loops/LoopStatusPill";
import { AgentBadge } from "../components/primitives/AgentBadge";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import { TranscriptTail } from "../components/primitives/TranscriptTail";
import {
  latestDataUpdatedAt,
  useAgentStatuses,
  useBudgetStatus,
  usePendingApprovals,
  useRunCancel,
  useTasksDocument
} from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import type { CurrentRunSummary, StatusActiveLoop, TaskRecord, TasksDocument } from "../lib/types";
import {
  cn,
  formatMetricValue,
  loopApprovalGateLabel,
  loopTypeLabel,
  timeAgo
} from "../lib/utils";

function addLogEntry(document: TasksDocument, actor: string, action: string, taskId?: string, detail?: string) {
  document.log.push({
    timestamp: new Date().toISOString(),
    actor,
    action,
    task_id: taskId,
    detail
  });
}

function stampDocument(document: TasksDocument) {
  document.updated = new Date().toISOString();
  document.updated_by = "portal";
}

function unblockDependents(document: TasksDocument, resolvedTaskId: string) {
  document.tasks.forEach((task) => {
    if (!task.blocked_by.includes(resolvedTaskId)) return;
    const allResolved = task.blocked_by.every((dependencyId) => {
      return document.tasks.find((entry) => entry.id === dependencyId)?.status === "done";
    });
    if (allResolved && task.status === "blocked") {
      task.status = "pending";
      task.updated = new Date().toISOString();
      addLogEntry(document, "system", "unblocked", task.id, `dependency ${resolvedTaskId} resolved`);
    }
  });
}

function agentStatusTone(status?: string, currentRun?: CurrentRunSummary | null) {
  if (currentRun && ["running", "queued", "working", "active"].includes(currentRun.status)) {
    return "active" as const;
  }
  if (status === "paused") return "paused" as const;
  if (status === "error" || status === "failed") return "error" as const;
  return "idle" as const;
}

function payloadRuns(statuses: ReturnType<typeof useAgentStatuses>["data"]) {
  return AGENTS.flatMap((agent) => {
    const currentRun = statuses[agent.id]?.current_run;
    return currentRun
      ? [{ agentId: agent.id, agentLabel: agent.label, status: statuses[agent.id], run: currentRun }]
      : [];
  }).sort((left, right) => {
    const leftActive = left.run.status === "running" || left.run.status === "queued";
    const rightActive = right.run.status === "running" || right.run.status === "queued";
    if (leftActive !== rightActive) return leftActive ? -1 : 1;
    return new Date(right.run.started_at).getTime() - new Date(left.run.started_at).getTime();
  });
}

function loopGroups(statuses: ReturnType<typeof useAgentStatuses>["data"]) {
  return AGENTS.map((agent) => ({
    agent,
    loops: (statuses[agent.id]?.active_loops ?? []).filter(Boolean) as StatusActiveLoop[]
  })).filter((group) => group.loops.length > 0);
}

function statusFeedsExposeLoops(statuses: ReturnType<typeof useAgentStatuses>["data"]) {
  return AGENTS.some((agent) => Array.isArray(statuses[agent.id]?.active_loops));
}

export function DashboardPage() {
  const [activeFilter, setActiveFilter] = useState("all");
  const [taskSearch, setTaskSearch] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");

  const tasks = useTasksDocument();
  const statuses = useAgentStatuses();
  const approvals = usePendingApprovals();
  const budget = useBudgetStatus();
  const runCancel = useRunCancel();

  const latestUpdate = latestDataUpdatedAt([tasks, approvals, budget, ...statuses.results]);
  const document = tasks.data;
  const hasStatusData = AGENTS.some((agent) => Boolean(statuses.data[agent.id]));
  const liveRuns = payloadRuns(statuses.data).slice(0, 4);
  const activeLoopGroups = loopGroups(statuses.data);
  const loopFeedsEnabled = statusFeedsExposeLoops(statuses.data);

  const visibleTasks = useMemo(() => {
    const all = [...(document?.tasks ?? [])].sort((a, b) => a.order - b.order);
    return all.filter((task) => {
      if (activeFilter !== "all" && task.block !== activeFilter) return false;
      if (!taskSearch.trim()) return true;
      const haystack = [
        task.id,
        task.title,
        task.description,
        task.assignee,
        task.status,
        document?.blocks[task.block]?.label
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(taskSearch.toLowerCase());
    });
  }, [activeFilter, document, taskSearch]);

  const activeLoopCount = activeLoopGroups.reduce((sum, group) => sum + group.loops.length, 0);

  async function withTasksUpdate(updater: (current: TasksDocument) => TasksDocument) {
    await tasks.updateDocument((current) => updater(structuredClone(current)));
  }

  async function addTask() {
    const title = newTaskTitle.trim();
    if (!title) return;
    await withTasksUpdate((current) => {
      const nextOrder = current.tasks.reduce((max, task) => Math.max(max, task.order), 0) + 1;
      // Find max address in system domain, first available class
      const domain = "00";
      const jobClass = Object.keys(current.blocks)[0] === "infrastructure" ? "001" : "001";
      const prefix = `job.${domain}.${jobClass}.`;
      const maxAddr = current.tasks
        .filter(t => t.id.startsWith(prefix))
        .reduce((max, t) => {
          const addr = parseInt(t.id.split(".").pop() || "0", 10);
          return Math.max(max, addr);
        }, 0);
      const taskId = `job.${domain}.${jobClass}.${String(maxAddr + 1).padStart(4, "0")}`;
      current.tasks.push({
        id: taskId,
        title,
        description: "",
        status: "pending",
        effort: "unknown",
        order: nextOrder,
        blocked_by: [],
        block: Object.keys(current.blocks)[0] ?? "unassigned",
        assignee: null,
        created: new Date().toISOString(),
        updated: new Date().toISOString()
      });
      stampDocument(current);
      addLogEntry(current, "portal", "created", taskId, title);
      return current;
    });
    setNewTaskTitle("");
  }

  async function toggleTask(taskId: string) {
    await withTasksUpdate((current) => {
      const task = current.tasks.find((entry) => entry.id === taskId);
      if (!task || task.status === "blocked") return current;
      task.status = task.status === "done" ? "pending" : "done";
      task.updated = new Date().toISOString();
      stampDocument(current);
      addLogEntry(current, "portal", task.status === "done" ? "completed" : "reopened", taskId);
      if (task.status === "done") {
        unblockDependents(current, taskId);
      }
      return current;
    });
  }

  async function cycleTask(taskId: string) {
    await withTasksUpdate((current) => {
      const task = current.tasks.find((entry) => entry.id === taskId);
      if (!task || task.status === "blocked") return current;
      const cycle: TaskRecord["status"][] = ["pending", "in-progress", "done"];
      const index = cycle.indexOf(task.status);
      task.status = cycle[(index + 1) % cycle.length];
      task.updated = new Date().toISOString();
      stampDocument(current);
      addLogEntry(current, "portal", `status → ${task.status}`, taskId);
      if (task.status === "done") {
        unblockDependents(current, taskId);
      }
      return current;
    });
  }

  async function assignTask(taskId: string, assignee: string) {
    await withTasksUpdate((current) => {
      const task = current.tasks.find((entry) => entry.id === taskId);
      if (!task) return current;
      task.assignee = assignee === "unassigned" ? null : assignee;
      task.updated = new Date().toISOString();
      stampDocument(current);
      addLogEntry(current, "portal", "assigned", taskId, assignee === "unassigned" ? "unassigned" : `→ ${assignee}`);
      return current;
    });
  }

  return (
    <AppShell
      title="Jobs Tracker"
      pageKey="/pages/jobs.html"
      statusSlot={
        <SyncClock
          updatedAt={latestUpdate}
          stale={Boolean(tasks.error || approvals.error || budget.error || statuses.hasError)}
        />
      }
    >
      {!loopFeedsEnabled && liveRuns.length === 0 ? null : (
        <div className="dashboard-highlights">
          <SurfaceCard title="Active Loops" subtitle="Current iteration pressure" className="surface-card--compact">
            {!loopFeedsEnabled ? (
              <EmptyState
                compact
                title="Waiting for loop status"
                detail={hasStatusData ? "Loop rows appear once status feeds expose `active_loops`." : "Status feeds are not available yet."}
              />
            ) : activeLoopCount === 0 ? (
              <EmptyState compact title="No active loops" detail="Loop rows appear here when an agent is running a loop." />
            ) : (
              <div className="loop-strip">
                {activeLoopGroups.map((group) => (
                  <section key={group.agent.id} className="loop-agent-group">
                    <div className="loop-agent-group__header">
                      <AgentBadge agentId={group.agent.id} status="idle" />
                      <span className="loop-agent-group__count">{group.loops.length} loop(s)</span>
                    </div>
                    <div className="loop-agent-group__rows">
                      {group.loops.map((loop) => (
                        <a
                          key={`${group.agent.id}-${loop.loop_id}`}
                          className="loop-row"
                          href={`/pages/loops.html?loop=${loop.loop_id}`}
                        >
                          <div className="loop-row__main">
                            <div className="loop-row__title">
                              <strong>{loop.spec.name}</strong>
                              <LoopStatusPill status={loop.status} />
                            </div>
                            <div className="loop-row__meta">
                              <span>{loopTypeLabel(loop.spec.loop_type)}</span>
                              <span>{loopApprovalGateLabel(loop.spec.approval_gate)}</span>
                              <span>
                                Iter {loop.current_iteration}/{loop.spec.budget.max_iterations}
                              </span>
                            </div>
                          </div>
                          <div className="loop-row__stats">
                            <span>Best {formatMetricValue(loop.best_metric)}</span>
                            <span>Open</span>
                          </div>
                        </a>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </SurfaceCard>

          <SurfaceCard title="Active Runs" subtitle="Transcript tails and operator stop control" className="surface-card--compact">
            {liveRuns.length === 0 ? (
              <EmptyState compact title="No active or recent runs" detail="Live run cards appear here when coordinator exposes run state." />
            ) : (
              <div className="live-run-grid">
                {liveRuns.map((item) => {
                  const isActive = item.run.status === "running" || item.run.status === "queued";
                  return (
                    <div key={`${item.agentId}-${item.run.run_id}`} className={cn("live-run-card", isActive && "is-live")}>
                      <div className="live-run-card__header">
                        <div>
                          <AgentBadge
                            agentId={item.agentId}
                            status={agentStatusTone(item.status?.status as string | undefined, item.run)}
                          />
                          <div className="live-run-card__meta">
                            {isActive ? "Live now" : `Finished ${timeAgo(item.run.finished_at ?? item.run.started_at)}`}
                          </div>
                        </div>
                        {isActive ? (
                          <button
                            className="danger-button"
                            type="button"
                            onClick={() => runCancel.mutate(item.run.run_id)}
                            disabled={runCancel.isPending}
                          >
                            Stop
                          </button>
                        ) : null}
                      </div>
                      <TranscriptTail entries={item.run.transcript_tail} />
                    </div>
                  );
                })}
              </div>
            )}
          </SurfaceCard>
        </div>
      )}

      <div className="dashboard-columns">
      <div>
        <div className="task-toolbar task-toolbar--primary">
          <input
            className="text-input"
            value={newTaskTitle}
            onChange={(event) => setNewTaskTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void addTask();
            }}
            placeholder="Add a job..."
          />
          <button className="primary-button" type="button" onClick={() => void addTask()}>
            Add
          </button>
          <input
            className="text-input task-toolbar__search"
            value={taskSearch}
            onChange={(event) => setTaskSearch(event.target.value)}
            placeholder="Search jobs, assignees, blocks..."
          />
        </div>
        <div className="filter-row-ui">
          <button
            className={cn("filter-chip-ui", activeFilter === "all" && "is-active")}
            type="button"
            onClick={() => setActiveFilter("all")}
          >
            All ({document?.tasks.length ?? 0})
          </button>
          {Object.entries(document?.blocks ?? {}).map(([blockId, block]) => {
            const count = (document?.tasks ?? []).filter((task) => task.block === blockId).length;
            return (
              <button
                key={blockId}
                className={cn("filter-chip-ui", activeFilter === blockId && "is-active")}
                type="button"
                onClick={() => setActiveFilter(blockId)}
              >
                {block.label} ({count})
              </button>
            );
          })}
        </div>

        <div id="task-list" className="task-list">
          {visibleTasks.length === 0 ? (
            <EmptyState title="No jobs match the current view" detail="Adjust the filter or wait for jobs.json." />
          ) : (
            visibleTasks.map((task) => (
              <div key={task.id} className="task-card-ui">
                <div className="task-card-ui__title-row">
                  <label className="checkbox-wrap">
                    <input
                      checked={task.status === "done"}
                      disabled={task.status === "blocked"}
                      type="checkbox"
                      onChange={() => void toggleTask(task.id)}
                    />
                    <span />
                  </label>
                  <div className="task-card-ui__title">{task.title}</div>
                </div>
                {task.description ? <p className="task-card-ui__desc">{task.description}</p> : null}
                <div className="task-card-ui__meta">
                  <span className={`task-status-chip is-${task.status}`}>{task.status}</span>
                  <span className="task-meta-mono job-address">{task.id.replace("job.", "")}</span>
                  <span className="task-meta-mono">{task.effort ?? "unknown"}</span>
                  <span className="task-meta-mono">{document?.blocks[task.block]?.label ?? task.block}</span>
                </div>
                <select
                  className="select-input task-card-ui__assign"
                  value={task.assignee ?? "unassigned"}
                  onChange={(event) => void assignTask(task.id, event.target.value)}
                >
                  <option value="unassigned">Unassigned</option>
                  {AGENTS.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.label}
                    </option>
                  ))}
                </select>
                <button className="secondary-button task-card-ui__cycle" type="button" onClick={() => void cycleTask(task.id)}>
                  Cycle
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <SurfaceCard title="Dependencies" subtitle="Blocked work and unresolved chains" className="surface-card--compact dashboard-sidebar">
        <div className="dependency-list">
          {(document?.tasks ?? []).filter((task) => task.blocked_by.length > 0).length === 0 ? (
            <EmptyState compact title="No active dependencies" />
          ) : (
            (document?.tasks ?? [])
              .filter((task) => task.blocked_by.length > 0)
              .map((task) => (
                <div key={task.id} className="dependency-card">
                  <strong>{task.title}</strong>
                  <span>Blocked by {task.blocked_by.join(", ")}</span>
                </div>
              ))
          )}
        </div>
      </SurfaceCard>
      </div>

      <SurfaceCard title="Activity Log" subtitle="Recent job mutations" className="surface-card--compact">
        <div className="activity-log-ui">
          {(document?.log ?? []).length === 0 ? (
            <EmptyState compact title="No recent job mutations" detail="Job activity will accumulate here as operators work." />
          ) : (
            (document?.log ?? []).slice().reverse().slice(0, 30).map((entry) => (
              <div key={`${entry.timestamp}-${entry.actor}-${entry.action}`} className="activity-log-ui__entry">
                <span>{new Date(entry.timestamp).toLocaleTimeString()}</span>
                <span>{entry.actor}</span>
                <span>
                  {entry.action} {entry.task_id ? <em>{entry.task_id}</em> : null} {entry.detail ?? ""}
                </span>
              </div>
            ))
          )}
        </div>
      </SurfaceCard>
    </AppShell>
  );
}
