import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { LoopDetailPanel } from "../components/loops/LoopDetailPanel";
import { LoopStatusPill } from "../components/loops/LoopStatusPill";
import { EmptyState } from "../components/primitives/EmptyState";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useLoopAbort, useLoopDetail, useLoops, useLoopStart } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import {
  formatMetricValue,
  loopApprovalGateLabel,
  loopTypeLabel,
  relativeTimestamp
} from "../lib/utils";

function readSearchParam(name: string) {
  return new URLSearchParams(window.location.search).get(name);
}

function setSearchParams(params: Record<string, string | null>) {
  const search = new URLSearchParams(window.location.search);
  Object.entries(params).forEach(([key, value]) => {
    if (!value) search.delete(key);
    else search.set(key, value);
  });
  const next = `${window.location.pathname}?${search.toString()}`;
  window.history.replaceState({}, "", next);
}

export function LoopsPage() {
  const loops = useLoops();
  const loopStart = useLoopStart();
  const loopAbort = useLoopAbort();
  const [specPath, setSpecPath] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [agentFilter, setAgentFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [approvalFilter, setApprovalFilter] = useState("all");

  const selectedLoopId = readSearchParam("loop");

  const filteredLoops = useMemo(() => {
    const list = loops.data ?? [];
    return list.filter((loop) => {
      if (statusFilter !== "all" && loop.status !== statusFilter) return false;
      if (agentFilter !== "all" && loop.spec.agent_id !== agentFilter) return false;
      if (typeFilter !== "all" && loop.spec.loop_type !== typeFilter) return false;
      if (approvalFilter !== "all" && loop.spec.approval_gate !== approvalFilter) return false;
      return true;
    });
  }, [agentFilter, approvalFilter, loops.data, statusFilter, typeFilter]);

  const selectedLoopSummary =
    filteredLoops.find((loop) => loop.loop_id === selectedLoopId) ?? filteredLoops[0] ?? null;
  const loopDetail = useLoopDetail(selectedLoopSummary?.loop_id ?? selectedLoopId);
  const selectedLoop = loopDetail.data ?? selectedLoopSummary;

  async function handleLoopStart() {
    const nextSpecPath = specPath.trim();
    if (!nextSpecPath) return;
    await loopStart.mutateAsync(nextSpecPath);
    setSpecPath("");
  }

  return (
    <AppShell
      title="Loop Console"
      description="Autoscope loop oversight, iteration detail, and operator controls."
      pageKey="/pages/loops.html"
      statusSlot={<LastUpdatedChip updatedAt={Math.max(loops.dataUpdatedAt || 0, loopDetail.dataUpdatedAt || 0)} stale={Boolean(loops.error || loopDetail.error)} />}
    >
      <SurfaceCard title="Loop Controls" subtitle="Expected coordinator HTTP contract">
        <div className="task-toolbar">
          <input
            className="text-input"
            placeholder="Loop Spec path, e.g. /Users/chrislyons/dev/autoresearch/loop-specs/researcher.yaml"
            value={specPath}
            onChange={(event) => setSpecPath(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void handleLoopStart();
            }}
          />
          <button
            className="primary-button"
            type="button"
            disabled={loopStart.isPending}
            onClick={() => void handleLoopStart()}
          >
            Start Loop
          </button>
        </div>
        {loopStart.error ? (
          <div className="alert-banner is-danger">Loop start failed. Waiting for coordinator `/loops/start`.</div>
        ) : (
          <div className="placeholder-copy">
            Start and abort actions are wired against the expected loop API and stay safe when the coordinator returns 404.
          </div>
        )}
      </SurfaceCard>

      <div className="filter-row-ui">
        <select className="select-input loop-filter" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="all">All statuses</option>
          <option value="pending">Pending</option>
          <option value="running">Running</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
          <option value="aborted">Aborted</option>
        </select>
        <select className="select-input loop-filter" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
          <option value="all">All agents</option>
          {AGENTS.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.label}
            </option>
          ))}
        </select>
        <select className="select-input loop-filter" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
          <option value="all">All loop types</option>
          {["researcher", "narrative", "infra_improve", "coding", "swarm"].map((value) => (
            <option key={value} value={value}>
              {loopTypeLabel(value)}
            </option>
          ))}
        </select>
        <select className="select-input loop-filter" value={approvalFilter} onChange={(event) => setApprovalFilter(event.target.value)}>
          <option value="all">All approval gates</option>
          {["none", "propose_then_execute", "human_approval_required"].map((value) => (
            <option key={value} value={value}>
              {loopApprovalGateLabel(value)}
            </option>
          ))}
        </select>
      </div>

      {loops.error ? (
        <SurfaceCard title="Loop Inventory" subtitle="Waiting on `/loops`">
          <EmptyState title="Waiting for coordinator…" detail="`GET /loops` is not returning data yet." />
        </SurfaceCard>
      ) : filteredLoops.length === 0 ? (
        <SurfaceCard title="Loop Inventory" subtitle="No active loop records">
          <EmptyState title="No loops yet" detail="`GET /loops` returned an empty array." />
        </SurfaceCard>
      ) : (
        <div className="loop-console-layout">
          <SurfaceCard title="Loop Inventory" subtitle="Full loop records">
            <div className="loop-inventory">
              {filteredLoops.map((loop) => {
                const isSelected = selectedLoop?.loop_id === loop.loop_id;
                return (
                  <button
                    key={loop.loop_id}
                    className={isSelected ? "loop-row is-selected" : "loop-row"}
                    type="button"
                    onClick={() => setSearchParams({ loop: loop.loop_id })}
                  >
                    <div className="loop-row__main">
                      <div className="loop-row__title">
                        <strong>{loop.spec.name}</strong>
                        <LoopStatusPill status={loop.status} />
                      </div>
                      <div className="loop-row__meta">
                        <span>{loop.spec.agent_id}</span>
                        <span>{loopTypeLabel(loop.spec.loop_type)}</span>
                        <span>{loopApprovalGateLabel(loop.spec.approval_gate)}</span>
                      </div>
                    </div>
                    <div className="loop-row__stats">
                      <span>
                        Iter {loop.current_iteration}/{loop.spec.budget.max_iterations}
                      </span>
                      <span>Best {formatMetricValue(loop.best_metric)}</span>
                      <span>{relativeTimestamp(loop.iterations.at(-1)?.ended_at ?? null)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </SurfaceCard>

          <SurfaceCard title="Selected Loop" subtitle="Exact loop_engine.rs shape">
            {!selectedLoop ? (
              <EmptyState title="Select a loop" detail="Choose a loop from the inventory to inspect it." />
            ) : (
              <LoopDetailPanel
                loop={selectedLoop}
                actionSlot={
                  selectedLoop.status === "completed" || selectedLoop.status === "aborted" ? null : (
                    <button
                      className="danger-button"
                      type="button"
                      disabled={loopAbort.isPending}
                      onClick={() => loopAbort.mutate(selectedLoop.loop_id)}
                    >
                      Abort Loop
                    </button>
                  )
                }
              />
            )}
            {loopDetail.error && selectedLoop ? (
              <div className="placeholder-copy">Loop detail is currently falling back to the `/loops` list payload.</div>
            ) : null}
          </SurfaceCard>
        </div>
      )}
    </AppShell>
  );
}
