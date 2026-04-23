# FCT069 Portal Memory Budget Guard and Safe Restart Gate

**Date:** 2026-04-15 | **Ref:** portal/config_api.py, ConfigPage.tsx

---

## Problem

Whitebox (M1 Max, 32GB) runs three inference servers simultaneously:
- :41961 MLX-VLM E4B (Boot) — ~7.3GB RSS
- :41962 MLX-VLM E4B (Kelk) — ~7.3GB RSS
- :41966 Flash-MoE 26B-A4B (shared aux) — ~3GB RSS

Total inference footprint: ~17.5GB on a 32GB machine with ~4GB free.
The `factory-startup.sh` script staggers model loads to avoid OOM, but
Portal-initiated restarts (`launchctl stop` + `start`) bypass this phasing.
A restart without stopping the old model first would attempt to load a second
copy, instantly OOM-ing the machine.

## Solution

### Backend (config_api.py)

**`check_memory_budget()`** — Live memory query using `sysctl -n hw.memsize`
and `top` output parsing (no psutil dependency). Returns per-agent model
status, estimated RSS, and system available memory.

**`restart_gateway_safe()`** — Pre-flight restart with:
1. Concurrent restart lock (5s cooldown)
2. Inference server health gate (refuses restart if model is down)
3. Memory budget check (blocks if <50% of model's estimated RSS is free)
4. Force-restart override (`force=True` bypasses memory check)
5. Post-restart gateway verification

**`GET /api/config/memory-budget`** — Frontend endpoint.

### Frontend (ConfigPage.tsx)

**MemoryBar component** — 40px horizontal bar showing inference usage
(accent color) vs available memory. Red when <1GB free, yellow when <3GB.
Rendered under Terminal & Compression as "Local Memory Budget" subsection
with per-model detail rows (agent, port, est GB, loaded/idle status).

**Restart gate** — Button blocked when memory critical. Shows inline error
with "Force Restart" fallback when API returns `needs_force: true`.

### Model Memory Estimates

| Model | Est. RSS | Port |
|-------|----------|------|
| gemma-4-e4b-it-6bit | 7.3GB | :41961, :41962 |
| gemma-4-26b-a4b-it-6bit | 3.0GB | :41966 |
| xiaomi/mimo-v2-pro | 0GB | cloud |

### Key Design Decisions

- **sysctl over psutil** — No pip dependency, macOS-native
- **8s health check timeout** — MLX servers can be slow during active inference
- **5s memory budget timeout** — Avoids false "idle" readings on busy aux server
- **Force restart** — Explicit opt-in when operator knows it's safe (e.g., after
  manually stopping a model)
- **30s auto-refresh** — Budget data refreshes with agent configs

## CSS Variables (Portal Theme)

The portal uses specific CSS variable names that differ from common conventions:

| Portal Variable | Purpose | Do NOT use |
|-----------------|---------|------------|
| `--text` | Primary text | `--text-primary` |
| `--text-dim` | Secondary text | |
| `--text-muted` | Tertiary text | `--text-tertiary`, `--muted` |
| `--green` | Success state | `--success` |
| `--red` | Danger/error | `--danger` |
| `--yellow` | Warning | `--warning` |
| `--bg-panel` | Card background | `--surface-1`, `--surface-3` |
| `--bg-panel-strong` | Elevated background | `--surface-2` |
| `--accent` | Brand/accent | (correct) |
| `--border` | Default border | (correct) |

## Files Modified

- `portal/config_api.py` — Memory budget API, safe restart, timeouts
- `portal/src/lib/api.ts` — `fetchMemoryBudget()`, `MemoryBudget` type
- `portal/src/pages/ConfigPage.tsx` — MemoryBar, restart gate, budget subsection
- `portal/src/styles/app.css` — Memory bar, budget rows, restart error, dropdown fixes

## Related

- FCT067 — Factory Agent topology and E2EE migration
- `scripts/factory-startup.sh` — Phased startup (reference for memory budget)
- `infra/ports.csv` — Port allocation
