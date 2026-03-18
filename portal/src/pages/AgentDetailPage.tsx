import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { LoopDetailPanel } from "../components/loops/LoopDetailPanel";
import { LoopStatusPill } from "../components/loops/LoopStatusPill";
import { AgentBadge } from "../components/primitives/AgentBadge";
import { BudgetBar } from "../components/primitives/BudgetBar";
import { EmptyState } from "../components/primitives/EmptyState";
import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { TranscriptTail } from "../components/primitives/TranscriptTail";
import {
  useAgentAction,
  useAgentDetail,
  useLoopDetail,
  useLoops,
  useRunCancel,
  useRunEvents
} from "../hooks/usePortalQueries";
import type { AgentId } from "../lib/types";
import {
  formatCents,
  loopApprovalGateLabel,
  loopTypeLabel,
  relativeTimestamp,
  runEventLabel
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

export function AgentDetailPage({ agentId }: { agentId: AgentId }) {
  const detail = useAgentDetail(agentId);
  const action = useAgentAction(agentId);
  const cancelRun = useRunCancel();
  const loops = useLoops();
  const [tab, setTab] = useState(readSearchParam("tab") ?? "overview");
  const selectedRunId = readSearchParam("run");
  const selectedLoopId = readSearchParam("loop");
  const events = useRunEvents(selectedRunId);
  const agentLoops = useMemo(() => {
    const queryLoops = loops.data ?? [];
    if (queryLoops.length > 0) {
      return queryLoops.filter((loop) => loop.spec.agent_id === agentId);
    }
    return (detail.data?.agent.loops ?? []).filter((loop) => loop.spec.agent_id === agentId);
  }, [agentId, detail.data?.agent.loops, loops.data]);

  const selectedRun = useMemo(() => {
    const runs = detail.data?.runs ?? [];
    return runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  }, [detail.data?.runs, selectedRunId]);
  const selectedLoopSummary = useMemo(() => {
    return agentLoops.find((loop) => loop.loop_id === selectedLoopId) ?? agentLoops[0] ?? null;
  }, [agentLoops, selectedLoopId]);
  const loopDetail = useLoopDetail(selectedLoopSummary?.loop_id ?? selectedLoopId);
  const selectedLoop = loopDetail.data ?? selectedLoopSummary;

  function setTabSelection(nextTab: string, options?: { runId?: string | null; loopId?: string | null }) {
    setTab(nextTab);
    setSearchParams({
      tab: nextTab,
      run: options?.runId ?? null,
      loop: options?.loopId ?? null
    });
  }

  const agent = detail.data?.agent;
  const budget = agent?.budget;

  return (
    <AppShell
      title={agent?.name ?? agentId}
      description="Per-agent identity, runtime state, run history, transcript, and controls."
      pageKey=""
      statusSlot={
        <LastUpdatedChip
          updatedAt={Math.max(detail.dataUpdatedAt || 0, loops.dataUpdatedAt || 0, loopDetail.dataUpdatedAt || 0)}
          stale={Boolean(detail.error || loops.error || loopDetail.error)}
        />
      }
    >
      <SurfaceCard title="Agent Header" subtitle="Identity and control plane">
        {!agent ? (
          <EmptyState title="Waiting for agent detail" detail="The coordinator agent detail endpoint is not available yet." />
        ) : (
          <div className="agent-header-grid">
            <div className="stack-tight">
              <AgentBadge agentId={agentId} fallback={agent.name} status={agent.status === "paused" ? "paused" : "idle"} />
              <div className="agent-detail-meta">
                <span>Model: {agent.model ?? "Unknown"}</span>
                <span>Trust: {agent.trust_level ?? "Unknown"}</span>
                <span>Context: {agent.context_mode ?? "Unknown"}</span>
              </div>
            </div>
            <div className="agent-action-row">
              <button className="secondary-button" type="button" onClick={() => action.mutate("heartbeat")} disabled={action.isPending}>
                Trigger Heartbeat
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => action.mutate(agent.status === "paused" ? "resume" : "pause")}
                disabled={action.isPending}
              >
                {agent.status === "paused" ? "Resume Agent" : "Pause Agent"}
              </button>
              {agent.current_run ? (
                <button className="danger-button" type="button" onClick={() => cancelRun.mutate(agent.current_run!.run_id)} disabled={cancelRun.isPending}>
                  Cancel Active Run
                </button>
              ) : null}
            </div>
          </div>
        )}
      </SurfaceCard>

      <div className="tab-row">
        {["overview", "runs", "loops", "budget", "config"].map((entry) => (
          <button
            key={entry}
            className={tab === entry ? "tab-button is-active" : "tab-button"}
            type="button"
            onClick={() => setTabSelection(entry)}
          >
            {entry}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="dashboard-grid">
          <SurfaceCard title="Current Status" subtitle="Latest live state">
            {agent?.current_run ? (
              <div className="stack">
                <div className="placeholder-copy">{agent.current_run.status} · {relativeTimestamp(agent.current_run.started_at)}</div>
                <TranscriptTail entries={agent.current_run.transcript_tail} />
              </div>
            ) : (
              <EmptyState title="No active run" detail="Run state appears here when the coordinator exposes it." />
            )}
          </SurfaceCard>
          <SurfaceCard title="Budget" subtitle="Shared budget component">
            {budget ? (
              <BudgetBar spent={budget.spent_this_month_usd} limit={budget.monthly_limit_usd} />
            ) : (
              <EmptyState title="No budget data" />
            )}
          </SurfaceCard>
        </div>
      ) : null}

      {tab === "runs" ? (
        <SurfaceCard title="Run History" subtitle="Last 10 runs">
          {(detail.data?.runs ?? []).length === 0 ? (
            <EmptyState title="No runs yet" detail="Coordinator run history will appear here." />
          ) : (
            <div className="agent-runs-layout">
              <div className="run-table">
                {(detail.data?.runs ?? []).slice(0, 10).map((run) => (
                  <button
                    key={run.id}
                    className="run-table__row"
                    type="button"
                    onClick={() => setTabSelection("runs", { runId: run.id })}
                  >
                    <span>{run.status}</span>
                    <span>{run.task ?? "No task"}</span>
                    <span>{run.cost_cents != null ? formatCents(run.cost_cents) : "n/a"}</span>
                  </button>
                ))}
              </div>
              <div className="run-viewer">
                {selectedRun ? (
                  <>
                    <div className="run-viewer__header">
                      <strong>{selectedRun.status}</strong>
                      <span>{relativeTimestamp(selectedRun.started_at)}</span>
                    </div>
                    <div className="run-events">
                      {(events.data ?? []).length === 0 ? (
                        <EmptyState title="No persisted transcript events" detail="Waiting for `/runs/{id}/events`." />
                      ) : (
                        (events.data ?? []).map((event) => (
                          <div key={`${event.seq}-${event.timestamp}`} className="run-events__row">
                            <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                            <span>{runEventLabel(event.event_type)}</span>
                            <span>{event.message}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                ) : (
                  <EmptyState title="Select a run" />
                )}
              </div>
            </div>
          )}
        </SurfaceCard>
      ) : null}

      {tab === "loops" ? (
        <SurfaceCard title="Agent Loops" subtitle="Loops scoped to this agent">
          {loops.error && agentLoops.length === 0 ? (
            <EmptyState title="Waiting for loop data" detail="`GET /loops` is not returning data yet." />
          ) : agentLoops.length === 0 ? (
            <EmptyState title="No loops for this agent" detail="Active loop records will appear here when coordinator exposes them." />
          ) : (
            <div className="agent-runs-layout">
              <div className="run-table">
                {agentLoops.map((loop) => (
                  <button
                    key={loop.loop_id}
                    className={selectedLoop?.loop_id === loop.loop_id ? "run-table__row is-selected" : "run-table__row"}
                    type="button"
                    onClick={() => setTabSelection("loops", { loopId: loop.loop_id })}
                  >
                    <span>
                      <LoopStatusPill status={loop.status} />
                    </span>
                    <span>{loop.spec.name}</span>
                    <span>{loopTypeLabel(loop.spec.loop_type)}</span>
                    <span>{loopApprovalGateLabel(loop.spec.approval_gate)}</span>
                  </button>
                ))}
              </div>
              <div className="run-viewer">
                {selectedLoop ? (
                  <LoopDetailPanel loop={selectedLoop} heading="Agent Loop Detail" />
                ) : (
                  <EmptyState title="Select a loop" />
                )}
                {loopDetail.error && selectedLoop ? (
                  <div className="placeholder-copy">Loop detail is currently falling back to the shared `/loops` list payload.</div>
                ) : null}
              </div>
            </div>
          )}
        </SurfaceCard>
      ) : null}

      {tab === "budget" ? (
        <SurfaceCard title="Budget Detail" subtitle="Per-agent budget summary">
          {budget ? (
            <div className="stack">
              <BudgetBar spent={budget.spent_this_month_usd} limit={budget.monthly_limit_usd} />
              {(budget.incidents ?? []).map((incident) => (
                <div key={incident.id} className="budget-incident">
                  <strong>{incident.threshold_type}</strong>
                  <span>{relativeTimestamp(incident.created_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No budget data" />
          )}
        </SurfaceCard>
      ) : null}

      {tab === "config" ? (
        <SurfaceCard title="Config" subtitle="Coordinator-exposed config surface">
          {agent?.config ? (
            <pre className="config-viewer">{JSON.stringify(agent.config, null, 2)}</pre>
          ) : (
            <EmptyState title="No config payload" detail="Waiting for coordinator config surface." />
          )}
        </SurfaceCard>
      ) : null}
    </AppShell>
  );
}
