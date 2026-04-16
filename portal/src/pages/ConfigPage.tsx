import { useState, useEffect, useRef, useMemo } from "react";
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

const AGENT_PROVIDERS: Record<string, { value: string; label: string }[]> = {
  boot: [
    { value: "mlx-vlm:41961", label: "MLX-VLM :41961" },
  ],
  kelk: [
    { value: "mlx-vlm:41962", label: "MLX-VLM :41962" },
  ],
  ig88: [
    { value: "nous", label: "Nous Portal" },
    { value: "openrouter", label: "OpenRouter" },
    { value: "flash-moe:41966", label: "Flash-MoE :41966" },
  ],
};

/** Aux provider options per agent — :41966 is aux engine for Boot/Kelk */
const AGENT_AUX_PROVIDERS: Record<string, { value: string; label: string }[]> = {
  boot: [
    { value: "flash-moe:41966", label: "Flash-MoE :41966" },
  ],
  kelk: [
    { value: "flash-moe:41966", label: "Flash-MoE :41966" },
  ],
  ig88: [
    { value: "nous", label: "Nous Portal" },
    { value: "openrouter", label: "OpenRouter" },
    { value: "flash-moe:41966", label: "Flash-MoE :41966" },
  ],
};

/** Model options per agent per provider — local ~/models/ paths, cloud model slugs */
const AGENT_PROVIDER_MODELS: Record<string, Record<string, string[]>> = {
  boot: {
    "mlx-vlm:41961": ["~/models/gemma-4-e4b-it-6bit"],
    "flash-moe:41966": ["~/models/gemma-4-26b-a4b-it-6bit"],
  },
  kelk: {
    "mlx-vlm:41962": ["~/models/gemma-4-e4b-it-6bit"],
    "flash-moe:41966": ["~/models/gemma-4-26b-a4b-it-6bit"],
  },
  ig88: {
    "nous": ["xiaomi/mimo-v2-pro", "nous-hermes-2-mixtral-8x7b-dpo", "nous-capybara-34b"],
    "openrouter": ["xiaomi/mimo-v2-omni", "anthropic/claude-sonnet-4", "anthropic/claude-opus-4", "openai/gpt-4o", "openai/o3-mini"],
    "flash-moe:41966": ["~/models/gemma-4-26b-a4b-it-6bit"],
  },
};

/** Shared flat provider list for display labels (providerLabel fallback) */
const ALL_PROVIDER_OPTIONS = [
  { value: "mlx-vlm:41961", label: "MLX-VLM :41961" },
  { value: "mlx-vlm:41962", label: "MLX-VLM :41962" },
  { value: "flash-moe:41966", label: "Flash-MoE :41966" },
  { value: "nous", label: "Nous Portal" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openai", label: "OpenAI" },
];

function agentProviderOptions(agentId: string): { value: string; label: string }[] {
  return AGENT_PROVIDERS[agentId] ?? [];
}

function agentAuxProviderOptions(agentId: string): { value: string; label: string }[] {
  return AGENT_AUX_PROVIDERS[agentId] ?? [];
}

function agentModelOptions(agentId: string, provider: string): string[] {
  if (!provider) return [];
  return AGENT_PROVIDER_MODELS[agentId]?.[provider] ?? [];
}

/** Derive the real inference provider from model path and config context */
function deriveProvider(config: Record<string, unknown>): string {
  const modelObj = (config.model ?? {}) as Record<string, unknown>;
  const stored = (modelObj.provider as string) ?? (config.provider as string) ?? "";
  const modelPath = (modelObj.default as string) ?? (config.model as string) ?? "";
  const baseUrl = (modelObj.base_url as string) ?? "";

  // Local engines: identify by base_url port (distinguishes :41961 from :41962)
  if (baseUrl.includes("127.0.0.1") || baseUrl.includes("localhost")) {
    const port = baseUrl.split(":").pop()?.split("/")[0] ?? "?";
    if (modelPath.includes("26b") || modelPath.includes("flash-moe")) return `flash-moe:${port}`;
    return `mlx-vlm:${port}`;
  }

  // Cloud providers by host
  if (baseUrl.includes("nousresearch")) return "nous";
  if (baseUrl.includes("openrouter")) return "openrouter";
  if (baseUrl.includes("anthropic")) return "anthropic";
  if (baseUrl.includes("openai")) return "openai";

  // Legacy "custom" → show as-is (can't determine port from config alone)
  if (stored === "custom") return stored;

  return stored;
}

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

const AUX_SLOTS = [
  "vision", "web_extract", "compression", "session_search",
  "skills_hub", "approval", "mcp", "flush_memories",
];

const TOKEN_OPTIONS = [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536];
const TURN_OPTIONS = [3, 5, 10, 15, 20, 50, 100];
const TIMEOUT_OPTIONS = [30, 60, 120, 180, 300, 600];
const CWD_OPTIONS = [
  "~/dev/factory", "~/dev/factory/agents/boot",
  "~/dev/factory/agents/kelk", "~/dev/factory/agents/ig88", "/tmp",
];

function providerBadgeClass(provider?: string) {
  if (!provider) return "config-provider-badge--default";
  const key = provider.toLowerCase();
  if (key === "nous") return "config-provider-badge--nous";
  if (key === "openrouter") return "config-provider-badge--openrouter";
  if (key.startsWith("mlx-vlm")) return "config-provider-badge--mlx";
  if (key.startsWith("flash-moe")) return "config-provider-badge--flash";
  return "config-provider-badge--default";
}

function providerLabel(provider?: string) {
  if (!provider) return "—";
  // Legacy "custom" value
  if (provider === "custom") return "local";
  // Find in options for nice label
  const opt = ALL_PROVIDER_OPTIONS.find((p) => p.value === provider);
  if (opt) return opt.label;
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
  selected,
  onClick,
}: {
  agent: (typeof CONFIG_AGENTS)[number];
  summary?: AgentConfigSummary;
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
        <div className="config-agent-card__identity">
          <span className="config-agent-card__name">{agent.label}</span>
          <span className="config-agent-card__model">{truncateModel(summary?.model ?? agent.model)}</span>
        </div>
        <span className={cn("config-provider-badge", providerBadgeClass(summary?.provider))}>
          {providerLabel(summary?.provider)}
        </span>
      </div>
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
  const thresholdRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (document.activeElement !== thresholdRef.current) {
      setLocalThreshold(String(compressionThreshold ?? 0.5));
    }
  }, [compressionThreshold]);

  const cwdValue = shortenPath((terminal.cwd as string) ?? "~/dev/factory");
  const timeoutValue = (terminal.timeout as number) ?? 180;

  const displayFields = [
    { key: "compact", label: "Compact mode", desc: "Reduce output verbosity" },
    { key: "streaming", label: "Streaming output", desc: "Stream tokens as generated" },
    { key: "show_cost", label: "Show cost", desc: "Display per-request cost" },
    { key: "show_reasoning", label: "Show reasoning", desc: "Expose chain-of-thought" },
  ] as const;

  return (
    <SurfaceCard title="Preferences" subtitle="Display, memory, terminal, and compression" className="surface-card--compact">
      <div className="config-prefs-layout">
        {/* Left Column: Display & Memory */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Display & Memory</span>
          
          {/* Display section */}
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Skin</span>
              <span className="config-pref-row__desc">CLI visual theme</span>
            </div>
            <select
              className="config-field__select select-input config-field__select--narrow"
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
          
          {/* Memory section */}
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

        {/* Right Column: Terminal & Compression */}
        <div className="config-prefs-col">
          <span className="config-prefs-col__title">Terminal & Compression</span>
          
          {/* Terminal section */}
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Working dir</span>
              <span className="config-pref-row__desc">Default shell directory</span>
            </div>
            <select
              className="config-field__select select-input config-field__select--narrow"
              value={cwdValue}
              disabled={disabled || patchMutation.isPending}
              onChange={(e) => {
                const val = e.target.value;
                const home = (terminal.cwd as string)?.match(/^\/Users\/[^/]+\//)?.[0] ?? "";
                const expanded = val.startsWith("~/") ? home + val.slice(2) : val;
                patch("terminal.cwd", expanded);
              }}
            >
              {CWD_OPTIONS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
              {cwdValue && !CWD_OPTIONS.includes(cwdValue) && (
                <option value={cwdValue}>{cwdValue}</option>
              )}
            </select>
          </div>
          <div className="config-pref-row">
            <div className="config-pref-row__label">
              <span className="config-pref-row__name">Timeout</span>
              <span className="config-pref-row__desc">Per-command timeout (s)</span>
            </div>
            <select
              className="config-field__select select-input config-field__select--narrow"
              value={String(timeoutValue)}
              disabled={disabled || patchMutation.isPending}
              onChange={(e) => patch("terminal.timeout", parseInt(e.target.value, 10))}
            >
              {TIMEOUT_OPTIONS.map((t) => (
                <option key={t} value={t}>{t}s</option>
              ))}
              {!TIMEOUT_OPTIONS.includes(timeoutValue) && (
                <option value={timeoutValue}>{timeoutValue}s</option>
              )}
            </select>
          </div>
          
          {/* Compression section */}
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
    onError: (err) => console.error(`[config] PATCH ${agentId} failed:`, err),
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
  const storedProvider = (modelObj.provider as string) ?? (config.provider as string) ?? "";
  const currentProvider = deriveProvider(config);
  const liveHealth = healthMutation.data ?? health;

  // ── Agent params data ──
  const agentObj = (config.agent ?? {}) as Record<string, unknown>;
  const maxTokens = config.max_tokens as number | undefined;
  const maxTurns = (agentObj.max_turns as number | undefined) ?? (config.max_turns as number | undefined);
  const contextLength = (config.model as Record<string, unknown>)?.context_length as number | undefined;
  const toolEnforcement = ((agentObj.tool_use_enforcement as string) ?? (config.tool_use_enforcement as string)) ?? "none";
  const approvalMode = ((config.approvals as Record<string, unknown>)?.mode as string) ?? "off";
  const toolsets = (config.toolsets ?? []) as string[];

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

            {/* Action buttons */}
            <div className="config-actions config-actions--inline">
              <button
                className="config-action-btn"
                disabled={healthMutation.isPending}
                onClick={() => healthMutation.mutate()}
              >
                {healthMutation.isPending ? "Refreshing…" : "Refresh Status"}
              </button>
              {!restartConfirm ? (
                <button className="config-action-btn config-action-btn--accent" onClick={() => setRestartConfirm(true)}>
                  Apply (Restart Agent)
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

            {/* Main model — same row layout as aux */}
            <div className="config-aux-section">
              <div className="config-aux-row">
                <div className="config-aux-row__label">
                  <HealthDot health={liveHealth} />
                  <span className="config-aux-row__name">main chat</span>
                </div>
                <select
                  className="config-field__select select-input config-field__select--inline"
                  value={currentProvider}
                  disabled={patchMutation.isPending}
                  onChange={(e) => {
                    if (e.target.value !== currentProvider) patchMutation.mutate({ "model.provider": e.target.value });
                  }}
                >
                  <option value="">—</option>
                  {agentProviderOptions(agentId).map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <select
                  className="config-field__select select-input config-field__select--inline"
                  value={currentModel}
                  disabled={patchMutation.isPending}
                  onChange={(e) => {
                    if (e.target.value !== currentModel) patchMutation.mutate({ "model.default": e.target.value });
                  }}
                >
                  <option value="">—</option>
                  {agentModelOptions(agentId, currentProvider).map((m) => (
                    <option key={m} value={m}>{shortenPath(m)}</option>
                  ))}
                  {currentModel && !agentModelOptions(agentId, currentProvider).includes(currentModel) && (
                    <option value={currentModel}>{shortenPath(currentModel)}</option>
                  )}
                </select>
              </div>
            </div>

            {/* Auxiliary Slots */}
            <div className="config-aux-section">
              <span className="config-aux-section__title">Auxiliary</span>
              {AUX_SLOTS.map((slotName) => {
                const aux = (config.auxiliary ?? {}) as Record<string, Record<string, unknown>>;
                const slot = (aux[slotName] ?? {}) as Record<string, unknown>;
                if (!slot.provider && !slot.model && !aux[slotName]) return null;

                const currentProvider = (slot.provider as string) ?? "";
                const currentModel = (slot.model as string) ?? "";

                return (
                  <div key={slotName} className="config-aux-row">
                    <div className="config-aux-row__label">
                      <HealthDot health={liveHealth} />
                      <span className="config-aux-row__name">{slotName.replace(/_/g, " ")}</span>
                    </div>
                    <select
                      className="config-field__select select-input config-field__select--inline"
                      value={currentProvider}
                      disabled={patchMutation.isPending}
                      onChange={(e) => patch(`auxiliary.${slotName}.provider`, e.target.value)}
                    >
                      <option value="">—</option>
                      {agentAuxProviderOptions(agentId).map((p) => (
                        <option key={p.value} value={p.value}>{p.label}</option>
                      ))}
                    </select>
                    <select
                      className="config-field__select select-input config-field__select--inline"
                      value={currentModel}
                      disabled={patchMutation.isPending}
                      onChange={(e) => patch(`auxiliary.${slotName}.model`, e.target.value)}
                    >
                      <option value="">—</option>
                      {agentModelOptions(agentId, currentProvider).map((m) => (
                        <option key={m} value={m}>{shortenPath(m)}</option>
                      ))}
                      {currentModel && !agentModelOptions(agentId, currentProvider).includes(currentModel) && (
                        <option value={currentModel}>{shortenPath(currentModel)}</option>
                      )}
                    </select>
                  </div>
                );
              })}
            </div>

          </div>

        {/* Right column: Agent params + Toolsets + MCP */}
        <div className="config-merged-col">
          <span className="config-merged-col__title">Runtime</span>
          <div className="config-settings-grid config-settings-grid--3col">
            <label className="config-field">
              <span className="config-field__label">Context</span>
              <select
                className="config-field__select"
                value={String(contextLength ?? 4096)}
                disabled={patchMutation.isPending}
                onChange={(e) => patch("model.context_length", parseInt(e.target.value, 10))}
              >
                {TOKEN_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t.toLocaleString()}</option>
                ))}
                {contextLength != null && !TOKEN_OPTIONS.includes(contextLength) && (
                  <option value={contextLength}>{contextLength.toLocaleString()}</option>
                )}
              </select>
            </label>
            <label className="config-field">
              <span className="config-field__label">Max Tokens</span>
              <select
                className="config-field__select"
                value={String(maxTokens ?? 4096)}
                disabled={patchMutation.isPending}
                onChange={(e) => patch("max_tokens", parseInt(e.target.value, 10))}
              >
                {TOKEN_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t.toLocaleString()}</option>
                ))}
                {maxTokens != null && !TOKEN_OPTIONS.includes(maxTokens) && (
                  <option value={maxTokens}>{maxTokens.toLocaleString()}</option>
                )}
              </select>
            </label>
            <label className="config-field">
              <span className="config-field__label">Max Turns</span>
              <select
                className="config-field__select"
                value={String(maxTurns ?? 10)}
                disabled={patchMutation.isPending}
                onChange={(e) => patch("agent.max_turns", parseInt(e.target.value, 10))}
              >
                {TURN_OPTIONS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
                {maxTurns != null && !TURN_OPTIONS.includes(maxTurns) && (
                  <option value={maxTurns}>{maxTurns}</option>
                )}
              </select>
            </label>
          </div>
          <div className="config-segmented-row">
            <div className="config-segmented-field">
              <span className="config-segmented-field__label">Enforcement</span>
              <div className="config-segmented-group">
                {(["none", "warn", "enforce"] as const).map((v) => (
                  <button
                    key={v}
                    className={cn("config-segmented-btn", toolEnforcement === v && "config-segmented-btn--active")}
                    disabled={patchMutation.isPending}
                    onClick={() => patch("agent.tool_use_enforcement", v)}
                  >
                    {v.charAt(0).toUpperCase() + v.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="config-segmented-field">
              <span className="config-segmented-field__label">Approval</span>
              <div className="config-segmented-group">
                {(["off", "per_tool", "always"] as const).map((v) => (
                  <button
                    key={v}
                    className={cn("config-segmented-btn", approvalMode === v && "config-segmented-btn--active")}
                    disabled={patchMutation.isPending}
                    onClick={() => patch("approvals.mode", v)}
                  >
                    {v === "per_tool" ? "Per Tool" : v.charAt(0).toUpperCase() + v.slice(1)}
                  </button>
                ))}
              </div>
            </div>
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
    return deriveProvider(c);
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
