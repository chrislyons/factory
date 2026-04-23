import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { SidePanel, SidePanelContent } from "../components/SidePanel";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import {
  useHermesSessions,
  useSessionDetail,
} from "../hooks/usePortalQueries";
import { cn, relativeTimestamp } from "../lib/utils";
import type { HermesSession, HermesSessionsResponse, SessionMessage } from "../lib/types";

// ── Helpers ─────────────────────────────────────────────────────────

function sourceLabel(source: string): string {
  switch (source) {
    case "cli": return "CLI";
    case "matrix": return "Matrix";
    case "acp": return "ACP";
    case "cron": return "Cron";
    case "webhook": return "Webhook";
    default: return source;
  }
}

function sourceTone(source: string): string {
  switch (source) {
    case "cli": return "session-source--cli";
    case "matrix": return "session-source--matrix";
    case "acp": return "session-source--acp";
    case "cron": return "session-source--cron";
    default: return "session-source--default";
  }
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function truncateModel(model: string | null): string {
  if (!model) return "—";
  return model.length > 30 ? model.slice(0, 27) + "…" : model;
}

type SortKey = "started" | "messages" | "tools" | "tokens";
type FilterSource = "all" | "cli" | "matrix" | "acp" | "cron" | "webhook";
type FilterStatus = "all" | "active" | "completed";

// ── Session Detail ──────────────────────────────────────────────────

function SessionDetailView({ sessionId }: { sessionId: string }) {
  const detail = useSessionDetail(sessionId);
  const d = detail.data;

  if (detail.isLoading) {
    return <div className="session-loading">Loading session…</div>;
  }

  if (!d || ("error" in d && (d as { error: string }).error)) {
    const err = d && "error" in d ? (d as { error: string }).error : "Session not found";
    return <EmptyState compact title="Session not found" detail={err} />;
  }

  return (
    <div className="session-detail">
      <div className="session-detail__header">
        <h4 className="session-detail__title">{d.title || d.id}</h4>
        <div className="session-detail__stats">
          <div className="session-stat">
            <span className="session-stat__label">Messages</span>
            <span className="session-stat__value">{d.message_count}</span>
          </div>
          <div className="session-stat">
            <span className="session-stat__label">Tool Calls</span>
            <span className="session-stat__value">{d.tool_call_count}</span>
          </div>
          <div className="session-stat">
            <span className="session-stat__label">Input</span>
            <span className="session-stat__value">{formatTokens(d.input_tokens)}</span>
          </div>
          <div className="session-stat">
            <span className="session-stat__label">Output</span>
            <span className="session-stat__value">{formatTokens(d.output_tokens)}</span>
          </div>
          {d.estimated_cost_usd != null && (
            <div className="session-stat">
              <span className="session-stat__label">Cost</span>
              <span className="session-stat__value">${d.estimated_cost_usd.toFixed(4)}</span>
            </div>
          )}
          {d.model && (
            <div className="session-stat session-stat--wide">
              <span className="session-stat__label">Model</span>
              <span className="session-stat__value">{d.model}</span>
            </div>
          )}
        </div>
      </div>

      {d.recent_messages.length > 0 && (
        <div className="session-messages">
          <h5 className="session-messages__heading">Recent Messages</h5>
          <div className="session-messages__list">
            {d.recent_messages.map((msg) => (
              <MessageRow key={msg.id} msg={msg} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function MessageRow({ msg }: { msg: SessionMessage }) {
  const isTool = msg.role === "tool" || msg.tool_names.length > 0;
  return (
    <div className={cn("session-msg", isTool && "session-msg--tool")}>
      <div className="session-msg__head">
        <span className={cn("session-msg__role", `session-msg__role--${msg.role}`)}>
          {msg.role}
        </span>
        {msg.tool_names.length > 0 && (
          <span className="session-msg__tools">{msg.tool_names.join(", ")}</span>
        )}
        <span className="session-msg__time">{relativeTimestamp(msg.timestamp)}</span>
      </div>
      {msg.preview && <div className="session-msg__preview">{msg.preview}</div>}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export function SessionsPage() {
  const sessions = useHermesSessions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<FilterSource>("all");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [sortBy, setSortBy] = useState<SortKey>("started");

  const data = sessions.data;

  const filteredSessions = useMemo(() => {
    if (!data) return [];
    let all = [...data.active, ...data.completed];

    // Source filter
    if (sourceFilter !== "all") {
      all = all.filter((s) => s.source === sourceFilter);
    }

    // Status filter
    if (statusFilter === "active") {
      all = all.filter((s) => !s.ended_at);
    } else if (statusFilter === "completed") {
      all = all.filter((s) => !!s.ended_at);
    }

    // Search
    if (search.trim()) {
      const q = search.toLowerCase();
      all = all.filter(
        (s) =>
          s.id.toLowerCase().includes(q) ||
          (s.title && s.title.toLowerCase().includes(q)) ||
          (s.model && s.model.toLowerCase().includes(q)) ||
          s.source.toLowerCase().includes(q)
      );
    }

    // Sort
    all.sort((a, b) => {
      switch (sortBy) {
        case "messages": return b.message_count - a.message_count;
        case "tools": return b.tool_call_count - a.tool_call_count;
        case "tokens": return (b.input_tokens + b.output_tokens) - (a.input_tokens + a.output_tokens);
        case "started":
        default:
          return new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime();
      }
    });

    return all;
  }, [data, sourceFilter, statusFilter, search, sortBy]);

  const sources: FilterSource[] = ["all", "cli", "matrix", "acp", "cron", "webhook"];

  return (
    <AppShell
      title="Sessions"
      description="Hermes conversation history — messages, tool calls, and token usage."
      pageKey="/pages/sessions.html"
      statusSlot={
        <SyncClock
          updatedAt={sessions.dataUpdatedAt || 0}
          stale={Boolean(sessions.error)}
        />
      }
    >
      <SurfaceCard
        title="Session Browser"
        subtitle={`${data?.total ?? 0} total · ${data?.active.length ?? 0} active · ${filteredSessions.length} shown`}
      >
        {/* Filters */}
        <div className="session-filters">
          <input
            className="session-search"
            type="text"
            placeholder="Search sessions…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="session-filter-row">
            <div className="session-filter-group">
              <span className="session-filter-label">Source</span>
              <div className="session-filter-pills">
                {sources.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={cn("session-pill", sourceFilter === s && "session-pill--active")}
                    onClick={() => setSourceFilter(s)}
                  >
                    {s === "all" ? "All" : sourceLabel(s)}
                  </button>
                ))}
              </div>
            </div>
            <div className="session-filter-group">
              <span className="session-filter-label">Status</span>
              <div className="session-filter-pills">
                {(["all", "active", "completed"] as FilterStatus[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={cn("session-pill", statusFilter === s && "session-pill--active")}
                    onClick={() => setStatusFilter(s)}
                  >
                    {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            <div className="session-filter-group">
              <span className="session-filter-label">Sort</span>
              <select
                className="session-sort-select"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortKey)}
              >
                <option value="started">Newest first</option>
                <option value="messages">Most messages</option>
                <option value="tools">Most tool calls</option>
                <option value="tokens">Most tokens</option>
              </select>
            </div>
          </div>
        </div>

        {/* Session list */}
        {sessions.isLoading ? (
          <div className="session-loading">Loading sessions…</div>
        ) : filteredSessions.length === 0 ? (
          <EmptyState
            compact
            title="No sessions found"
            detail={
              search || sourceFilter !== "all" || statusFilter !== "all"
                ? "Try adjusting your filters."
                : "Hermes state.db has no session records."
            }
          />
        ) : (
          <div className="session-list">
            <div className="session-list__header">
              <span className="session-col session-col--source">Source</span>
              <span className="session-col session-col--title">Session</span>
              <span className="session-col session-col--model">Model</span>
              <span className="session-col session-col--msgs">Msgs</span>
              <span className="session-col session-col--tools">Tools</span>
              <span className="session-col session-col--tokens">Tokens</span>
              <span className="session-col session-col--time">Started</span>
            </div>
            {filteredSessions.map((s) => {
              const isSelected = selectedId === s.id;
              const isActive = !s.ended_at;
              return (
                <button
                  key={s.id}
                  type="button"
                  className={cn("session-row", isSelected && "session-row--selected")}
                  onClick={() => setSelectedId(isSelected ? null : s.id)}
                >
                  <span className="session-col session-col--source">
                    <span className={cn("session-source-badge", sourceTone(s.source))}>
                      {sourceLabel(s.source)}
                    </span>
                    {isActive && <span className="session-live-dot" title="Active" />}
                  </span>
                  <span className="session-col session-col--title" title={s.id}>
                    {s.title || s.id.slice(0, 20)}
                  </span>
                  <span className="session-col session-col--model" title={s.model ?? undefined}>
                    {truncateModel(s.model)}
                  </span>
                  <span className="session-col session-col--msgs">{s.message_count}</span>
                  <span className="session-col session-col--tools">{s.tool_call_count}</span>
                  <span className="session-col session-col--tokens">
                    {formatTokens(s.input_tokens + s.output_tokens)}
                  </span>
                  <span className="session-col session-col--time">
                    {relativeTimestamp(s.started_at)}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {/* Tool distribution */}
        {data && Object.keys(data.tool_distribution).length > 0 && (
          <div className="session-tool-dist">
            <h5 className="session-tool-dist__heading">Tool Distribution (all sessions)</h5>
            <div className="session-tool-bars">
              {Object.entries(data.tool_distribution)
                .sort(([, a], [, b]) => b - a)
                .slice(0, 12)
                .map(([name, count]) => {
                  const max = Math.max(...Object.values(data.tool_distribution));
                  const pct = max > 0 ? (count / max) * 100 : 0;
                  return (
                    <div key={name} className="session-tool-bar">
                      <span className="session-tool-bar__name">{name}</span>
                      <div className="session-tool-bar__track">
                        <div className="session-tool-bar__fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="session-tool-bar__count">{count}</span>
                    </div>
                  );
                })}
            </div>
          </div>
        )}
      </SurfaceCard>

      {/* Detail side panel */}
      <SidePanel
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
        title="Session Detail"
      >
        <SidePanelContent>
          {selectedId && <SessionDetailView sessionId={selectedId} />}
        </SidePanelContent>
      </SidePanel>
    </AppShell>
  );
}
