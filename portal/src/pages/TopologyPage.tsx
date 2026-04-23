import { useRef, useState } from "react";
import { SyncClock } from "../components/primitives/SyncClock";
import { useAgentStatuses, useTasksDocument, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import { AppShell, SurfaceCard } from "../components/AppShell";
import type { RegistryEntry } from "../lib/types";

const DISPLAY_TRIALS = [
  { id: "", label: "Geist Pixel", detail: "current" },
  { id: "input-sans", label: "Input Sans", detail: "original" },
  { id: "departure-mono", label: "Departure Mono", detail: "mono display" },
  { id: "geist", label: "Geist", detail: "600wt" },
  { id: "basement", label: "Basement", detail: "600wt" },
  { id: "clash", label: "Clash Grotesk", detail: "600wt" },
] as const;

const BODY_TRIALS = [
  { id: "", label: "Geist Mono", detail: "current, 200wt" },
  { id: "inter", label: "Inter", detail: "original" },
  { id: "input-mono", label: "Input Mono", detail: "100wt" },
  { id: "monaspace", label: "Monaspace Neon", detail: "100wt" },
] as const;

function FontTrialRow({ label, attr, options }: {
  label: string;
  attr: string;
  options: readonly { id: string; label: string; detail: string }[];
}) {
  const [active, setActive] = useState(() => document.documentElement.getAttribute(attr) ?? "");

  function apply(id: string) {
    if (id) {
      document.documentElement.setAttribute(attr, id);
    } else {
      document.documentElement.removeAttribute(attr);
    }
    setActive(id);
  }

  return (
    <div className="font-trial-row">
      <span className="font-trial-bar__label">{label}</span>
      {options.map((f) => (
        <button
          key={f.id}
          className={`font-trial-btn${active === f.id ? " is-active" : ""}`}
          onClick={() => apply(f.id)}
          title={f.detail}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}

function FontTrialSwitcher() {
  return (
    <div className="font-trial-bar">
      <FontTrialRow label="Display" attr="data-font-trial" options={DISPLAY_TRIALS} />
      <FontTrialRow label="Body" attr="data-body-trial" options={BODY_TRIALS} />
    </div>
  );
}

function EditableCell({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  if (!editing) {
    return (
      <span className="registry-editable" onClick={() => setEditing(true)}>
        {value || <span className="registry-editable__empty">—</span>}
      </span>
    );
  }

  const commit = () => {
    const next = ref.current?.value.trim() ?? "";
    if (next !== value) onSave(next);
    setEditing(false);
  };

  return (
    <input
      ref={ref}
      className="registry-editable__input"
      defaultValue={value}
      autoFocus
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}

const AGENT_CSS_COLORS: Record<string, string> = {
  coord: "var(--agent-coord)",
  boot: "var(--agent-boot)",
  kelk: "var(--agent-kelk)",
  nan: "var(--agent-nan)",
  xamm: "var(--agent-xamm)",
  ig88: "var(--agent-ig88)",
};

export function TopologyPage() {
  const statuses = useAgentStatuses();
  const tasksDoc = useTasksDocument();
  const registry = tasksDoc.data?.registry;

  function updateRegistry(table: "domains" | "classes", code: string, field: string, value: string) {
    tasksDoc.updateDocument((doc) => ({
      ...doc,
      registry: {
        ...doc.registry!,
        [table]: {
          ...doc.registry![table],
          [code]: { ...doc.registry![table][code], [field]: value },
        },
      },
    }));
  }

  return (
    <AppShell
      title="Configuration"
      pageKey="/pages/topology.html"
      statusSlot={<SyncClock updatedAt={latestDataUpdatedAt(statuses.results)} stale={statuses.hasError} />}
    >
      {/* Agent Strip */}
      <div className="topology-agent-strip">
        {AGENTS.map((agent) => {
          const status = statuses.data[agent.id];
          const currentTask = status?.current_task as string | undefined;
          const agentStatus = status?.status ?? "waiting";
          return (
            <a
              key={agent.id}
              className="topology-agent-card"
              href={`/pages/agents/${agent.id}.html`}
              style={{ ["--node-accent" as string]: AGENT_CSS_COLORS[agent.id] ?? agent.color }}
            >
              <div className="topology-agent-card__header">
                <span className="topology-agent-card__name">{agent.label}</span>
                <div className={`topology-node__status is-${agentStatus}`}>
                  {agentStatus}
                </div>
              </div>
              <div className="topology-agent-card__model">
                <span className="topology-agent-card__model-dot" style={{ background: agent.color }} />
                {agent.model}
              </div>
              <div className="topology-agent-card__trust">{agent.trust}</div>
              <div className="topology-agent-card__task">
                {currentTask || "idle"}
              </div>
            </a>
          );
        })}
      </div>

      {/* System Infrastructure */}
      <SurfaceCard title="System Infrastructure" subtitle="Core services and hardware" className="surface-card--compact">
        <h4 className="topology-layer-title">Services</h4>
        <div className="topology-mini-grid">
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Coordinator</div>
            <div className="topology-mini-node__meta">Rust, Matrix E2EE</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Memory Service</div>
            <div className="topology-mini-node__meta">Graphiti + Qdrant</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">LLM Layer</div>
            <div className="topology-mini-node__meta">MLX local + OpenRouter fallback</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Hardware</div>
            <div className="topology-mini-node__meta">Local GPU nodes</div>
          </div>
        </div>
      </SurfaceCard>

      {/* Escalation Chain */}
      <SurfaceCard title="Escalation Chain" subtitle="Approval flow tiers" className="surface-card--compact">
        <div className="topology-flow">
          <div className="topology-flow-node topology-flow-node--low">
            <div className="topology-mini-node__label">Auto-approve</div>
            <div className="topology-mini-node__meta">Low risk actions</div>
          </div>
          <div className="topology-flow-connector" />
          <div className="topology-flow-node topology-flow-node--medium">
            <div className="topology-mini-node__label">Propose-then-execute</div>
            <div className="topology-mini-node__meta">Medium risk actions</div>
          </div>
          <div className="topology-flow-connector" />
          <div className="topology-flow-node topology-flow-node--high">
            <div className="topology-mini-node__label">Human approval required</div>
            <div className="topology-mini-node__meta">High risk actions</div>
          </div>
        </div>
      </SurfaceCard>

      {/* Reasoning Escalation */}
      <SurfaceCard title="Reasoning Escalation" subtitle="Model tier routing — Nan dispatches" className="surface-card--compact">
        <div className="topology-tier-list">
          {[
            { tier: 0, label: "coordinator-rs — deterministic, no LLM", color: "#22c55e", trigger: "all routing" },
            { tier: 1, label: "Permanent Agents", color: "var(--text)", model: "Nanbeige4.1-3B-8bit / Qwen3.5-4B-MLX-8bit / LFM2.5-1.2B-Thinking-MLX-6bit", trigger: "routine tasks" },
            { tier: 2, label: "On-Demand Reasoning", color: "var(--yellow)", model: "Qwen3.5-9B-MLX-6bit (port 41966)", trigger: "Nan escalation" },
            { tier: 3, label: "Anthropic API", color: "var(--purple)", model: "Claude Sonnet 4.6 / Opus 4.6", trigger: "Tier 2 insufficient" },
            { tier: 4, label: "Solo Intensive", color: "var(--red)", model: "Qwen3.5-35B-A3B (external volume)", trigger: "explicit user request" },
          ].map((row) => (
            <div key={row.tier} className="topology-tier-row">
              <div
                className="topology-tier-badge"
                style={{
                  background: `color-mix(in srgb, ${row.color} 15%, transparent)`,
                  border: `1px solid color-mix(in srgb, ${row.color} 40%, transparent)`,
                  color: row.color,
                }}
              >
                T{row.tier}
              </div>
              <div className="topology-tier-row__body">
                <div className="topology-tier-row__label" style={{ color: row.color }}>{row.label}</div>
                {row.model ? <div className="topology-tier-row__model">{row.model}</div> : null}
              </div>
              {row.trigger ? <div className="topology-tier-row__trigger">{row.trigger}</div> : null}
            </div>
          ))}
        </div>
      </SurfaceCard>
      {/* Operator Context */}
      <div className="portal-columns">
        <SurfaceCard title="Operator Flow" subtitle="Where each surface earns its keep" className="surface-card--compact">
          <ul className="compact-list">
            <li>Open Jobs first for dispatch, task handling, and live operator context.</li>
            <li>Loops now includes the approval queue — gate decisions and loop controls in one surface.</li>
            <li>Analytics absorbs budget policies alongside trend charts for full operational context.</li>
            <li>System is the shortest path into agent-specific detail when a surface needs more context.</li>
          </ul>
        </SurfaceCard>
        <SurfaceCard title="Shared Signals" subtitle="Conventions that carry across every page" className="surface-card--compact">
          <ul className="compact-list">
            <li>Agent color is consistent between topology, task rails, and detail entry points.</li>
            <li>Selected navigation and urgent incidents are the only places that should glow brightly.</li>
            <li>Every page keeps working in a useful degraded state when coordinator routes are unavailable.</li>
            <li>{"`Cmd/Ctrl + K`"} is global, so navigation does not depend on visual scanning alone.</li>
          </ul>
        </SurfaceCard>
      </div>

      {/* Domain & Class Registries */}
      {registry && (
        <SurfaceCard title="Job Registry" subtitle="Domain and class definitions — click to edit" className="surface-card--compact">
          <div className="registry-tables">
            <div>
              <h4 className="topology-layer-title">Domains</h4>
              <table className="registry-table">
                <thead>
                  <tr><th>Code</th><th>Label</th><th>Description</th></tr>
                </thead>
                <tbody>
                  {Object.entries(registry.domains).sort(([a], [b]) => a.localeCompare(b)).map(([code, entry]: [string, RegistryEntry]) => (
                    <tr key={code}>
                      <td className="registry-table__code">{code}</td>
                      <td>
                        <EditableCell
                          value={entry.label}
                          onSave={(v) => updateRegistry("domains", code, "label", v)}
                        />
                      </td>
                      <td className="registry-table__desc">
                        <EditableCell
                          value={entry.description ?? ""}
                          onSave={(v) => updateRegistry("domains", code, "description", v)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div>
              <h4 className="topology-layer-title">Classes</h4>
              <table className="registry-table">
                <thead>
                  <tr><th>Code</th><th>Label</th><th>Color</th></tr>
                </thead>
                <tbody>
                  {Object.entries(registry.classes).sort(([a], [b]) => a.localeCompare(b)).map(([code, entry]: [string, RegistryEntry]) => (
                    <tr key={code}>
                      <td className="registry-table__code">{code}</td>
                      <td>
                        <EditableCell
                          value={entry.label}
                          onSave={(v) => updateRegistry("classes", code, "label", v)}
                        />
                      </td>
                      <td>
                        <span className="registry-color-swatch" style={{ background: entry.color }} />
                        <EditableCell
                          value={entry.color ?? ""}
                          onSave={(v) => updateRegistry("classes", code, "color", v)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </SurfaceCard>
      )}
      <FontTrialSwitcher />
    </AppShell>
  );
}
