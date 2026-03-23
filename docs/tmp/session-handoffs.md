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

## Session 1: Restore Agent Health (Phase A) — COMPLETE

**Status:** Completed 2026-03-23. Commits: `694834d`, `063f6a6`.

**What was done:**
- MLX-LM :8080-8083 started manually on Whitebox (all verified)
- Graphiti :8444 verified healthy
- Fresh Pantalaimon tokens generated for all 4 identities, stored in Bitwarden
- All Matrix passwords rotated — all are fresh in BW
- Coordinator-rs hardened: `read_token_env()` replaces `read_token()`, plaintext token file fallback removed
- Portal deployed to Blackbox with corrected auth gate (`header_regexp` replacing `forward_auth`)
- FCT034 sprint report committed

**Deferred to Session 3 (Whitebox migration):**
- Coordinator restart with fresh tokens (requires BWS-injected env vars, not Blackbox age store)
- Agent Matrix verification (@ig88, @kelk responding to messages)
- `agent-config.yaml` schema update (`token_file` → `token_env`)
- Plaintext token file deletion on Blackbox
- Kelk Matrix password was reset — flag for password rotation tracking

**Note:** `jobs/` directory doesn't exist locally on Cloudkicker (jobs.json build fails) — may need restoring from Blackbox during Session 3.

---

## Session 2: Jupiter Wiring + Secrets Manager (Phase B + 2c.1) — COMPLETE

**Status:** Completed 2026-03-23. Sprint report: FCT035.

**What was done:**
- Three Solana wallets generated on Whitebox (trading, funding, alt) with BIP39 passphrases
- JSON wallet files deleted from disk — seed phrases + passphrases in BW only
- BWS project `factory-agents` created with 13 secrets (kebab-case naming)
- Machine account `factory-agents` with access token in Whitebox Keychain
- `mcp-env.sh` deployed to `~/.config/ig88/mcp-env.sh` on Whitebox, smoke tested
- **All 11 secrets rotated** due to accidental `bws secret list` plaintext exposure
- `openrouter-api-key` and `jupiter-api-key` added to BWS (not leaked, no rotation needed)
- UUID mapping documented in FCT035

**Important for Session 3:**
- `bws` requires `--server-url https://vault.bitwarden.eu` on every call
- Keychain `-w` retrieval blocked over SSH — all BWS-dependent services must run locally on Whitebox
- MLX-LM servers were DOWN this session — restart before Session 3
- Server configs (Graphiti, Qdrant, auth.py) need updating with rotated values
- Verify BWS secret names are all kebab-case (graphiti-auth-token, qdrant-api-key)

**Original handoff prompt (for reference):**

```
You are executing Phase B (IG-88 API Key Wiring) and Phase 2c.1 (Bitwarden Secrets Manager setup) of FCT033. This is Session 2 of 4.

Read these documents first:
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 5: BWS Setup, Section 7: API Key Wiring)
2. ~/dev/blackbox/docs/bkx/BKX122 Secrets Manager Headless Machine Credentials Whitebox.md
3. agents/ig88/docs/ig88/IG88029 Jupiter Integration — Execution Capabilities.md
4. docs/fct/FCT034 Phase A Sprint Report — Agent Health Restoration.md (for Session 1 outcomes)

PRE-FLIGHT:
- git pull to get Session 1's commits
- Verify MLX-LM servers still running on Whitebox: ssh whitebox "curl -s http://localhost:8080/v1/models | head -1" (repeat 8081-8083)
- Verify Graphiti healthy: curl http://100.88.222.111:8444/sse (should connect)
- Note: Agents are NOT yet verified on Matrix. IG-88 and Kelk tokens are in Bitwarden but NOT yet injected into coordinator env. Agent verification is deferred to Session 3 when coordinator moves to Whitebox with BWS-injected tokens.

SYSTEM STATE after Session 1:
- Whitebox: MLX-LM :8080-8083 running (manually started), Graphiti :8444 LIVE, Pantalaimon :8009 LIVE, Qdrant :6333 LIVE, FalkorDB :6379 LIVE, Ollama :11434 LIVE
- Blackbox: coordinator-rs running but tokens NOT refreshed (still using stale env). Portal Caddy :41910 deployed with auth fixes.
- Bitwarden: Fresh Pantalaimon tokens for all 4 identities stored. All Matrix passwords freshly rotated.
- Coordinator hardened: read_token_env() replaces read_token(), plaintext fallback removed. Schema needs token_file → token_env update in agent-config.yaml (deferred to Session 3).
- jobs/ directory doesn't exist locally on Cloudkicker — jobs.json build will fail. May need restoring from Blackbox.

PART 1 — JUPITER API KEY WIRING (Phase B):

B1. Jupiter API key already exists in Bitwarden as "jupiter-api-key" in factory/agents collection. No action needed — verify it's present:
    bw get password "jupiter-api-key" (should return a value; do NOT echo it)

B2. Generate Solana trading keypair. Since Blackbox is being retired, generate on WHITEBOX:
    ssh whitebox "mkdir -p ~/.config/ig88 && solana-keygen new -o ~/.config/ig88/trading_wallet.json"
    ssh whitebox "chmod 600 ~/.config/ig88/trading_wallet.json"
    ssh whitebox "solana-keygen pubkey ~/.config/ig88/trading_wallet.json" → note the public key for funding
    If solana-keygen is not installed on Whitebox: ssh whitebox "brew install solana" (or sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)")
    NEVER read the private key contents. NEVER cat the wallet file.

B3. Jupiter API key is already in Bitwarden (confirmed B1). It will be available on Whitebox via BWS after Part 2 is complete. No additional storage needed.

B4. The user will fund the hot wallet externally ($200-800 USDC + ~0.05 SOL to the public key from B2). This is async — proceed to Part 2 while waiting.

B5. SKIP in this session. Jupiter connectivity verification requires IG-88 responding on Matrix, which is deferred to Session 3 (after coordinator migrates to Whitebox with BWS-injected tokens). Session 3 will pick up B5.

PART 2 — BITWARDEN SECRETS MANAGER SETUP (Phase 2c.1):

This follows BKX122 exactly. The purpose is to give Whitebox launchd plists a way to inject credentials at unattended startup. This is the CRITICAL PATH prerequisite for Session 3.

2c.1.1. Guide the user through the Bitwarden web vault setup:
    - Log into vault.bitwarden.eu → Boot Industries org → Secrets Manager tab
    - Create project: "factory/agents"
    - Populate all secrets from FCT033 Section 5.3 (14 entries). Also include these keys already in BW but not listed in FCT033:
      - JUPITER_API_KEY (already in BW as "jupiter-api-key")
      - COINGECKO_API_KEY (already in BW as "coingecko-api-key")
    - Also add the 4 freshly-rotated Matrix Pan tokens (matrix-token-pan-ig88, matrix-token-pan-kelk, matrix-token-pan-boot, matrix-token-pan-coord — verify exact BW item names with user)
    - Create service account: "whitebox-factory-agents", read-only access to factory/agents
    - Generate access token — user copies it immediately

2c.1.2. Store the access token in Whitebox Keychain:
    ssh whitebox "security add-generic-password -s 'bws-factory-agents' -a 'factory-agents' -w '<TOKEN>'"
    Verify retrieval: ssh whitebox "security find-generic-password -s 'bws-factory-agents' -a 'factory-agents' -w"
    NEVER echo the token in conversation.

2c.1.3. Install bws CLI on Whitebox if not present:
    ssh whitebox "which bws || brew install bitwarden/tap/bws"

2c.1.4. Verify bws CLI works on Whitebox:
    ssh whitebox "BWS_ACCESS_TOKEN=\$(security find-generic-password -s 'bws-factory-agents' -a 'factory-agents' -w) bws secret list"
    This should return the populated secrets.

2c.1.5. Write the Whitebox variant of mcp-env.sh:
    Create ~/.config/ig88/mcp-env.sh on Whitebox. Follow BKX122 Step 5 pattern:
    - Retrieve BWS_ACCESS_TOKEN from Keychain via `security find-generic-password`
    - For each requested env var, fetch via `bws secret get <UUID>`
    - Export and exec the wrapped command
    - chmod 755
    Record the UUID mapping for each secret (needed for the script and for Session 3 plists).

2c.1.6. Smoke test: manually invoke mcp-env.sh with one secret to confirm the full chain works.

Commit any factory repo changes (config updates, doc corrections discovered during this work).

EXIT CONDITION: Jupiter API key confirmed in Bitwarden. Solana keypair generated on Whitebox. BWS operational on Whitebox — bws secret list returns all entries, mcp-env.sh variant tested and working. Secret UUID mapping documented. Report what was done and any issues. Note that B5 (Jupiter connectivity) and agent Matrix verification are deferred to Session 3.
```

---

## Session 3: Blackbox Retirement Migration (Phase 2c.2-2c.7)

**Run from:** Whitebox, `~/dev/factory/`

**Important:** This session runs on Whitebox because all launchd plists, service deployments, and cargo builds happen locally there. The agent needs SSH back to Cloudkicker only for `~/.mcp.json` updates.

```
You are executing Phase 2c.2 through 2c.7 of FCT033 — migrating all remaining Blackbox services to Whitebox and running the 48h parallel validation window. This is Session 3 of 4.

Read these documents first:
1. docs/fct/FCT033 Definitive Execution Plan — Agent Equipping, Blackbox Retirement, and Trading Validation.md (Section 4: Migration Manifest, Section 6: Launchd Plists)
2. docs/fct/FCT035 Phase B Sprint Report — BWS Setup and Secret Rotation.md (UUID mapping table, mcp-env.sh details, rotation incident, pre-flight notes)
3. ~/dev/whitebox/CLAUDE.md (Whitebox machine identity and conventions)

PRE-FLIGHT:
- git pull to get Sessions 1-2 commits
- Verify BWS is operational: BWS_ACCESS_TOKEN=$(security find-generic-password -s 'bws-factory-agents' -a 'factory-agents' -w) bws secret list
- Verify MLX-LM servers still running: curl http://localhost:8080/v1/models (8080-8083)
- Verify coordinator on Blackbox is still running: ssh blackbox "systemctl is-active matrix-coordinator"

SYSTEM STATE after Sessions 1-2:
- Whitebox: MLX-LM :8080-8083 DOWN (need restarting). Graphiti :8444 LIVE. Pantalaimon :8009 LIVE. Qdrant :6333 LIVE. FalkorDB :6379 LIVE. Ollama :11434 LIVE. Solana wallet JSON files DELETED (keys recoverable from BW seed phrases). BWS operational with mcp-env.sh at ~/.config/ig88/mcp-env.sh (smoke tested). bws requires --server-url https://vault.bitwarden.eu.
- Blackbox: coordinator-rs running with STALE tokens (not restarted since Session 1 hardening). Agents NOT yet verified on Matrix — token injection deferred to this session. Portal Caddy :41910 deployed with auth fixes.
- Bitwarden Secrets Manager: 13 secrets in project "factory-agents" (ALL ROTATED 2026-03-23 — see FCT035). Machine account "factory-agents" (not "whitebox-factory-agents"). Keychain entry: service=bws-factory-agents, account=factory-agents. Keychain values CANNOT be read over SSH — all BWS consumers must run locally on Whitebox.
- DEFERRED from Sessions 1-2: Agent Matrix verification, Jupiter connectivity test (B5), agent-config.yaml token_file → token_env update, Blackbox plaintext token file deletion.
- jobs/ directory doesn't exist locally on Cloudkicker — may need restoring from Blackbox.

You are on Whitebox as user `nesbitt`, HOME=/Users/nesbitt.

IMPORTANT CONTEXT:
- Whitebox username is `nesbitt`. All plist paths use /Users/nesbitt/.
- Factory repo is at ~/dev/factory/ (git remote: github.com/chrislyons/factory.git)
- Coordinator-rs was hardened in Session 1: read_token_env() replaces read_token(). The token_file field in agent-config.yaml must be updated to token_env before deploying on Whitebox. The env vars are injected by mcp-env.sh via BWS.
- All Matrix passwords were freshly rotated. All 13 BWS secrets were rotated 2026-03-23 (see FCT035). Do NOT use `bws secret list` to view secrets — it outputs values in plaintext. Use UUID mapping from FCT035 directly.
- No cargo on Whitebox — install Rust as a prerequisite (Tier 0).
- Caddy is NOT installed on Whitebox — must be installed (brew install caddy).
- Blackbox portal deployment is at /home/nesbitt/projects/factory-portal/ on Blackbox.
- bws requires `--server-url https://vault.bitwarden.eu` on EVERY command.
- Keychain `-w` retrieval is blocked over SSH — all BWS-dependent services must run locally on Whitebox, NOT via SSH from Cloudkicker.
- mcp-env.sh usage: `mcp-env.sh VAR_NAME=UUID [VAR_NAME=UUID ...] -- command [args...]`
- mcp-env.sh location: `~/.config/ig88/mcp-env.sh` on Whitebox
- BWS secret naming is kebab-case. Verify with FCT035 UUID table — some may still be snake_case and need renaming.
- Solana wallet JSON files were deleted from disk. Keys recoverable from BW seed phrases + BIP39 passphrases only (BW item: `solana-keypair-ig88`).

SERVER CONFIGS NEEDING ROTATED VALUES (deferred from Session 2):
- Graphiti config on Whitebox: needs new graphiti-auth-token value
- Qdrant config on Whitebox: needs new qdrant-api-key value
- These should be injected via BWS/mcp-env.sh in the launchd plists, NOT written to config files.

EXECUTE in dependency order per FCT033 Section 4.2:

TIER 0 — PREREQUISITES:
- mkdir -p ~/Library/Logs/factory
- Restart MLX-LM servers (were DOWN during Session 2):
    Kill any stale processes, then start fresh:
    mlx_lm.server --model ~/models/Nanbeige4.1-3B-8bit --port 8080 &
    mlx_lm.server --model ~/models/Qwen3.5-4B-MLX-8bit --port 8081 &
    mlx_lm.server --model ~/models/LFM2.5-1.2B-Thinking-MLX-6bit --port 8082 &
    mlx_lm.server --model ~/models/Qwen3.5-9B-MLX-6bit --port 8083 &
    Verify: curl http://localhost:8080/v1/models (repeat 8081-8083)
    These will be replaced by launchd plists in Tier 1.
- Update server configs with rotated secret values (FCT035):
    Graphiti and Qdrant configs on Whitebox need the new rotated values.
    Identify where these configs live and update them. Prefer BWS injection via launchd plists
    over hardcoded config values wherever possible.
- Verify Graphiti healthy after MLX-LM restart: curl http://localhost:8444/sse
- Install Caddy: brew install caddy
- Install Rust if not present: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
- Verify: caddy version, cargo --version
- Verify BWS secret names are kebab-case (FCT035 note 6): run `bws secret list --server-url https://vault.bitwarden.eu 2>&1 | python3 -c "import sys,json; [print(s['key']) for s in json.load(sys.stdin)]"` and rename any snake_case entries

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
These need QDRANT_API_KEY via mcp-env.sh. Use UUID from FCT035: `QDRANT_API_KEY=3f9dcc24-7137-4cf2-916f-b416011fbc03`
mcp-env.sh call: `~/.config/ig88/mcp-env.sh QDRANT_API_KEY=3f9dcc24-7137-4cf2-916f-b416011fbc03 -- <command>`
Gate: test Qdrant search via the new Whitebox endpoint.

TIER 2 — MATRIX MCP (2 plists):
- Copy IdentityRegistry state from Blackbox: scp -r blackbox:/home/nesbitt/.local/state/matrix-mcp/ ~/.local/state/matrix-mcp/ (if state dir exists on Blackbox)
- com.bootindustries.matrix-mcp-boot.plist (port 8445)
- com.bootindustries.matrix-mcp-coord.plist (port 8448)
Both need Matrix tokens via mcp-env.sh. UUIDs from FCT035:
- Boot: `MATRIX_TOKEN_PAN_BOOT=8e9bcc76-a4fc-4b7f-88c2-b416011f40cb`
- Coord: `MATRIX_TOKEN_PAN_COORD=31d23df6-f50f-43d3-99c0-b416011f7024`
LISTEN_HOST=100.88.222.111.
Gate: test message round-trip via Whitebox matrix-mcp.

TIER 3 — COORDINATOR:
- Install Rust on Whitebox if not done in Tier 0
- cd ~/dev/factory/coordinator && cargo build --release
- Update agent-config.yaml:
  - graphiti_url → http://127.0.0.1:8444/sse
  - Add devices.whitebox block with Tailscale IP 100.88.222.111
  - All agents: default_device → whitebox
  - All agents: token_file → token_env (Session 1 hardened coordinator to env-only via read_token_env())
  - The token env vars are injected by mcp-env.sh via BWS. UUIDs from FCT035:
    MATRIX_TOKEN_PAN_BOOT=8e9bcc76-a4fc-4b7f-88c2-b416011f40cb
    MATRIX_TOKEN_PAN_COORD=31d23df6-f50f-43d3-99c0-b416011f7024
    MATRIX_TOKEN_PAN_IG88=3ad5ea9f-de29-4f5e-ab6f-b416011f7e0e
    MATRIX_TOKEN_PAN_KELK=0fe1c283-a1ef-42ea-b645-b416011f928b
    GRAPHITI_AUTH_TOKEN=99e55357-7977-4925-8671-b416011fac6a
    OPENROUTER_API_KEY=ee959bd0-ee17-4328-a4eb-b416012d217f
- Create com.bootindustries.coordinator-rs.plist per FCT033 Section 6.3
- Load plist. Watch logs: tail -f ~/Library/Logs/factory/coordinator.log

AGENT VERIFICATION (deferred from Session 1):
- After Whitebox coordinator starts, verify all 3 agents respond on Matrix:
  - Ask user to send a test DM to @boot, @ig88, and @kelk in Element
  - @coord can send to Backrooms to test coordinator-agent paths
  - Confirm all 3 respond. This is the first time IG-88 and Kelk have been online since FCT022.

JUPITER CONNECTIVITY (B5, deferred from Session 2):
- After agents are verified, test Jupiter MCP via IG-88:
  - Send a message in IG-88's Matrix room asking it to call jupiter_price for SOL
  - Confirm: jupiter_price returns a valid SOL price
  - Confirm: jupiter_quote returns a quote with priceImpactPct
  - If jupiter-mcp is not yet deployed as an MCP server for IG-88, test directly:
    ssh whitebox (or wherever the MCP server binary lives) and invoke via stdio

- Begin 48h parallel: Whitebox coordinator handles dispatch; Blackbox coordinator remains running but should be paused or de-privileged to prevent dual-dispatch.

TIER 4 — PORTAL STACK (3 plists):
- com.bootindustries.auth-sidecar.plist (port 41914, needs AUTH_SECRET + AUTH_BCRYPT via mcp-env.sh)
    UUIDs: AUTH_SECRET=297da199-6348-4ba4-b368-b416011ffbc0, AUTH_BCRYPT=a574a840-bb94-44a7-bf15-b416011fe96f
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

EXIT CONDITION: All 12 launchd plists created and loaded. All services running on Whitebox. All 3 agents verified responding on Matrix via Whitebox coordinator. Jupiter connectivity verified (B5 complete). agent-config.yaml updated with token_env fields. 48h parallel window initiated. Degradation testing plan documented. Cloudkicker ~/.mcp.json updated. Report all service statuses and any issues.
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
