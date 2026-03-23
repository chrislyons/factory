# Session 4B Sprint Plan — Agent Readiness and Infrastructure Cleanup

**Date:** 2026-03-23
**Run from:** Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/blackbox`
**Objective:** Resolve all carry-forward items so agents present correct personalities, have working tools, and infrastructure is clean. No new features.

---

## Pre-Reading

1. `docs/fct/FCT039 Phase D Sprint Report — Session 4 Stabilization and Blackbox Retirement.md` (carry-forward items)
2. `docs/fct/FCT038 Conversational Room Behavior — Design Spec.md` (deferred design — understand scope)
3. `docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md` (Section 7: API Key Wiring)

---

## System State

- Whitebox: 10 launchd services running. All 3 agents respond to DMs and room mentions.
- MLX-LM on ports 41960-41963 (all healthy)
- Portal on :41910 (auth working)
- Coordinator running (PID alive, KeepAlive active)
- Pantalaimon :8009 bound to 127.0.0.1 (localhost only)
- Blackbox: all agent services stopped/disabled. Watchdog cron running but 2 checks permanently failing.

### Critical Issues Discovered by Subagent Exploration

**IDENTITY FILES SILENTLY FAILING.** All 3 agents' `default_cwd` in agent-config.yaml points to `/Users/nesbitt/factory/agents/{agent}/` — this path DOES NOT EXIST. The correct path is `/Users/nesbitt/dev/factory/agents/{agent}/`. Identity files (soul.md, principles.md, agents.md) exist at the correct path. The coordinator resolves identity file paths against `default_cwd`. Because the directory doesn't exist, `read_identity()` returns empty string via `unwrap_or_default()` — **no error, no warning**. All agents are currently running on their inline `system_prompt` fallback, NOT their soul files.

**MCP SERVERS NOT ON WHITEBOX.** The `mcp-servers/` directory (jupiter-mcp, dexscreener-mcp) does not exist on Whitebox. The compiled `dist/` artifacts exist only on Cloudkicker. There is also no `.mcp.json` in the ig88 working directory on Whitebox. Even if there were, it would reference Cloudkicker paths. Agents spawned by the coordinator have NO MCP tools available.

**COORD PAN SESSION DEAD.** `MATRIX_TOKEN_PAN_COORD` is in BWS and injected into the coordinator env, but the underlying Pantalaimon session for `@coord:matrix.org` was invalidated by the cross-sign toolkit. The coordinator logs `coord sync failed` every ~20 seconds. This only affects approval-room polling, not agent routing — but it's noisy and should be fixed.

---

## Sprint Items

### P0 — Fix identity file paths (CRITICAL — agents have wrong personalities)

**What:** Change `default_cwd` for all 3 agents in agent-config.yaml from `/Users/nesbitt/factory/agents/{agent}` to `/Users/nesbitt/dev/factory/agents/{agent}`.

**Where:** `/Users/nesbitt/dev/factory/agents/ig88/config/agent-config.yaml` on Whitebox (this is the live config — CONFIG_PATH in the coordinator plist points here).

**How:** SSH to Whitebox, edit the 3 `default_cwd` lines. Restart coordinator: `launchctl stop com.bootindustries.coordinator-rs` (KeepAlive restarts it).

**Verify:** After restart, check coordinator log for identity file loading. Send a test DM to each agent — they should now reflect their soul personality, not the generic system_prompt. Ask each agent "Who are you?" and verify they answer with their soul identity, not a generic response.

**Risk:** Low — only changes path resolution, not logic.

**Can be done by agent:** Yes, via SSH.

---

### P0 — Deploy MCP servers to Whitebox (CRITICAL — agents have no tools)

**What:** Copy jupiter-mcp and dexscreener-mcp compiled artifacts from Cloudkicker to Whitebox. Create a Whitebox-specific `.mcp.json` for IG-88's working directory.

**How:**
1. SCP the MCP server dirs from Cloudkicker:
   ```
   scp -r ~/dev/factory/agents/ig88/mcp-servers whitebox:~/dev/factory/agents/ig88/
   ```

2. Create `/Users/nesbitt/dev/factory/agents/ig88/.mcp.json` on Whitebox with Whitebox paths:
   ```json
   {
     "mcpServers": {
       "jupiter": {
         "command": "/Users/nesbitt/.config/ig88/mcp-env.sh",
         "args": [
           "JUPITER_API_KEY=<UUID-from-FCT035>",
           "--",
           "/opt/homebrew/bin/node",
           "/Users/nesbitt/dev/factory/agents/ig88/mcp-servers/jupiter-mcp/dist/index.js"
         ]
       },
       "dexscreener": {
         "command": "/opt/homebrew/bin/node",
         "args": [
           "/Users/nesbitt/dev/factory/agents/ig88/mcp-servers/dexscreener-mcp/dist/index.js"
         ]
       }
     }
   }
   ```
   Note: Dexscreener needs no API key (public API). Jupiter key UUID is in FCT035.

3. Consider adding `jupiter_price`, `jupiter_quote`, `dex_token_info`, `dex_search`, `dex_trending` to `AUTO_APPROVE_TOOLS` in coordinator source (these are read-only market data calls — no execution risk). `jupiter_swap` should NOT be auto-approved. This requires a code change on Whitebox — apply via targeted python3 edit per the established pattern (never SCP coordinator.rs).

**Verify:** After coordinator restart, send IG-88 a DM asking it to check the SOL price. It should use `jupiter_price` tool. If auto-approval is not set up, the tool call will appear as an approval request in Matrix — approve it manually to confirm the chain works.

**Risk:** Medium — MCP server process spawning on Whitebox is untested. May need npm install for dependencies.

**Can be done by agent:** Yes (SCP + SSH), except the `.mcp.json` UUID value which I'll inline.

---

### P1 — Fix coord sync (noisy but non-critical)

**What:** Re-login `@coord:matrix.org` through Pantalaimon on Whitebox, get a fresh token, update BWS.

**How:**
1. Retrieve coord Matrix password from Bitwarden: `bw get password "matrix-pw-coord"` (verify item name)
2. Login to Pantalaimon:
   ```
   ssh whitebox "curl -s -X POST http://127.0.0.1:8009/_matrix/client/r0/login \
     -H 'Content-Type: application/json' \
     -d '{\"type\":\"m.login.password\",\"user\":\"@coord:matrix.org\",\"password\":\"<PW>\"}'"
   ```
3. Extract access_token from response
4. Update BWS `matrix-token-pan-coord` via web vault (BWS machine account is read-only)
5. Restart coordinator

**Verify:** Coordinator log stops showing `coord sync failed`. Should see clean sync cycles.

**Risk:** Low. The cross-sign tool invalidates Pan tokens on logout — if we need to cross-sign again later, this token will need refreshing again. Document this.

**Can be done by agent:** Partially — agent can do the curl login, but user must update BWS via web vault.

**USER ACTION REQUIRED:** Update BWS secret value via vault.bitwarden.eu web interface.

---

### P1 — Fix watchdog checks

**What:** Two watchdog checks permanently fail: Pantalaimon TCP (bound to localhost) and coordinator log freshness (SSH key not authorized).

**Fix Pantalaimon check:** Change watchdog.sh to use SSH-based check instead of direct TCP:
```bash
# Instead of: echo >/dev/tcp/100.88.222.111/8009
# Use: ssh whitebox "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8009/_matrix/client/versions"
```
This requires Blackbox→Whitebox SSH to work (see next item).

**Fix SSH auth:** Add Whitebox's public key to Blackbox authorized_keys AND add Blackbox's public key to Whitebox authorized_keys:
```bash
# From Cloudkicker (has access to both):
ssh whitebox "cat ~/.ssh/id_whitebox_cerulean.pub" | ssh blackbox "cat >> ~/.ssh/authorized_keys"
ssh blackbox "cat ~/.ssh/id_blackbox_navy.pub" | ssh whitebox "cat >> ~/.ssh/authorized_keys"
```

**Fix stale .fail files:** After SSH is working, manually clear:
```bash
ssh blackbox "rm /home/nesbitt/.local/share/watchdog/*.fail"
```

**Clean up legacy cron entries on Blackbox:**
```bash
ssh blackbox "crontab -l" → review
ssh blackbox "crontab -e" → remove the two IG-88 run-cycle.sh entries and the graphiti auto-failover entry if the script no longer exists
```

**Verify:** Wait 4 minutes (2 cron cycles). Check that no new `.fail` files appear. Check alerts.log for recovery messages.

**Can be done by agent:** Yes, all via SSH.

---

### P1 — Clean up broken launchd plists

**`claude-config-sync`** — exit code 255, not running. Either fix or unload:
```bash
ssh whitebox "launchctl list | grep claude-config"
# If broken and not needed now:
ssh whitebox "launchctl unload ~/Library/LaunchAgents/com.bootindustries.claude-config-sync.plist"
```

**`matrix-mcp-boot` and `matrix-mcp-coord`** — plists exist but not loaded. These were deferred in Session 3 (need manual .env with Matrix passwords). For now, leave unloaded — they're not blocking anything (the coordinator talks to Pan directly).

**Can be done by agent:** Yes.

---

### P2 — GitHub SSH key on Whitebox

**What:** Whitebox cannot `git pull` — no GitHub SSH key. Currently using SCP from Cloudkicker.

**Options:**
a) Generate a new key on Whitebox, add to GitHub
b) Continue with SCP workflow (it works, just inconvenient)

**Recommendation:** Set up the key. It's a 2-minute task and eliminates a friction point for all future sessions:
```bash
ssh whitebox "ssh-keygen -t ed25519 -f ~/.ssh/id_whitebox_github -C 'whitebox-github'"
ssh whitebox "cat ~/.ssh/id_whitebox_github.pub"
# User adds to GitHub → Settings → SSH keys
ssh whitebox "echo 'Host github.com\n  IdentityFile ~/.ssh/id_whitebox_github' >> ~/.ssh/config"
ssh whitebox "ssh -T git@github.com"  # verify
```

**USER ACTION REQUIRED:** Add public key to GitHub account.

**Can be done by agent:** Partially — agent generates key, user adds to GitHub.

---

### P2 — BWS kebab-case audit

**What:** FCT035 noted some BWS secret names may still be snake_case. Should be kebab-case per naming convention.

**How:** User checks via web vault (bws machine account is read-only, can't rename via CLI).

**USER ACTION REQUIRED:** Check and rename in vault.bitwarden.eu if needed.

---

### P2 — Verify Graphiti uses rotated token

**What:** FCT039 says Graphiti token was rotated and service restarted. Verify it's actually using the new token.

**How:**
```bash
ssh whitebox "curl -s http://localhost:8444/sse" # Should connect (SSE stream)
```

If Graphiti is down, it may need `docker compose down && docker compose up -d` with the new token injected.

**Can be done by agent:** Yes.

---

## Items NOT in This Sprint (Correctly Deferred)

| Item | Why Deferred | When |
|------|-------------|------|
| **FCT038 — Conversational room behavior** | Requires architectural changes to coordinator sync loop filter. Identity anchoring must be proven stable first (prerequisite 1 in FCT038). | After identity files are working + 1 week stability |
| **Phase C — Paper trading** | Requires MCP tools wired + validated (this sprint) + funded wallet + stable agent identity. | After this sprint's P0 items verified |
| **Phase D — megOLM cutover** | 7-day stability gate. Clock starts when agents are presenting correct personalities with working tools. | Week 6+ |
| **matrix-mcp plists** | Need manual .env, not blocking anything | Low priority |

---

## Execution Order

```
P0: Fix default_cwd → restart coordinator → verify identity    [agent, ~10 min]
P0: SCP MCP servers → create .mcp.json → verify tools          [agent, ~15 min]
P1: Re-login coord Pan → USER updates BWS → restart            [agent + user, ~10 min]
P1: SSH key exchange (BB↔WB) → fix watchdog → clean cron       [agent, ~15 min]
P1: Unload broken claude-config-sync plist                      [agent, ~2 min]
P2: GitHub SSH key on Whitebox                                  [agent + user, ~5 min]
P2: BWS kebab-case audit                                        [user only, ~5 min]
P2: Verify Graphiti token                                        [agent, ~2 min]
```

Total estimated: ~60 minutes of agent work + 3 user-action gates (BWS update, GitHub key, kebab-case check).

---

## Exit Condition

- All 3 agents respond to "Who are you?" with their soul identity (not generic)
- IG-88 can call `jupiter_price` (manual approval or auto-approved)
- Coordinator log shows clean sync cycles (no more `coord sync failed`)
- Watchdog has zero stale `.fail` files and all checks passing
- No broken launchd plists in `launchctl list`
- Blackbox cron has no legacy entries pointing to deleted paths
- GitHub SSH working on Whitebox (`ssh -T git@github.com`)

---

## Post-Sprint State

After this sprint, the system is in a genuinely clean state:
- Agents have their souls, their tools, and a stable coordinator
- Infrastructure monitoring is accurate (no false alerts)
- Both source deployment paths work (SCP and git pull)
- The only remaining architectural work is FCT038 (conversational rooms) — a design problem, not a broken-state problem
- Phase C (paper trading) and Phase D (megOLM) can proceed on their defined schedules
