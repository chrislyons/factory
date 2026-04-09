# FCT027 Post-Deployment Recovery and Next Steps

**Date:** 2026-03-22
**Status:** Active
**Related:** FCT020–FCT024, BKX126, GSD002

---

## 1. Current State

The FCT022 security sprint (documented in FCT023) was verified and graded at B+ by FCT024. Five immediate fixes were deployed to Cloudkicker (PORTAL-1/2/3/6, C4-a), raising the grade to A-. The coordinator-rs was rebuilt with the index-out-of-bounds panic fix and deployed to Blackbox. The matrix-mcp cache eviction fix was deployed to Blackbox.

**What's working:**
- Coordinator-rs running on Blackbox (new binary, panic fix, all FCT022 security changes)
- All 3 Claude agent sessions initialized (Boot, IG-88, Kelk) with resumed sessions
- Boot responds via matrix-mcp on port 8445 (independent sync via Pantalaimon)
- Matrix-mcp Boot and Coord instances restarted with cache eviction fix
- Pantalaimon is running and responsive on port 8009
- Portal security headers, forward_auth, CSRF, mandatory AUTH_SECRET — all deployed to Cloudkicker source

**What's broken:**
- IG-88 and Kelk do not respond to Element messages
- Root cause: token files `matrix_token_{boot,ig88,kelk}_pan` are missing from `~/.config/ig88/` on Blackbox
- Only `matrix_token_coord_pan` exists
- The coordinator starts and creates sync filters for all agents, but cannot authenticate their Matrix syncs without tokens
- Boot works only because the matrix-mcp Boot instance (port 8445) has its own token injected via `mcp-env.sh`
- `coord sync failed` repeating every ~90s — coord identity sync broken (pre-existing, env var `MATRIX_TOKEN_COORD_PAN` not injected into systemd service)

**What's deployed to Cloudkicker but NOT yet to Blackbox:**
- Portal Caddyfile with `forward_auth` (PORTAL-1 fix)
- Portal auth.py with mandatory `AUTH_SECRET` (PORTAL-2 fix)
- Portal auth.py with `//` redirect rejection (PORTAL-3 fix)
- matrix-mcp http-server.ts with timing-safe comparison (C4-a fix)

---

## 2. Immediate Recovery: Restore Agent Tokens (Manual)

**Priority: HIGH — IG-88 and Kelk are offline.**

The three Pantalaimon token files were present before the FCT022 source sync overwritten the Blackbox coordinator directory. They need to be regenerated from Bitwarden.

### Step 1: Retrieve Matrix passwords from Bitwarden

The passwords for these Matrix accounts are needed:
- `@boot.industries:matrix.org`
- `@ig88bot:matrix.org`
- `@sir.kelk:matrix.org`

### Step 2: Login each agent to Pantalaimon

On Blackbox, for each agent:

```bash
curl -s -X POST "http://localhost:8009/_matrix/client/r0/login" \
  -H "Content-Type: application/json" \
  -d '{"type":"m.login.password","user":"<username>","password":"<password>"}' \
  | jq -r '.access_token' > ~/.config/ig88/matrix_token_<agent>_pan

chmod 600 ~/.config/ig88/matrix_token_<agent>_pan
```

Agents: `boot`, `ig88`, `kelk`

### Step 3: Restart coordinator

```bash
sudo systemctl restart matrix-coordinator.service
```

### Step 4: Verify

```bash
# Check all 3 agents show sync activity
tail -f ~/dev/factory/coordinator/logs/coordinator.log | grep -E "\[boot\]|\[ig88\]|\[kelk\]"
```

Message each agent in Element — all three should respond.

### Step 5: Inject coord token into systemd

To fix the persistent `coord sync failed` warnings, add the coordinator's Pantalaimon token to the systemd environment:

```bash
# Get coord token
cat ~/.config/ig88/matrix_token_coord_pan

# Add to coordinator.env
echo "MATRIX_TOKEN_COORD_PAN=<token>" > ~/.config/ig88/coordinator.env
chmod 600 ~/.config/ig88/coordinator.env

# Restart
sudo systemctl restart matrix-coordinator.service
```

---

## 3. Deploy Portal Fixes to Blackbox

**Priority: MEDIUM — portal is functional but auth has known bypass on Blackbox.**

### Step 1: Generate AUTH_SECRET

On Blackbox:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Store the output in Bitwarden and in the auth service environment.

### Step 2: Sync and restart portal

From Cloudkicker:
```bash
cd ~/dev/factory/portal && make sync
```

On Blackbox:
```bash
# Add AUTH_SECRET to auth service environment
# Then restart services
sudo systemctl restart factory-portal.service
sudo systemctl restart auth.service
```

### Step 3: Verify

```bash
# Test that bare cookie is rejected (PORTAL-1)
curl -sf -H "Cookie: factory_session=garbage" http://100.87.53.109:41910/jobs.json
# Should redirect to /login, not return JSON

# Test that the login page loads
curl -sf http://100.87.53.109:41910/login | head -5
```

---

## 4. Commit and Push Status

### Repos with uncommitted changes

**factory (Cloudkicker):**
- `coordinator/src/coordinator.rs` — panic fix (bounds-safe indexing)
- `portal/Caddyfile` — forward_auth, object-src CSP
- `portal/auth.py` — mandatory AUTH_SECRET, open redirect fix
- `docs/fct/FCT022–FCT025` — documentation

**matrix-mcp (Cloudkicker):**
- `src/matrix/clientCache.ts` — sync-aware cache eviction
- `src/http-server.ts` — timing-safe auth comparison, crypto import

**blackbox:**
- Coordinator binary rebuilt and deployed
- matrix-mcp source synced and MCP instances restarted

---

## 5. E2EE Cutover (FCT023 Section 7) — Deferred

The Pantalaimon-to-native-E2EE cutover remains pending. All checklist items from FCT023 Section 7 are still incomplete:

| Step | Status | Dependency |
|------|--------|------------|
| Add 8 secrets to Bitwarden (passwords + recovery keys) | Pending | Bitwarden access |
| Deploy coordinator-rs with `--features native-e2ee` | Pending | Secrets provisioned |
| Stop and disable Pantalaimon | Pending | E2EE verified working |
| Archive `pan.db` | Pending | Pantalaimon stopped |
| Remove `matrix_token_*_pan` from secrets | Pending | Native E2EE confirmed |
| Cross-sign all agent devices from Element | Pending | BKX058 |
| 48h monitoring window | Pending | All above complete |

**Recommendation:** Do not attempt E2EE cutover until Sections 2 and 3 above are complete and agents are stable on the current Pantalaimon-based system. The native E2EE code exists (feature-gated behind `native-e2ee`) but the credential provisioning and device cross-signing are manual steps that require focused attention.

---

## 6. Phase 3 Sprint Readiness

FCT024 Part 2 specifies Sprints 6–12 for A- to A+. Phase 3 can begin once:

- [ ] Section 2 complete (agent tokens restored, all 3 agents responding)
- [ ] Section 3 complete (portal fixes deployed to Blackbox)
- [ ] All changes committed and pushed
- [ ] E2EE cutover decision made (proceed or defer)

Phase 3 Sprint 6 (API Key Infrastructure) has no dependency on the E2EE cutover and can proceed independently.

---

## References

[1] FCT023, Section 7, "Cutover Checklist."
[2] FCT024, Part 3, "Addendum — Immediate Fixes Executed."
[3] GSD002, "Coordinator Rename and Trust Level Corrections" — documents coordinator using Boot's token.
[4] KELK002, "Matrix Multi-Agent Coordinator Plan" — original token file locations.

---

*Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>*
