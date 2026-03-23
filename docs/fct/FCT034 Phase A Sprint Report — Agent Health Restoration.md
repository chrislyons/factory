# FCT034 Phase A Sprint Report — Agent Health Restoration

**Date:** 2026-03-23
**Status:** Complete (with deferred items)
**Type:** Sprint Report
**Parent:** FCT033 §11 Phase A
**Commit:** `694834d` fix(coordinator,portal): harden token loading, fix Caddyfile auth

---

## 1. Objectives

Restore agent infrastructure to operational status per FCT033 Phase A:
- Start MLX-LM inference servers on Whitebox
- Verify Graphiti recovery
- Restore Pantalaimon tokens for IG-88, Kelk, and Boot
- Fix coordinator systemd token injection
- Deploy portal security fixes
- Harden plaintext secret handling

---

## 2. Completed

### A1: MLX-LM Servers — Whitebox (:8080-8083)

All four servers started and verified on Whitebox:

| Port | Model | Status |
|------|-------|--------|
| :8080 | Nanbeige4.1-3B-8bit | LIVE |
| :8081 | Qwen3.5-4B-MLX-8bit | LIVE |
| :8082 | LFM2.5-1.2B-Thinking-MLX-6bit | LIVE |
| :8083 | Qwen3.5-9B-MLX-6bit | LIVE |

**Notes:**
- Requires `--host 0.0.0.0` for non-localhost binding
- Requires `--use-default-chat-template` to avoid HuggingFace API lookups
- Model name in API requests must use the full local path (e.g., `/Users/nesbitt/models/Nanbeige4.1-3B-8bit`)
- macOS firewall blocks Tailscale inbound to these ports — not an issue since consumers (Graphiti, LiteLLM) run on Whitebox localhost
- No launchd plists yet — manual start required (FCT033 §6 covers plist creation)

### A2: Graphiti — Verified

Graphiti MCP (:8444) was already operational. Confirmed via `get_status`: connected to FalkorDB, status OK.

### A3: Pantalaimon Token Restoration

Fresh tokens obtained for all four identities via Pantalaimon login on Whitebox (:8009):

| Identity | BW Item Updated | Status |
|----------|----------------|--------|
| @ig88bot:matrix.org | `matrix-token-pan-ig88` | ✅ |
| @sir.kelk:matrix.org | `matrix-token-pan-kelk` | ✅ (password reset required) |
| @boot.industries:matrix.org | `matrix-token-pan-boot` | ✅ |
| @coord:matrix.org | `matrix-token-pan-coord` | ✅ |

**Kelk issue:** Existing BW password (`matrix-pw-kelk`) was invalid. Password reset on matrix.org required before Pan login succeeded.

**Pan login helper script:** `/tmp/pan-login.sh` on Whitebox — reusable for future token rotations.

### A7: Portal Security Deploy

- **Caddyfile:** Replaced `forward_auth` block (incompatible with Caddy v2.11.2) with `header_regexp` cookie-based session gate. Local source now matches Blackbox production.
- **Portal build:** 17/17 tests pass, `dist/` synced to Blackbox via `make sync-dist`
- **Caddy restarted:** Login (200), root redirect (302), fonts (200) — all verified.

### Security Hardening: Coordinator Token Loading

**Problem:** Coordinator read Matrix tokens from plaintext files on disk (`~/.config/ig88/matrix_token_*_pan`, chmod 600) as a fallback when env vars were missing.

**Fix (commit `694834d`):**
- `AgentConfig.token_file` → `AgentConfig.token_env` (env var name, not file path)
- `read_token()` (reads file) → `read_token_env()` (reads env var)
- Removed plaintext file fallback from both coord token and agent token loading
- Removed `token_file` path expansion from `expand_paths()`
- All 41 tests pass

**Pending:** Update `agent-config.yaml` on deployment target (`token_file` → `token_env` with env var names like `MATRIX_TOKEN_IG88_PAN`). This happens during Whitebox coordinator standup (FCT033 Tier 3).

---

## 3. Deferred

### A4/A5: Coordinator Restart — Deferred to Whitebox Migration

The Blackbox coordinator is running but with stale tokens. Per FCT033 §4.2 Tier 3, the coordinator migrates to Whitebox. Restarting on Blackbox with fresh tokens would require updating the age secrets file — unnecessary work given imminent retirement.

**Decision:** Fresh BW tokens are stored and ready. Coordinator will be stood up on Whitebox with BW-backed secret injection (FCT033 §5 BWS setup).

### A6: Agent Verification — Blocked on Coordinator

Cannot verify agent Matrix responses until coordinator is running with fresh tokens. Deferred to Whitebox coordinator standup.

### Plaintext Token File Deletion

`/home/nesbitt/.config/ig88/matrix_token_coord_pan` (41 bytes, plaintext) remains on Blackbox. Delete during Tier 5 decommission.

### `mcp-env.sh` Migration (age → BW)

Current `mcp-env.sh` decrypts age-encrypted `secrets.env.age`. Migration to BW Secrets Manager is planned in FCT033 §5. Not attempted this sprint.

---

## 4. Discoveries

1. **Pantalaimon on Whitebox is SSH-tunneled**, not natively exposed. Port :8009 is only reachable via localhost or SSH tunnel. Same pattern as Graphiti :8444.
2. **MLX-LM v0.31.1** uses the `model` field in API requests as a HuggingFace repo ID for chat template lookup. Fails with 401 unless the model field matches the exact local path. Downstream consumers (LiteLLM config) must use full paths.
3. **Coordinator `credentials.conf` drop-in** overrides `EnvironmentFile=` and wraps `ExecStart` with `mcp-env.sh` for age-based secret injection. The empty `coordinator.env` is intentional.
4. **Kelk Matrix password was stale** — BW had an outdated value. Required password reset on matrix.org.
5. **`matrix-token-*` (non-Pan) BW items** are unused by any active service. Candidates for archival.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `coordinator/src/config.rs` | `token_file`→`token_env`, `read_token`→`read_token_env`, remove file path expansion |
| `coordinator/src/coordinator.rs` | Remove plaintext file fallback from coord + agent token loading |
| `portal/Caddyfile` | Replace `forward_auth` with `header_regexp` cookie auth gate |

---

## 6. Next Steps (for coordinating agent)

1. **FCT033 §5:** Set up Bitwarden Secrets Manager on Whitebox for machine-accessible secret injection
2. **FCT033 §6:** Create launchd plists for MLX-LM servers (currently manual start)
3. **FCT033 §4.2 Tier 1-2:** Migrate MCP proxies and matrix-mcp to Whitebox
4. **FCT033 §4.2 Tier 3:** Build coordinator on Whitebox, update `agent-config.yaml` (`token_file`→`token_env`), deploy with BWS-backed secret injection
5. **Post-Tier 3:** Verify all three agents respond to Matrix DMs
6. **Deferred maintenance:** Rotate agent Matrix passwords + recovery keys; archive unused `matrix-token-*` BW items
