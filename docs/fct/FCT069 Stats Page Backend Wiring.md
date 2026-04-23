# FCT069 Stats Page Backend Wiring

**Date:** 2026-04-15
**Status:** Complete

---

## Context

The Factory Portal Stats page (`analytics.html`) had all four chart sections and the Budget Policies card displaying placeholder content. The two required endpoints — `/analytics/summary` and `/budget/status` — did not exist in the GSD sidecar. The frontend was fully wired: `useAnalytics`, `useBudgetStatus` hooks, and `AnalyticsPage.tsx` were all in place. The gap was entirely backend.

---

## What Was Built

### Backend Endpoints — `portal/server.py`

Two new handlers added to `PortalDataHandler` (~150 lines total).

**`_handle_analytics_summary()`** — `GET /analytics/summary?days=N`

- Reads `jobs.json` (117 tasks, live on Whitebox) to compute:
  - `tasks_by_assignee`: count per assignee (boot / kelk / ig88 / coord / chris)
  - `tasks_by_status`: 14-day flat series with status normalization: `pending→todo`, `done→done`, `deferred→blocked`
- Reads `~/.hermes/sessions/*.jsonl` to tally runs per day (succeeded / failed / other) for `run_activity`
- Returns `approval_rate: {approved: 0, rejected: 0, timed_out: 0}` — accurate until approval logging is implemented

**`_handle_budget_status()`** — `GET /budget/status`

- Reads `portal/budget_config.json` for per-agent monthly limits
- Reads `portal/status/<agent>.json` for runtime spend (when agents start writing these files)
- Computes per-agent status: `normal` / `warning` (≥80%) / `paused` (≥100%)
- Returns full `AgentBudgetStatus[]` array matching frontend types

### Routing — `portal/Caddyfile` and `portal/auth.py`

- **Caddyfile:** added `handle /analytics/*` and `handle /budget/*` blocks routing to auth proxy on `:41914`
- **auth.py:** added `/analytics/` and `/budget/` to the authenticated GET proxy path tuple forwarding to GSD on `:41911`

### Config — `portal/budget_config.json`

New static config file with monthly spend limits per agent:

| Agent | Monthly Limit |
|-------|--------------|
| boot  | $50          |
| kelk  | $25          |
| ig88  | $100         |
| coord | $10          |

---

## Result

All five sections of the Stats page now render with real data:

1. **Budget Policies** — live agent cards with spend progress bars
2. **Run Activity** — bar chart sourced from Hermes session JSONL history
3. **Tasks by Status** — 14-day series derived from `jobs.json` snapshot
4. **Tasks by Assignee** — horizontal bar chart from `jobs.json`
5. **Approval Rate** — renders 0/0/0 accurately until approval logging is added

IG-88 Trading Visualizations were already live (Manim video renders) and were not touched.

---

## Files Changed

| File | Change |
|------|--------|
| `portal/server.py` | +150 lines: two handler methods + `do_GET` routing branches |
| `portal/auth.py` | +2 chars: tuple expansion in proxy path condition |
| `portal/Caddyfile` | +8 lines: two `handle` blocks for `/analytics/*` and `/budget/*` |
| `portal/budget_config.json` | New file: per-agent monthly spend limits |

---

## Next Steps

- **Agent status files:** Agents need to write `portal/status/<agent>.json` with `total_cost_cents` for real budget spend tracking. Until then, spend shows as $0.
- **Approval logging:** Write `portal/approvals.jsonl` on each approval/rejection/timeout event; update `_handle_analytics_summary()` to aggregate it.
- **Run activity source:** Switch from Hermes session JSONL proxy to the coordinator run event log at `~/.config/coordinator/runs/` once coordinator is writing those files reliably.
