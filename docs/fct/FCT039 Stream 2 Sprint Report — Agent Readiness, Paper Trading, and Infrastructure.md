# FCT039 Stream 2 Sprint Report — Agent Readiness, Paper Trading, and Infrastructure

**Sessions:** FCT033 Session 4B + Stream 2 follow-up sprints
**Date:** 2026-03-23
**Predecessors:** FCT038
**References:** FCT033 S8, FCT035, FCT036

---

## Part 1 — Session 4B: Agent Readiness and Infrastructure Cleanup

**Duration:** ~30 minutes
**Objective:** Resolve all carry-forward items from Session 4 — fix agent identity loading, deploy MCP tools, clean up watchdog and infrastructure

### Summary

Fixed critical identity file path bug (agents now load all 9 soul/principles/agents files), deployed IG-88 MCP servers to Whitebox, established Blackbox-to-Whitebox SSH, fixed watchdog Pantalaimon check, cleaned 3 legacy cron entries, unloaded broken launchd service, and verified Graphiti health.

---

### Completed

#### P0 — Fix Identity File Paths (CRITICAL)
- [x] Changed `default_cwd` for all 3 agents from `/Users/nesbitt/factory/agents/{agent}` to `/Users/nesbitt/dev/factory/agents/{agent}`
- [x] Coordinator restarted; log confirms `Identity baseline established (9 files)` (was 0)
- [x] All 9 identity files (3 agents x soul.md + principles.md + agents.md) now resolvable

#### P0 — Deploy MCP Servers to Whitebox (CRITICAL)
- [x] SCP'd `jupiter-mcp` and `dexscreener-mcp` from Cloudkicker to Whitebox
- [x] `node_modules/` transferred with SCP (17 packages each, `@modelcontextprotocol/sdk` included)
- [x] `.mcp.json` written at `/Users/nesbitt/dev/factory/agents/ig88/.mcp.json`
- [x] Jupiter: spawned via `mcp-env.sh` with `JUPITER_API_KEY=jupiter-api-key` BWS secret injection
- [x] Dexscreener: spawned directly via `/opt/homebrew/bin/node` (public API, no key)
- [x] Node.js v25.8.1 confirmed on Whitebox
- **Prerequisite:** `jupiter-api-key` must exist in BWS `factory-agents` project

#### P1 — Blackbox-to-Whitebox SSH
- [x] Added `whitebox` host entry to Blackbox SSH config (`id_blackbox_cerulean` key)
- [x] Added Blackbox public key to Whitebox `authorized_keys`
- [x] Tested: `ssh blackbox "ssh whitebox echo ok"` → success

#### P1 — Fix Watchdog
- [x] Pantalaimon check changed from direct TCP (`/dev/tcp/$WHITEBOX/8009`) to SSH-based curl (`ssh whitebox "curl ... http://127.0.0.1:8009/_matrix/client/versions"`)
- [x] Cleared stale `.fail` files (pantalaimon.fail, coordinator-log.fail)
- [x] Both checks now functional via SSH

#### P1 — Clean Blackbox Cron
- [x] Removed 3 legacy entries:
  - `0 13 * * *` IG-88 run-cycle.sh (deleted path)
  - `0 1 * * *` IG-88 run-cycle.sh (deleted path)
  - `* * * * *` graphiti auto-failover.sh (Graphiti on Whitebox now)
- [x] Only watchdog entry remains: `*/2 * * * *`

#### P1 — Unload Broken launchd Plist
- [x] `com.bootindustries.claude-config-sync` (exit 255) unloaded
- [x] Plist moved to `.plist.disabled` (preserved, not deleted)
- [x] Service was a file-watcher for Claude config sync — script missing on Whitebox

#### P2 — Verify Graphiti Token
- [x] SSE endpoint at `localhost:8444/sse` responding (tunneled from Cloudkicker)
- [x] Rotated token confirmed working

#### P2 — GitHub SSH Key on Whitebox
- [x] Key already existed: `id_whitebox_cerulean` (ed25519)
- [x] SSH config already pointed to it for `github.com`
- [ ] **USER ACTION:** Add pubkey to GitHub Settings → SSH keys

---

## Part 2 — Paper Trading Readiness

**Objective:** Bridge IG-88 from "has MCP tools" to "can execute a paper trade cycle." Validate the full chain and add auto-approval for read-only trading tools — the last prerequisite before IG-88's 100-trade validation sprint (FCT033 §8).

### 1. Jupiter Connectivity — Pre-flight Checks

| Check | Status | Detail |
|-------|--------|--------|
| jupiter-mcp/dist/index.js | Present | 2358 bytes, 2026-03-23 |
| dexscreener-mcp/dist/index.js | Present | 2134 bytes, 2026-03-23 |
| .mcp.json paths | Correct | Whitebox absolute paths, mcp-env.sh BWS injection |
| Coordinator running | Yes | PID 69099, com.bootindustries.coordinator-rs |
| BWS injection (SSH) | Expected fail | Keychain `-w` blocked over SSH — works locally via launchd |

**Matrix DM test status:** Pending user manual verification.

DM IG-88 with: "Check SOL price using `jupiter_price` (mint: `So11111111111111111111111111111111111111112`)"

Expected outcomes:
- **Success:** Price in ~$120-200 range with timestamp
- **Partial (CoinGecko fallback):** BWS injection failed — check mcp-env.sh
- **Failure (no response):** Coordinator routing issue
- **"Unknown tool":** .mcp.json not loaded by Claude subprocess

---

### 2. AUTO_APPROVE_TOOLS Changes

7 read-only market data tools added:

```rust
// IG-88 trading tools -- read-only market data (jupiter_swap stays OUT)
"mcp__jupiter__jupiter_price",
"mcp__jupiter__jupiter_quote",
"mcp__jupiter__jupiter_portfolio",
"mcp__dexscreener__dex_token_info",
"mcp__dexscreener__dex_token_pairs",
"mcp__dexscreener__dex_search",
"mcp__dexscreener__dex_trending",
```

`jupiter_swap` deliberately excluded — moves money, requires human approval via approval room.

**Deployment:** Edit applied on Whitebox via python3 (targeted string replacement, not SCP). `cargo build --release` — success (22 warnings, 0 errors, 23.6s). Coordinator restarted via launchctl. Same edit applied on Cloudkicker source.

**Tool name format:** `mcp__jupiter__jupiter_price` (double-underscore separators matching MCP server name from .mcp.json `"jupiter"` key). To be confirmed via first Matrix DM test — if actual prefix differs (e.g. `mcp__jupiter-mcp__`), entries must be updated.

---

### 3. trades.csv Schema Update

Extended header from 16 to 19 columns:

```
ID,Date,Time,Token,Direction,Entry,SL,TP,Exit,Result,R,Regime_Status,Regime_Conf,Narrative,Narrative_Conv,Notes,regime_label,regime_entry_date,regime_age_days
```

New fields (per FCT033 §8.3):

| Field | Type | Valid values |
|-------|------|-------------|
| `regime_label` | enum | `RISK_ON_TRENDING`, `RISK_ON_VOLATILE`, `RISK_OFF_RANGING`, `RISK_OFF_DECLINING` |
| `regime_entry_date` | date | YYYY-MM-DD when current regime was first detected |
| `regime_age_days` | int | Days since regime entry date |

Applied on both Cloudkicker (`agents/ig88/.claude/validation/trades.csv`) and Whitebox (created fresh — directory didn't exist on WB).

---

### 4. 25-Trade Checkpoint Framework

Created `agents/ig88/.claude/validation/CHECKPOINT-TEMPLATE.md` per FCT033 §8.5-8.6.

Template covers:
1. Core metrics (win rate, expectancy, max consecutive losses, max drawdown)
2. OOS decay ratio calculation
3. Regime diversity breakdown (4 labels, 15-trade minimum per regime)
4. Kill switch status (6 triggers from §8.4)
5. Coordination tax metrics (4 metrics from §8.6)
6. NO_TRADE cycle log with counterfactuals
7. Prompt change audit trail
8. GO / EXTEND / NO-GO assessment

---

### 5. First Paper Trade Cycle

**Status:** Pending — requires manual Matrix DM to IG-88.

DM IG-88 to run full Regime → Scanner → Narrative → Governor cycle. Log output to `cycles/C002.md`. If TRADE signal, log to `trades.csv` as T001 with `dryRun:true`. NO_TRADE is a valid outcome.

---

## Part 3 — Infrastructure Sprint: Port Allocation and Matrix MCP Deployment

**Objective:** Deploy Matrix MCP servers on Whitebox and rationalize the 844x MCP port block into a clean, consistent allocation.

### 1. Matrix MCP Deployment (Whitebox)

Two matrix-mcp instances deployed on Whitebox using the existing source at `/Users/nesbitt/projects/matrix-mcp/`. The `dist/` directory was already built; `npm install` completed with no issues.

**Configuration — both instances:**
- Auth mode: Pan access tokens from BWS (non-OAuth — uses `MATRIX_ACCESS_TOKEN` env var fallback path)
- Homeserver: Pantalaimon on `localhost:8009` via `MATRIX_HOMESERVER_URL`
- Binding: `0.0.0.0` (`LISTEN_HOST`) to allow Tailscale access from Cloudkicker
- Management: launchd plists with KeepAlive

| Instance | Identity | Port | Plist Label |
|----------|----------|------|-------------|
| Coord | @coord:matrix.org | :8440 | `com.bootindustries.matrix-mcp-coord` |
| Boot | @boot.industries:matrix.org | :8448 | `com.bootindustries.matrix-mcp-boot` |

Both plists created and loaded on Whitebox. Servers start, bind their ports, and accept TCP connections.

**Known issues:**

*MCP handshake hang.* `curl` POST to `/mcp` on both instances times out. The servers listen and accept connections but do not complete the MCP initialize handshake. Likely cause: Matrix sync blocking on the first request before the MCP protocol layer gets a chance to respond. Needs debugging — may require an async initialization path or a pre-warmed sync state.

*DM room access limitation.* Neither Boot nor Coord can read the IG-88 DM room (`!ReiEgMIHlHqCVZwfTY:matrix.org`). DM rooms on Matrix are scoped to the two participants (Chris and the agent), so a matrix-mcp instance logged in as Boot or Coord has no membership. Resolving this requires either:
- A matrix-mcp instance logged in as Chris or IG-88
- Inviting a third identity to the DM room (changes room semantics)
- Using a shared "operations" room instead of DMs for tool-mediated communication

---

### 2. Port Allocation Reshuffle

The 844x MCP port block was inconsistent — Qdrant MCP sat on 8446, Research MCP on 8447, with gaps. This sprint consolidated all MCP services into a clean sequential block.

| Port | Before | After |
|------|--------|-------|
| 8440 | (unassigned) | Matrix MCP Coord (new) |
| 8442 | (unassigned) | Qdrant MCP (moved from 8446) |
| 8443 | (unassigned) | Research MCP (moved from 8447) |
| 8444 | Graphiti MCP | Graphiti MCP (unchanged) |
| 8448 | (unassigned) | Matrix MCP Boot (new) |

Pantalaimon remains on `:8009`. Moving it would cascade through coordinator-rs YAML config, all agent identity files, and every matrix-mcp plist — high blast radius for no functional gain.

**Files updated:**
- Whitebox launchd plists: `com.bootindustries.qdrant-mcp` and `com.bootindustries.research-mcp` updated to new ports; both matrix-mcp plists created fresh
- `~/.mcp.json` (Cloudkicker global): all four MCP server URLs updated to Whitebox IP with new port numbers
- `~/dev/research-vault/.mcp.json`: URL updated to Whitebox IP + new port (8443)
- Factory `CLAUDE.md` port table: already reflected the new allocation prior to this doc

---

### 3. Master Port Table

Created `infra/ports.csv` as the single source of truth for all Whitebox service port allocations (19 entries). Any future port allocation should be recorded there before deployment.

---

## Pending User Actions

1. **Coord Pan re-login:** Run login curl, update BWS `matrix-token-pan-coord`, restart coordinator
2. **GitHub SSH:** Add `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICPXTXkkFr0hfB0OIzXshOdvekvZY3BmuNP9C9R8Esh3 whitebox-cerulean` to GitHub
3. **BWS kebab-case audit:** Check naming in vault.bitwarden.eu
4. **Manual verification:** DM IG-88, confirm `jupiter_price` works and auto-approves
5. **First cycle:** Run full paper trade cycle, produce C002.md

---

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

---

## Next Steps

1. Debug Matrix MCP handshake hang — investigate Pan token sync blocking, test with pre-warmed sync token
2. Decide Matrix MCP identity strategy for IG-88 DM room access (Chris instance vs. shared room)
3. Execute first paper trade cycle (manual, Chris-initiated)
4. Begin 100-trade validation sprint (FCT033 S8) once cycle 1 completes successfully

---

## Files Changed

| File | Change |
|------|--------|
| `coordinator/src/coordinator.rs` | +7 tools in AUTO_APPROVE_TOOLS; agent sync timeout None→Some(3000); DM routing fix |
| `agents/ig88/.mcp.json` | New — MCP server config for Whitebox |
| `agents/ig88/.claude/validation/trades.csv` | Header extended: +3 regime fields (19 cols) |
| `agents/ig88/.claude/validation/CHECKPOINT-TEMPLATE.md` | New — 25-trade checkpoint report template |
| `infra/ports.csv` | New — master port allocation table |
| Whitebox launchd plists (x4) | qdrant-mcp, research-mcp updated; matrix-mcp-coord, matrix-mcp-boot created |
| `~/.mcp.json` (Cloudkicker) | All MCP server URLs updated to Whitebox IP + new ports |

---

## References

[1] FCT033, "Whitebox Migration — Session Plans and Execution," 2026-03-23.

[2] FCT038, "Conversational Room Behavior — Design Spec and Session 4 Sprint Report," 2026-03-23.

[3] FCT035, "BWS Secrets Audit," 2026-03-23.

[4] FCT036, "Session 4 Final Report and Handoff," 2026-03-23.
