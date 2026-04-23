import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import type { ActivityEntry } from "../lib/demo-data";
import { DEMO_ACTIVITY } from "../lib/demo-data";
import { cn, relativeTimestamp } from "../lib/utils";

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

// ── Helpers ─────────────────────────────────────────────────────────

function kindIcon(kind: ActivityEntry["kind"]): string {
  switch (kind) {
    case "session_start": return "→";
    case "session_end": return "✓";
    case "tool_call": return "⚡";
    case "cron_run": return "⟳";
    case "task_update": return "■";
    case "approval": return "⊘";
    case "error": return "✗";
    case "config_change": return "⚙";
    default: return "·";
  }
}

function kindLabel(kind: ActivityEntry["kind"]): string {
  switch (kind) {
    case "session_start": return "Session";
    case "session_end": return "Session";
    case "tool_call": return "Tool";
    case "cron_run": return "Cron";
    case "task_update": return "Task";
    case "approval": return "Approval";
    case "error": return "Error";
    case "config_change": return "Config";
    default: return "Other";
  }
}

function kindTone(kind: ActivityEntry["kind"]): string {
  switch (kind) {
    case "session_start": return "activity-kind--session";
    case "session_end": return "activity-kind--session";
    case "tool_call": return "activity-kind--tool";
    case "cron_run": return "activity-kind--cron";
    case "task_update": return "activity-kind--task";
    case "approval": return "activity-kind--approval";
    case "error": return "activity-kind--error";
    case "config_change": return "activity-kind--config";
    default: return "activity-kind--default";
  }
}

type GroupFilter = "all" | "session" | "tool" | "cron" | "task" | "error" | "config";

// ── Activity Row ────────────────────────────────────────────────────

function ActivityRow({ entry }: { entry: ActivityEntry }) {
  return (
    <div className={cn("activity-row", entry.kind === "error" && "activity-row--error")}>
      <div className="activity-row__icon">
        <span className={cn("activity-kind-icon", kindTone(entry.kind))}>
          {kindIcon(entry.kind)}
        </span>
      </div>
      <div className="activity-row__body">
        <div className="activity-row__head">
          <span className={cn("activity-kind-badge", kindTone(entry.kind))}>
            {kindLabel(entry.kind)}
          </span>
          <span className="activity-row__agent">{entry.agent}</span>
          <span className="activity-row__time">{relativeTimestamp(entry.timestamp)}</span>
        </div>
        <div className="activity-row__summary">{entry.summary}</div>
        {entry.detail && <div className="activity-row__detail">{entry.detail}</div>}
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export function ActivityPage() {
  const [search, setSearch] = useState("");

  const allActivity: ActivityEntry[] = DEMO_MODE ? DEMO_ACTIVITY : [];

  const [groupFilter, setGroupFilter] = useState<GroupFilter>("all");

  const groupKinds: Record<string, ActivityEntry["kind"][]> = {
    session: ["session_start", "session_end"],
    tool: ["tool_call"],
    cron: ["cron_run"],
    task: ["task_update"],
    error: ["error"],
    config: ["config_change"],
  };

  const groupLabels: Record<string, string> = {
    all: "All",
    session: "Session",
    tool: "Tool",
    cron: "Cron",
    task: "Task",
    error: "Error",
    config: "Config",
  };

  const groups: GroupFilter[] = ["all", "session", "tool", "cron", "task", "error", "config"];

  // Update filtered logic
  const filtered = useMemo(() => {
    let entries = [...allActivity];

    if (groupFilter !== "all") {
      const matchKinds = groupKinds[groupFilter] ?? [];
      entries = entries.filter((e) => matchKinds.includes(e.kind));
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      entries = entries.filter(
        (e) =>
          e.summary.toLowerCase().includes(q) ||
          (e.agent ?? "").toLowerCase().includes(q) ||
          (e.detail ?? "").toLowerCase().includes(q)
      );
    }

    return entries;
  }, [allActivity, groupFilter, search]);

  const errorCount = allActivity.filter((e) => e.kind === "error").length;

  return (
    <AppShell
      title="Activity"
      description="Real-time feed of agent actions, sessions, and system events."
      pageKey="/pages/activity.html"
      statusSlot={<SyncClock updatedAt={Date.now()} stale={false} />}
    >
      {/* Summary */}
      <div className="activity-summary">
        <div className="activity-summary__stat">
          <span className="activity-summary__value">{allActivity.length}</span>
          <span className="activity-summary__label">Events</span>
        </div>
        <div className="activity-summary__stat">
          <span className="activity-summary__value">
            {new Set(allActivity.map((e) => e.agent)).size}
          </span>
          <span className="activity-summary__label">Agents</span>
        </div>
        {errorCount > 0 && (
          <div className="activity-summary__stat">
            <span className="activity-summary__value activity-summary__value--error">{errorCount}</span>
            <span className="activity-summary__label">Errors</span>
          </div>
        )}
      </div>

      <SurfaceCard
        title="Event Feed"
        subtitle={`${filtered.length} of ${allActivity.length} events shown`}
      >
        {/* Filters */}
        <div className="activity-filters">
          <input
            className="activity-search"
            type="text"
            placeholder="Search events…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="activity-filter-pills">
            {groups.map((g) => (
              <button
                key={g}
                type="button"
                className={cn("activity-pill", groupFilter === g && "activity-pill--active")}
                onClick={() => setGroupFilter(g)}
              >
                {groupLabels[g]}
              </button>
            ))}
          </div>
        </div>

        {/* Feed */}
        {filtered.length === 0 ? (
          <EmptyState
            compact
            title="No events found"
            detail={
              search || groupFilter !== "all"
                ? "Try adjusting your filters."
                : "Activity will appear here as agents work."
            }
          />
        ) : (
          <div className="activity-feed">
            {filtered.map((entry) => (
              <ActivityRow key={entry.id} entry={entry} />
            ))}
          </div>
        )}
      </SurfaceCard>
    </AppShell>
  );
}
