import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  useQueries,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { SyncClock } from "../components/primitives/SyncClock";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { AGENTS } from "../lib/constants";
import { cn } from "../lib/utils";
import {
  fetchAgentConfig,
  patchAgentConfig,
  fetchAgentHealth,
  restartAgentGateway,
  toggleMcpServer,
} from "../lib/api";
import type {
  AgentConfigSummary,
  AgentHealth,
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

const SKIN_OPTIONS = [
  { value: "", label: "Default" },
  { value: "mono", label: "Mono" },
  { value: "slate", label: "Slate" },
  { value: "dracula", label: "Dracula" },
  { value: "solarized", label: "Solarized" },
  { value: "nord", label: "Nord" },
  { value: "gruvbox", label: "Gruvbox" },
  { value: "tokyo-night", label: "Tokyo Night" },
];

const ALL_TOOLSETS = [
  "terminal", "file", "code_execution", "web", "delegation",
  "memory", "session_search", "todo", "skills", "clarify",
  "image_gen", "cronjob", "vision", "tts", "browser", "homeassistant",
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
  auxModel,
  health,
  selected,
  onClick,
}: {
  agent: (typeof CONFIG_AGENTS)[number];
  summary?: AgentConfigSummary;
  auxModel?: string;
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
      {auxModel && (
        <div className="config-agent-card__aux">
          <span className="config-agent-card__aux-label">aux</span>
          <span className="config-agent-card__aux-model">{truncateModel(auxModel, 30)}</span>
        </div>
      )}
    </button>
  );
}

// ── Preferences Panel (full width) ──────────────────────────────────

function Preferences({
  agentId,
  config,
  disabled,
}: {
  agentId: string;
  config: Record<string, unknown>;
  disabled: boolean;
}) {
  const queryClient = useQueryClient();
  const display = (config.display ?? {}) as Record<string, unknown>;
  const memory = (config.memory ?? {}) as Record<string, unknown>;
  const terminal = (config.terminal ?? {}) as Record<string, unknown>;

  const patchMutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => patchAgentConfig(agentId, patch),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  function patch(field: string, value: unknown) {
    patchMutation.mutate({ [field]: value });
  }

  const skinValue = (display.skin as string) ?? "";
  const compressionThreshold = config.compression_threshold as number | undefined;
  const [localThreshold, setLocalThreshold] = useState(String(compressionThreshold ?? 0.5));
  const [localCwd, setLocalCwd] = useState(shortenPath((terminal.cwd as string) ?? ""));
  const [localTimeout, setLocalTimeout] = useState(String((terminal.timeout as number) ?? 180));

  const thresholdRef = useRef<HTMLInputElement>(null);
  const cwdRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (document.activeElement !== thresholdRef.current) {
      setLocalThreshold(String(compressionThreshold ?? 0.5));
    }
  }, [compressionThreshold]);

  useEffect(() => {
    if (document.activeElement !== cwdRef.current) {
      setLocalCwd(shortenPath((terminal.cwd as string) ?? ""));
    }
  }, [terminal.cwd]);

  useEffect(() => {
    if (document.activeElement !== timeoutRef.current) {
      setLocalTimeout(String((terminal.timeout as number) ?? 180));
    }
  }, [terminal.timeout]);

  const displayFields = [
    { key: "compact", label: "Compact mode", desc: "Reduce output verbosity" },
    { key: "streaming", label: "Streaming output", desc: "Stream tokens as generated" },
    { key: "show_cost", label: "Show cost", desc: "Display per-request cost" },
    { key: "show_reasoning", label: "Show reasoning", desc: "Expose chain-of-thought" },
  ] as const;

  return (
    <SurfaceCard title="Preferences" subtitle="Display, memory, terminal, and compression" className="surface-card--compact">
      <div className="config-prefs-layout">
        {/* Column 1: Display */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Display</span>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Skin</span>
              <span className="config-pref-row__desc">CLI visual theme</span>
            </div>
            <select
              className="config-field__select select-input config-field__select--inline"
              value={skinValue}
              disabled={disabled || patchMutation.isPending}
              onChange={(e) => {
                const val = e.target.value;
                if (val) {
                  patch("display.skin", val);
                } else {
                  patchMutation.mutate({ "display.skin": null });
                }
              }}
            >
              {SKIN_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          {displayFields.map((f) => {
            const current = Boolean(display[f.key]);
            return (
              <div key={f.key} className="config-pref-row">
                <div className="config-pref-row__label">
                  <span className="config-pref-row__name">{f.label}</span>
                </div>
                <Toggle
                  checked={current}
                  disabled={disabled || patchMutation.isPending}
                  onChange={(v) => patch(`display.${f.key}`, v)}
                />
              </div>
            );
          })}
        </div>

        {/* Column 2: Memory */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Memory</span>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Memory enabled</span>
              <span className="config-pref-row__desc">Persistent memory across sessions</span>
            </div>
            <Toggle
              checked={Boolean(memory.memory_enabled)}
              disabled={disabled || patchMutation.isPending}
              onChange={(v) => patch("memory.memory_enabled", v)}
            />
          </div>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">User profile</span>
              <span className="config-pref-row__desc">Learn user preferences</span>
            </div>
            <Toggle
              checked={Boolean(memory.user_profile_enabled)}
              disabled={disabled || patchMutation.isPending}
              onChange={(v) => patch("memory.user_profile_enabled", v)}
            />
          </div>
        </div>

        {/* Column 3: Terminal */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Terminal</span>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Working dir</span>
              <span className="config-pref-row__desc">Default shell directory</span>
            </div>
            <input
              ref={cwdRef}
              className="config-field__input config-field__input--compact"
              type="text"
              value={localCwd}
              disabled={disabled}
              onChange={(e) => setLocalCwd(e.target.value)}
              onBlur={() => {
                const home = (terminal.cwd as string)?.match(/^\/Users\/[^/]+\//)?.[0] ?? "";
                const expanded = localCwd.startsWith("~/") ? home + localCwd.slice(2) : localCwd;
                if (expanded !== terminal.cwd) patch("terminal.cwd", expanded);
              }}
            />
          </div>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Timeout</span>
              <span className="config-pref-row__desc">Per-command timeout (s)</span>
            </div>
            <input
              ref={timeoutRef}
              className="config-field__input config-field__input--compact"
              type="number"
              value={localTimeout}
              min={1}
              max={600}
              disabled={disabled}
              onChange={(e) => setLocalTimeout(e.target.value)}
              onBlur={() => {
                const v = parseInt(localTimeout, 10);
                if (!Number.isNaN(v) && v !== terminal.timeout) patch("terminal.timeout", v);
              }}
            />
          </div>
        </div>

        {/* Column 4: Compression */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Compression</span>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Threshold</span>
              <span className="config-pref-row__desc">Context fill ratio trigger</span>
            </div>
            <div className="config-threshold-control">
              <input
                ref={thresholdRef}
                className="config-field__input config-field__input--compact"
                type="number"
                value={localThreshold}
                min={0.1}
                max={1.0}
                step={0.05}
                disabled={disabled}
                onChange={(e) => setLocalThreshold(e.target.value)}
                onBlur={() => {
                  const v = parseFloat(localThreshold);
                  if (!Number.isNaN(v) && v !== compressionThreshold) {
                    patch("auxiliary.compression.threshold", v);
                  }
                }}
              />
              <span className="config-threshold-control__label">{Math.round(parseFloat(localThreshold || "0.5") * 100)}%</span>
            </div>
          </div>
        </div>
      </div>
    </SurfaceCard>
  );
}

// ── Merged Model & Agent Panel (full width) ─────────────────────────

function ModelAndAgent({
  agentId,
  agentLabel,
  config,
  health,
}: {
  agentId: string;
  agentLabel: string;
  config: Record<string, unknown>;
  health?: AgentHealth;
}) {
  const queryClient = useQueryClient();
  const [restartConfirm, setRestartConfirm] = useState(false);

  // ── Mutations ──
  const healthMutation = useMutation({
    mutationFn: () => fetchAgentHealth(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["config-detail", agentId] }),
  });

  const patchMutation = useMutation({
    mutationFn: (patch: Record<string, unknown>) => patchAgentConfig(agentId, patch),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["config"] }),
  });

  const restartMutation = useMutation({
    mutationFn: () => restartAgentGateway(agentId),
    onSuccess: () => {
      setRestartConfirm(false);
      queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  const mcpToggleMutation = useMutation({
    mutationFn: ({ server, enabled }: { server: string; enabled: boolean }) =>
      toggleMcpServer(agentId, server, enabled),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["config"] }),
  });

  function patch(field: string, value: unknown) {
    patchMutation.mutate({ [field]: value });
  }

  // ── Model / Provider data ──
  const modelObj = (config.model ?? {}) as Record<string, unknown>;
  const currentModel = (modelObj.default as string) ?? (config.model as string) ?? "";
  const currentProvider = (modelObj.provider as string) ?? (config.provider as string) ?? "";
  const baseUrl = (modelObj.base_url as string) ?? (config.base_url as string) ?? health?.url ?? "—";
  const contextLength = (modelObj.context_length as number | undefined) ?? undefined;
  const liveHealth = healthMutation.data ?? health;

  const customProviders = (config.custom_providers ?? []) as Array<{
    name?: string;
    base_url?: string;
    models?: Record<string, unknown>;
  }>;

  const modelOptions: string[] = [];
  for (const cp of customProviders) {
    const models = cp.models ?? {};
    for (const modelName of Object.keys(models)) {
      if (!modelOptions.includes(modelName)) modelOptions.push(modelName);
    }
  }
  if (currentModel && !modelOptions.includes(currentModel)) modelOptions.unshift(currentModel);

  // ── Agent params data ──
  const agentObj = (config.agent ?? {}) as Record<string, unknown>;
  const maxTokens = config.max_tokens as number | undefined;
  const maxTurns = (agentObj.max_turns as number | undefined) ?? (config.max_turns as number | undefined);
  const toolEnforcement = ((agentObj.tool_use_enforcement as string) ?? (config.tool_use_enforcement as string)) ?? "none";
  const approvalMode = ((config.approvals as Record<string, unknown>)?.mode as string) ?? "off";
  const toolsets = (config.toolsets ?? []) as string[];

  const [localMaxTokens, setLocalMaxTokens] = useState(String(maxTokens ?? 4096));
  const [localMaxTurns, setLocalMaxTurns] = useState(String(maxTurns ?? 10));
  const tokensRef = useRef<HTMLInputElement>(null);
  const turnsRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (document.activeElement !== tokensRef.current) setLocalMaxTokens(String(maxTokens ?? 4096));
  }, [maxTokens]);
  useEffect(() => {
    if (document.activeElement !== turnsRef.current) setLocalMaxTurns(String(maxTurns ?? 10));
  }, [maxTurns]);

  // ── MCP data ──
  const mcpServers = (config.mcp_servers ?? {}) as Record<string, Record<string, unknown>>;
  const mcpEntries = Object.entries(mcpServers);

  function toggleToolset(tool: string, enabled: boolean) {
    const next = enabled ? [...toolsets, tool] : toolsets.filter((t) => t !== tool);
    patch("toolsets", next);
  }

  return (
    <SurfaceCard
      title={`Model & Agent — ${agentLabel}`}
      subtitle="Inference, runtime, capabilities"
      className="surface-card--compact"
    >
      <div className="config-merged-layout">
        {/* Left column: Model & Provider info */}
        <div className="config-merged-col">
          <span className="config-merged-col__title">Model & Provider</span>
          <div className="config-info-grid">
            <div className="config-info-row">
              <span className="config-info-row__key">Model</span>
              {modelOptions.length > 1 ? (
                <select
                  className="config-field__select select-input config-field__select--inline"
                  value={currentModel}
                  disabled={patchMutation.isPending}
                  onChange={(e) => {
                    if (e.target.value !== currentModel) patchMutation.mutate({ "model.default": e.target.value });
                  }}
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
                onChange={(e) => {
                  if (e.target.value !== currentProvider) patchMutation.mutate({ "model.provider": e.target.value });
                }}
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

            {/* Aux slots */}
            {(() => {
              const aux = (config.auxiliary ?? {}) as Record<string, Record<string, unknown>>;
              const entries = Object.entries(aux);
              if (entries.length === 0) return null;
              const modelSlots = new Map<string, string[]>();
              for (const [slotName, slot] of entries) {
                const m = ((slot as Record<string, unknown>)?.model as string) ?? "—";
                if (!modelSlots.has(m)) modelSlots.set(m, []);
                modelSlots.get(m)!.push(slotName);
              }
              return (
                <div className="config-aux-section">
                  <span className="config-aux-section__title">Auxiliary Slots</span>
                  {[...modelSlots.entries()].map(([model, slots]) => (
                    <div key={model} className="config-aux-group">
                      <code className="config-aux-group__model">{shortenPath(model)}</code>
                      <div className="config-aux-group__slots">
                        {slots.map((s) => <span key={s} className="config-aux-chip">{s}</span>)}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* Actions */}
            <div className="config-actions config-actions--inline">
              <button
                className="config-action-btn"
                disabled={healthMutation.isPending}
                onClick={() => healthMutation.mutate()}
              >
                {healthMutation.isPending ? "Checking…" : "Health Check"}
              </button>
              {!restartConfirm ? (
                <button className="config-action-btn config-action-btn--accent" onClick={() => setRestartConfirm(true)}>
                  Apply Now (Restart)
                </button>
              ) : (
                <div className="config-restart-confirm">
                  <span className="config-restart-confirm__text">Restart?</span>
                  <button
                    className="config-action-btn config-action-btn--danger"
                    disabled={restartMutation.isPending}
                    onClick={() => restartMutation.mutate()}
                  >
                    {restartMutation.isPending ? "Restarting…" : "Confirm"}
                  </button>
                  <button className="config-action-btn" onClick={() => setRestartConfirm(false)}>Cancel</button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right column: Agent params + Toolsets + MCP */}
        <div className="config-merged-col">
          <span className="config-merged-col__title">Runtime</span>
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
                disabled={false}
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
                disabled={false}
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
                disabled={false}
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
                disabled={false}
                onChange={(e) => patch("approvals.mode", e.target.value)}
              >
                <option value="off">Off</option>
                <option value="per_tool">Per Tool</option>
                <option value="always">Always</option>
              </select>
            </label>
          </div>

          {/* Toolsets */}
          <div className="config-capabilities">
            <span className="config-capabilities__title">Toolsets</span>
            <div className="config-toolsets__grid">
              {ALL_TOOLSETS.map((tool) => {
                const enabled = toolsets.includes(tool);
                return (
                  <label key={tool} className={cn("config-toolset-chip", enabled && "config-toolset-chip--active")}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={patchMutation.isPending}
                      onChange={(e) => toggleToolset(tool, e.target.checked)}
                    />
                    <span>{tool.replace(/_/g, " ")}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* MCP Servers (only if agent has any) */}
          {mcpEntries.length > 0 && (
            <div className="config-capabilities">
              <span className="config-capabilities__title">MCP Servers</span>
              <div className="config-mcp-grid">
                {mcpEntries.map(([name, server]) => {
                  const enabled = server.enabled !== false;
                  const url = (server.url as string) ?? "";
                  const command = (server.command as string) ?? "";
                  const displayUrl = url || (command ? `${command} ${(server.args as string[] ?? []).join(" ")}` : "—");
                  return (
                    <div key={name} className="config-mcp-row">
                      <div className="config-mcp-row__header">
                        <span className="config-mcp-row__name">{name}</span>
                        <Toggle
                          checked={enabled}
                          disabled={mcpToggleMutation.isPending}
                          onChange={(v) => mcpToggleMutation.mutate({ server: name, enabled: v })}
                        />
                      </div>
                      <code className="config-mcp-row__url">{shortenPath(displayUrl)}</code>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </SurfaceCard>
  );
}

// ── Main Page ────────────────────────────────────────────────────────

export function ConfigPage() {
  const [selectedId, setSelectedId] = useState<string>(CONFIG_AGENTS[0].id);

  const detailQueries = useQueries({
    queries: CONFIG_AGENTS.map((agent) => ({
      queryKey: ["config-detail", agent.id] as const,
      queryFn: () => fetchAgentConfig(agent.id),
      refetchInterval: 30_000,
      staleTime: 0,
    })),
  });

  const configMap = useMemo(() => {
    const map: Record<string, { config: Record<string, unknown>; health?: AgentHealth }> = {};
    detailQueries.forEach((q, i) => {
      const id = CONFIG_AGENTS[i].id;
      if (q.data) map[id] = { config: q.data.config, health: q.data.health };
    });
    return map;
  }, [detailQueries]);

  const selectedIdx = CONFIG_AGENTS.findIndex((a) => a.id === selectedId);
  const detail = detailQueries[selectedIdx]?.data;
  const config = detail?.config ?? {};
  const health = detail?.health;

  const updatedAt = useMemo(
    () => Math.max(...detailQueries.map((q) => q.dataUpdatedAt || 0), 0),
    [detailQueries]
  );

  const hasError = detailQueries.some((q) => q.isError);
  const showContent = Boolean(detail);

  const selectedAgent = CONFIG_AGENTS.find((a) => a.id === selectedId);

  function cardModel(id: string): string {
    const c = configMap[id]?.config;
    if (!c) return "—";
    const m = (c.model ?? {}) as Record<string, unknown>;
    return (m.default as string) ?? (c.model as string) ?? "—";
  }

  function cardProvider(id: string): string {
    const c = configMap[id]?.config;
    if (!c) return "—";
    const m = (c.model ?? {}) as Record<string, unknown>;
    return (m.provider as string) ?? (c.provider as string) ?? "—";
  }

  function cardAuxModel(id: string): string | undefined {
    const c = configMap[id]?.config;
    if (!c) return undefined;
    const aux = (c.auxiliary ?? {}) as Record<string, Record<string, unknown>>;
    const models = new Set<string>();
    for (const slot of Object.values(aux)) {
      const m = (slot as Record<string, unknown>)?.model as string | undefined;
      if (m) models.add(m);
    }
    return models.size > 0 ? [...models].join(", ") : undefined;
  }

  return (
    <AppShell
      title="Configuration"
      pageKey="/pages/config.html"
      statusSlot={<SyncClock updatedAt={updatedAt} stale={hasError} />}
    >
      {/* Agent selector cards */}
      <div className="config-agents-grid">
        {CONFIG_AGENTS.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            summary={{ id: agent.id, label: agent.label, model: cardModel(agent.id), provider: cardProvider(agent.id) }}
            auxModel={cardAuxModel(agent.id)}
            health={configMap[agent.id]?.health}
            selected={selectedId === agent.id}
            onClick={() => setSelectedId(agent.id)}
          />
        ))}
      </div>

      {detailQueries[selectedIdx]?.isError && (
        <SurfaceCard title="Error" subtitle="Failed to load agent config" className="surface-card--compact">
          <div className="config-error">
            {(detailQueries[selectedIdx]?.error as Error)?.message ?? "Unknown error"}
          </div>
        </SurfaceCard>
      )}

      {showContent && (
        <div className="config-rows">
          {/* Row 1: Preferences (full width) */}
          <Preferences agentId={selectedId} config={config} disabled={false} />

          {/* Row 2: Model & Agent (full width, merged) */}
          <ModelAndAgent
            agentId={selectedId}
            agentLabel={selectedAgent?.label ?? selectedId}
            config={config}
            health={health}
          />
        </div>
      )}
    </AppShell>
  );
}
