# FCT036 Phase C Sprint Report — Whitebox Migration Execution

> **Note (2026-03-31):** Port assignments documented in this report (41960–41963 for Nanbeige/Qwen4B/LFM/Qwen9B) are superseded by the 2026-03-31 re-plumb sprint. Current assignments: Boot→41961, Kelk→41962, Nan→41963, IG-88→41988, Reasoning→41966, Coordinator reserved→41960. See FCT002 section 2.3 for the authoritative port table.

**Session:** FCT033 Session 3 of 4
**Date:** 2026-03-23
**Duration:** ~3 hours
**Objective:** Migrate all factory services from Blackbox (RP5) to Whitebox (Mac Mini)

## Summary

Successfully migrated 10 of 12 planned launchd services to Whitebox. All 3 agents (Boot, Kelk, IG-88) responding to DMs and room mentions. Portal live. MCP proxies operational. MLX-LM inference on dedicated ports. Blackbox coordinator stopped and disabled.

## Completed

### TIER 0 — Prerequisites
- [x] Log directory created (`~/Library/Logs/factory/`)
- [x] Rust 1.94.0 installed on Whitebox
- [x] Caddy 2.11.2 installed via Homebrew
- [x] MLX-LM stale processes killed (were zombie-bound on 8080-8083)

### TIER 1 — MLX-LM Inference (4 plists)
- [x] Ports changed: 8080-8083 → **41960-41963** (factory port scheme)
- [x] All 4 models loaded and serving: Nanbeige4.1-3B, Qwen3.5-4B, LFM2.5-1.2B-Thinking, Qwen3.5-9B
- [x] Chat completions verified working
- [x] HuggingFace cache dir created (fixed `/v1/models` endpoint)

### TIER 1 — MCP Proxies (2 plists)
- [x] qdrant-mcp and research-mcp copied from Blackbox
- [x] Fresh macOS venvs created (Linux venvs incompatible)
- [x] Dependencies installed: qdrant-client, fastembed, mcp[cli]
- [x] mcp-env.sh patched with absolute paths for launchd compatibility
- [x] Hardcoded `/home/nesbitt` paths fixed to `/Users/nesbitt`
- [x] Both serving on :8446 (projects-vault) and :8447 (research-vault)

### TIER 2 — Matrix MCP (DEFERRED)
- **Deferred by user decision** — matrix-mcp requires `MATRIX_PASSWORD` (password-based login), and Matrix account passwords are intentionally kept out of BWS for security
- Plists created and deployed to Whitebox for future manual `.env` setup

### TIER 3 — Coordinator-rs
- [x] Source synced from Cloudkicker (Whitebox git has no GitHub SSH key)
- [x] Built in release mode, rebuilt 3x for iterative fixes
- [x] Config updated: trust_level, multi_agent_stagger, delegate, lifecycle, timer, mention_aliases
- [x] `MATRIX_TOKEN_PAN_COORD` env var naming fixed (consistent with BWS convention)
- [x] `--permission-mode delegate` → `auto` (delegate unsupported in Claude 2.1.79)
- [x] PATH added to plist EnvironmentVariables for `/opt/homebrew/bin` discovery
- [x] ANTHROPIC_API_KEY added to BWS injection list
- [x] DM routing fixed: was hardcoded to Boot only (`get_dm_agent` Phase 1 stub)
- [x] ig88 mention_aliases added: `ig-88`, `iggy`
- [x] ig88 added to Backrooms `agents` list
- [x] Running: 3 agents, 13 rooms, all responding to DMs and room mentions

### TIER 4 — Portal Stack (3 plists)
- [x] Portal Caddy running on :41910
- [x] GSD sidecar on :41911
- [x] Factory-auth on :41914 (with `.auth-venv` for bcrypt)
- [x] dist-production, jobs.json, repos/, index.json copied from Blackbox
- [x] Caddyfile updated: Blackbox IP → Whitebox, Linux paths → macOS
- [x] macOS firewall rule added for Caddy (user action)
- [x] Portal accessible from Cloudkicker

### Cross-Signing
- [x] Cross-sign toolkit migrated from blackbox to `factory/scripts/matrix-cross-sign/`
- [x] All Blackbox references updated to Whitebox (panctl, pan.db path, systemd → launchd)
- [x] Credential helpers updated for BWS env vars (no more plaintext token files)
- [x] All 4 accounts cross-signed: boot, ig88, kelk, coord
- [x] Coord Pan token rotated after cross-sign tool invalidated it
- [x] Stale sync tokens deleted (`~/.config/ig88/sync-tokens.json`)
- [x] `thedotmack/claude-mem` plugin removed from Whitebox (was blocking Claude init)

### Post-Migration
- [x] `~/.mcp.json` on Cloudkicker updated: all 4 MCP URLs → Whitebox IPs
- [x] Blackbox coordinator stopped and disabled

## Service Status (End of Session)

| Service | Port | Status | Plist |
|---------|------|--------|-------|
| MLX-LM Nanbeige 3B | :41960 | Running | mlx-lm-41960 |
| MLX-LM Qwen 4B | :41961 | Running | mlx-lm-41961 |
| MLX-LM LFM Thinking | :41962 | Running | mlx-lm-41962 |
| MLX-LM Qwen 9B | :41963 | Running | mlx-lm-41963 |
| Qdrant MCP | :8446 | Running | qdrant-mcp |
| Research MCP | :8447 | Running | research-mcp |
| Matrix MCP Boot | :8445 | **Deferred** | matrix-mcp-boot |
| Matrix MCP Coord | :8448 | **Deferred** | matrix-mcp-coord |
| Coordinator-rs | — | Running | coordinator-rs |
| Factory Auth | :41914 | Running | factory-auth |
| GSD Sidecar | :41911 | Running | gsd-sidecar |
| Portal Caddy | :41910 | Running | portal-caddy |

## Agent Status (End of Session)

| Agent | DMs | Room Mentions | Room Default | Claude Init |
|-------|-----|---------------|--------------|-------------|
| Boot | Working | Working | Backrooms default | Confirmed |
| Kelk | Working | Working (@kelk) | — | Confirmed |
| IG-88 | Working | Working (@ig88, @iggy) | IG-88 Training default | Confirmed |

## Issues Encountered & Resolved

1. **mcp-env.sh PATH** — launchd doesn't inherit Homebrew PATH. Fixed with absolute paths for `bws`, `python3`, `security`
2. **Linux venvs on macOS** — Blackbox venvs non-functional. Recreated fresh
3. **Hardcoded `/home/nesbitt` paths** — in qdrant-daemon.py. Patched to `/Users/nesbitt`
4. **HuggingFace cache dir missing** — Created `~/.cache/huggingface/hub/`
5. **Coordinator source drift** — No GitHub SSH key on Whitebox. Manually scp'd all source files
6. **Missing config fields** — `multi_agent_stagger_ms`, `delegate_timeout_ms`, `trust_level`. Added from Blackbox reference
7. **Env var naming** — `MATRIX_TOKEN_COORD_PAN` → `MATRIX_TOKEN_PAN_COORD` (BWS convention)
8. **auth.py bcrypt** — PEP 668 managed Python. Created `.auth-venv`
9. **`--permission-mode delegate`** — Unsupported in Claude 2.1.79. Changed to `auto`
10. **`claude` CLI not found** — Added `PATH` to coordinator plist
11. **ANTHROPIC_API_KEY missing** — Added to BWS injection list
12. **macOS firewall** — User added Caddy allow rule
13. **Cross-sign token invalidation** — Coord Pan token invalidated by cross-sign tool logout. Rotated in BWS.
14. **Stale sync tokens** — Old Blackbox Pantalaimon sync cursors. Deleted `sync-tokens.json`.
15. **`thedotmack/claude-mem` plugin** — Blocking Claude init on all agents. Removed from `known_marketplaces.json` and filesystem.
16. **DM routing hardcoded to Boot** — `get_dm_agent()` was a Phase 1 stub returning only `["boot"]`. Fixed to return all agents.
17. **panctl not functional** — PyGObject/GLib missing on Whitebox. Cross-signing works server-side without panctl.

## Known Issues (Carry Forward)

### `coord sync failed: sync request failed`
The coordinator's own sync (used for approval room reactions) fails intermittently. Does NOT affect agent DM/room routing — those use per-agent sync loops. Likely a Pantalaimon session issue with the coord account. Low priority.

### Agent Identity Confusion in Shared Rooms
When multiple agents are in a room (Backrooms), they confuse each other's identities. Boot responded as "Kelk" and vice versa. Root cause: agents see each other's messages but system prompts don't strongly anchor identity. Needs stronger identity reinforcement in system prompts and/or context injection architecture.

### Conversational Room Behavior Not Implemented
Current architecture: agents only respond when explicitly tagged or are the room's default agent. Desired: agents read all messages in shared rooms and use judgment about when to contribute (ambient listening + selective response). This requires:
1. Room history context injection into each agent's Claude session
2. A "should I respond?" decision layer
3. Stronger identity boundaries in system prompts

### `worker_cwd` Paths Stale
Room configs reference `~/projects/ig88/` which is a Blackbox path. On Whitebox this dir is nearly empty. Needs updating to appropriate Whitebox paths.

## Commits

- `a63297d` fix(config): ig88 aliases + Backrooms membership
- `ec0f78b` fix(coordinator): route DMs to all agents, not just Boot
- `711cef3` feat(scripts): migrate matrix cross-sign toolkit from blackbox
- `157e5ac` fix(coordinator): auto permission mode, PATH in plist, API key injection
- `8b5b77e` docs(fct): FCT036 Phase C sprint report (initial)
- `d4197cd` feat(infra): Whitebox migration — 12 launchd plists, config updates
- `1b5878f` (ig88 submodule) feat(config): migrate agent-config to Whitebox

## References

- [1] FCT033 Definitive Execution Plan
- [2] FCT034 Phase A Sprint Report
- [3] FCT035 Phase B Sprint Report
