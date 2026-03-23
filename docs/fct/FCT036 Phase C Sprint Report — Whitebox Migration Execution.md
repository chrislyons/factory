# FCT036 Phase C Sprint Report — Whitebox Migration Execution

**Session:** FCT033 Session 3 of 4
**Date:** 2026-03-23
**Duration:** ~90 minutes
**Objective:** Migrate all factory services from Blackbox (RP5) to Whitebox (Mac Mini)

## Summary

Successfully migrated 10 of 12 planned launchd services to Whitebox. Coordinator-rs running, sending startup messages to Matrix. Portal live and accessible. MCP proxies operational. MLX-LM inference on dedicated ports.

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
- [x] mcp-env.sh patched with absolute paths (`/opt/homebrew/bin/bws`, `/opt/homebrew/bin/python3`, `/usr/bin/security`) for launchd compatibility
- [x] Hardcoded `/home/nesbitt` paths fixed to `/Users/nesbitt`
- [x] Both serving on :8446 (projects-vault) and :8447 (research-vault)
- [x] Embedding model: `sentence-transformers/all-MiniLM-L6-v2` (matches existing Qdrant collections)

### TIER 2 — Matrix MCP (DEFERRED)
- [ ] **Deferred by user decision** — matrix-mcp requires `MATRIX_PASSWORD` (password-based login), and Matrix account passwords are intentionally kept out of BWS for security
- Plists created and deployed to Whitebox for future manual `.env` setup
- Not a blocker — coordinator handles all Matrix comms directly

### TIER 3 — Coordinator-rs
- [x] Source synced from Cloudkicker (Whitebox git has no GitHub SSH key)
- [x] Built in release mode (22s incremental)
- [x] Config updated: trust_level, multi_agent_stagger, delegate, lifecycle, timer settings
- [x] `MATRIX_TOKEN_COORD_PAN` → `MATRIX_TOKEN_PAN_COORD` in coordinator.rs (consistent with BWS kebab-case convention)
- [x] Running: 3 agents, 13 rooms, startup message sent to Matrix Status room
- [x] Expected errors: "Failed to spawn Claude" — claude CLI not installed on Whitebox (agents dispatch to Cloudkicker)

### TIER 4 — Portal Stack (3 plists)
- [x] Portal Caddy running on :41910
- [x] GSD sidecar on :41911
- [x] Factory-auth on :41914 (with bcrypt venv)
- [x] dist-production copied from Blackbox
- [x] jobs.json, repos/, index.json copied
- [x] Caddyfile updated: Blackbox IP → Whitebox, Linux paths → macOS
- [x] macOS firewall rule added for Caddy (user action)
- [x] Portal accessible from Cloudkicker: `http://100.88.222.111:41910` (302 → login)

### Post-Migration
- [x] `~/.mcp.json` on Cloudkicker updated: all 4 MCP URLs → Whitebox IPs

## Service Status (Final)

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

## Issues Encountered & Resolved

1. **mcp-env.sh PATH issue** — launchd doesn't inherit Homebrew PATH. Fixed with absolute paths for `bws`, `python3`, `security`
2. **Linux venvs on macOS** — Blackbox venvs copied but non-functional. Recreated fresh
3. **Hardcoded `/home/nesbitt` paths** — in qdrant-daemon.py `cache_dir`. Patched to `/Users/nesbitt`
4. **HuggingFace cache dir missing** — MLX-LM `/v1/models` returned empty. Created `~/.cache/huggingface/hub/`
5. **Coordinator config drift** — Whitebox source was stale (no GitHub SSH key for git pull). Manually scp'd all source files
6. **Missing config fields** — `multi_agent_stagger_ms`, `delegate_timeout_ms`, `trust_level` required by coordinator but absent from config. Added from Blackbox reference
7. **Env var naming** — Coordinator had `MATRIX_TOKEN_COORD_PAN` hardcoded; fixed to `MATRIX_TOKEN_PAN_COORD` matching BWS convention
8. **auth.py bcrypt** — System Python on Whitebox is managed (PEP 668). Created `.auth-venv` with bcrypt
9. **`--permission-mode delegate`** — unsupported in Claude Code 2.1.79. Changed to `auto`
10. **`claude` CLI not found** — launchd PATH didn't include `/opt/homebrew/bin`. Added `PATH` to coordinator plist EnvironmentVariables
11. **ANTHROPIC_API_KEY missing** — Claude CLI exited immediately. Added API key UUID to BWS injection list in coordinator plist
12. **macOS firewall** — blocked Tailscale inbound to Caddy. User added firewall allow rule for `/opt/homebrew/bin/caddy`

## Late-Session Wins

- **Blackbox coordinator stopped and disabled** (`systemctl stop && disable matrix-coordinator`)
- **Boot responding in Element DMs** — Claude initialized on Whitebox, near-zero latency
- All 3 agents session-initialized; Boot confirmed live with haiku model

## Remaining for Session 4

- [x] ~~Stop Blackbox coordinator~~ (done — disabled)
- [x] ~~Install Claude CLI on Whitebox~~ (was already installed)
- [ ] Verify all 3 agent devices in Element (cross-signing)
- [ ] `~/projects/ig88/` worker_cwd — should not exist on Whitebox; update room config cwds
- [ ] Set up matrix-mcp with manual `.env` when ready (Matrix passwords kept out of BWS by design)
- [ ] Graphiti secret rotation via Docker Compose (running with 3-day-old secrets)
- [ ] Degradation testing (kill/restart individual services)
- [ ] Set up GitHub SSH key on Whitebox for direct git operations
- [ ] BWS snake_case audit (check `graphiti_auth_token`, `qdrant_api_key`)
- [ ] Jupiter connectivity test (B5 — IG-88 Training room)

## Commits

- `157e5ac` fix(coordinator): auto permission mode, PATH in plist, API key injection
- `8b5b77e` docs(fct): FCT036 Phase C sprint report
- `d4197cd` feat(infra): Whitebox migration — 12 launchd plists, config updates
- `1b5878f` (ig88 submodule) feat(config): migrate agent-config to Whitebox

## References

- [1] FCT033 Definitive Execution Plan
- [2] FCT034 Phase A Sprint Report
- [3] FCT035 Phase B Sprint Report
