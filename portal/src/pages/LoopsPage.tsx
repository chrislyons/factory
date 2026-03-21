import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { LoopDetailPanel } from "../components/loops/LoopDetailPanel";
import { LoopStatusPill } from "../components/loops/LoopStatusPill";
import { CountdownTimer } from "../components/primitives/CountdownTimer";
import { EmptyState } from "../components/primitives/EmptyState";
import { GateTypePill } from "../components/primitives/GateTypePill";
import { SyncClock } from "../components/primitives/SyncClock";
import { useApprovalDecision, useLoopAbort, useLoopDetail, useLoops, useLoopStart, usePendingApprovals, useResolvedApprovals } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import {
  approvalGateLabel,
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

function payloadSummary(payload: Record<string, unknown> | null | undefined) {
  if (!payload) return "No payload";
  const entries = Object.entries(payload).slice(0, 4);
  return entries.map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`).join(" · ");
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

  const pending = usePendingApprovals();
  const resolved = useResolvedApprovals();
  const decision = useApprovalDecision();
  const [showResolved, setShowResolved] = useState(false);

  const pendingItems = useMemo(
    () => [...(pending.data ?? [])].sort((left, right) => new Date(left.requested_at).getTime() - new Date(right.requested_at).getTime()),
    [pending.data]
  );
  const resolvedItems = useMemo(
    () => [...(resolved.data ?? [])].slice(0, 20),
    [resolved.data]
  );

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
      statusSlot={<SyncClock updatedAt={Math.max(loops.dataUpdatedAt || 0, loopDetail.dataUpdatedAt || 0, pending.dataUpdatedAt || 0, resolved.dataUpdatedAt || 0)} stale={Boolean(loops.error || loopDetail.error || pending.error || resolved.error)} />}
    >
      {/* Approval Queue */}
      <SurfaceCard
        title="Pending Approvals"
        subtitle="Live queue"
        action={pendingItems.length > 0 ? <span className="count-badge is-alert">{pendingItems.length}</span> : null}
      >
        {pendingItems.length === 0 ? (
          <EmptyState compact title="No pending approvals" detail={pending.error ? "Waiting for coordinator…" : "The approval queue is clear."} />
        ) : (
          <div className="approval-list">
            {pendingItems.map((approval) => (
              <article key={approval.id} className="approval-card">
                <div className="approval-card__header">
                  <div>
                    <div className="approval-card__title">
                      <strong>{approval.agent_name}</strong>
                      <GateTypePill gateType={approval.gate_type} />
                    </div>
                    <div className="approval-card__meta">
                      {approval.tool_name ? `${approval.tool_name} · ` : ""}
                      {approvalGateLabel(approval.gate_type)}
                    </div>
                  </div>
                  <CountdownTimer requestedAt={approval.requested_at} timeoutMs={approval.timeout_ms} />
                </div>
                <div className="approval-card__body">{payloadSummary(approval.payload)}</div>
                <div className="approval-card__footer">
                  <span>{relativeTimestamp(approval.requested_at)}</span>
                  <div className="approval-card__actions">
                    <button
                      className="primary-button"
                      type="button"
                      disabled={decision.isPending}
                      onClick={() => decision.mutate({ id: approval.id, decision: "approve" })}
                    >
                      Approve
                    </button>
                    <button
                      className="danger-button"
                      type="button"
                      disabled={decision.isPending}
                      onClick={() => decision.mutate({ id: approval.id, decision: "reject" })}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </SurfaceCard>

      <SurfaceCard
        title="Resolved History"
        subtitle="Recent outcomes"
        className="surface-card--compact"
        action={
          <button className="secondary-button" type="button" onClick={() => setShowResolved((value) => !value)}>
            {showResolved ? "Collapse" : "Expand"}
          </button>
        }
      >
        {showResolved ? (
          resolvedItems.length === 0 ? (
            <EmptyState compact title="No resolved approvals yet" detail="Coordinator history will appear here." />
          ) : (
            <div className="approval-history">
              {resolvedItems.map((approval) => (
                <div key={`${approval.id}-${approval.resolved_at ?? approval.requested_at}`} className="approval-history__row">
                  <div>
                    <strong>{approval.agent_name}</strong>
                    <span>{payloadSummary(approval.payload)}</span>
                  </div>
                  <div>
                    <GateTypePill gateType={approval.gate_type} />
                    <span className="history-decision">{approval.decision}</span>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          <div className="placeholder-copy">Collapsed by default so pending work keeps the visual priority.</div>
        )}
      </SurfaceCard>

      <SurfaceCard title="Loop Controls" subtitle="Start, filter, and inspect active loops" className="surface-card--compact">
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
          <div className="alert-banner is-danger">Loop start failed. Coordinator loop actions are not available yet.</div>
        ) : (
          <div className="placeholder-copy">
            Start and abort controls stay visible even when the coordinator loop routes are unavailable.
          </div>
        )}
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
      </SurfaceCard>

      {loops.error ? (
        <SurfaceCard title="Loop Inventory" subtitle="Waiting on `/loops`" className="surface-card--compact">
          <EmptyState compact title="Waiting for coordinator…" detail="`GET /loops` is not returning data yet." />
        </SurfaceCard>
      ) : filteredLoops.length === 0 ? (
        <SurfaceCard title="Loop Inventory" subtitle="No active loop records" className="surface-card--compact">
          <EmptyState compact title="No loops yet" detail="`GET /loops` returned an empty array." />
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

          <SurfaceCard title="Selected Loop" subtitle="Iteration detail and operator control">
            {!selectedLoop ? (
              <EmptyState compact title="Select a loop" detail="Choose a loop from the inventory to inspect it." />
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
