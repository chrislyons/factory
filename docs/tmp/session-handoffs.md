# FCT033 Session Handoff Prompts

**Created:** 2026-03-23
**Purpose:** Four handoff prompts for sequential execution of FCT033.

---

## Session Architecture

### Why Not Worktrees

Worktrees are the wrong tool here. The sessions are **sequential, not parallel** — each changes system state that the next depends on. A worktree isolates changes on a branch, but these sessions need to:
- SSH into remote machines and change running services
- Modify files that the next session reads
- Commit to main as they go (each phase is a deployable state)

Use **main branch, sequential sessions, commit at each phase boundary.** Each session starts by pulling latest main to get the previous session's commits.

### Directory Routing

| Session | Primary Machine | Working Directory | Why |
|---------|----------------|-------------------|-----|
| **1 (Agent Health)** | **Cloudkicker** | `~/dev/factory/` | SSH tunnels to both Whitebox and Blackbox. All token restoration commands run from Cloudkicker via SSH. Portal sync via `make sync`. Commits to factory repo. |
| **2 (Jupiter + BWS)** | **Cloudkicker** | `~/dev/factory/` with `--add-dir ~/dev/factory/agents/ig88` | Jupiter key goes to Bitwarden (Cloudkicker has bw CLI). BWS setup requires Bitwarden web vault + Whitebox SSH for Keychain storage. IG-88 config changes in agents/ig88 subdir. |
| **3 (Migration)** | **Whitebox** | `~/dev/factory/` | Launchd plists are written on Whitebox. Coordinator builds on Whitebox. All service deployment is local to Whitebox. Caddy install is local. Cloudkicker needed only for `~/.mcp.json` update (brief SSH back). |
| **4 (Cutover + Watchdog)** | **Cloudkicker** | `~/dev/factory/` with `--add-dir ~/dev/blackbox` | Blackbox decommission commands via SSH. Watchdog script deployed to RP5 via SSH. Doc updates span factory + blackbox repos. |

### Pre-Session Checklist (Every Session)

Before pasting each handoff prompt:
1. `cd ~/dev/factory && git pull` (get previous session's commits)
2. Read FCT033 Section 11 for the phase you're about to execute
3. Verify the previous phase's **exit condition** is met

---

## Session 1: Restore Agent Health (Phase A)

**Run from:** Cloudkicker, `~/dev/factory/`

```
You are executing Phase A of FCT033 — Restore Agent Health. This is Day 1, Session 1 of a 4-session execution plan.

Read these documents first (in this order):
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 2: Current State, Section 11: Phase A)
2. docs/fct/FCT029 Factory Consolidated Plan — Architecture, Recovery, and Roadmap.md (Section 5: Recovery Priorities)
3. docs/fct/FCT027 Post-Deployment Recovery and Next Steps.md (token restoration procedure)

SYSTEM STATE as of session start:
- Whitebox (100.88.222.111, user: nesbitt): Pantalaimon :8009 LIVE (launchd), Qdrant :6333 LIVE, FalkorDB :6379 LIVE, Ollama :11434 LIVE. MLX-LM :8080-8083 are DOWN (no launchd plists — manual start required). Graphiti :8444 is DOWN because MLX-LM :8081 isn't running.
- Blackbox (100.87.53.109, user: nesbitt): coordinator-rs BROKEN (sync fails every ~90s — MATRIX_TOKEN_COORD_PAN not in systemd env). matrix-mcp Boot :8445 LIVE. matrix-mcp Coord :8448 LIVE. Portal Caddy :41910 LIVE. IG-88 and Kelk OFFLINE (token files lost).
- Cloudkicker has Bitwarden CLI (`bw`) with active BW_SESSION. SSH aliases `whitebox` and `blackbox` are configured.

EXECUTE these steps in order. Do not skip steps. Confirm each step's result before proceeding:

A1. SSH to Whitebox and start all four MLX-LM inference servers:
    ssh whitebox
    mlx_lm.server --model ~/models/Nanbeige4.1-3B-8bit --port 8080 &
    mlx_lm.server --model ~/models/Qwen3.5-4B-MLX-8bit --port 8081 &
    mlx_lm.server --model ~/models/LFM2.5-1.2B-Thinking-MLX-6bit --port 8082 &
    mlx_lm.server --model ~/models/Qwen3.5-9B-MLX-6bit --port 8083 &
    Verify each is listening: curl http://localhost:8080/v1/models (repeat for 8081-8083)

A2. Verify Graphiti recovers now that :8081 is running:
    curl http://100.88.222.111:8444/sse (from Cloudkicker)
    If Graphiti does not recover, check its logs. It may need a restart.

A3. Restore IG-88 and Kelk Pantalaimon tokens:
    - On Cloudkicker, retrieve Matrix passwords from Bitwarden:
      bw get password "matrix-password-ig88" (or whatever the item name is — search with: bw list items --search ig88 | jq '.[].name')
      bw get password "matrix-password-kelk" (same pattern)
    - Login each identity to Pantalaimon on WHITEBOX :8009:
      curl -X POST http://100.88.222.111:8009/_matrix/client/r0/login -H "Content-Type: application/json" -d '{"type":"m.login.password","user":"@ig88bot:matrix.org","password":"<PASSWORD>"}'
      (repeat for @sir.kelk:matrix.org)
    - Extract the access_token from each response
    - Write token files to BLACKBOX:
      ssh blackbox "echo '<TOKEN>' > ~/.config/ig88/matrix_token_ig88_pan && chmod 600 ~/.config/ig88/matrix_token_ig88_pan"
      (repeat for kelk)
    NEVER echo tokens into the conversation. Use variables or write directly to files.

A4. Fix coordinator systemd token injection on Blackbox:
    ssh blackbox
    - Find the systemd service file: systemctl cat matrix-coordinator
    - Add MATRIX_TOKEN_COORD_PAN to the Environment or EnvironmentFile
    - The coord token should already exist — check: ls -la ~/.config/ig88/matrix_token_coord_pan
    - If missing, restore it the same way as A3 (login @coord identity to Pantalaimon)
    - sudo systemctl daemon-reload

A5. Restart coordinator-rs on Blackbox:
    ssh blackbox "sudo systemctl restart matrix-coordinator"
    Watch logs for 30 seconds: ssh blackbox "journalctl -u matrix-coordinator -f --no-pager" (Ctrl+C after confirming startup)
    The ~90s sync failure should stop.

A6. Verify all three agents respond:
    Send a test message to each agent's DM room in Element (or via curl to Matrix).
    Confirm @boot, @ig88, and @kelk all respond.

A7. Deploy portal security fixes to Blackbox:
    cd ~/dev/factory/portal && make sync
    SSH to Blackbox and generate AUTH_SECRET if not already set:
    ssh blackbox "openssl rand -hex 32" → add to /home/nesbitt/projects/factory-portal/.env as AUTH_SECRET=<value>
    Restart Caddy and auth service on Blackbox.

A8. Commit and push all outstanding changes:
    In ~/dev/factory/ on Cloudkicker:
    - git add docs/fct/FCT031* docs/fct/FCT032* docs/fct/FCT033* docs/fct/FCT.md
    - Also add FCT030 rename if needed (the old filename was deleted, new one untracked)
    - Commit: type(scope) format, e.g. "docs(fct): FCT031-033 agent equipping plan + research review"
    - git push

EXIT CONDITION: All three agents online and responding in Matrix. Portal serving with security fixes. No uncommitted changes. Report what was done and any issues encountered.
```

---

## Session 2: Jupiter Wiring + Secrets Manager (Phase B + 2c.1)

**Run from:** Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/factory/agents/ig88`

```
You are executing Phase B (IG-88 API Key Wiring) and Phase 2c.1 (Bitwarden Secrets Manager setup) of FCT033. This is Session 2 of 4.

Read these documents first:
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 5: BWS Setup, Section 7: API Key Wiring)
2. ~/dev/blackbox/docs/bkx/BKX122 Secrets Manager Headless Machine Credentials Whitebox.md
3. agents/ig88/docs/ig88/IG88029 Jupiter Integration — Execution Capabilities.md

PRE-FLIGHT: Verify Phase A exit condition:
- ssh blackbox "systemctl is-active matrix-coordinator" → should be "active"
- Confirm all 3 agents responded in Matrix in Session 1 (ask the user if unsure)
- git pull to get Session 1's commits

SYSTEM STATE: All 3 agents online. MLX-LM servers running manually on Whitebox. Graphiti operational. Coordinator sync working.

PART 1 — JUPITER API KEY WIRING (Phase B):

B1. Guide the user to obtain a Jupiter API key from portal.jup.ag. Do NOT navigate there yourself. Tell the user what to do and wait for the key.

B2. Generate Solana trading keypair on Blackbox:
    ssh blackbox "solana-keygen new -o ~/.config/ig88/trading_wallet.json"
    ssh blackbox "chmod 600 ~/.config/ig88/trading_wallet.json"
    ssh blackbox "solana-keygen pubkey ~/.config/ig88/trading_wallet.json" → note the public key for funding
    NEVER read the private key contents. NEVER cat the wallet file.

B3. Store Jupiter API key:
    - Add to Bitwarden on Cloudkicker:
      bw create item (or use the web vault) — item name: "jupiter-api-key", in factory/agents collection
    - Add to Blackbox age store:
      ssh blackbox — add JUPITER_API_KEY=<value> to ~/.config/ig88/.env
      Re-encrypt with age if the .env is age-encrypted
    NEVER echo the API key in conversation.

B4. The user will fund the hot wallet externally ($200-800 USDC + ~0.05 SOL to the public key from B2). This is async — proceed to Part 2 while waiting.

B5. AFTER Phase A is fully confirmed AND B3 is done: verify Jupiter connectivity via IG-88.
    This requires dispatching to IG-88 through the coordinator. The simplest test:
    - Send a message in IG-88's Matrix room asking it to call jupiter_price for SOL
    - Or test the MCP server directly if accessible:
      ssh blackbox "cd ~/factory/agents/ig88 && node mcp-servers/jupiter-mcp/dist/index.js" (stdio test)
    Confirm: jupiter_price returns a valid SOL price. jupiter_quote returns a quote with priceImpactPct.

PART 2 — BITWARDEN SECRETS MANAGER SETUP (Phase 2c.1):

This follows BKX122 exactly. The purpose is to give Whitebox launchd plists a way to inject credentials at unattended startup.

2c.1.1. Guide the user through the Bitwarden web vault setup:
    - Log into vault.bitwarden.eu → Boot Industries org → Secrets Manager tab
    - Create project: "factory/agents"
    - Populate all secrets from FCT033 Section 5.3 (14 entries)
    - Create service account: "whitebox-factory-agents", read-only access to factory/agents
    - Generate access token — user copies it immediately

2c.1.2. Store the access token in Whitebox Keychain:
    ssh whitebox "security add-generic-password -s 'bitwarden-secrets-manager' -a 'whitebox-factory-agents' -w '<TOKEN>'"
    Verify retrieval: ssh whitebox "security find-generic-password -s 'bitwarden-secrets-manager' -a 'whitebox-factory-agents' -w"
    NEVER echo the token in conversation.

2c.1.3. Verify bws CLI works on Whitebox:
    ssh whitebox "BWS_ACCESS_TOKEN=\$(security find-generic-password -s 'bitwarden-secrets-manager' -a 'whitebox-factory-agents' -w) bws secret list"
    This should return the populated secrets.

2c.1.4. Write the Whitebox variant of mcp-env.sh:
    Create ~/.config/ig88/mcp-env.sh on Whitebox. Follow BKX122 Step 5 pattern:
    - Retrieve BWS_ACCESS_TOKEN from Keychain
    - For each requested env var, fetch via `bws secret get <UUID>`
    - Export and exec the wrapped command
    - chmod 755

2c.1.5. Smoke test: manually invoke mcp-env.sh with one secret to confirm the full chain works.

Commit any factory repo changes (config updates, doc corrections discovered during this work).

EXIT CONDITION: Jupiter API key wired and verified (price + quote calls work). BWS operational on Whitebox — mcp-env.sh variant tested. Secrets Manager project populated with all 14 entries. Report what was done, any issues, and the Jupiter connectivity test results.
```

---

## Session 3: Blackbox Retirement Migration (Phase 2c.2-2c.7)

**Run from:** Whitebox, `~/dev/factory/`

**Important:** This session runs on Whitebox because all launchd plists, service deployments, and cargo builds happen locally there. The agent needs SSH back to Cloudkicker only for `~/.mcp.json` updates.

```
You are executing Phase 2c.2 through 2c.7 of FCT033 — migrating all remaining Blackbox services to Whitebox and running the 48h parallel validation window. This is Session 3 of 4.

Read these documents first:
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 4: Migration Manifest, Section 6: Launchd Plists)
2. ~/dev/whitebox/CLAUDE.md (Whitebox machine identity and conventions)

PRE-FLIGHT:
- git pull to get Sessions 1-2 commits
- Verify BWS is operational: BWS_ACCESS_TOKEN=$(security find-generic-password -s 'bitwarden-secrets-manager' -a 'whitebox-factory-agents' -w) bws secret list
- Verify MLX-LM servers still running: curl http://localhost:8080/v1/models (8080-8083)
- Verify coordinator on Blackbox is still healthy: ssh blackbox "systemctl is-active matrix-coordinator"

SYSTEM STATE: All agents online (via Blackbox coordinator). BWS operational. MLX-LM running manually. Jupiter API key wired. You are on Whitebox as user `nesbitt`, HOME=/Users/nesbitt.

IMPORTANT CONTEXT:
- Whitebox username is `nesbitt`. All plist paths use /Users/nesbitt/.
- Factory repo is at ~/dev/factory/ (git remote: github.com/chrislyons/factory.git)
- No cargo on Whitebox — coordinator-rs must be cross-compiled on Cloudkicker (cargo build --release --target aarch64-apple-darwin) OR compiled on Whitebox after installing Rust.
- Caddy is NOT installed on Whitebox — must be installed (brew install caddy).
- Blackbox portal deployment is at /home/nesbitt/projects/factory-portal/ on Blackbox.

EXECUTE in dependency order per FCT033 Section 4.2:

TIER 0 — PREREQUISITES:
- mkdir -p ~/Library/Logs/factory
- Install Caddy: brew install caddy
- Install Rust if not present: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
- Verify: caddy version, cargo --version

TIER 1 — CREATE LAUNCHD PLISTS FOR MLX-LM (4 plists):
Follow FCT033 Section 6.2 template. Create:
- ~/Library/LaunchAgents/com.bootindustries.mlx-lm-8080.plist (Nanbeige4.1-3B-8bit)
- ~/Library/LaunchAgents/com.bootindustries.mlx-lm-8081.plist (Qwen3.5-4B-MLX-8bit)
- ~/Library/LaunchAgents/com.bootindustries.mlx-lm-8082.plist (LFM2.5-1.2B-Thinking-MLX-6bit)
- ~/Library/LaunchAgents/com.bootindustries.mlx-lm-8083.plist (Qwen3.5-9B-MLX-6bit)
Model paths are in ~/models/. Host: 0.0.0.0. KeepAlive: true.
Kill the manually-running servers, then load plist: launchctl load ~/Library/LaunchAgents/com.bootindustries.mlx-lm-8080.plist
Verify each: curl http://localhost:8080/v1/models (repeat 8081-8083)

TIER 1 CONTINUED — MCP PROXIES (2 plists):
- com.bootindustries.qdrant-mcp.plist (port 8446)
- com.bootindustries.research-mcp.plist (port 8447)
These need QDRANT_API_KEY via mcp-env.sh. Use the bws variant from Session 2.
Gate: test Qdrant search via the new Whitebox endpoint.

TIER 2 — MATRIX MCP (2 plists):
- Copy IdentityRegistry state from Blackbox: scp -r blackbox:/home/nesbitt/.local/state/matrix-mcp/ ~/.local/state/matrix-mcp/ (if state dir exists on Blackbox)
- com.bootindustries.matrix-mcp-boot.plist (port 8445)
- com.bootindustries.matrix-mcp-coord.plist (port 8448)
Both need Matrix tokens via mcp-env.sh. LISTEN_HOST=100.88.222.111.
Gate: test message round-trip via Whitebox matrix-mcp.

TIER 3 — COORDINATOR:
- Install Rust on Whitebox if not done in Tier 0
- cd ~/dev/factory/coordinator && cargo build --release
- Update agent-config.yaml: graphiti_url → http://127.0.0.1:8444/sse; add devices.whitebox block; default_device → whitebox
- Create com.bootindustries.coordinator-rs.plist per FCT033 Section 6.3
- Load plist. Verify coordinator starts and all 3 agents connect.
- Begin 48h parallel: Whitebox coordinator handles dispatch; Blackbox coordinator remains running but should be paused or de-privileged to prevent dual-dispatch.

TIER 4 — PORTAL STACK (3 plists):
- com.bootindustries.auth-sidecar.plist (port 41914, needs AUTH_SECRET + AUTH_BCRYPT_HASH via mcp-env.sh)
- com.bootindustries.gsd-sidecar.plist (port 41911, copy server.py + jobs.json from Blackbox)
- com.bootindustries.portal-caddy.plist (port 41910, update Caddyfile bind to 100.88.222.111:41910)
- Copy portal dist/ from Blackbox: scp -r blackbox:/home/nesbitt/projects/factory-portal/dist ~/dev/factory/portal/dist-production (or equivalent)
Gate: curl http://100.88.222.111:41910/jobs.json works. Portal loads in browser.

UPDATE CLOUDKICKER MCP CONFIG:
SSH back to Cloudkicker and update ~/.mcp.json — all MCP server URLs from 100.87.53.109 → 100.88.222.111.

PHASE 2c.7 — DEGRADATION TESTING (during 48h window):
After at least 24h of stable parallel operation, intentionally kill each Whitebox service one at a time and observe:
1. Stop MLX-LM :8081 → does Graphiti degrade gracefully? Does coordinator log warnings but continue?
2. Stop one matrix-mcp instance → does coordinator route around it?
3. Stop FalkorDB → does Graphiti degrade? Does coordinator continue without memory writes?
Restore each service after testing. Document results.

Commit all changes (plists, config updates, Caddyfile) to factory repo on Whitebox. Push to origin.

EXIT CONDITION: All 12 launchd plists created and loaded. All services running on Whitebox. 48h parallel window initiated. Degradation testing plan documented. Cloudkicker ~/.mcp.json updated. Report all service statuses and any issues.
```

---

## Session 4: Cutover, Decommission, Watchdog, Docs (Phase 2c.8-2c.11)

**Run from:** Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/blackbox`

```
You are executing the final migration steps: Blackbox cutover, decommission, RP5 watchdog deployment, and documentation updates. This is Session 4 of 4, completing Phase 2c.

Read these documents first:
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 4.2 Tier 5, Section 4.3 RP5 Watchdog, Section 9: Doc Updates)
2. docs/fct/FCT029 Factory Consolidated Plan — Architecture, Recovery, and Roadmap.md (Section 11: Open Decisions — for status updates)

PRE-FLIGHT:
- git pull to get Session 3's commits
- Verify 48h parallel window has passed and all services are stable on Whitebox:
  curl http://100.88.222.111:41910/jobs.json (portal)
  curl http://100.88.222.111:8444/sse (graphiti)
  curl http://100.88.222.111:8080/v1/models (MLX-LM)
  Send test message to each agent via Matrix — confirm responses route through Whitebox coordinator
- Verify degradation test results from Session 3 are acceptable (ask user if needed)

SYSTEM STATE: All services running on both Whitebox (primary) and Blackbox (paused/shadow). 48h window complete. Degradation testing done.

PART 1 — BLACKBOX CUTOVER (Phase 2c.8):

Stop all Blackbox services in this order:
ssh blackbox
sudo systemctl stop matrix-coordinator
sudo systemctl stop factory-portal
sudo systemctl stop gsd-backend (or whatever the GSD service is named)
sudo systemctl stop factory-auth
sudo systemctl stop qdrant-mcp research-mcp
# Disable all so they don't restart on reboot:
sudo systemctl disable matrix-coordinator factory-portal gsd-backend factory-auth qdrant-mcp research-mcp

Verify Whitebox is now the sole service host — all agent messages route correctly, portal loads, MCP tools work from Cloudkicker.

PART 2 — BKX119 CLEANUP:

ssh blackbox
# Check what's in the old monolith:
ls -la /home/nesbitt/projects/ig88/ | head -20
# Verify no active service references this path:
grep -r "/home/nesbitt/projects/ig88" /etc/systemd/system/ 2>/dev/null
# If clean, remove:
rm -rf /home/nesbitt/projects/ig88/
# Check for compat symlinks:
ls -la /home/nesbitt/ig88 2>/dev/null
# Remove if found.

PART 3 — RP5 WATCHDOG DEPLOYMENT (FCT033 Section 4.3):

Create a health-check script on Blackbox RP5. This is ~50 lines of bash, no LLM:

The script should:
1. Define an array of service endpoints to check:
   - http://100.88.222.111:8080/v1/models (MLX-LM 8080)
   - http://100.88.222.111:8081/v1/models (MLX-LM 8081)
   - http://100.88.222.111:8082/v1/models (MLX-LM 8082)
   - http://100.88.222.111:8083/v1/models (MLX-LM 8083)
   - http://100.88.222.111:6333/collections (Qdrant)
   - http://100.88.222.111:8444/sse (Graphiti — use timeout, SSE streams)
   - http://100.88.222.111:8009 (Pantalaimon — just TCP connect check)
   - http://100.88.222.111:41910 (Portal Caddy)
2. For each endpoint: curl with 5s timeout, check HTTP 200 (or TCP connect for :8009)
3. Track consecutive failures per service in /tmp/watchdog-fails-<port>
4. On 2 consecutive failures: send a Matrix alert via curl to Synapse API (use a dedicated bot token or the coord token)
   The message should name the failed service, port, and timestamp.
5. On recovery after alert: send "recovered" message

Deploy to /home/nesbitt/scripts/watchdog.sh, chmod +x.
Set up cron: */2 * * * * /home/nesbitt/scripts/watchdog.sh >> /var/log/watchdog.log 2>&1

Test by temporarily stopping one MLX-LM server on Whitebox, waiting for 2 cron cycles, confirming the Matrix alert fires, then restarting the server.

PART 4 — DOCUMENTATION UPDATES (FCT033 Section 9):

Update these files — read each before editing:

4a. ~/dev/factory/CLAUDE.md:
    - Port Scheme section: all Blackbox 100.87.53.109 entries → Whitebox 100.88.222.111
    - Add note: "Blackbox retired 2026-03-XX. RP5 serves as dumb watchdog only."

4b. ~/dev/blackbox/CLAUDE.md:
    - Add "RETIRED" banner at top
    - Update topology: Blackbox no longer runs agent services
    - Keep Matrix room IDs and historical context as read-only reference

4c. Factory MEMORY.md (~/.claude/projects/-Users-chrislyons-dev-factory/memory/MEMORY.md):
    - Update Port Scheme section
    - Update "Factory Portal Status" section
    - Add note about Blackbox retirement and RP5 watchdog
    - Update Caddy Routing section if needed

4d. Update FCT029 with cross-reference:
    Add to Section 11 (Open Decisions): "Blackbox post-Whitebox role: RESOLVED — full retirement, FCT033"

4e. Update ~/dev/factory/docs/fct/ports.md (if it exists) with the consolidated Whitebox port table.

4f. Update Makefile in portal/:
    Rename BLACKBOX variable to WHITEBOX, update REMOTE path to Whitebox.

Commit all changes across both repos:
- factory: "feat(infra): complete Blackbox retirement — all services on Whitebox"
- blackbox: "docs(bkx): mark Blackbox retired, update topology"

Push both repos.

EXIT CONDITION: Blackbox services stopped and disabled. RP5 watchdog operational (tested). All documentation updated. Both repos committed and pushed. The Factory runs entirely on Whitebox + Cloudkicker. Report final service inventory and any remaining issues for Phase C (paper trading) and Phase D (megOLM).
```

---

## Post-Session Notes

### After Session 4 Completes

The system is in a clean state for two independent workstreams:

**Phase C (Paper Trading)** — Start from Cloudkicker, `~/dev/factory/` with `--add-dir ~/dev/factory/agents/ig88`. This is weeks-long work with checkpoint sessions at every 25 trades. Read FCT033 Section 8 at the start of each checkpoint session.

**Phase D (megOLM Cutover)** — Cannot start until 7 consecutive days of agent stability post-migration. Track from the date Session 4 completes. When the gate is met, start from Cloudkicker `~/dev/factory/` with `--add-dir ~/dev/blackbox`. Read FCT033 Section 10 as the procedure.

### Whitebox Username Resolution

Session 3 needs this resolved before it begins. The answer is `nesbitt` (confirmed via SSH: `whoami` returns `nesbitt`, HOME=/Users/nesbitt). All plist templates in Session 3 should use `/Users/nesbitt/`.
