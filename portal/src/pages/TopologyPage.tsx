import { LastUpdatedChip } from "../components/primitives/LastUpdatedChip";
import { useAgentStatuses, latestDataUpdatedAt } from "../hooks/usePortalQueries";
import { AGENTS } from "../lib/constants";
import { AppShell, SurfaceCard } from "../components/AppShell";

const AGENT_CSS_COLORS: Record<string, string> = {
  boot: "var(--agent-boot)",
  ig88: "var(--agent-ig88)",
  kelk: "var(--agent-kelk)",
  nan: "var(--agent-nan)",
};

export function TopologyPage() {
  const statuses = useAgentStatuses();

  return (
    <AppShell
      title="Factory Topology"
      pageKey="/pages/topology.html"
      statusSlot={<LastUpdatedChip updatedAt={latestDataUpdatedAt(statuses.results)} stale={statuses.hasError} />}
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
            <div className="topology-mini-node__meta">Blackbox RP5 / Cloudkicker M2</div>
          </div>
        </div>
      </SurfaceCard>

      {/* Escalation Chain */}
      <SurfaceCard title="Escalation Chain" subtitle="Approval flow tiers" className="surface-card--compact">
        <div className="topology-mini-grid">
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Auto-approve</div>
            <div className="topology-mini-node__meta">Low risk actions</div>
          </div>
          <div className="topology-mini-node">
            <div className="topology-mini-node__label">Propose-then-execute</div>
            <div className="topology-mini-node__meta">Medium risk actions</div>
          </div>
          <div className="topology-mini-node">
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
            { tier: 1, label: "Permanent Agents", color: "var(--text)", model: "Nanbeige 3B / Qwen3.5-4B / LFM2.5-1.2B", trigger: "routine tasks" },
            { tier: 2, label: "On-Demand Reasoning", color: "var(--yellow)", model: "Qwen3.5-9B-Opus-Distilled", trigger: "Nan escalation" },
            { tier: 3, label: "Anthropic API", color: "var(--purple)", model: "Claude Sonnet 4.6 / Opus 4.6", trigger: "Tier 2 insufficient" },
            { tier: 4, label: "Solo Intensive", color: "var(--red)", model: "Qwen3.5-27B-Opus-Distilled", trigger: "explicit user request" },
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
    </AppShell>
  );
}
