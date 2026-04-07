# FCT050 Coordinator-rs Deployment Status and Operational Runbook

> **Purpose:** Zero-ambiguity operational runbook. Every step is a copy-paste command or a decision with clear criteria. No theory, no architecture discussion.

---

## Current State (As of 2026-04-06)

The coordinator-rs is **already deployed and running on Whitebox.** This is not a greenfield deployment — it is an operational service that needs diagnosis and stabilization.

**Key facts:**

| Item | Value |
|------|-------|
| Binary | `/Users/nesbitt/dev/factory/coordinator/target/release/coordinator-rs` (built Mar 31, 6.7MB arm64) |
| Launchd plist | `com.bootindustries.coordinator-rs` (loaded, running, PID 52170) |
| Uptime | Running since at least Mar 23; last restart Apr 4 |
| Config | 3 agents (boot, ig88, kelk), 13 rooms |
| Agent sessions | All 3 initialize successfully; Claude sessions start (haiku model) |
| Identity baseline | 9 soul/principles/agents files loaded |
| Status HUD | Created successfully in Matrix |
| Boot status | Successfully initialized Claude sessions and relayed messages |

**The problem:** The coordinator's own Matrix sync loop (`coord sync`) fails repeatedly — roughly every 2 minutes. Agent syncs (boot, ig88, kelk) work fine with occasional transient failures that self-recover. The coord sync failure is isolated to the coordinator's own Matrix account polling, not the agent sync loops.

The `coord sync failed` entries have been appearing since Mar 23 (first log entry). The agents themselves function — boot, ig88, kelk all sync, initialize Claude, and relay messages. Only the coordinator's own sync is broken.

**Probable causes (in order of likelihood):**
1. The coordinator Matrix account (`@coord:matrix.org`) has a connectivity issue through Pantalaimon (port 41200)
2. The sync filter/token for the coord account is stale or invalid
3. A Pantalaimon session issue specific to the coord account

---

## Phase 1: Diagnose the Coord Sync Failure

All commands run on **Whitebox** (`ssh nesbitt@100.88.222.111`).

### Step 1.1 — Check Pantalaimon Health

```bash
# Is Pantalaimon running?
launchctl list | grep pantalaimon

# Can we reach it?
curl -s http://127.0.0.1:41200/_matrix/client/versions

# Check Pantalaimon logs for coord-specific errors
grep -i "coord" ~/Library/Logs/factory/pantalaimon.log | tail -20
```

**Expected:** `launchctl list` shows the plist with a PID. The curl returns a JSON object with `versions` array. If either fails, Pantalaimon is down — restart it before continuing.

### Step 1.2 — Test the Coord Token Directly

```bash
# Source the env file to get tokens
source ~/.config/ig88/mcp-env.sh

# Test a whoami call with the coord token through Pantalaimon
curl -s -H "Authorization: Bearer $MATRIX_TOKEN_PAN_COORD" \
  http://127.0.0.1:41200/_matrix/client/v3/account/whoami
```

**If this returns a `user_id`:** The token works. Proceed to Step 1.3.
**If this returns an error (401/403):** The token is the problem. Skip to Phase 2 "If token/Pantalaimon issue."

### Step 1.3 — Compare Agent vs Coord Sync Behavior

```bash
# Test a sync call as the coord user
curl -s -H "Authorization: Bearer $MATRIX_TOKEN_PAN_COORD" \
  "http://127.0.0.1:41200/_matrix/client/v3/sync?timeout=5000&filter=0" | head -200

# Compare with boot (which works)
curl -s -H "Authorization: Bearer $MATRIX_TOKEN_PAN_BOOT" \
  "http://127.0.0.1:41200/_matrix/client/v3/sync?timeout=5000&filter=0" | head -200
```

**If coord sync works via curl but fails in the binary:** The issue is in the coordinator-rs code's sync loop. Skip to Phase 2 "If code issue."
**If coord sync fails via curl too:** The issue is Pantalaimon or the Matrix account. Skip to Phase 2 "If token/Pantalaimon issue."

### Step 1.4 — Check Sync Filter Creation

The log shows agents creating sync filters (kelk=4, ig88=5, boot=4) but no coord filter creation. Check if the coordinator code creates its own filter or relies on a pre-existing one.

```bash
# Search the coordinator source for filter creation logic
grep -rn "sync.*filter\|create.*filter\|filter_id" ~/dev/factory/coordinator/src/
```

**If the coordinator never creates a filter for itself:** That is likely the root cause.

---

## Phase 2: Fix and Validate

### If Token/Pantalaimon Issue

```bash
# Re-register the coord account with Pantalaimon
# (exact command depends on Pantalaimon setup — check BKX docs)

# Restart Pantalaimon
launchctl kickstart -k gui/$(id -u)/com.bootindustries.pantalaimon
# (substitute actual plist label if different)

# Wait 5 seconds for Pantalaimon to fully start
sleep 5

# Verify Pantalaimon is responding
curl -s http://127.0.0.1:41200/_matrix/client/versions

# Restart coordinator after Pantalaimon is healthy
launchctl kickstart -k gui/$(id -u)/com.bootindustries.coordinator-rs

# Watch logs for clean startup
tail -f ~/Library/Logs/factory/coordinator.log
```

### If Code Issue

On **Cloudkicker:**

```bash
# Fix the code, rebuild
cd ~/dev/factory/coordinator
# (make your fix)
cargo build --release

# Push to Whitebox via git
cd ~/dev/factory && git add -A && git commit -m "fix(coordinator): [description]"
git push  # whitebox remote updates working tree
```

On **Whitebox:**

```bash
# Rebuild from updated source
cd ~/dev/factory/coordinator && cargo build --release

# Restart service
launchctl kickstart -k gui/$(id -u)/com.bootindustries.coordinator-rs

# Watch logs
tail -f ~/Library/Logs/factory/coordinator.log
```

---

## Phase 3: Rebuild and Redeploy Latest Code

The binary on Whitebox was built Mar 31. The source on Cloudkicker has changes since then. After fixing the sync issue, deploy the latest code.

### Step 3.1 — Rebuild on Whitebox

```bash
ssh nesbitt@100.88.222.111

# Pull latest factory repo
cd ~/dev/factory && git pull

# Build release binary
cd coordinator && cargo build --release

# Verify the new binary
ls -la target/release/coordinator-rs
```

### Step 3.2 — Restart the Service

```bash
# Graceful restart (launchd sends SIGTERM, KeepAlive restarts it)
launchctl kickstart -k gui/$(id -u)/com.bootindustries.coordinator-rs

# Verify startup
tail -f ~/Library/Logs/factory/coordinator.log
```

### Step 3.3 — Validate

Watch the log for these lines in order. Check each off as it appears:

- [ ] `coordinator-rs v0.1.0 starting` — binary launched
- [ ] `Loaded config: 3 agents, 13 rooms` — config parsed
- [ ] `[boot] Agent session initialized` — boot agent up
- [ ] `[ig88] Agent session initialized` — ig88 agent up
- [ ] `[kelk] Agent session initialized` — kelk agent up
- [ ] `Coordinator Matrix user_id: @coord:matrix.org` — coord authenticated
- [ ] `Coordinator poll loop started (3 agents)` — main loop running
- [ ] `[boot] Created sync filter` — boot sync working
- [ ] `[ig88] Created sync filter` — ig88 sync working
- [ ] `[kelk] Created sync filter` — kelk sync working
- [ ] `Status HUD created` — Matrix posting works
- [ ] **NO repeated `coord sync failed` lines for 10+ minutes** — this is the fix validation

---

## Phase 4: Operational Steady-State

Once the coordinator is running clean.

### Log Rotation

`coordinator.log` is currently 58K lines. Set up rotation:

```bash
cat > ~/Library/LaunchDaemons/coordinator-logrotate.conf << 'EOF'
/Users/nesbitt/Library/Logs/factory/coordinator.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
EOF
```

Or simpler — truncate periodically via cron:

```bash
crontab -e
# Add:
0 4 * * * truncate -s 0 /Users/nesbitt/Library/Logs/factory/coordinator.log
```

### Health Monitoring

The coordinator posts to a Status room in Matrix and creates a HUD. Check the Status room for heartbeat messages. If heartbeats stop, check the service:

```bash
launchctl list | grep coordinator
tail -20 ~/Library/Logs/factory/coordinator.log
```

### Known Operational Patterns

| Pattern | Normal? | Action |
|---------|---------|--------|
| 1-3 consecutive transient sync failures | Yes | Self-recovers. Ignore. |
| `coord sync failed` every ~2 minutes | **No** | This is the bug. Run Phase 1. |
| Boot Claude sessions on haiku model | Yes | Change model in agent-config.yaml provider chain if desired. |

---

## Check: TypeScript Coordinator on Blackbox

**IMPORTANT:** Verify whether `matrix-coordinator.ts` on Blackbox (100.87.53.109) is still running. Two coordinators fighting over the same Matrix rooms will cause problems.

```bash
ssh nesbitt@100.87.53.109 'systemctl --user status matrix-coordinator 2>/dev/null; ps aux | grep -i coordinator | grep -v grep'
```

**Decision:**

| Condition | Action |
|-----------|--------|
| TypeScript coordinator IS running AND coordinator-rs handles all rooms | Kill the TypeScript coordinator: `ssh nesbitt@100.87.53.109 'systemctl --user stop matrix-coordinator && systemctl --user disable matrix-coordinator'` |
| TypeScript coordinator IS running AND coordinator-rs only partially works | Keep both temporarily until coordinator-rs sync is fixed |
| TypeScript coordinator is NOT running | No action needed |

---

## References

[1] FCT002 — Factory Agent Architecture (agent roles, model strategy, loop design)
[2] FCT045 — Hermes Agent Competitive Analysis (provider failover pattern)
[3] FCT049 — Agentic Orchestration Philosophy (strategic context)
[4] WHB018 — Inference Port Re-Plumb (port assignments)
[5] WHB019 — Infrastructure Services Port Re-Plumb (unified 41xxx scheme)
[6] ATR005 — Loop Engine First Live Run Prep (loop engine readiness)
[7] BTI011 — Infrastructure & Service Operations (trust levels, stagger delays)
