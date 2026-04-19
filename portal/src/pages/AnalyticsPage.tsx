import { useMemo } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { AgentBadge } from "../components/primitives/AgentBadge";
import { BudgetBar } from "../components/primitives/BudgetBar";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import {
  useFactoryStats,
  useTasksDocument
} from "../hooks/usePortalQueries";
import { MemoryBar } from "../components/primitives/MemoryBar";
import type { AgentId } from "../lib/types";
import { budgetStatusKind, cn, formatUsd } from "../lib/utils";

// ── Provider badge ──────────────────────────────────────────────────

function providerClass(provider: string): string {
  if (provider.startsWith("mlx-vlm")) return "stats-provider--mlx";
  if (provider.startsWith("flash-moe")) return "stats-provider--flash";
  if (provider === "nous") return "stats-provider--nous";
  if (provider === "openrouter") return "stats-provider--openrouter";
  return "stats-provider--default";
}

function providerLabel(provider: string): string {
  if (provider.startsWith("mlx-vlm")) return `MLX-VLM ${provider.split(":")[1] ? ":" + provider.split(":")[1] : ""}`;
  if (provider.startsWith("flash-moe")) return `Flash-MoE ${provider.split(":")[1] ? ":" + provider.split(":")[1] : ""}`;
  if (provider === "nous") return "Nous Portal";
  if (provider === "openrouter") return "OpenRouter";
  if (provider === "anthropic") return "Anthropic";
  if (provider === "openai") return "OpenAI";
  if (provider === "custom") return "Custom";
  return provider;
}

function shortModel(model: string): string {
  if (!model) return "—";
  // Strip ~/models/ prefix
  const m = model.replace(/^~\/models\//, "");
  // Truncate long names
  return m.length > 40 ? m.slice(0, 37) + "..." : m;
}

// ── Overview stat card ──────────────────────────────────────────────

function OverviewCard({
  label,
  value,
  detail,
  accent
}: {
  label: string;
  value: string | number;
  detail?: string;
  accent?: string;
}) {
  return (
    <div className="stats-overview-card">
      <div className="stats-overview-card__label">{label}</div>
      <div className="stats-overview-card__value" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      {detail ? <div className="stats-overview-card__detail">{detail}</div> : null}
    </div>
  );
}

// ── Agent card ──────────────────────────────────────────────────────

function AgentStatCard({
  agentId,
  label,
  model,
  provider,
  toolsets,
  healthReachable
}: {
  agentId: string;
  label: string;
  model: string;
  provider: string;
  toolsets: string[];
  healthReachable: boolean | null;
}) {
  const agentDef = { id: agentId as AgentId, label, shortLabel: label.slice(0, 2).toUpperCase() };

  return (
    <div className="stats-agent-card">
      <div className="stats-agent-card__header">
        <div className="stats-agent-card__left">
          <span
            className={cn(
              "stats-agent-card__dot",
              healthReachable === true && "stats-agent-card__dot--up",
              healthReachable === false && "stats-agent-card__dot--down",
              healthReachable === null && "stats-agent-card__dot--unknown"
            )}
          />
          <span className="stats-agent-card__name">{label}</span>
        </div>
        <span className={cn("stats-provider-badge", providerClass(provider))}>
          {providerLabel(provider)}
        </span>
      </div>
      <div className="stats-agent-card__model" title={model}>
        {shortModel(model)}
      </div>
      {toolsets.length > 0 ? (
        <div className="stats-agent-card__tools">
          {toolsets.slice(0, 5).map((t) => (
            <span key={t} className="stats-tool-pill">{t}</span>
          ))}
          {toolsets.length > 5 ? (
            <span className="stats-tool-pill stats-tool-pill--muted">+{toolsets.length - 5}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────────────

export function AnalyticsPage() {
  const stats = useFactoryStats();
  const tasks = useTasksDocument();

  const configAgents = stats.config.data?.agents ?? [];
  const memBudget = stats.memory.data;
  const budgetAgents = stats.budget.data?.agents ?? [];
  const taskList = tasks.data?.tasks ?? [];

  // Task counts
  const taskCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of taskList) {
      counts[t.status] = (counts[t.status] || 0) + 1;
    }
    return counts;
  }, [taskList]);

  const taskAssignees = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const t of taskList) {
      const who = t.assignee || "unassigned";
      counts[who] = (counts[who] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [taskList]);

  // Memory summary
  const loadedModels = memBudget?.models.filter((m) => m.loaded) ?? [];

  return (
    <AppShell
      title="Stats"
      description="Factory system overview — inference, memory, tasks, and budget."
      pageKey="/pages/analytics.html"
      statusSlot={
        <SyncClock
          updatedAt={stats.dataUpdatedAt}
          stale={stats.hasError}
        />
      }
    >
      {/* ── Overview ─────────────────────────────────────────────────── */}
      <div className="stats-overview-grid">
        <OverviewCard
          label="Inference"
          value={`${loadedModels.length} / ${memBudget?.models.length ?? "?"}`}
          detail={
            memBudget
              ? `${memBudget.used_by_inference_gb.toFixed(1)} GB allocated`
              : undefined
          }
          accent="var(--accent)"
        />
        <OverviewCard
          label="Tasks"
          value={taskList.length}
          detail={`${taskCounts["pending"] || 0} pending · ${taskCounts["done"] || 0} done`}
          accent="var(--blue)"
        />
        <OverviewCard
          label="Budget"
          value={`${budgetAgents.length} agents`}
          detail={
            budgetAgents.length > 0
              ? `${formatUsd(budgetAgents.reduce((s, a) => s + a.spent_this_month_usd, 0))} spent this month`
              : "No budget data"
          }
          accent="var(--green)"
        />
        <OverviewCard
          label="Memory"
          value={memBudget ? `${memBudget.available_gb.toFixed(1)} GB` : "—"}
          detail={memBudget ? `of ${memBudget.total_gb.toFixed(0)} GB total` : undefined}
          accent={
            memBudget
              ? memBudget.available_gb < 4
                ? "var(--red)"
                : memBudget.available_gb < 8
                  ? "var(--yellow)"
                  : "var(--green)"
              : undefined
          }
        />
      </div>

      {/* ── Agent Roster ────────────────────────────────────────────── */}
      <SurfaceCard title="Agent Roster" subtitle="Inference topology and health">
        {configAgents.length === 0 ? (
          <EmptyState compact title="No agents found" detail="Config API returned empty." />
        ) : (
          <div className="stats-agents-grid">
            {configAgents.map((agent) => (
              <AgentStatCard
                key={agent.id}
                agentId={agent.id}
                label={agent.label}
                model={agent.model || "—"}
                provider={agent.provider || "unknown"}
                toolsets={agent.toolsets || []}
                healthReachable={null}
              />
            ))}
          </div>
        )}
      </SurfaceCard>

      {/* ── Memory & Inference ──────────────────────────────────────── */}
      <SurfaceCard
        title="Memory & Inference"
        subtitle={memBudget ? `${memBudget.total_gb.toFixed(0)} GB total on Whitebox` : "Loading..."}
      >
        {!memBudget ? (
          <EmptyState compact title="Loading memory data" detail="Polling /api/config/memory-budget" />
        ) : (
          <div className="stats-memory-section">
            <MemoryBar budget={memBudget} />

            <div className="stats-models-grid">
              {memBudget.models.map((m) => {
                const agentDef = configAgents.find((a) => a.id === m.agent);
                return (
                  <div
                    key={`${m.agent}-${m.port}`}
                    className={cn("stats-model-row", m.loaded && "stats-model-row--loaded")}
                  >
                    <div className="stats-model-row__left">
                      <span
                        className={cn(
                          "stats-model-row__dot",
                          m.loaded ? "stats-model-row__dot--up" : "stats-model-row__dot--down"
                        )}
                      />
                      <span className="stats-model-row__agent">
                        {agentDef?.label || m.agent}
                      </span>
                      <span className={cn("stats-provider-badge stats-provider-badge--sm", providerClass(m.provider))}>
                        {providerLabel(m.provider)}
                      </span>
                    </div>
                    <div className="stats-model-row__right">
                      <span className="stats-model-row__model" title={m.model}>
                        {shortModel(m.model)}
                      </span>
                      <span className="stats-model-row__mem">
                        {m.loaded ? `${m.est_gb.toFixed(1)} GB` : "—"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </SurfaceCard>

      {/* ── Task Breakdown ─────────────────────────────────────────── */}
      <div className="stats-two-col">
        <SurfaceCard title="Tasks by Status" subtitle={`${taskList.length} total`}>
          {taskList.length === 0 ? (
            <EmptyState compact title="No tasks" detail="jobs.json may be empty or unreachable." />
          ) : (
            <div className="stats-status-grid">
              {[
                { key: "pending", label: "Pending", color: "var(--blue)" },
                { key: "in-progress", label: "In Progress", color: "var(--accent)" },
                { key: "done", label: "Done", color: "var(--green)" },
                { key: "blocked", label: "Blocked", color: "var(--red)" },
                { key: "deferred", label: "Deferred", color: "var(--text-muted)" },
                { key: "deprecated", label: "Deprecated", color: "var(--text-muted)" }
              ].map((s) => {
                const count = taskCounts[s.key] || 0;
                if (count === 0 && (s.key === "deprecated" || s.key === "blocked")) return null;
                return (
                  <div key={s.key} className="stats-status-item">
                    <div className="stats-status-item__bar-track">
                      <div
                        className="stats-status-item__bar-fill"
                        style={{
                          width: `${taskList.length > 0 ? (count / taskList.length) * 100 : 0}%`,
                          background: s.color
                        }}
                      />
                    </div>
                    <div className="stats-status-item__info">
                      <span className="stats-status-item__label">{s.label}</span>
                      <span className="stats-status-item__count">{count}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </SurfaceCard>

        <SurfaceCard title="Tasks by Assignee" subtitle="Current allocation">
          {taskAssignees.length === 0 ? (
            <EmptyState compact title="No assignee data" />
          ) : (
            <div className="stats-assignee-list">
              {taskAssignees.map(([name, count]) => {
                const color =
                  name === "chris"
                    ? "#94a3b8"
                    : name === "boot"
                      ? "#38bdf8"
                      : name === "ig88"
                        ? "#f97316"
                        : name === "kelk"
                          ? "#a78bfa"
                          : "var(--text-dim)";
                return (
                  <div key={name} className="stats-assignee-row">
                    <div className="stats-assignee-row__info">
                      <span className="stats-assignee-row__name" style={{ color }}>
                        {name}
                      </span>
                      <span className="stats-assignee-row__count">{count}</span>
                    </div>
                    <div className="stats-assignee-row__bar-track">
                      <div
                        className="stats-assignee-row__bar-fill"
                        style={{
                          width: `${(count / taskList.length) * 100}%`,
                          background: color
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </SurfaceCard>
      </div>

      {/* ── Budget by Agent ────────────────────────────────────────── */}
      <SurfaceCard title="Budget" subtitle="Monthly spending per agent">
        {budgetAgents.length === 0 ? (
          <EmptyState compact title="No budget data" detail="Budget endpoint returned empty." />
        ) : (
          <div className="budget-grid">
            {budgetAgents.map((agent) => {
              const statusKind = budgetStatusKind(agent.status);
              return (
                <article key={agent.agent_id} className="budget-card-ui">
                  <div className="budget-card-ui__header">
                    <div>
                      <AgentBadge
                        agentId={agent.agent_id}
                        fallback={agent.agent_id}
                        status={statusKind === "paused" ? "paused" : "idle"}
                      />
                      <div className="budget-card-ui__meta">
                        {formatUsd(agent.monthly_limit_usd)} monthly cap
                      </div>
                    </div>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={true}
                      title="Budget override not yet implemented"
                    >
                      Override
                    </button>
                  </div>
                  {statusKind === "paused" ? (
                    <div className="alert-banner is-danger">Budget exhausted — agent paused</div>
                  ) : null}
                  <BudgetBar spent={agent.spent_this_month_usd} limit={agent.monthly_limit_usd} />
                </article>
              );
            })}
          </div>
        )}
      </SurfaceCard>
    </AppShell>
  );
}
