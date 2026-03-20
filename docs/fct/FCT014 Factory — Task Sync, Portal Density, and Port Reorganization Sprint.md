# FCT014 Factory — Task Sync, Portal Density, and Port Reorganization Sprint
## Sprint Report — 2026-03-20

**Prefix:** FCT | **Repo:** `~/dev/factory/` | **Status:** Complete

---

## Summary

Five-deliverable sprint focused on bridging the FCT012 task backlog with the portal frontend, tightening portal information density, and establishing a permanent port allocation scheme for Factory services on Blackbox. The sprint produced a stdlib-only Python sync script, an architecture document for coordinator-native task tracking, Caddy routing fixes, density improvements across six portal components, and a comprehensive port reorganization with documentation.

---

## Deliverables

### 1. FCT012 to tasks.json Sync Script

Created `scripts/sync-fct012.py` — a zero-dependency Python parser that converts FCT012's markdown task tables into the portal's `TasksDocument` JSON schema.

- **Table variants handled:** 4 (standard 8-column, completed 4-column, GSD legacy 7-column, curriculum-derived 7-column)
- **Deduplication:** FCT-008 appears in both Infrastructure and GSD Legacy sections; parser detects and merges the duplicate
- **Synthetic IDs:** Completed items lacking explicit IDs receive generated identifiers
- **Status mapping:** Translates markdown status labels and effort estimates to portal-compatible values
- **Output:** 102 tasks across 9 colour-coded category blocks
- **CLI interface:** `--dry-run` for validation, `-o path.json` for output path
- **Commit:** `6953a4e`

### 2. FCT013 Architecture Document

Created FCT013 [1] — a Layer 3 architecture document defining the migration path from markdown-based task tracking to coordinator-native authority.

- **Scope:** 9 sections, 254 lines
- **Migration phases:** 4 (sync script, read-only coordinator, write integration, full coordinator authority)
- **Technical coverage:** `task_store.rs` module design, `RunEvent` task_id field extension, REST endpoint specifications, Paperclip pattern mapping (#1 task leases, #2 approval gates)
- **FCT.md index:** Updated with FCT013 entry
- **Commit:** `6953a4e`

### 3. Portal Deployment Fix (Caddy Routing)

Resolved HTTP 404 errors on `/tasks.json` and other proxied routes caused by Caddy route evaluation order.

- **Root cause:** Bare `reverse_proxy @matcher` directives were evaluated after the catch-all `handle { file_server }` block, so proxied paths never matched
- **Fix:** Wrapped each `reverse_proxy` route in its own `handle` block, leveraging Caddy's mutual exclusion semantics — the first matching `handle` wins, preventing the `file_server` fallback from intercepting API routes
- **Additional fix:** Updated `Makefile` sync-gsd target to source from `factory/tasks.json` instead of the retired `get-shit-done/` repository
- **Commits:** `084e26a`, `eebcb83`

### 4. Information Density Cleanup

Reduced vertical whitespace and visual weight across six portal components to increase information density on the dashboard.

| Component | Change |
|-----------|--------|
| `MetricCard` | min-height 96 to 56px, reduced padding, value font-size 19 to 16px |
| `EmptyState` | min-height 112 to 48px (normal), 74 to 36px (compact), switched to inline flex layout |
| `DashboardPage` | Collapsed empty Active Loops + Active Runs into a single compact status bar when no coordinator data is present |
| `SurfaceCard` | Tightened header margin |
| Portal layout | Reduced `portal-main` padding and `page-content` margin |
| Live run card | Height 180 to 140px, chart placeholder 210 to 160px |

- **Test update:** `DashboardPage` test updated for new collapsed status bar text
- **Commit:** `63299f6`

### 5. Port Reorganization

Established a permanent port allocation scheme for all Factory services, replacing the ad-hoc port assignments accumulated during development.

| Range | Purpose | Assignments |
|-------|---------|-------------|
| 41910-41919 | Production | :41910 (portal Caddy), :41911 (GSD sidecar) |
| 41920-41929 | Preview / comparison | Reserved for A/B deploys |
| 41930-41939 | Staging | Reserved |
| 41940-41949 | Development | Reserved for local dev |
| 41950-41959 | Coordinator | Reserved for coordinator-rs endpoints |
| 41960-41969 | Reserved | Future use |

- **Cleanup:** Stopped and disabled old systemd services on :41966 and :41977
- **Documentation:** Created `VERSIONS.md` with version registry and port scheme
- **Code changes:** Updated `serve.sh` defaults and `Makefile` verify target to use :41910
- **Commit:** `63299f6`

---

## Test Results

| Suite | Files | Tests | Status |
|-------|-------|-------|--------|
| Portal (Vitest) | 13 | 25 | All passing |
| Build (pnpm) | -- | -- | Clean, zero warnings |
| Deployment | -- | -- | Live on Blackbox :41910, tasks.json serving 102 tasks |

---

## Commit Log

| Hash | Description |
|------|-------------|
| `6953a4e` | feat(tasks): add FCT012 to tasks.json sync script + FCT013 architecture doc |
| `084e26a` | fix(portal): point sync-gsd at factory/tasks.json instead of get-shit-done |
| `eebcb83` | fix(portal): use handle blocks for Caddy reverse_proxy routing |
| `fbb4e58` | fix(portal): guard matchMedia in useTheme for test env + update topology test |
| `40cca6d` | feat(portal): v8 shell + theme toggle + hotkey nav + chart palette |
| `63299f6` | Portal density cleanup + port reorganization |

---

## Architecture Decisions

1. **Stdlib-only sync script:** `sync-fct012.py` uses only Python standard library modules (no pandas, no YAML parser). This keeps the tool dependency-free and runnable on any system with Python 3.8+, including Blackbox without virtual environments.

2. **Caddy handle blocks over matcher priority:** Rather than relying on Caddy's implicit route ordering or `route` directives, wrapping each proxy in a `handle` block provides explicit mutual exclusion. This is more readable and resilient to future Caddyfile additions.

3. **Logical 10-port ranges:** The new port scheme reserves 10-port ranges per environment tier. This provides room for growth (up to 10 services per tier) while keeping port numbers predictable and documentable.

4. **Collapsed empty state:** When the coordinator is not yet wired (FCT-055 pending), the dashboard shows a single compact status bar instead of two separate empty-state cards. This reduces visual noise during the pre-integration phase without removing the UI scaffolding.

---

## Next Steps

- **FCT-055:** Wire coordinator-rs dispatch loop — critical path blocker for live agent orchestration
- **Phase 1 of FCT013:** Coordinator-rs reads `tasks.json` at startup (dependent on FCT-055 completion)
- **Automated sync:** Evaluate cron job or git hook for `sync-fct012.py` execution on FCT012 changes
- **Portal v9 candidates:** Live WebSocket event streaming from coordinator-rs, approval inbox UI

---

## References

[1] FCT013, "Factory — Coordinator-Native Task Tracking Architecture," 2026-03-20.
[2] FCT012, "Factory — Task Backlog and Work Item Registry," 2026-03-20.
[3] FCT011, "Factory Portal v8 — Design Overhaul and Deployment," 2026-03-20.
[4] FCT008, "Sprint Complete — Paperclip x Factory Gap Analysis and Implementation," 2026-03-17.
