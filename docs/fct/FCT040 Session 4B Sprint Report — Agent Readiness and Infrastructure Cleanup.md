# FCT040 Session 4B Sprint Report — Agent Readiness and Infrastructure Cleanup

**Session:** FCT033 Session 4B (follow-up)
**Date:** 2026-03-23
**Duration:** ~30 minutes
**Objective:** Resolve all carry-forward items from Session 4 — fix agent identity loading, deploy MCP tools, clean up watchdog and infrastructure

## Summary

Fixed critical identity file path bug (agents now load all 9 soul/principles/agents files), deployed IG-88 MCP servers to Whitebox, established Blackbox-to-Whitebox SSH, fixed watchdog Pantalaimon check, cleaned 3 legacy cron entries, unloaded broken launchd service, and verified Graphiti health.

## Completed

### P0 — Fix Identity File Paths (CRITICAL)
- [x] Changed `default_cwd` for all 3 agents from `/Users/nesbitt/factory/agents/{agent}` to `/Users/nesbitt/dev/factory/agents/{agent}`
- [x] Coordinator restarted; log confirms `Identity baseline established (9 files)` (was 0)
- [x] All 9 identity files (3 agents x soul.md + principles.md + agents.md) now resolvable

### P0 — Deploy MCP Servers to Whitebox (CRITICAL)
- [x] SCP'd `jupiter-mcp` and `dexscreener-mcp` from Cloudkicker to Whitebox
- [x] `node_modules/` transferred with SCP (17 packages each, `@modelcontextprotocol/sdk` included)
- [x] `.mcp.json` written at `/Users/nesbitt/dev/factory/agents/ig88/.mcp.json`
- [x] Jupiter: spawned via `mcp-env.sh` with `JUPITER_API_KEY=jupiter-api-key` BWS secret injection
- [x] Dexscreener: spawned directly via `/opt/homebrew/bin/node` (public API, no key)
- [x] Node.js v25.8.1 confirmed on Whitebox
- **Prerequisite:** `jupiter-api-key` must exist in BWS `factory-agents` project

### P1 — Blackbox-to-Whitebox SSH
- [x] Added `whitebox` host entry to Blackbox SSH config (`id_blackbox_cerulean` key)
- [x] Added Blackbox public key to Whitebox `authorized_keys`
- [x] Tested: `ssh blackbox "ssh whitebox echo ok"` → success

### P1 — Fix Watchdog
- [x] Pantalaimon check changed from direct TCP (`/dev/tcp/$WHITEBOX/8009`) to SSH-based curl (`ssh whitebox "curl ... http://127.0.0.1:8009/_matrix/client/versions"`)
- [x] Cleared stale `.fail` files (pantalaimon.fail, coordinator-log.fail)
- [x] Both checks now functional via SSH

### P1 — Clean Blackbox Cron
- [x] Removed 3 legacy entries:
  - `0 13 * * *` IG-88 run-cycle.sh (deleted path)
  - `0 1 * * *` IG-88 run-cycle.sh (deleted path)
  - `* * * * *` graphiti auto-failover.sh (Graphiti on Whitebox now)
- [x] Only watchdog entry remains: `*/2 * * * *`

### P1 — Unload Broken launchd Plist
- [x] `com.bootindustries.claude-config-sync` (exit 255) unloaded
- [x] Plist moved to `.plist.disabled` (preserved, not deleted)
- [x] Service was a file-watcher for Claude config sync — script missing on Whitebox

### P2 — Verify Graphiti Token
- [x] SSE endpoint at `localhost:8444/sse` responding (tunneled from Cloudkicker)
- [x] Rotated token confirmed working

### P2 — GitHub SSH Key on Whitebox
- [x] Key already existed: `id_whitebox_cerulean` (ed25519)
- [x] SSH config already pointed to it for `github.com`
- [ ] **USER ACTION:** Add pubkey to GitHub Settings → SSH keys

## Pending User Actions

1. **Coord Pan re-login:** Run login curl, update BWS `matrix-token-pan-coord`, restart coordinator
2. **GitHub SSH:** Add `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICPXTXkkFr0hfB0OIzXshOdvekvZY3BmuNP9C9R8Esh3 whitebox-cerulean` to GitHub
3. **BWS kebab-case audit:** Check naming in vault.bitwarden.eu

## Exit Condition Progress

| Criterion | Status |
|-----------|--------|
| All 3 agents respond with soul identity | Identity files loaded (9/9) — needs DM test |
| IG-88 can call `jupiter_price` | MCP servers deployed — needs end-to-end test |
| Coordinator log shows clean sync | Pending coord Pan re-login (user action) |
| Watchdog zero stale `.fail` files | Done |
| No broken launchd plists | Done |
| Blackbox cron has no legacy entries | Done |
| GitHub SSH working on Whitebox | Pending user adding key to GitHub |

## References

- [1] FCT033 Definitive Execution Plan
- [2] FCT039 Session 4 Sprint Report
- [3] Session 4B Sprint Plan (docs/tmp/session-4b-sprint.md)
