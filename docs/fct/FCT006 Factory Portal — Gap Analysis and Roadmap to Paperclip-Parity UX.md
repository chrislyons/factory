# FCT006 Factory Portal — Gap Analysis and Roadmap to Paperclip-Parity UX

**Prefix:** FCT | **Repo:** ~/dev/factory/ | **Status:** Living document | **Related:** FCT004, FCT005

---

## 1. Executive Summary

Factory Portal (`~/dev/factory/portal/`) is a production-deployed MVP: vanilla HTML/JS/CSS task dashboard + documentation hub served via Caddy on Blackbox (port 41933). It handles task management, agent health visibility, repo documentation, and system topology. It is well-engineered for what it does.

Paperclip's dashboard (`ui/` — React + Tailwind + shadcn/ui) is a full operator control plane: live agent run transcripts, multi-scope budget management, typed approval inbox, 14-day activity charts, cost attribution, real-time streaming, and a plugin slot architecture.

The gap is substantial but not architectural — Factory's portal already has the right deployment model (self-hosted, auth-gated, agent-status polling). The missing surface areas are: **approval workflow UI**, **live agent run transcripts**, **budget/cost tracking UI**, **activity analytics**, and **agent control commands**.

**Approach:** Incremental additions to the existing portal. Do not rewrite. Do not migrate to React. Add focused pages/widgets in the existing vanilla JS + Input Sans stack, progressively enhancing toward Paperclip parity. React can be introduced selectively (as topology.html already does) for complex interactive components only.

---

## 2. Current State Inventory

### Factory Portal — What Exists

| Page | File | Size | Status |
|------|------|------|--------|
| Landing hub | portal.html | 7.9KB | Production |
| Mission Control (tasks) | dashboard-v4.html + runtime.js | 5.3KB + 22KB | Production |
| Repo Explorer | explainers-v4.html | 23KB | Production |
| System Topology | topology.html | 40KB | Production |
| Architecture Gallery | architecture-gallery.html | 34KB | Production |
| Documentation pages | 3 x HTML guides | 55-65KB each | Static |

**Tech stack:** Vanilla HTML/JS/CSS, Input Sans font, Caddy reverse proxy, Python GSD backend (port 41935), polling at 5s intervals, systemd services.

**Data sources:**
- `tasks.json` — task CRUD via GET/PUT
- `status/{agent}.json` — agent health (read-only)
- `index.json` — generated repo manifest

**What works well:** task management, dependency tracking, agent health sidebar, keyboard-driven repo explorer, topology diagram.

### Paperclip Dashboard — Feature Inventory

**Navigation:** CompanyRail + Sidebar + Breadcrumbs + CommandPalette (Cmd+K) + mobile swipe gestures

**Dashboard view:**
- 4 metric cards: Agents Enabled, Tasks In Progress, Month Spend, Pending Approvals
- Budget incident alert (red gradient, active incident count, paused agent/project counts)
- 4 activity charts: Run Activity (14d stacked bars), Issues by Priority, Issues by Status, Success Rate
- Active agent run cards (up to 4, 320px fixed height, live streaming transcript)
- Recent Activity feed (10 items, animated entry)
- Recent Tasks list (10 items, priority + status icons)
- Plugin slot (dashboardWidget type, 2-col grid)

**Approval inbox (`/approvals`):** typed approval queue, operator approve/reject, per-type display

**Costs page (`/costs`, 49KB):** spend by biller, by provider model, by agent model; budget policy cards per scope; finance timeline; quota bars

**Agent detail (`/agents/{id}`, 111KB):** per-agent config, run history, budget marker in sidebar, live run widget, transcript streaming, config revision history

**Live run widget:** streaming transcript (compact density, 8 entries), stop button, run status, 3s poll

**Budget policy card:** dual-column (observed + limit), progress bar (emerald/amber/red), pause state alert, inline edit (USD input), soft warn % + hard stop %, per scope (agent/project/company)

---

## 3. Gap Analysis

| Feature | Factory Portal | Paperclip | Gap |
|---------|---------------|-----------|-----|
| Task management | Full CRUD, deps, assignee | Issues + kanban | Equivalent |
| Agent health status | Sidebar, 5s poll | Status badges + run cards | Factory: no run cards |
| Live agent transcripts | None | Streaming, compact, 8 entries | Critical gap |
| Approval workflow UI | None | Typed inbox, approve/reject | Critical gap |
| Budget tracking UI | None | Per-scope, progress bars, pause cascade | Critical gap |
| Activity charts | None | 4 charts, 14d window | High priority |
| Metric cards | Agent count only | 4 cards (agents, tasks, spend, approvals) | High priority |
| Cost attribution | None | By biller, model, agent | Medium priority |
| Agent control (stop/restart) | None | Stop run, pause agent | Medium priority |
| Command palette | None | Cmd+K | Low priority |
| Plugin slots | None | dashboardWidget type | Low priority |
| Mobile swipe nav | Bottom nav | Swipe gestures | Equivalent |
| Dark theme | Input Sans dark | Tailwind dark mode | Equivalent |

---

## 4. Roadmap — Incremental to Paperclip Parity

### Phase 1 — Critical Gaps (Weeks 1-2)

**P1.1: Approval Inbox Page (`approvals.html`)**

New page surfacing Factory's typed approval gates. Polls `coordinator-rs` approval API (or approval JSON files from `~/.config/coordinator/approvals/`).

UI elements:
- Pending approvals list with gate type badge (TradingExecution, LoopSpecDeploy, BudgetOverride, AgentElevation, ToolCall)
- Per-approval card: agent name, gate type, payload summary, requested timestamp, timeout countdown
- Approve / Reject buttons — POST to coordinator approval endpoint
- Resolved approvals history (last 20, collapsible)
- Red alert badge on portal.html landing card when pending count > 0

Data source: `GET /approvals/pending` returns array of `{id, gate_type, agent_id, payload, requested_at, timeout_ms}`

**P1.2: Live Agent Run Cards (`dashboard-v4.html` enhancement)**

Add `ActiveAgentsPanel` equivalent to the Mission Control dashboard. Below the metric cards row, above the task list.

UI elements:
- Up to 4 agent run cards (320px height, fixed)
- Per card: agent name, status dot (ping animation if active), "Live now" / "Finished Xm ago"
- Compact transcript: last 5 log lines, monospace, scrollable
- Active card styling: cyan border + subtle cyan glow (matching Paperclip's aesthetic)
- Stop button (red) if run is active

Data source: `GET /status/{agent}.json` enhanced to include `current_run: {id, started_at, status, transcript_tail[]}` — coordinator-rs writes this on each heartbeat.

**P1.3: Budget Status Panel (`budget.html` or sidebar widget)**

New page (or expandable sidebar panel) for per-agent budget status.

UI elements:
- Per-agent budget card: agent name, monthly limit, spent this month, utilization progress bar
- Color-coded: green (<80%), amber (80-99%), red (100% / paused)
- Pause indicator: red banner "Agent paused — budget exhausted"
- Override button: triggers approval request to coordinator
- Company-level total spend row at top

Data source: `GET /budget/status` returns `{agents: [{id, name, monthly_limit_usd, spent_usd, status}]}`

---

### Phase 2 — High Priority (Weeks 3-4)

**P2.1: Dashboard Metric Cards**

Add 4-card metric row to `dashboard-v4.html` above existing task list.

Cards:
1. **Agents Active** — count of non-paused, non-error agents. Link to topology.html
2. **Tasks In Progress** — count from tasks.json where status=in-progress. Link to task list
3. **Month Spend** — sum from budget API. Link to budget.html
4. **Pending Approvals** — count from approvals API. Link to approvals.html. Red badge if >0.

Implementation: vanilla JS, fetch from existing + new endpoints, render into 4-col CSS grid.

**P2.2: Activity Charts Page (`analytics.html`)**

New page with 4 chart panels matching Paperclip's 14-day charts.

Charts (using Chart.js via CDN):
1. **Run Activity** — stacked bar: succeeded (emerald), failed (red), other (neutral). X: last 14 days
2. **Tasks by Status** — stacked bar: todo, in-progress, done, blocked. By creation date
3. **Tasks by Assignee** — pie or bar: Boot, IG-88, Kelk, Nan, Unassigned
4. **Approval Rate** — percentage bar: approved vs rejected vs timed-out

Data source: `GET /analytics/summary?days=14` — coordinator-rs or a Python aggregation script reading from activity logs.

---

### Phase 3 — Medium Priority (Weeks 5-6)

**P3.1: Agent Detail Pages (`agent/{name}.html`)**

Per-agent pages linked from topology.html and the agent status sidebar.

Sections:
- Agent identity (name, model, trust level, soul file link)
- Current status (active/idle/paused/error)
- Budget card (same as P1.3 component, scoped to this agent)
- Run history (last 10 runs, status, duration, task title)
- Full transcript viewer for selected run (scrollable, monospace)
- Config: model, context window, assigned timers

**P3.2: Agent Control Panel**

Add control actions to agent detail pages and the Mission Control sidebar.

Actions:
- **Pause agent** — POST to coordinator, sets agent status to paused
- **Resume agent** — POST to coordinator, clears pause
- **Trigger heartbeat** — POST to coordinator, fires immediate task check
- **Cancel active run** — POST to coordinator, sets run status to cancelled

Requires coordinator-rs to expose a simple HTTP control API (or Matrix command bridge).

---

### Phase 4 — Polish (Week 7+)

**P4.1: Portal Landing Refresh**

Update `portal.html` with:
- Live metric badges on each card (agent count, pending approval count, budget status)
- Last-updated timestamp
- Red alert overlay on Approvals card when pending > 0

**P4.2: Command Palette**

Add Cmd+K global search across: tasks, agents, approvals, docs.
Vanilla JS implementation, overlay modal, keyboard navigation.
Data: union of tasks.json + index.json + static page list.

**P4.3: WebSocket Real-Time**

Replace 5s polling with WebSocket push from coordinator-rs (or a lightweight Python broadcaster).
Reduces perceived latency for approval inbox and live run transcripts.
Low engineering priority — polling is adequate for current scale.

---

## 5. Backend Requirements

Each portal phase requires coordinator-rs (or a thin Python sidecar) to expose new endpoints:

| Endpoint | Phase | Source |
|----------|-------|--------|
| `GET /approvals/pending` | P1.1 | coordinator-rs approval files |
| `POST /approvals/{id}/decide` | P1.1 | coordinator-rs HMAC approval |
| `GET /status/{agent}.json` (enhanced with transcript_tail) | P1.2 | coordinator-rs writes on heartbeat |
| `GET /budget/status` | P1.3 | budget.rs (FCT004 borrow #3) |
| `GET /analytics/summary?days=N` | P2.2 | Python aggregator or coordinator-rs |
| `POST /agents/{id}/pause` | P3.2 | coordinator-rs lifecycle |
| `POST /agents/{id}/resume` | P3.2 | coordinator-rs lifecycle |
| `POST /agents/{id}/heartbeat` | P3.2 | coordinator-rs dispatch |
| `POST /runs/{id}/cancel` | P3.2 | coordinator-rs run management |

Note: P1.1 and P1.3 are directly enabled by FCT004's `budget.rs` and typed `ApprovalGateType` implementations. The portal UI and coordinator-rs backend work can proceed in parallel.

---

## 6. Implementation Notes

**Tech choices:**
- Keep vanilla JS for all Phase 1-2 work. No new framework dependencies.
- Chart.js (CDN, ~200KB gzip) for analytics charts — already common in vanilla JS dashboards.
- Introduce React only for Phase 3 agent detail pages if transcript streaming complexity demands it (as topology.html already does).
- Maintain Input Sans as primary font — do not introduce Tailwind or new CSS frameworks.
- Approval inbox polling: 3s interval (matching coordinator-rs POLL_INTERVAL_MS).
- Budget polling: 10s interval (matching timer.rs cadence).

**Styling direction:**
- Match existing portal dark theme (CSS custom properties already established).
- Adopt Paperclip's status color semantics: emerald (healthy), amber (warning), red (error/paused), cyan (active/live).
- Active run cards: `border: 1px solid rgba(6,182,212,0.25); box-shadow: 0 16px 40px rgba(6,182,212,0.08)` — matches Paperclip's live run aesthetic.

**Deployment:**
- New pages added to `portal/pages/` directory.
- `portal.html` updated with new card links.
- `Makefile` rsync targets updated to include new pages.
- `serve.sh` Caddy config unchanged — static files served automatically.

---

## 7. Success Metrics

After Phase 1 (critical gaps closed):
- Operator can approve/reject `TradingExecution` and `LoopSpecDeploy` gates from the portal without touching Element or the filesystem
- Live transcript tail visible for all 4 active agents on the Mission Control dashboard
- IG-88 budget status visible with utilization bar and pause indicator

After Phase 2 (high priority):
- 4 metric cards on dashboard load in <500ms
- 14-day activity chart renders from coordinator analytics endpoint
- Pending approval count visible on portal landing page

After Phase 3 (full parity):
- Per-agent detail pages accessible from topology view
- Agent pause/resume operable from portal (no SSH required)
- Factory portal UX is functionally equivalent to Paperclip's operator dashboard

---

## References

[1] FCT004, "Paperclip vs Factory — Architecture Study and Adoption Assessment," 2026-03-17.
[2] FCT005, "Hermes Agent — Fit Assessment for Paperclip x Factory Workflow," 2026-03-17.
[3] Factory Portal source, ~/dev/factory/portal/. Accessed 2026-03-17.
[4] Paperclip UI source, github.com/paperclipai/paperclip/tree/master/ui. Accessed 2026-03-17.

---

## Appendix A — React Migration Path

### Rationale

The portal's destination is a full operator control plane with complex interactive state: live transcript streaming, approval workflows, multi-scope budget management, real-time chart updates. This is the exact problem React solves. However, the codebase currently has no build toolchain, no npm, no bundler. A wholesale migration today means rewriting working code before the new features exist.

**The pragmatic path: hybrid portal during Phase 1–2, then unified React codebase by Phase 3+.**

This approach:
- Ships new features in React immediately (approvals, run cards, budget pages get React UX from day one)
- Preserves working vanilla JS pages (dashboard-v4, explainers, topology continue as-is)
- Avoids the "rewrite cost" trap (you're not rebuilding old code, building new features in better framework)
- Naturally completes the migration as old pages are superseded

### Implementation Strategy

**Immediate (before Phase 1):**

1. **Scaffold Vite + React project** in `portal/src/`
   - `npm init vite@latest . -- --template react`
   - `npm install`
   - TypeScript (optional but recommended for approval/budget complexity)
   - Tailwind + shadcn/ui (matches Paperclip aesthetics, optional but recommended)
   - eslint + prettier

2. **Configure build output**
   - Vite outputs to `portal/pages/` (where static files are served)
   - Makefile updated with `npm run build` step in deployment target
   - Keep Input Sans font loading in index.html or CSS

3. **Create React entry points** for new pages
   - `src/pages/Approvals.tsx`
   - `src/pages/Budget.tsx`
   - `src/pages/Analytics.tsx`
   - `src/pages/AgentDetail.tsx`
   - Each bundled as a separate chunk or single SPA, served as `approvals.html`, `budget.html`, etc.

4. **Shared state/hooks**
   - `hooks/useApprovals.ts` — fetch + polling logic for `/approvals/pending`
   - `hooks/useBudget.ts` — fetch + polling logic for `/budget/status`
   - `hooks/useAgents.ts` — fetch + polling logic for `/status/{agent}.json`
   - `lib/api.ts` — axios/fetch wrapper with error handling

**Phase 1–2 (hybrid state):**

- Portal landing page: still vanilla HTML (`portal.html`)
- Mission Control dashboard: still vanilla JS (`dashboard-v4.html`, enhanced but not rewritten)
- Topology, architecture gallery: still vanilla/React-in-HTML (`topology.html`, unchanged)
- **Approvals page:** React component, linked from portal.html
- **Budget page:** React component, linked from portal.html
- **Analytics page:** React component, linked from portal.html

**Phase 3–4 (unification):**

- Backfill old pages into React as needed
- Approval/budget/analytics experience stabilizes → apply patterns to agent detail pages
- Eventually migrate dashboard-v4 to React for consistency
- Final state: single Vite build, all pages React components, consistent UX

### Tech Stack Choices

**Build:**
- **Vite** — fast dev server, minimal config, outputs optimized SPA bundles
- **React 18** — core framework
- **TypeScript** — optional but recommended for approval/budget state complexity
- **Tailwind CSS** — style consistency with Paperclip's design (not required, can extend Input Sans CSS)
- **shadcn/ui** — component library, works on Tailwind, ships only what you use
- **React Query / TanStack Query** — handles polling, caching, refetching of approval/budget/agent data
- **Zod or React Hook Form** — validation for approval decision forms, budget overrides

**Styling:**
- Extend Input Sans font loading to Vite build
- Keep existing CSS custom properties (dark mode variables, spacing scale)
- OR: adopt Tailwind for React pages, vanilla CSS for legacy pages (temporary inconsistency, acceptable during Phase 1–2)

**API communication:**
- Fetch or axios in React hooks
- Mirror the polling intervals: 3s for approvals, 10s for budget, 5s for agent status
- Graceful error states, offline fallback (retry with backoff)

### Deployment Changes

**Makefile additions:**
```makefile
build-portal:
	cd portal && npm run build

deploy-portal: build-portal
	# rsync new portal/dist/ to Blackbox
	# restart Caddy service
```

**Caddy configuration (serve.sh):**
- No changes — Vite outputs static files to `portal/pages/`, Caddy serves them as-is
- SPA routing: if you use React Router, configure Caddy to rewrite 404s to `index.html`

**Systemd service:**
- No changes — portal and GSD backend continue to run as services

### Fallback Plan

If React migration proves slower than expected:
- Stick with vanilla JS + Chart.js for Phase 1–2 (still ships features on schedule)
- Migrate to React in Phase 3 or later
- The hybrid state is stable — you can ship a working portal with vanilla + React pages indefinitely

### Success Criteria

- Phase 1 approvals/budget/run-cards ship in React with streaming updates and complex state management
- No build complexity leaks into ops — `npm run build` is the only build step, rest is unchanged
- Old vanilla pages continue to work without modification
- Deployment time increases by <5min (npm install + build)


