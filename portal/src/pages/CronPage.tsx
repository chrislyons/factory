import { useMemo, useState } from "react";
import { AppShell, SurfaceCard } from "../components/AppShell";
import { EmptyState } from "../components/primitives/EmptyState";
import { SyncClock } from "../components/primitives/SyncClock";
import { useCronJobs } from "../hooks/usePortalQueries";
import { cn, relativeTimestamp } from "../lib/utils";
import type { CronJob } from "../lib/types";

// ── Helpers ─────────────────────────────────────────────────────────

function stateBadge(state: string): string {
  switch (state) {
    case "scheduled": return "cron-state--scheduled";
    case "paused": return "cron-state--paused";
    case "completed": return "cron-state--completed";
    case "running": return "cron-state--running";
    default: return "cron-state--default";
  }
}

type FilterState = "all" | "scheduled" | "paused" | "running" | "completed";

// ── Job Detail Card ─────────────────────────────────────────────────

function JobDetail({ job }: { job: CronJob }) {
  return (
    <div className="cron-detail">
      <div className="cron-detail__header">
        <h4 className="cron-detail__name">{job.name || job.id}</h4>
        <span className={cn("cron-state", stateBadge(job.state))}>{job.state}</span>
        {!job.enabled && <span className="cron-state cron-state--disabled">disabled</span>}
      </div>

      <div className="cron-detail__grid">
        <div className="cron-detail__field">
          <span className="cron-detail__label">Schedule</span>
          <span className="cron-detail__value">{job.schedule_display}</span>
        </div>
        <div className="cron-detail__field">
          <span className="cron-detail__label">ID</span>
          <span className="cron-detail__value cron-detail__value--mono">{job.id}</span>
        </div>
        {job.next_run && (
          <div className="cron-detail__field">
            <span className="cron-detail__label">Next Run</span>
            <span className="cron-detail__value">{relativeTimestamp(job.next_run)}</span>
          </div>
        )}
        {job.last_run && (
          <div className="cron-detail__field">
            <span className="cron-detail__label">Last Run</span>
            <span className="cron-detail__value">{relativeTimestamp(job.last_run)}</span>
          </div>
        )}
        {job.run_count != null && (
          <div className="cron-detail__field">
            <span className="cron-detail__label">Total Runs</span>
            <span className="cron-detail__value">{job.run_count}</span>
          </div>
        )}
        {job.created_at && (
          <div className="cron-detail__field">
            <span className="cron-detail__label">Created</span>
            <span className="cron-detail__value">{relativeTimestamp(job.created_at)}</span>
          </div>
        )}
      </div>

      {job.prompt && (
        <div className="cron-detail__section">
          <span className="cron-detail__label">Prompt</span>
          <div className="cron-detail__prompt">{job.prompt}</div>
        </div>
      )}

      {job.skills && job.skills.length > 0 && (
        <div className="cron-detail__section">
          <span className="cron-detail__label">Skills</span>
          <div className="cron-detail__skills">
            {job.skills.map((s) => (
              <span key={s} className="cron-detail__skill">{s}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────

export function CronPage() {
  const cron = useCronJobs();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<FilterState>("all");
  const [search, setSearch] = useState("");

  const data = cron.data;

  const filteredJobs = useMemo(() => {
    if (!data) return [];
    let jobs = [...data.jobs];

    if (stateFilter !== "all") {
      jobs = jobs.filter((j) => j.state === stateFilter);
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      jobs = jobs.filter(
        (j) =>
          (j.name && j.name.toLowerCase().includes(q)) ||
          j.id.toLowerCase().includes(q) ||
          (j.prompt && j.prompt.toLowerCase().includes(q)) ||
          j.schedule_display.toLowerCase().includes(q)
      );
    }

    // Sort: scheduled first, then paused, then by next_run
    jobs.sort((a, b) => {
      if (a.state === "scheduled" && b.state !== "scheduled") return -1;
      if (b.state === "scheduled" && a.state !== "scheduled") return 1;
      if (a.next_run && b.next_run) return new Date(a.next_run).getTime() - new Date(b.next_run).getTime();
      if (a.next_run) return -1;
      if (b.next_run) return 1;
      return 0;
    });

    return jobs;
  }, [data, stateFilter, search]);

  const selectedJob = data?.jobs.find((j) => j.id === selectedId) ?? null;
  const states: FilterState[] = ["all", "scheduled", "running", "paused", "completed"];

  const scheduledCount = data?.jobs.filter((j) => j.state === "scheduled").length ?? 0;
  const pausedCount = data?.jobs.filter((j) => j.state === "paused").length ?? 0;
  const totalRuns = data?.jobs.reduce((sum, j) => sum + (j.run_count ?? 0), 0) ?? 0;

  return (
    <AppShell
      title="Cron"
      description="Scheduled tasks and recurring jobs."
      pageKey="/pages/cron.html"
      statusSlot={
        <SyncClock
          updatedAt={cron.dataUpdatedAt || 0}
          stale={Boolean(cron.error)}
        />
      }
    >
      {/* Summary bar */}
      <div className="cron-summary">
        <div className="cron-summary__stat">
          <span className="cron-summary__value">{data?.count ?? 0}</span>
          <span className="cron-summary__label">Jobs</span>
        </div>
        <div className="cron-summary__stat">
          <span className="cron-summary__value">{scheduledCount}</span>
          <span className="cron-summary__label">Active</span>
        </div>
        <div className="cron-summary__stat">
          <span className="cron-summary__value">{pausedCount}</span>
          <span className="cron-summary__label">Paused</span>
        </div>
        <div className="cron-summary__stat">
          <span className="cron-summary__value">{totalRuns.toLocaleString()}</span>
          <span className="cron-summary__label">Total Runs</span>
        </div>
      </div>

      <SurfaceCard
        title="Scheduled Jobs"
        subtitle={`${filteredJobs.length} of ${data?.count ?? 0} shown`}
      >
        {/* Filters */}
        <div className="cron-filters">
          <input
            className="cron-search"
            type="text"
            placeholder="Search jobs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="cron-filter-pills">
            {states.map((s) => (
              <button
                key={s}
                type="button"
                className={cn("cron-pill", stateFilter === s && "cron-pill--active")}
                onClick={() => setStateFilter(s)}
              >
                {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Job list */}
        {cron.isLoading ? (
          <div className="cron-loading">Loading cron jobs…</div>
        ) : filteredJobs.length === 0 ? (
          <EmptyState
            compact
            title="No cron jobs found"
            detail={
              search || stateFilter !== "all"
                ? "Try adjusting your filters."
                : "Create scheduled tasks via /cron in any Hermes chat session."
            }
          />
        ) : (
          <div className="cron-list">
            {filteredJobs.map((job) => {
              const isSelected = selectedId === job.id;
              return (
                <div
                  key={job.id}
                  className={cn("cron-row", isSelected && "cron-row--selected")}
                  onClick={() => setSelectedId(isSelected ? null : job.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setSelectedId(isSelected ? null : job.id);
                  }}
                >
                  <div className="cron-row__head">
                    <div className="cron-row__left">
                      <span className="cron-row__name">{job.name || job.id}</span>
                      <span className={cn("cron-state", stateBadge(job.state))}>{job.state}</span>
                      {!job.enabled && <span className="cron-state cron-state--disabled">off</span>}
                    </div>
                    <span className="cron-row__schedule">{job.schedule_display}</span>
                  </div>
                  <div className="cron-row__meta">
                    {job.next_run && <span>Next: {relativeTimestamp(job.next_run)}</span>}
                    {job.last_run && <span>Last: {relativeTimestamp(job.last_run)}</span>}
                    {job.run_count != null && <span>Runs: {job.run_count}</span>}
                    {job.skills && job.skills.length > 0 && (
                      <span className="cron-row__skills">Skills: {job.skills.join(", ")}</span>
                    )}
                  </div>
                  {job.prompt && isSelected && (
                    <div className="cron-row__prompt">{job.prompt}</div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </SurfaceCard>

      {/* Detail panel */}
      {selectedJob && (
        <SurfaceCard
          title="Job Detail"
          subtitle={selectedJob.name || selectedJob.id}
          className="surface-card--compact"
        >
          <JobDetail job={selectedJob} />
        </SurfaceCard>
      )}
    </AppShell>
  );
}
