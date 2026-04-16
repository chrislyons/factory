import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import {
  useCronJobs,
  useHermesSessions,
  useRLRuns,
  useSessionDetail
} from "../hooks/usePortalQueries";
import { relativeTimestamp, timeAgo } from "../lib/utils";

// ── Helpers ─────────────────────────────────────────────────────────

function sourceBadge(source: string): string {
  switch (source) {
    case "cli": return "loop-source--cli";
    case "matrix": return "loop-source--matrix";
    case "acp": return "loop-source--acp";
    default: return "loop-source--default";
  }
}

function cronStateBadge(state: string): string {
  switch (state) {
    case "scheduled": return "loop-cron-state--scheduled";
    case "paused": return "loop-cron-state--paused";
    case "completed": return "loop-cron-state--completed";
    default: return "loop-cron-state--default";
  }
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function truncateModel(model: string | null): string {
  if (!model) return "—";
  return model.length > 28 ? model.slice(0, 25) + "…" : model;
}

// ── Sessions Panel ──────────────────────────────────────────────────

function SessionsPanel({ sessions }: { sessions: ReturnType<typeof useHermesSessions> }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useSessionDetail(selectedId);

  const data = sessions.data;
  const allSessions = useMemo(() => {
    if (!data) return [];
    return [...data.active, ...data.completed];
  }, [data]);

  return (
    <SurfaceCard
      title="Hermes Sessions"
      subtitle={`${data?.total ?? 0} total · ${data?.active.length ?? 0} active`}
      className="surface-card--compact"
    >
      {sessions.isLoading ? (
        <div className="loop-loading">Loading sessions…</div>
      ) : allSessions.length === 0 ? (
        <EmptyState compact title="No sessions found" detail="Hermes state.db has no session records." />
      ) : (
        <div className="loop-sessions-layout">
          <div className="loop-session-list">
            {allSessions.map((s) => {
              const isSelected = selectedId === s.id;
              return (
                <button
                  key={s.id}
                  className={isSelected ? "loop-session-row is-selected" : "loop-session-row"}
                  type="button"
                  onClick={() => setSelectedId(isSelected ? null : s.id)}
                >
                  <div className="loop-session-row__head">
                    <span className={`loop-source-badge ${sourceBadge(s.source)}`}>{s.source}</span>
                    <span className="loop-session-row__model">{truncateModel(s.model)}</span>
                    {!s.ended_at && <span className="loop-live-dot" title="Active" />}
                  </div>
                  <div className="loop-session-row__title">{s.title || s.id.slice(0, 16)}</div>
                  <div className="loop-session-row__meta">
                    <span>{s.message_count} msgs</span>
                    <span>{s.tool_call_count} tools</span>
                    <span>{relativeTimestamp(s.started_at)}</span>
                  </div>
                </button>
              );
            })}
          </div>

          {selectedId && detail.data && !("error" in detail.data) ? (
            <div className="loop-session-detail">
              <h4>{detail.data.title || selectedId}</h4>
              <div className="loop-detail-stats">
                <span>Messages: {detail.data.message_count}</span>
                <span>Tool calls: {detail.data.tool_call_count}</span>
                <span>In: {formatTokens(detail.data.input_tokens)}</span>
                <span>Out: {formatTokens(detail.data.output_tokens)}</span>
                {detail.data.estimated_cost_usd != null && (
                  <span>Cost: ${detail.data.estimated_cost_usd.toFixed(4)}</span>
                )}
              </div>
              {detail.data.recent_messages.length > 0 && (
                <div className="loop-tool-feed">
                  <h5>Recent Tool Calls</h5>
                  {detail.data.recent_messages.slice(0, 15).map((msg) => (
                    <div key={msg.id} className="loop-tool-entry">
                      <span className="loop-tool-entry__time">{relativeTimestamp(msg.timestamp)}</span>
                      <span className="loop-tool-entry__tools">
                        {msg.tool_names.length > 0 ? msg.tool_names.join(", ") : msg.role}
                      </span>
                      {msg.preview && <span className="loop-tool-entry__preview">{msg.preview}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : selectedId && detail.data && "error" in detail.data ? (
            <div className="loop-session-detail">
              <EmptyState compact title="Session not found" detail={(detail.data as { error: string }).error} />
            </div>
          ) : null}
        </div>
      )}

      {data && Object.keys(data.tool_distribution).length > 0 && (
        <div className="loop-tool-dist">
          <h5>Tool Distribution</h5>
          <div className="loop-tool-bars">
            {Object.entries(data.tool_distribution).map(([name, count]) => {
              const max = Math.max(...Object.values(data.tool_distribution));
              const pct = max > 0 ? (count / max) * 100 : 0;
              return (
                <div key={name} className="loop-tool-bar">
                  <span className="loop-tool-bar__name">{name}</span>
                  <div className="loop-tool-bar__track">
                    <div className="loop-tool-bar__fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="loop-tool-bar__count">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </SurfaceCard>
  );
}

// ── Cron Panel ──────────────────────────────────────────────────────

function CronPanel({ cron }: { cron: ReturnType<typeof useCronJobs> }) {
  const data = cron.data;

  return (
    <SurfaceCard
      title="Cron Jobs"
      subtitle={`${data?.count ?? 0} scheduled`}
      className="surface-card--compact"
    >
      {cron.isLoading ? (
        <div className="loop-loading">Loading cron jobs…</div>
      ) : !data || data.jobs.length === 0 ? (
        <EmptyState
          compact
          title="No cron jobs"
          detail="Create scheduled tasks via /cron in any Hermes chat session."
        />
      ) : (
        <div className="loop-cron-list">
          {data.jobs.map((job) => (
            <div key={job.id} className="loop-cron-row">
              <div className="loop-cron-row__head">
                <span className="loop-cron-row__name">{job.name || job.id}</span>
                <span className={`loop-cron-state ${cronStateBadge(job.state)}`}>{job.state}</span>
              </div>
              <div className="loop-cron-row__schedule">{job.schedule_display}</div>
              {job.prompt && <div className="loop-cron-row__prompt">{job.prompt}</div>}
              <div className="loop-cron-row__meta">
                {job.skills && job.skills.length > 0 && (
                  <span>Skills: {job.skills.join(", ")}</span>
                )}
                {job.next_run && <span>Next: {relativeTimestamp(job.next_run)}</span>}
                {job.last_run && <span>Last: {relativeTimestamp(job.last_run)}</span>}
                {job.run_count != null && <span>Runs: {job.run_count}</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </SurfaceCard>
  );
}

// ── RL/GRPO Panel ───────────────────────────────────────────────────

function RLPanel({ rl }: { rl: ReturnType<typeof useRLRuns> }) {
  const data = rl.data;

  return (
    <SurfaceCard
      title="RL Training (GRPO)"
      subtitle={data?.configured ? "Configured" : "Not configured"}
      className="surface-card--compact"
    >
      {rl.isLoading ? (
        <div className="loop-loading">Checking RL status…</div>
      ) : !data ? (
        <EmptyState compact title="Unable to check RL status" detail="API returned no data." />
      ) : (
        <div className="loop-rl-panel">
          <div className="loop-rl-checklist">
            <div className={data.has_tinker_key ? "loop-rl-check is-ok" : "loop-rl-check is-missing"}>
              <span className="loop-rl-check__icon">{data.has_tinker_key ? "✓" : "✗"}</span>
              <span>TINKER_API_KEY</span>
            </div>
            <div className={data.has_wandb_key ? "loop-rl-check is-ok" : "loop-rl-check is-missing"}>
              <span className="loop-rl-check__icon">{data.has_wandb_key ? "✓" : "✗"}</span>
              <span>WANDB_API_KEY</span>
            </div>
            <div className={data.tinker_atropos_exists ? "loop-rl-check is-ok" : "loop-rl-check is-missing"}>
              <span className="loop-rl-check__icon">{data.tinker_atropos_exists ? "✓" : "✗"}</span>
              <span>tinker-atropos submodule</span>
            </div>
          </div>

          {data.configured ? (
            data.runs.length === 0 ? (
              <EmptyState compact title="No training runs" detail="Start a GRPO run from any Hermes session with rl_start_training()." />
            ) : (
              <div className="loop-rl-runs">
                <h5>Runs ({data.run_count})</h5>
                {data.runs.map((run) => (
                  <div key={run.id} className="loop-rl-run-row">
                    <span className="loop-rl-run-row__id">{run.id}</span>
                    <span className="loop-rl-run-row__path">{run.path}</span>
                  </div>
                ))}
              </div>
            )
          ) : (
            <div className="loop-rl-setup-hint">
              Set TINKER_API_KEY and WANDB_API_KEY in ~/.hermes/.env to enable GRPO training.
            </div>
          )}
        </div>
      )}
    </SurfaceCard>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export function LoopsPage() {
  const sessions = useHermesSessions();
  const cron = useCronJobs();
  const rl = useRLRuns();

  const updatedAt = Math.max(
    sessions.dataUpdatedAt || 0,
    cron.dataUpdatedAt || 0,
    rl.dataUpdatedAt || 0
  );
  const hasError = Boolean(sessions.error || cron.error || rl.error);

  return (
    <AppShell
      title="Loops"
      description="Hermes sessions, scheduled tasks, and RL training runs."
      pageKey="/pages/loops.html"
      statusSlot={<SyncClock updatedAt={updatedAt} stale={hasError} />}
    >
      <SessionsPanel sessions={sessions} />
      <CronPanel cron={cron} />
      <RLPanel rl={rl} />
    </AppShell>
  );
}
