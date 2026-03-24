# FCT039 Phase D Sprint Report — Session 4 Stabilization and Blackbox Retirement

**Session:** FCT033 Session 4 of 4
**Date:** 2026-03-23
**Duration:** ~2 hours
**Objective:** Stabilize coordinator, retire Blackbox services, deploy RP5 watchdog, update documentation

## Summary

Completed Blackbox retirement, deployed RP5 watchdog, fixed agent sync performance (30s→3s timeout), fixed DM routing regression, added identity anchoring to all 3 agents, rotated Graphiti token, and updated all documentation. All 3 agents confirmed responding via Matrix.

## Completed

### 0.1 — Coordinator Env Var Fix
- [x] `MATRIX_TOKEN_COORD_PAN` → `MATRIX_TOKEN_PAN_COORD` in Cloudkicker source (parity fix)
- [x] File fallback path `matrix_token_coord_pan` → `matrix_token_pan_coord`
- [x] Whitebox source already had correct name from Session 3 — applied targeted fix via python3

### 0.2 — Agent Identity Anchoring
- [x] Added `identity_files` blocks (soul.md, principles.md, agents.md) to all 3 agents in agent-config.yaml
- [x] Added `default_cwd` per agent for identity file resolution
- [x] Prepended IDENTITY BOUNDARY block to all system prompts (placed FIRST per research findings)
- [x] Cross-agent awareness: each agent knows who the others are and their roles

### 0.3 — Conversational Room Behavior
- [x] **Design only** — Created FCT038 design spec (deferred implementation to future session)

### 0.4 — worker_cwd Fix
- [x] IG-88 Training room: `~/projects/ig88` → `~/dev/factory/agents/ig88`

### 0.5 — Jupiter Connectivity Test
- [x] IG-88 responds to DMs — confirmed agent→coordinator→Matrix chain works
- [ ] Jupiter MCP tools not yet wired to agent sessions (Phase C scope)

### 0.6 — Graphiti Secret Rotation
- [x] New token generated and stored via BWS web vault
- [x] Graphiti service restarted on Whitebox
- **Learning:** BWS machine account is read-only. Cannot `bws secret edit` from CLI. Must use web vault.

### Agent Sync Performance Fix (discovered during session)
- [x] Agent sync timeout changed from `None` (30s long-poll) to `Some(3000)` (3s)
- [x] Previous behavior: sequential 30s per agent = 90s+ per poll cycle = agents appeared unresponsive
- [x] New behavior: 3s per agent = ~9s per cycle = responsive

### DM Routing Fix (regression from SCP overwrite)
- [x] `get_dm_agent()` was reverted to Phase 1 stub (Boot only) when coordinator.rs was SCP'd from Cloudkicker
- [x] Fixed to return all agents
- **Learning:** Whitebox coordinator source diverges from Cloudkicker. Never blindly SCP coordinator.rs — apply targeted fixes via python3 on Whitebox.

### Part 1 — Blackbox Service Cleanup
- [x] Stopped and disabled: factory-portal, gsd-backend, factory-auth, qdrant-mcp, research-mcp
- [x] Caddy process killed (was still bound to :41910)
- [x] All ports verified clear

### Part 2 — BKX119 Cleanup
- [x] `/home/nesbitt/projects/ig88/` removed from Blackbox
- [x] Stale systemd refs found (Documentation= lines only, no active service configs)

### Part 3 — RP5 Watchdog
- [x] `watchdog.sh` written (~75 lines) and deployed to `/home/nesbitt/scripts/`
- [x] Checks: MLX-LM x4, Qdrant, Graphiti SSE, Pantalaimon TCP, Portal, coordinator log freshness
- [x] State in `~/.local/share/watchdog/` (survives reboots)
- [x] First-failure-only Matrix alerts with recovery messages to System Status room
- [x] Heartbeat file + alert log
- [x] Cron: `*/2 * * * *`
- [x] Known: Pantalaimon and coordinator-log checks require SSH from Blackbox→Whitebox (no key auth yet)

### Part 4 — Documentation
- [x] `factory/CLAUDE.md` — Port scheme updated to single Whitebox table, retirement note added
- [x] `blackbox/CLAUDE.md` — RETIRED banner, new architecture diagram, service table updated
- [x] `portal/Makefile` — BLACKBOX→WHITEBOX, paths, journalctl→launchctl
- [x] `FCT029` — Section 11: Blackbox and Pantalaimon decisions resolved
- [x] `FCT038` — Conversational room behavior design spec created
- [x] `MEMORY.md` — Updated with session learnings
- [x] Session handoffs doc updated

## Issues Encountered

1. **Whitebox source divergence** — SCP'd coordinator.rs from Cloudkicker, broke build (missing fields/functions in Whitebox's newer codebase). Had to revert and apply fixes directly on Whitebox.
2. **identity_files missing `agents` field** — Whitebox IdentityFiles struct requires soul, principles, AND agents. Initial config only had soul + principles.
3. **BWS read-only** — Spent 20 minutes trying `bws secret edit` before discovering machine account is read-only by design. Must use web vault.
4. **Agent sync 90s cycle** — 30s sequential long-poll per agent made agents appear dead. Changed to 3s timeout.
5. **DM routing regression** — SCP overwrite reverted `get_dm_agent()` to Phase 1 stub. Fixed.
6. **Blackbox Caddy not stopped by systemctl** — `factory-portal` service was disabled but Caddy process persisted. Required explicit kill.

## Known Issues (Carry Forward)

### coord sync failed
Still broken. Approval-room polling fails with "sync request failed" (network-level). Does NOT affect agent routing. Low priority — approvals can be done manually.

### Watchdog SSH checks
Pantalaimon TCP check and coordinator log freshness check require SSH from Blackbox→Whitebox. No key auth set up yet. These two checks will always alert until SSH keys are configured.

### Jupiter MCP not wired
IG-88 responds to DMs but has no Jupiter tools available. Requires MCP tool server configuration in agent sessions. Phase C scope.

### GitHub SSH key on Whitebox
Not set up. Still using SCP from Cloudkicker for source deployment.

### BWS kebab-case audit
Not run. Low priority.

## Commits

### factory repo
- `e06f3d0` feat(infra): FCT033 Session 4 — stabilization, Blackbox retirement, watchdog
- `21cd5b3` fix(watchdog): Pantalaimon check via SSH, StrictHostKeyChecking, Graphiti set -e fix

### blackbox repo
- `4943496` docs(bkx): mark Blackbox retired, fix coordinator env var name

## Whitebox Coordinator Changes (applied directly, not in git)

These changes were applied to Whitebox source via python3, not SCP'd from Cloudkicker:
- Agent sync timeout: `None` → `Some(3000)` in `poll_once()`
- DM routing: `get_dm_agent()` returns all agents
- Agent sync event count logging added
- Agent sync error level: `warn!` → `error!`
- `token_file` → `token_env` references fixed
- `config::read_token` → `std::fs::read_to_string` for coord file fallback

## References

- [1] FCT033 Definitive Execution Plan
- [2] FCT036 Phase C Sprint Report
- [3] FCT037 Research Vault Audit
- [4] FCT038 Conversational Room Behavior Design Spec
