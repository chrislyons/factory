# FCT030 Sprint Completion — Port Allocation, GSD SQLite Design, and Git Housekeeping

**Date:** 2026-03-22
**Status:** Complete
**Related:** FCT029, FCT026, FCT028

---

## 1. Sprint Summary

This sprint executed all tasks from FCT029 that could be done without manual SSH/ops work on Blackbox. Three parallel workstreams completed:

**Team 1 — Git Housekeeping:**
- Committed FCT029 consolidated plan document
- Updated FCT.md MOC through FCT029
- Gitignored `jobs/` directory (operational data, private)
- Removed 103 tracked YAML job files + jobs.json from repository
- All changes pushed to origin/main

**Team 2 — Port Allocation Formalization:**
- Created `docs/fct/ports.md` master port reference (living document)
- Tables organized by host: Cloudkicker, Whitebox, Blackbox
- Allocation principles codified (range assignments for proxy, DB, inference, MCP, application)
- Cross-referenced from FCT029 Section 9 and CLAUDE.md

**Team 3 — CLAUDE.md Port Update:**
- Expanded port scheme table from single-host to multi-host
- Added Whitebox inference + database ports, Blackbox MCP + infrastructure ports
- Cross-reference to `docs/fct/ports.md` for full details

**Bonus — Hook Fix:**
- Fixed `scan-secrets-commit.sh` hook: `timeout` command not available on macOS
- Added portable fallback: tries `timeout`, then `gtimeout`, then runs without timeout

---

## 2. GSD Sidecar SQLite Design Specification

This section specifies the evolution of the GSD sidecar from a static file server to a job state service with SQLite persistence. This is a design document — implementation is deferred to Stream 2 integration work.

### 2.1 Current Architecture

The GSD sidecar (`portal/server.py`) is a plain Python `http.server` subclass running on Blackbox :41911. It serves `jobs.json` (GET) and accepts writes (PUT) to `jobs.json` and `status/*.json`. Authentication is layered: Caddy `forward_auth` (cookie-based, CSRF) gates all traffic, with optional Bearer token on the sidecar itself.

The data pipeline is unidirectional:
```
YAML files -> build-jobs-json.py -> jobs.json -> GSD sidecar -> Portal
```

Portal can read and write `jobs.json` through the sidecar, but changes are not propagated back to YAML source files. The entire document is read/written atomically — no field-level updates.

### 2.2 SQLite Schema

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,           -- job.DD.CCC.AAAA format
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/done/deferred/deprecated
    priority    TEXT DEFAULT 'p2',
    effort      TEXT DEFAULT 'low',
    assignee    TEXT DEFAULT 'chris',
    domain      TEXT NOT NULL,
    job_class   TEXT NOT NULL,
    blocked_by  TEXT,                       -- JSON array
    thread_ids  TEXT,                       -- JSON array (FCT026 join key)
    tags        TEXT,                       -- JSON array
    created     TEXT NOT NULL,              -- ISO 8601
    updated     TEXT NOT NULL               -- ISO 8601
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_domain ON jobs(domain);
CREATE INDEX idx_jobs_assignee ON jobs(assignee);
```

Design notes:
- JSON arrays stored as TEXT columns (SQLite has no native array type)
- `thread_ids` is the FCT026 Seam 1 join key — links jobs to Matrix conversation threads
- Status enum matches existing `TaskRecord` TypeScript type (pending/done/deferred/deprecated, plus in-progress and blocked for Portal display)
- `id` format enforced at application layer, not DB constraint

### 2.3 New API Endpoints

Added to `server.py` alongside existing file-serving:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | List all jobs. Optional query params: `?status=pending&domain=10&assignee=boot` |
| `GET` | `/api/jobs/:id` | Single job detail by ID |
| `PUT` | `/api/jobs/:id` | Update job fields (status, assignee, description, thread_ids, etc.) |
| `POST` | `/api/jobs` | Create new job |
| `POST` | `/api/jobs/import` | Bulk import from YAML files (bootstrap/recovery) |
| `GET` | `/jobs.json` | **Compatibility endpoint** — reads from SQLite, returns same JSON format as current |

All mutating endpoints require CSRF token (existing `X-CSRF-Token` header mechanism). Response format: JSON with appropriate HTTP status codes. Error responses include `{"error": "description"}`.

### 2.4 Migration Path

**Phase 1 — Dual Mode (SQLite alongside JSON):**
- Add SQLite database file (`gsd.db`) alongside existing `jobs.json`
- New `/api/jobs` endpoints read/write SQLite
- Existing `GET /jobs.json` reads from SQLite, returns same format
- Existing `PUT /jobs.json` writes to both SQLite and JSON file
- `POST /api/jobs/import` bootstraps SQLite from existing YAML/JSON
- Both systems work simultaneously — no Portal changes required

**Phase 2 — Portal API Migration:**
- Portal switches from `fetchTasks()` (GET `/jobs.json`) to new `/api/jobs` endpoints
- Field-level updates replace whole-document PUT
- React Query hooks updated to use individual job endpoints
- Optimistic updates still work but are per-field, not per-document

**Phase 3 — JSON Removal:**
- Remove JSON file dependency
- `GET /jobs.json` becomes a pure compatibility shim (reads from SQLite)
- `PUT /jobs.json` deprecated and eventually removed
- `build-jobs-json.py` becomes import-only tool, not part of live pipeline

### 2.5 Cross-Device Sync Model

**Primary:** One sidecar instance on the host machine (currently Blackbox, future Whitebox). All devices connect over Tailscale encrypted mesh. Portal on any device hits the same sidecar endpoint.

**Fallback — Cached Degraded Mode:**
- Sidecar periodically exports `jobs.json` snapshot for offline/cached reads
- Portal detects connection loss (fetch timeout or network error)
- Falls back to cached copy — read-only, stale indicator shown in UI
- Reconnection automatically restores full read/write capability
- No conflict resolution needed: single-writer model, sidecar is authoritative

**Decision captured (Q5):** Tailscale is the primary sync transport. Cached JSON fallback provides offline resilience. No distributed database required.

---

## 3. Decisions Captured

| ID | Decision | Rationale |
|----|----------|-----------|
| Q4 | E2EE cutover before Whitebox migration | Eliminates Pantalaimon migration complexity — if native Megolm is active, Pantalaimon doesn't need to move |
| Q5 | Tailscale primary + cached JSON fallback | Single-writer model avoids distributed DB complexity. Tailscale mesh provides encrypted transport. Cached JSON gives offline resilience |

---

## 4. Blocked Items (Requires Manual Ops)

These items from FCT029 could not be completed this sprint:

| Item | Blocker | FCT029 Section |
|------|---------|----------------|
| Restore IG-88 + Kelk agent tokens | Needs Blackbox SSH + Bitwarden | 5 (P0) |
| Deploy Portal security fixes | Needs Blackbox SSH + `make sync` | 5 (P1) |
| Rotate Matrix secrets | Needs Blackbox SSH | 5 (P1) |
| E2EE cutover | Blocked by agent stability gate | 7 |
| GSD sidecar code changes | Design only this sprint | 4 |
| @Xamm agent creation | Needs model selection + Matrix account | 2 |

---

## 5. Next Sprint Scope

**Stream 2 — Integration Work (after Blackbox recovery):**

1. GSD sidecar SQLite implementation (Phase 1 from Section 2.4)
2. Jobs-to-Matrix thread binding (FCT026 Seam 1)
3. Portal API migration to `/api/jobs` endpoints
4. Coordinator HTTP REST API stub (port 41950)

**Agent Creation Modularization:**

@Xamm and @Nan are the first test cases for a modular agent creation workflow:
- Model selection (from validated Whitebox inference stack)
- Identity prompt authoring (class 008 curriculum jobs)
- Matrix account registration
- matrix-mcp instance deployment
- Coordinator config update

This workflow should be documented as a repeatable procedure, not a one-off.

---

## 6. References

[1] FCT029, "Factory Consolidated Plan — Architecture, Recovery, and Roadmap," 2026-03-22.

[2] FCT026, "Three Integration Seams: Jobs, Approval, Transcript," 2026-03-21.

[3] FCT028, "v0 Factory Jobs Audit Report," 2026-03-21.
