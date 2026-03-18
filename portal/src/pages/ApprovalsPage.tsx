import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { EmptyState } from "../components/primitives/EmptyState";
import { GateTypePill } from "../components/primitives/GateTypePill";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { CountdownTimer } from "../components/primitives/CountdownTimer";
import { useApprovalDecision, usePendingApprovals, useResolvedApprovals } from "../hooks/usePortalQueries";
import { approvalGateLabel, relativeTimestamp } from "../lib/utils";

function payloadSummary(payload: Record<string, unknown> | null | undefined) {
  if (!payload) return "No payload";
  const entries = Object.entries(payload).slice(0, 4);
  return entries.map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`).join(" · ");
}

export function ApprovalsPage() {
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

  return (
    <AppShell
      title="Approvals"
      description="Typed approval queue with optimistic resolution and history."
      pageKey="/pages/approvals.html"
      statusSlot={<LastUpdatedChip updatedAt={Math.max(pending.dataUpdatedAt || 0, resolved.dataUpdatedAt || 0)} stale={Boolean(pending.error || resolved.error)} />}
    >
      <div className="approvals-layout">
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
      </div>
    </AppShell>
  );
}
