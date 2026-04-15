import { useState, useEffect, useRef, useCallback } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { SyncClock } from "../components/primitives/SyncClock";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { AGENTS } from "../lib/constants";
import { cn } from "../lib/utils";
import {
  fetchConfigSummaries,
  fetchAgentConfig,
  patchAgentConfig,
  fetchAgentHealth,
  restartAgentGateway,
} from "../lib/api";
import type {
  AgentConfigSummary,
  AgentHealth,
  ConfigDetailResponse,
} from "../lib/api";

const CONFIG_AGENTS = AGENTS.filter((a) =>
  ["boot", "kelk", "ig88"].includes(a.id)
);

const PROVIDER_OPTIONS = [
  { value: "custom", label: "Custom (local)" },
  { value: "nous", label: "Nous" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
];

function providerBadgeClass(provider?: string) {
  if (!provider) return "config-provider-badge--default";
  const key = provider.toLowerCase();
  if (key === "nous") return "config-provider-badge--nous";
  if (key === "openrouter") return "config-provider-badge--openrouter";
  return "config-provider-badge--custom";
}

function providerLabel(provider?: string) {
  if (!provider) return "—";
  return provider;
}

/** Replace absolute home paths with ~/ for display */
function shortenPath(p: string): string {
  return p.replace(/^\/Users\/[^/]+\//, "~/");
}

function truncateModel(model?: string, max = 28) {
  if (!model) return "—";
  const short = shortenPath(model);
  if (short.length <= max) return short;
  return short.slice(0, max - 1) + "…";
}

// ── Toggle Switch ────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className={cn("config-toggle", disabled && "config-toggle--disabled")}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="config-toggle__track">
        <span className="config-toggle__thumb" />
      </span>
    </label>
  );
}

// ── Health Dot ───────────────────────────────────────────────────────

function HealthDot({ health }: { health?: AgentHealth }) {
  if (!health) return <span className="config-health-dot config-health-dot--unknown" />;
  return (
    <span
      className={cn(
        "config-health-dot",
        health.reachable ? "config-health-dot--up" : "config-health-dot--down"
      )}
      title={health.reachable ? "Reachable" : `Down: ${health.error ?? "unreachable"}`}
    />
  );
}

// ── Agent Card ───────────────────────────────────────────────────────

function AgentCard({
  agent,
  summary,
  health,
  selected,
  onClick,
}: {
  agent: (typeof CONFIG_AGENTS)[number];
  summary?: AgentConfigSummary;
  health?: AgentHealth;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className={cn("config-agent-card", selected && "config-agent-card--selected")}
      style={{ ["--agent-accent" as string]: agent.color }}
      onClick={onClick}
    >
      <div className="config-agent-card__header">
        <span className="config-agent-card__dot" style={{ background: agent.color }} />
        <span className="config-agent-card__name">{agent.label}</span>
        <HealthDot health={health} />
      </div>
      <div className="config-agent-card__model">{truncateModel(summary?.model ?? agent.model)}</div>
      <div className="config-agent-card__provider-row">
        <span className={cn("config-provider-badge", providerBadgeClass(summary?.provider))}>
          {providerLabel(summary?.provider)}
        </span>
      </div>
    </button>
  );
}

// ── Display Toggles Section ──────────────────────────────────────────

function DisplayToggles({
  agentId,
  config,
  disabled,
}: {
  agentId: string;
  config: Record<string, unknown>;
  disabled: boolean;
}) {
  const queryClient = useQueryClient();
  const display = (config.display ?? {}) as Record<string, boolean>;

  const patchMutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => patchAgentConfig(agentId, patch),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.refetchQueries({ queryKey: ["config-summaries"] });
    },
  });

  function toggle(key: string, value: boolean) {
    patchMutation.mutate({ [`display.${key}`]: value });
  }

  const fields = [
    { key: "compact", label: "Compact mode", desc: "Reduce output verbosity" },
    { key: "streaming", label: "Streaming output", desc: "Stream tokens as generated" },
    { key: "show_cost", label: "Show cost", desc: "Display per-request cost" },
    { key: "show_reasoning", label: "Show reasoning", desc: "Expose chain-of-thought" },
  ] as const;

  return (
    <SurfaceCard title="Display Toggles" subtitle="Output rendering options" className="surface-card--compact">
      <div className="config-toggles-grid">
        {fields.map((f) => {
          const current = Boolean(display[f.key]);
          const isPending = patchMutation.isPending;
          return (
            <div key={f.key} className="config-toggle-row">
              <div className="config-toggle-row__label">
                <span className="config-toggle-row__name">{f.label}</span>
                <span className="config-toggle-row__desc">{f.desc}</span>
              </div>
              <Toggle
                checked={current}
                disabled={disabled || isPending}
                onChange={(v) => toggle(f.key, v)}
              />
            </div>
          );
        })}
      </div>
    </SurfaceCard>
  );
}

// ── Agent Settings Section ───────────────────────────────────────────

function AgentSettings({
  agentId,
  config,
  disabled,
}: {
  agentId: string;
  config: Record<string, unknown>;
  disabled: boolean;
}) {
  const queryClient = useQueryClient();

  const patchMutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => patchAgentConfig(agentId, patch),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.refetchQueries({ queryKey: ["config-summaries"] });
    },
  });

  function patch(field: string, value: unknown) {
    patchMutation.mutate({ [field]: value });
  }

  const agentObj = (config.agent ?? {}) as Record<string, unknown>;
  const maxTokens = config.max_tokens as number | undefined;
  const maxTurns = (agentObj.max_turns as number | undefined) ?? (config.max_turns as number | undefined);
  const toolEnforcement = ((agentObj.tool_use_enforcement as string) ?? (config.tool_use_enforcement as string)) ?? "none";
  const approvalMode = ((config.approvals as Record<string, unknown>)?.mode as string) ?? "off";

  const [localMaxTokens, setLocalMaxTokens] = useState(String(maxTokens ?? 4096));
  const [localMaxTurns, setLocalMaxTurns] = useState(String(maxTurns ?? 10));

  const tokensRef = useRef<HTMLInputElement>(null);
  const turnsRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (document.activeElement !== tokensRef.current) {
      setLocalMaxTokens(String(maxTokens ?? 4096));
    }
  }, [maxTokens]);

  useEffect(() => {
    if (document.activeElement !== turnsRef.current) {
      setLocalMaxTurns(String(maxTurns ?? 10));
    }
  }, [maxTurns]);

  return (
    <SurfaceCard title="Agent Settings" subtitle="Runtime parameters" className="surface-card--compact">
      <div className="config-settings-grid">
        <label className="config-field">
          <span className="config-field__label">Max Tokens</span>
          <input
            ref={tokensRef}
            className="config-field__input"
            type="number"
            value={localMaxTokens}
            min={256}
            max={128000}
            disabled={disabled}
            onChange={(e) => setLocalMaxTokens(e.target.value)}
            onBlur={() => {
              const v = parseInt(localMaxTokens, 10);
              if (!Number.isNaN(v) && v !== maxTokens) patch("max_tokens", v);
            }}
          />
        </label>

        <label className="config-field">
          <span className="config-field__label">Max Turns</span>
          <input
            ref={turnsRef}
            className="config-field__input"
            type="number"
            value={localMaxTurns}
            min={1}
            max={100}
            disabled={disabled}
            onChange={(e) => setLocalMaxTurns(e.target.value)}
            onBlur={() => {
              const v = parseInt(localMaxTurns, 10);
              if (!Number.isNaN(v) && v !== maxTurns) patch("agent.max_turns", v);
            }}
          />
        </label>

        <label className="config-field">
          <span className="config-field__label">Tool Enforcement</span>
          <select
            className="config-field__select"
            value={toolEnforcement}
            disabled={disabled}
            onChange={(e) => patch("agent.tool_use_enforcement", e.target.value)}
          >
            <option value="none">None</option>
            <option value="warn">Warn</option>
            <option value="enforce">Enforce</option>
          </select>
        </label>

        <label className="config-field">
          <span className="config-field__label">Approval Mode</span>
          <select
            className="config-field__select"
            value={approvalMode}
            disabled={disabled}
            onChange={(e) => patch("approvals.mode", e.target.value)}
          >
            <option value="off">Off</option>
            <option value="per_tool">Per Tool</option>
            <option value="always">Always</option>
          </select>
        </label>
      </div>
    </SurfaceCard>
  );
}

// ── Model / Provider Section ─────────────────────────────────────────

function ModelProvider({
  agentId,
  config,
  health,
  onQueued,
}: {
  agentId: string;
  config: Record<string, unknown>;
  health?: AgentHealth;
  onQueued?: (label: string) => void;
}) {
  const queryClient = useQueryClient();
  const [restartConfirm, setRestartConfirm] = useState(false);

  const healthMutation = useMutation({
    mutationFn: () => fetchAgentHealth(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config-detail", agentId] });
    },
  });

  const patchMutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => patchAgentConfig(agentId, patch),
    onSuccess: (_data, variables) => {
      const keys = Object.keys(variables);
      if (keys.length > 0 && onQueued) {
        onQueued(keys.join(", "));
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.refetchQueries({ queryKey: ["config-summaries"] });
    },
  });

  const restartMutation = useMutation({
    mutationFn: () => restartAgentGateway(agentId),
    onSuccess: () => {
      setRestartConfirm(false);
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.refetchQueries({ queryKey: ["config-summaries"] });
    },
  });

  const modelObj = (config.model ?? {}) as Record<string, unknown>;
  const currentModel = (modelObj.default as string) ?? (config.model as string) ?? "";
  const currentProvider = (modelObj.provider as string) ?? (config.provider as string) ?? "";
  const baseUrl = (modelObj.base_url as string) ?? (config.base_url as string) ?? health?.url ?? "—";
  const contextLength = (modelObj.context_length as number | undefined) ?? undefined;
  const liveHealth = healthMutation.data ?? health;

  // Extract available models from custom_providers in the config
  const customProviders = (config.custom_providers ?? []) as Array<{
    name?: string;
    base_url?: string;
    models?: Record<string, unknown>;
  }>;

  const modelOptions: string[] = [];
  for (const cp of customProviders) {
    const models = cp.models ?? {};
    for (const modelName of Object.keys(models)) {
      if (!modelOptions.includes(modelName)) {
        modelOptions.push(modelName);
      }
    }
  }
  if (currentModel && !modelOptions.includes(currentModel)) {
    modelOptions.unshift(currentModel);
  }

  function handleModelChange(newModel: string) {
    if (newModel === currentModel) return;
    patchMutation.mutate({ "model.default": newModel });
  }

  function handleProviderChange(newProvider: string) {
    if (newProvider === currentProvider) return;
    patchMutation.mutate({ "model.provider": newProvider });
  }

  return (
    <SurfaceCard
      title="Model & Provider"
      subtitle="Inference endpoint — changes are queued"
      className="surface-card--compact"
    >
      <div className="config-info-grid">
        <div className="config-info-row">
          <span className="config-info-row__key">Model</span>
          {modelOptions.length > 1 ? (
            <select
              className="config-field__select select-input config-field__select--inline"
              value={currentModel}
              disabled={patchMutation.isPending}
              onChange={(e) => handleModelChange(e.target.value)}
            >
              {modelOptions.map((m) => (
                <option key={m} value={m}>{shortenPath(m)}</option>
              ))}
            </select>
          ) : (
            <span className="config-info-row__val">{shortenPath(currentModel) || "—"}</span>
          )}
        </div>

        <div className="config-info-row">
          <span className="config-info-row__key">Provider</span>
          <select
            className="config-field__select select-input config-field__select--inline"
            value={currentProvider}
            disabled={patchMutation.isPending}
            onChange={(e) => handleProviderChange(e.target.value)}
          >
            {PROVIDER_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        <div className="config-info-row">
          <span className="config-info-row__key">URL</span>
          <code className="config-info-row__code">{shortenPath(baseUrl)}</code>
        </div>

        {contextLength != null && (
          <div className="config-info-row">
            <span className="config-info-row__key">Context</span>
            <span className="config-info-row__val">{contextLength.toLocaleString()} tokens</span>
          </div>
        )}

        <div className="config-info-row">
          <span className="config-info-row__key">Health</span>
          <span className="config-info-row__val config-info-row__val--inline">
            <HealthDot health={liveHealth} />
            {liveHealth
              ? liveHealth.reachable
                ? `OK (${liveHealth.status ?? "200"})`
                : `Down — ${liveHealth.error ?? "unreachable"}`
              : "Unknown"}
          </span>
        </div>
      </div>

      <div className="config-actions">
        <button
          className="config-action-btn"
          disabled={healthMutation.isPending}
          onClick={() => healthMutation.mutate()}
        >
          {healthMutation.isPending ? "Checking…" : "Health Check"}
        </button>

        {!restartConfirm ? (
          <button
            className="config-action-btn config-action-btn--accent"
            onClick={() => setRestartConfirm(true)}
          >
            Apply Now (Restart)
          </button>
        ) : (
          <div className="config-restart-confirm">
            <span className="config-restart-confirm__text">Restart this gateway?</span>
            <button
              className="config-action-btn config-action-btn--danger"
              disabled={restartMutation.isPending}
              onClick={() => restartMutation.mutate()}
            >
              {restartMutation.isPending ? "Restarting…" : "Confirm"}
            </button>
            <button
              className="config-action-btn"
              onClick={() => setRestartConfirm(false)}
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </SurfaceCard>
  );
}

// ── Command Queue Section ────────────────────────────────────────────

function CommandQueue({
  agentId,
  agentLabel,
  items,
  onClear,
  onClearOne,
  onApplyNow,
}: {
  agentId: string;
  agentLabel: string;
  items: Array<{ id: string; label: string; timestamp: number }>;
  onClear: () => void;
  onClearOne: (id: string) => void;
  onApplyNow: () => void;
}) {
  const [restartPending, setRestartPending] = useState(false);
  const queryClient = useQueryClient();

  const restartMutation = useMutation({
    mutationFn: () => restartAgentGateway(agentId),
    onSuccess: () => {
      setRestartPending(false);
      onClear();
      queryClient.invalidateQueries({ queryKey: ["config"] });
      queryClient.refetchQueries({ queryKey: ["config-summaries"] });
    },
    onError: () => {
      setRestartPending(false);
    },
  });

  function formatAge(ts: number) {
    const secs = Math.floor((Date.now() - ts) / 1000);
    if (secs < 60) return `${secs}s ago`;
    return `${Math.floor(secs / 60)}m ago`;
  }

  return (
    <SurfaceCard
      title="Command Queue"
      subtitle="Pending changes applied on next restart"
      className="surface-card--compact"
    >
      {items.length === 0 ? (
        <div className="config-queue-empty">
          <span className="config-queue-empty__icon">✓</span>
          <span className="config-queue-empty__text">No pending changes</span>
        </div>
      ) : (
        <div className="config-queue-list">
          {items.map((item) => (
            <div key={item.id} className="config-queue-item">
              <div className="config-queue-item__info">
                <span className="config-queue-item__label">{item.label}</span>
                <span className="config-queue-item__time">{formatAge(item.timestamp)}</span>
              </div>
              <button
                className="config-queue-item__remove"
                onClick={() => onClearOne(item.id)}
                title="Remove"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <div className="config-actions">
          <button
            className="config-action-btn"
            onClick={onClear}
          >
            Clear All
          </button>

          {!restartPending ? (
            <button
              className="config-action-btn config-action-btn--accent"
              onClick={() => setRestartPending(true)}
            >
              Apply Now ({items.length})
            </button>
          ) : (
            <div className="config-restart-confirm">
              <span className="config-restart-confirm__text">Restart {agentLabel}?</span>
              <button
                className="config-action-btn config-action-btn--danger"
                disabled={restartMutation.isPending}
                onClick={() => restartMutation.mutate()}
              >
                {restartMutation.isPending ? "Restarting…" : "Confirm"}
              </button>
              <button
                className="config-action-btn"
                onClick={() => setRestartPending(false)}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </SurfaceCard>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

interface QueueItem {
  id: string;
  label: string;
  timestamp: number;
}

export function ConfigPage() {
  const [selectedId, setSelectedId] = useState<string>(CONFIG_AGENTS[0].id);
  const [queue, setQueue] = useState<QueueItem[]>([]);

  const summariesQuery = useQuery({
    queryKey: ["config-summaries"],
    queryFn: fetchConfigSummaries,
    refetchInterval: 30_000,
    staleTime: 0,
    placeholderData: (previousData) => previousData,
  });

  const detailQuery = useQuery({
    queryKey: ["config-detail", selectedId],
    queryFn: () => fetchAgentConfig(selectedId),
    refetchInterval: 30_000,
    staleTime: 0,
    enabled: Boolean(selectedId),
    placeholderData: (previousData) => previousData,
  });

  const summaries = summariesQuery.data?.agents ?? [];
  const detail = detailQuery.data;
  const config = detail?.config ?? {};
  const health = detail?.health;

  const updatedAt = Math.max(
    summariesQuery.dataUpdatedAt || 0,
    detailQuery.dataUpdatedAt || 0
  );

  const hasError = summariesQuery.isError || detailQuery.isError;

  // Queue management
  const addQueued = useCallback((label: string) => {
    setQueue((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, label, timestamp: Date.now() },
    ]);
  }, []);

  const clearQueue = useCallback(() => setQueue([]), []);
  const clearOne = useCallback((id: string) => {
    setQueue((prev) => prev.filter((item) => item.id !== id));
  }, []);

  // Clear queue when switching agents
  useEffect(() => {
    setQueue([]);
  }, [selectedId]);

  const selectedAgent = CONFIG_AGENTS.find((a) => a.id === selectedId);

  // Decide content visibility: show content whenever we have data (current or placeholder)
  const showContent = Boolean(detail);

  return (
    <AppShell
      title="Configuration"
      pageKey="/pages/config.html"
      statusSlot={
        <SyncClock updatedAt={updatedAt} stale={hasError} />
      }
    >
      {/* Agent Cards Grid — always visible, no loading state */}
      <div className="config-agents-grid">
        {CONFIG_AGENTS.map((agent) => {
          const agentDetail = summaries.find((s) => s.id === agent.id);
          // For the selected agent, overlay live detail data so cards stay in sync
          let effectiveSummary = agentDetail;
          if (agent.id === selectedId && detail) {
            const m = (config.model ?? {}) as Record<string, unknown>;
            effectiveSummary = {
              ...agentDetail,
              id: agent.id,
              label: agentDetail?.label ?? agent.label,
              model: (m.default as string) ?? (config.model as string) ?? agentDetail?.model ?? "—",
              provider: (m.provider as string) ?? (config.provider as string) ?? agentDetail?.provider ?? "—",
            };
          }
          return (
            <AgentCard
              key={agent.id}
              agent={agent}
              summary={effectiveSummary}
              health={selectedId === agent.id ? health : undefined}
              selected={selectedId === agent.id}
              onClick={() => setSelectedId(agent.id)}
            />
          );
        })}
      </div>

      {detailQuery.isError && (
        <SurfaceCard title="Error" subtitle="Failed to load agent config" className="surface-card--compact">
          <div className="config-error">
            {(detailQuery.error as Error)?.message ?? "Unknown error"}
          </div>
        </SurfaceCard>
      )}

      {showContent && (
        <div className="config-grid-2x2">
          <AgentSettings
            agentId={selectedId}
            config={config}
            disabled={false}
          />
          <ModelProvider
            agentId={selectedId}
            config={config}
            health={health}
            onQueued={addQueued}
          />
          <DisplayToggles
            agentId={selectedId}
            config={config}
            disabled={false}
          />
          <CommandQueue
            agentId={selectedId}
            agentLabel={selectedAgent?.label ?? selectedId}
            items={queue}
            onClear={clearQueue}
            onClearOne={clearOne}
            onApplyNow={clearQueue}
          />
        </div>
      )}
    </AppShell>
  );
}
