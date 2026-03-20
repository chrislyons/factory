# FCT016 Factory — Job Registry Migration Sprint Report

**Date:** 2026-03-20
**Status:** Complete
**Related:** FCT015, FCT012, FCT013, ATR005

---

## 1. Summary

Sprint completed 2026-03-20. Migrated 102 tasks from `tasks.json` (generated from FCT012 markdown tables) to 99 individual YAML job files using the `job.##.###.####` addressing scheme defined in FCT015. Three tasks were culled as superseded or duplicated. The portal was updated to consume `jobs.json` as its data source. All 25 tests passing. Agent instruction files for Boot, IG-88, and Kelk updated to reference the new job registry protocol.

---

## 2. Migration Statistics

| Metric | Value |
|--------|-------|
| Input tasks | 102 (from tasks.json) |
| Output job files | 99 |
| Tasks culled | 3 (fct-085 duplicate, fct-086/087 superseded) |
| Tasks marked done | 2 (fct-055, fct-010) |
| Tasks flagged deferred | 7 (research placeholders, needs-scoping) |
| Descriptions updated | 5 (fct-001, fct-002, fct-003, fct-007, fct-040) |
| Dependencies fixed | 2 (fct-027, fct-028 unblocked) |
| Portal tests | 25/25 passing |
| Domain directories | 4 (00, 10, 20, 30) |

### By Domain

| Domain | Label | Jobs |
|--------|-------|------|
| 00 | System | 38 |
| 10 | Boot | 56 |
| 20 | IG-88 | 2 |
| 30 | Kelk | 3 |

### By Status

| Status | Count |
|--------|-------|
| pending | 67 |
| done | 25 |
| deferred | 7 |

---

## 3. Audit Findings Applied

A 4-subagent Qdrant sweep across FCT, BKX, ATR, and WHB documentation sets was executed alongside codebase verification to reconcile task states against actual project reality. The following changes were applied during migration.

### Marked as DONE

- **`fct-055`** mapped to **`job.10.006.0001`** — "Wire coordinator-rs modules into main dispatch loop." Codebase verification confirmed BudgetTracker, RuntimeStateManager, RunEventLog, and TaskLeaseManager are all instantiated in `CoordinatorState`. 41 coordinator tests passing. Closed by ATR005 [4].

- **`fct-010`** mapped to **`job.00.001.0009`** — "Evaluate deprecation timeline for portal v5 on :41933." Portal v5 has been retired and all legacy ports (:41933, :41944, :41966, :41977, :41988) decommissioned. Closed by FCT014.

### Culled

- **`fct-085`** — "Plan coordinated directory rename." Duplicate of fct-005; removed during migration.
- **`fct-086`** — "GSD health check endpoint." Superseded by the GSD sidecar deprecation path; the sidecar is being replaced by coordinator-rs native task management.
- **`fct-087`** — "GSD task completion webhooks." Superseded by `coordinator-rs` `run_events.rs` module, which provides JSONL-based run event tracking.

### Details Updated

- **`fct-001`** (Bitwarden secrets migration) — Noted Cloudkicker migration complete per BKX121 [5].
- **`fct-002`** (Matrix MCP audit) — Noted core audit complete per BKX029/BKX071; 2 MEDIUM-severity items deferred to future sprint.
- **`fct-003`** (Tailscale audit) — Noted ACL audit complete per BKX070/BKX071.
- **`fct-007`** — Retitled to "Verify @coord:matrix.org coordinator identity" per BKX083 [6].
- **`fct-040`** — Corrected GSD sidecar port reference from :41935 to :41911 (the canonical port per factory memory).
- **`fct-done-005`** — Clarified that ContextMode implementation lives in `config.rs`, not a standalone file.
- **`fct-done-019`** — Corrected portal deployment port from :41988 to :41910 (current Caddy target).

### Dependencies Fixed

- **`fct-027`** and **`fct-028`** — Removed incorrect dependency on fct-050 (JSX rendering in Element). The loop spec handoff mechanism was resolved independently by ATR003/ATR005 via the `LOOP_SPEC_PATH` environment variable passed through the delegate spawn path.
- All tasks previously blocked by **fct-055** are now unblocked (fct-055 marked done).

### Flagged for Review

Seven research placeholder tasks (`fct-045` through `fct-051`) were set to `status: deferred` with the `needs-scoping` tag. These require dedicated research sessions before they can be converted to actionable work items.

---

## 4. Files Created

| File | Purpose |
|------|---------|
| `jobs/registry.yaml` | Domain and class definitions (draft) |
| `jobs/SCHEMA.md` | Human-readable ID scheme reference |
| `jobs/migration-map.yaml` | Legacy `fct-###` to `job.##.###.####` mapping |
| `jobs/<domain>/job.*.yaml` | 99 individual job files across 4 domain directories |
| `jobs.json` | Portal-compatible build artifact |
| `scripts/migrate-tasks-to-jobs.py` | One-time migration script |
| `scripts/build-jobs-json.py` | Ongoing YAML-to-JSON build script |
| `docs/fct/FCT015 Factory — Job Registry Architecture and Migration.md` | Design rationale document |

---

## 5. Files Modified

| File | Change |
|------|--------|
| `portal/src/lib/api.ts` | Endpoint swap: `/tasks.json` to `/jobs.json` |
| `portal/src/lib/types.ts` | Added `domain`, `job_class`, `legacy_id` fields to task type |
| `portal/src/pages/DashboardPage.tsx` | New job ID generation logic in `addTask()` |
| `portal/src/pages/DashboardPage.test.tsx` | Updated mock URLs to match new endpoint |
| `portal/src/components/CommandPalette.tsx` | Updated fetch URL to `/jobs.json` |
| `portal/server.py` | Added `jobs.json` to allowed write paths |
| `portal/serve.sh` | Added `/jobs.json` Caddy route |
| `portal/Makefile` | Updated sync targets, added `build-jobs` target |
| `agents/boot/agents.md` | Task protocol updated to job registry |
| `agents/ig88/agents.md` | Task protocol updated to job registry |
| `agents/kelk/agents.md` | Task protocol updated to job registry |
| `scripts/sync-fct012.py` | Deprecated (archival header added) |
| `docs/fct/FCT012 Factory — Task Backlog and Work Item Registry.md` | Archival header added |

---

## 6. Archived

| File | Destination |
|------|-------------|
| `tasks.json` | `archive/tasks.json` |

The original `tasks.json` (102 entries, generated by `sync-fct012.py`) is preserved in the archive directory for reference. The `sync-fct012.py` script has been deprecated with a header warning but not deleted, as it documents the original parsing logic.

---

## 7. Deployment Status

All portal changes are local to Cloudkicker. Deployment to Blackbox (:41910) requires the following sequence:

1. `make build-jobs` — rebuild `jobs.json` from individual YAML files
2. `make sync` — rsync portal build and `jobs.json` to Blackbox
3. `systemctl restart factory-portal` on Blackbox

Deployment was not executed in this sprint as it requires an SSH session to Blackbox (100.87.53.109).

---

## 8. Open Items

| Item | Status | Notes |
|------|--------|-------|
| Domain registry finalization | Blocked | Depends on agent roster decision |
| Class registry finalization | Blocked | May shift with agent restructuring |
| Portal write-back to YAML | Future | Currently read-only; individual file writes are a future enhancement |
| Blackbox deployment | Pending | Separate SSH session required |
| TaskLeaseManager integration | Future | See FCT015 section 11 for coordinator-rs native lease tracking |
| Qdrant vault reindex | Blocked | Auth issue on Blackbox needs resolution before vault can be reindexed |

---

## References

[1] FCT015, "Factory — Job Registry Architecture and Migration," 2026-03-20.
[2] FCT012, "Factory — Task Backlog and Work Item Registry," 2026-03-20.
[3] FCT013, "Factory — Coordinator-Native Task Tracking Architecture," 2026-03-20.
[4] ATR005, "Sprint Loop Engine First Live Run Prep," 2026-03-20.
[5] BKX121, "Secrets Architecture — age to Bitwarden Migration," 2026-03-15.
[6] BKX083, "The @coord Matrix Identity — Reference Guide," 2026-03-07.
