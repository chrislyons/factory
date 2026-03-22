# FCT023 Sprint Complete — FCT022 Unified Security and E2EE Migration

**Date:** 2026-03-21
**Status:** Complete
**Related:** FCT020, FCT021, FCT022, BKX058, BKX126
**Repos:** `~/dev/matrix-mcp/`, `~/dev/factory/`, `~/dev/blackbox/`

---

## 1. Summary

FCT022 merged two independent workstreams — BKX126 (Pantalaimon to native Megolm E2EE) and FCT021 (security hardening B- to A+) — into a single six-sprint execution sequence. The sprint eliminated the Pantalaimon reverse-proxy dependency across both matrix-mcp and coordinator-rs, and closed all 24 actionable security findings from the FCT020 red-hat assessment: 4 CRITICAL, 6 HIGH, 10 MEDIUM, and 4 LOW.

**Security grade before:** B-
**Security grade after:** A-

The remaining gap to A/A+ (FCT021 Phase 3: API key infrastructure, container sandboxing, secrets rotation API) is scoped as a separate epic.

---

## 2. Sprint Breakdown

### Sprint 0: Security Quick Wins (B- to B+)

Immediate fixes targeting all 4 CRITICALs and the worst HIGH findings.

**matrix-mcp:**

| Finding | Action |
|---------|--------|
| C3 | Upgraded `@modelcontextprotocol/sdk` from `^1.16.0` to `^1.26.0` |
| C4/H11 | Default `LISTEN_HOST` changed to `127.0.0.1`; shared-secret auth middleware for non-OAuth mode (`MCP_AUTH_SECRET`) |
| H9 | Homeserver URL allowlist via `MATRIX_ALLOWED_HOMESERVERS`; non-OAuth mode ignores caller headers |
| H10 | Removed `matrixAccessToken` from tool input schemas |
| H12 | `npm audit fix` — 0 vulnerabilities remaining |

**coordinator-rs:**

| Finding | Action |
|---------|--------|
| H1 | Input validation on delegate SSH params (regex whitelist: alphanumeric, hyphen, slash, dot, underscore) |
| H2 | HMAC signer made mandatory — coordinator fails to start without secret file |
| H3/H4 | Removed `send-message`, `send-direct-message`, `send-reaction`, `add_memory` from `AUTO_APPROVE_TOOLS` |

### Sprint 1: E2EE Foundation + MCP Security Hardening

**IdentityRegistry module** (`matrix-mcp/src/identity/`):

7 new files totaling ~230 lines:
- `types.ts` — `AgentIdentity`, `CredentialProvider` interfaces
- `credential-providers.ts` — `EnvCredentialProvider` reads `MATRIX_PASSWORD_{AGENT}` / `MATRIX_RECOVERY_KEY_{AGENT}`
- `device-store.ts` — Device ID persistence with `0600` file permissions
- `crypto-setup.ts` — WASM Rust crypto via `initRustCrypto()`, SSSS key restore, cross-signing bootstrap
- `registry.ts` — Central registry mapping user IDs to initialized Matrix clients
- `polyfill.ts` — `fake-indexeddb` polyfill for Node.js (required by Rust crypto WASM)
- `index.ts` — Barrel export

**MCP security hardening:**

| Finding | Action |
|---------|--------|
| M12 | Room allowlist per agent (`MATRIX_ROOM_ALLOWLIST`), validated in 12 tool handlers |
| M13 | Access token hash in client cache key (SHA-256 first 8 chars) |
| M14 | Default `NODE_ENV=production`; tightened `ALLOW_SELF_SIGNED_CERTS` guard |
| M15 | Block `m.*` type writes in `set-account-data` |
| L9 | LRU eviction with max 20 cached clients |
| L10 | Security test suite (8 tests covering allowlists, blocking, cache hashing) |

### Sprint 2: matrix-mcp E2EE Migration

Wired IdentityRegistry into the runtime:

- Polyfill import added as first line in `http-server.ts` and `stdio-server.ts`
- `IdentityRegistry` initialization at startup when `MATRIX_USER_ID` + `MATRIX_PASSWORD` are set
- `createMatrixClient()` checks registry before creating ephemeral clients
- `clientCache` checks registry before TTL cache
- Deleted Pantalaimon fallback block from `messaging.ts`
- `getAccessToken()` returns empty string for registry-managed identities

### Sprint 3: Coordinator-rs Security Hardening

Executed in parallel with matrix-mcp Sprints 1 and 2.

| Finding | Action |
|---------|--------|
| C1 | Per-command RBAC on slash commands — privileged commands require `approval_owner` |
| C2 | HMAC verification on Matrix reaction-based approvals (embedded tag + verification) |
| H5 | Path validation on delegate `Edit`/`Write` — reject `..` traversal |
| M1 | `/loop start` spec paths restricted to configured directory |
| M2 | `kill_on_drop(true)` on agent subprocesses |
| M3 | Required `trust_level` in config — fail startup if missing |
| M5 | Rate limiting on slash commands (10/60s per user) |
| M6 | Fail startup if `whoami()` fails — removed `@coord:matrix.org` fallback |
| M16 | Added `..` to shell metacharacter deny regex |
| L2 | `cargo-audit` clean (fixed RUSTSEC-2026-0049 rustls-webpki) |
| L5 | Absolute paths for system commands in infra health checks |
| M4/L6 | Sync token files written with `0600` permissions |

### Sprint 4: Coordinator-rs E2EE Migration

Native E2EE support via `matrix-sdk` 0.16.0, feature-gated behind `native-e2ee`:

- `identity_store.rs` (83 lines) — SQLite-backed E2EE state, password login, recovery key support
- `matrix_native.rs` (385 lines) — `NativeMatrixClient` with full API parity to the legacy client
- `matrix_legacy.rs` — renamed from `matrix.rs` (741 lines) for rollback capability
- `config.rs` — added `E2eeSettings` and per-agent credential fields
- `infra.rs` — removed Pantalaimon from health checks
- Both compilation paths clean: `cargo check` (legacy) and `cargo check --features native-e2ee`

### Sprint 5: Portal Hardening + Pantalaimon Decommission Prep

**Portal:**

| Finding | Action |
|---------|--------|
| H6a | GSD sidecar shared-secret auth (`GSD_AUTH_SECRET`) |
| H7 | CSRF tokens (`factory_csrf` cookie + `X-CSRF-Token` header validation) |
| H8/M7 | CSP + `X-Frame-Options` + `X-Content-Type-Options` + `Referrer-Policy` in Caddyfile |
| M8 | Self-hosted Inter fonts (4 weights — Regular, Medium, SemiBold, Bold), eliminated Google Fonts CDN dependency |
| M9 | Zod runtime schema validation for API responses |
| M10 | Path traversal protection in GSD sidecar PUT handler |
| N1 | Documented Tailscale-as-TLS assumption |

**Pantalaimon decommission prep:**

- `pantalaimon_url` commented out in `agent-config.yaml`
- Removed from `infra.rs` health checks
- `CLAUDE.md` files updated across matrix-mcp and blackbox repos
- Decommission checklist prepared (actual service stop is manual)

---

## 3. Infrastructure: Claude Config Sync

Bidirectional sync of `~/.claude/` between Cloudkicker and Whitebox was implemented as part of this sprint:

- `~/dev/scripts/claude-config-sync.sh` — rsync-based sync with conflict detection
- `~/dev/scripts/claude-config-watch.sh` — `WatchPaths`-triggered auto-sync
- `launchd` agents installed on both machines
- Excludes ephemeral state (history, plans, sessions, cache)
- Syncs config files (CLAUDE.md, hooks, agents, skills, settings, projects/memory)

---

## 4. Commits

| Repo | SHA | Files | Insertions | Deletions |
|------|-----|-------|------------|-----------|
| matrix-mcp | `5eaccc0` | 28 | 885 | 55 |
| factory | `81311f8` | 23 | 3,916 | 257 |
| blackbox | `d2fa3d7` | 3 | 33 | 46 |
| **Total** | — | **54** | **4,834** | **358** |

---

## 5. Files Changed

### matrix-mcp (28 files)

**New files:**
- `src/identity/types.ts` — Agent identity and credential provider interfaces
- `src/identity/credential-providers.ts` — Environment-based credential loading
- `src/identity/device-store.ts` — Persistent device ID storage (0600 perms)
- `src/identity/crypto-setup.ts` — WASM Rust crypto initialization
- `src/identity/registry.ts` — Central identity registry
- `src/identity/polyfill.ts` — fake-indexeddb for Node.js
- `src/identity/index.ts` — Barrel export
- `src/auth/roomAllowlist.ts` — Per-agent room access control
- `src/tools/tier0/account-data.ts` — m.* write blocking
- `src/tools/tier0/relations.ts` — Room allowlist enforcement
- `src/tools/tier1/account-data.ts` — m.* write blocking (tier1)
- `src/tools/tier1/reactions.ts` — Room allowlist enforcement
- `tests/security.test.ts` — 8-test security suite
- `jest.config.cjs` — Test configuration

**Modified files:**
- `CLAUDE.md` — Updated architecture for E2EE, removed Pantalaimon references
- `package.json` — SDK upgrade, new dependencies
- `src/http-server.ts` — Polyfill import, shared-secret auth, identity init
- `src/stdio-server.ts` — Polyfill import, identity init
- `src/server.ts` — Listen host binding
- `src/matrix/client.ts` — Registry-aware client creation
- `src/matrix/clientCache.ts` — Token-hash cache keys, LRU eviction
- `src/schemas/toolSchemas.ts` — Removed matrixAccessToken
- `src/tools/tier0/messages.ts` — Room allowlist check
- `src/tools/tier0/rooms.ts` — Room allowlist check
- `src/tools/tier1/messaging.ts` — Pantalaimon fallback removed
- `src/tools/tier1/room-admin.ts` — Room allowlist check
- `src/tools/tier1/room-management.ts` — Room allowlist check
- `src/utils/server-helpers.ts` — Homeserver allowlist, auth helpers

### factory (23 files)

**New files:**
- `coordinator/src/identity_store.rs` — SQLite-backed E2EE state store
- `coordinator/src/matrix_native.rs` — Native Matrix client (matrix-sdk)
- `coordinator/src/matrix_legacy.rs` — Renamed from matrix.rs (rollback path)
- `portal/auth.py` — CSRF token generation and validation
- `portal/public/fonts/Inter-Regular.ttf` — Self-hosted font
- `portal/public/fonts/Inter-Medium.ttf` — Self-hosted font
- `portal/public/fonts/Inter-SemiBold.ttf` — Self-hosted font
- `portal/public/fonts/Inter-Bold.ttf` — Self-hosted font

**Modified files:**
- `coordinator/Cargo.toml` — matrix-sdk 0.16.0 with e2e-encryption + sqlite features
- `coordinator/Cargo.lock` — Updated dependency tree (+2,556 lines)
- `coordinator/src/config.rs` — E2EE settings, per-agent credentials
- `coordinator/src/coordinator.rs` — RBAC, rate limiting, HMAC on reactions, fail-closed whoami
- `coordinator/src/delegate.rs` — SSH param sanitization, path traversal protection
- `coordinator/src/agent.rs` — kill_on_drop, required trust_level
- `coordinator/src/infra.rs` — Absolute paths, removed Pantalaimon
- `coordinator/src/main.rs` — Module registration for new files
- `portal/Caddyfile` — CSP, X-Frame-Options, security headers
- `portal/VERSIONS.md` — Version history update
- `portal/package.json` — Zod dependency
- `portal/pnpm-lock.yaml` — Lock file update
- `portal/server.py` — GSD auth, path traversal protection
- `portal/src/lib/api.ts` — Zod schema validation, CSRF tokens, auth headers
- `portal/src/styles/app.css` — Inter font-face declarations

### blackbox (3 files)

- `CLAUDE.md` — Removed Pantalaimon from architecture diagram, services table, examples
- `src/agent-config.yaml` — Commented out `pantalaimon_url`, updated for native E2EE
- `src/coordinator-rs/src/infra.rs` — Removed Pantalaimon health check

---

## 6. Security Scorecard

| Severity | Before | After | Closed |
|----------|--------|-------|--------|
| CRITICAL | 4 | 0 | C1, C2, C3, C4 |
| HIGH | 6 | 0 | H1, H2, H3, H5, H9, H10, H11, H12 |
| MEDIUM | 10 | 0 (in scope) | M1–M10, M12–M16 |
| LOW | 4 | 0 (in scope) | L2, L5, L6, L9, L10 |
| **Total** | **24** | **0** | **24** |

**Path to A/A+:** FCT021 Phase 3 — API key rotation infrastructure, container sandboxing for agent subprocesses, secrets rotation API. Scoped as a separate epic.

---

## 7. Cutover Checklist

The following steps are required before full production cutover to native E2EE:

| Step | Status | Notes |
|------|--------|-------|
| Add 8 secrets to `secrets.env.age` / Bitwarden | Pending | 4 passwords + 4 recovery keys (Boot, IG-88, Kelk, Coord) |
| Deploy coordinator-rs with `--features native-e2ee` | Pending | Compile on Blackbox or cross-compile |
| Stop and disable Pantalaimon systemd service | Pending | Manual SSH to Blackbox |
| Archive `pan.db` | Pending | Move to `~/archive/` on Blackbox |
| Remove `matrix_token_*_pan` from `secrets.env.age` | Pending | 4 entries to remove |
| Cross-sign all agent devices from Element | Pending | See BKX058 for procedure |
| 48h monitoring window | Pending | Verify E2EE message delivery across all rooms |

---

## 8. Architecture Changes

### Before (Pantalaimon)

```
Agent → matrix-mcp → Pantalaimon (reverse proxy) → Synapse
                      ├── E2EE encrypt/decrypt
                      └── pan.db (key storage)
```

### After (Native Megolm)

```
Agent → matrix-mcp → IdentityRegistry → matrix-js-sdk (Rust crypto WASM) → Synapse
                      ├── EnvCredentialProvider
                      ├── DeviceStore (0600 perms)
                      └── SSSS + cross-signing bootstrap

Agent → coordinator-rs → NativeMatrixClient (matrix-sdk 0.16.0) → Synapse
                          ├── identity_store.rs (SQLite)
                          └── feature-gated: native-e2ee
```

**Key differences:**
- No reverse proxy — E2EE handled natively in each component
- Credential management via environment variables, not shared token files
- Device persistence per-agent with strict file permissions
- Feature-gated rollback path in coordinator-rs (`matrix_legacy.rs` retained)

---

## 9. Open Items

| Item | Status | Notes |
|------|--------|-------|
| Cutover checklist (Section 7) | Pending | Requires SSH to Blackbox + Bitwarden updates |
| FCT021 Phase 3 | Future | API key infra, container sandboxing, secrets rotation |
| Portal deployment to Blackbox | Pending | `make sync` after cutover |
| Vault reindex | Pending | `~/dev/scripts/reindex-vault.sh` after doc creation |

---

## References

[1] FCT020, "Factory Security Audit — Red-Hat Team Assessment," 2026-03-21.
[2] FCT021, "Security Hardening Roadmap — B- to A+," 2026-03-21.
[3] BKX126, "Pantalaimon to Native Megolm E2EE Migration Plan."
[4] BKX058, "Element Cross-Signing Procedure."
