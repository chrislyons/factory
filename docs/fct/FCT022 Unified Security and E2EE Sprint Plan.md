# FCT022 — Unified Security & E2EE Sprint Plan

## Context

Two independent workstreams — BKX126 (Pantalaimon → native Megolm E2EE) and FCT021 (security hardening B- → A+) — share significant overlap in files, systems, and sequencing. This plan merges them into a single execution sequence that eliminates redundant work, respects dependencies, and produces a system that is both E2EE-native and hardened to A- grade (with a clear path to A/A+).

**Why now:** Whitebox (Mac Studio) is coming online. Pantalaimon's `pan.db` is device-bound and non-portable. Eliminating it makes the stack hardware-agnostic. Simultaneously, FCT020's red-hat assessment identified 4 CRITICAL and 13 HIGH findings that must be resolved before any public release.

**Key architectural fact:** coordinator-rs (Rust, ~11,600 LOC) is the live production coordinator. BKX126 was written targeting the legacy TypeScript coordinator — Phase 3 must be adapted for Rust using the `matrix-sdk` crate with native Vodozemac E2EE.

**Recent commits (verified):** `d5d004d` already implements cookie-based HMAC session auth for the portal (partially addressing H6). CSP/CSRF/X-Frame-Options still needed.

---

## Sprint 0: Quick Wins (2 days)

**Goal:** B- → B+ — eliminate all 4 CRITICALs and worst HIGHs. Zero E2EE dependency.

### matrix-mcp fixes

| # | Finding | Action | File |
|---|---------|--------|------|
| 1 | C3 | Upgrade `@modelcontextprotocol/sdk` to `>= 1.26.0` | `matrix-mcp/package.json` |
| 2 | C4/H11 | Default `LISTEN_HOST` to `127.0.0.1`; add shared-secret auth header validation for non-OAuth HTTP mode | `matrix-mcp/src/http-server.ts` |
| 3 | H9 | Validate `homeserverUrl` against allowlist; ignore caller-provided headers in non-OAuth mode | `matrix-mcp/src/utils/server-helpers.ts` |
| 4 | H10 | Remove `matrixAccessToken` from MCP tool input schemas | `matrix-mcp/src/schemas/toolSchemas.ts` |
| 5 | H12 | Run `npm audit fix` — resolve all high-severity dependency vulns | `matrix-mcp/package-lock.json` |

### coordinator-rs fixes

| # | Finding | Action | File |
|---|---------|--------|------|
| 6 | H1 | Sanitize `repo`/`model` in delegate SSH command — alphanumeric+hyphen+slash+dot whitelist regex | `coordinator/src/delegate.rs` (lines 89-101) |
| 7 | H2 | Make HMAC signer mandatory; fail closed (deny) when signer unavailable | `coordinator/src/coordinator.rs` |
| 8 | H3/H4 | Remove `send-message`, `send-direct-message`, `send-reaction`, `add_memory` from `AUTO_APPROVE_TOOLS` | `coordinator/src/coordinator.rs` |

### Verification
- `npm audit` clean on matrix-mcp
- matrix-mcp starts with `LISTEN_HOST=127.0.0.1` by default
- Delegate command with metacharacters is rejected
- HMAC signer failure → startup error (not silent fallback)
- All 4 CRITICALs resolved

---

## Sprint 1: E2EE Foundation — IdentityRegistry Module (3-4 days)

**Goal:** Build the shared TypeScript E2EE module; single-identity smoke test.

### New files: `matrix-mcp/src/identity/`

| File | Purpose |
|------|---------|
| `types.ts` | `IdentityConfig`, `MatrixIdentity`, `CredentialProvider` interfaces |
| `credential-providers.ts` | `EnvCredentialProvider`, `AgeCredentialProvider`, `BitwardenCredentialProvider` |
| `device-store.ts` | Per-identity `device_id` persistence to `${stateDir}/device-${sanitizedUserId}.json` |
| `crypto-setup.ts` | `initializeCrypto(client, recoveryKey)` — SSSS callback + `initRustCrypto()` |
| `registry.ts` | `IdentityRegistry` class: `register()`, `unregister()`, `get()`, `reconcile()`, `shutdownAll()` |
| `polyfill.ts` | `import 'fake-indexeddb/auto'` — must be first import in every entry point |
| `index.ts` | Barrel export |

### Dependencies to add
- `fake-indexeddb` — IndexedDB polyfill for Node.js (WASM crypto store)
- matrix-js-sdk already at `^38.2.0`

### Secrets (manual step)
- Add 8 new secrets to `secrets.env.age` / Bitwarden: `MATRIX_PASSWORD_{BOOT,COORD,IG88,KELK}` + `MATRIX_RECOVERY_KEY_{BOOT,COORD,IG88,KELK}`

### Verification
- Register single identity (Coord) on Blackbox
- Verify decryption of messages in encrypted room
- Verify sending encrypted messages
- Verify `device_id` persists across restart
- Verify SSSS key restore (no new device in Element)
- Confirm WASM crypto loads on ARM64

---

## Sprint 2: matrix-mcp E2EE Migration + Security Hardening (4-5 days)

**Goal:** Both MCP instances running native E2EE; remaining matrix-mcp security findings closed.

### E2EE migration (both instances: Boot :8445, Coord :8448)

| File | Change |
|------|--------|
| `src/http-server.ts` | Add polyfill import (first line). Initialize `IdentityRegistry` before Express. |
| `src/stdio-server.ts` | Same polyfill import + eager init |
| `src/matrix/client.ts` | Rewrite: `createMatrixClient()` → get client from `IdentityRegistry.get(userId)` |
| `src/matrix/clientCache.ts` | Replace TTL cache with thin wrapper around registry |
| `src/tools/tier1/messaging.ts` | **Delete lines 98-123** — Pantalaimon fallback block |
| `src/utils/server-helpers.ts` | Remove `getAccessToken()`, simplify to registry lookup |

### Security hardening (merged into same sprint)

| # | Finding | Action | File |
|---|---------|--------|------|
| 9 | M12 | Implement room allowlist per agent identity | `src/matrix/client.ts` or new `src/auth/roomAllowlist.ts` |
| 10 | M13 | Include access token hash in client cache key | `src/matrix/clientCache.ts` (may be moot after registry rewrite) |
| 11 | M14 | Default `NODE_ENV=production` in startup; tighten `ALLOW_SELF_SIGNED_CERTS` | `src/http-server.ts` |
| 12 | M15 | Block `m.*` type writes in `set-account-data` | `src/tools/tier1/account.ts` or equivalent |
| 13 | L10 | Add test suite for security-critical paths | `tests/security.test.ts` |
| 14 | L9 | LRU eviction with max size on client cache | `src/matrix/clientCache.ts` (may be moot) |

### Startup command change
```bash
# Before: MATRIX_TOKEN_BOOT_PAN → MATRIX_ACCESS_TOKEN
# After:  MATRIX_PASSWORD_BOOT + MATRIX_RECOVERY_KEY_BOOT → native E2EE
```

### Verification
1. Start Boot MCP → crypto init + PREPARED in logs
2. `mcp__matrix-boot__get-room-messages` in encrypted room → decrypted text
3. `mcp__matrix-boot__send-message` to encrypted room → succeeds
4. Element shows MCP device as verified
5. Restart → same `device_id`, repeat tests
6. Repeat all for Coord MCP (port 8448)
7. Room allowlist rejects unauthorized room access
8. `npm audit` still clean

---

## Sprint 3: Coordinator-rs Security Hardening (5-7 days)

**Goal:** Close all remaining coordinator HIGH and MEDIUM findings. Can run in parallel with Sprint 2 (different codebase).

### Coordinator hardening

| # | Finding | Action | File | Effort |
|---|---------|--------|------|--------|
| 15 | C1 | Per-command RBAC on slash commands — map trust levels to command permissions | `coordinator.rs` | 1d |
| 16 | C2 | Extend HMAC verification to Matrix reaction-based approval path | `coordinator.rs` / `approval.rs` | 1d |
| 17 | H5 | Path validation on delegate `Edit`/`Write` auto-approve — verify within delegate `worker_cwd` | `delegate.rs` | 2h |
| 18 | M2 | Change agent subprocesses to `kill_on_drop(true)` | `agent.rs` | 30min |
| 19 | M3 | Require explicit `trust_level` in config — fail startup if missing | `config.rs` | 1h |
| 20 | M1 | Restrict `/loop start` spec paths to configured directory | `coordinator.rs` / `loop_engine.rs` | 1h |
| 21 | M5 | Rate limiting on slash commands (especially `/delegate`) | `coordinator.rs` | 2h |
| 22 | M6 | Fail startup if `whoami()` fails — remove `@coord:matrix.org` fallback | `coordinator.rs` | 30min |
| 23 | M16 | Add `..` to `glob_match` metacharacter deny regex | `coordinator.rs` | 30min |
| 24 | L2 | Install `cargo-audit`; add to CI/pre-commit | `Cargo.toml` / scripts | 30min |
| 25 | L5 | Use absolute paths for system commands in infra health checks | `infra.rs` | 1h |
| 26 | M4/L6 | Write sync token file and session IDs with mode `0600` | `matrix.rs` | 30min |

### Verification
- `cargo test` passes (41 existing + new tests)
- `cargo audit` clean
- Slash command RBAC: non-operator user cannot `/approve` or `/delegate`
- HMAC verification on Matrix reaction approvals
- Agent subprocess orphan test (kill coordinator, verify agents die)
- Sync tokens file permissions: `stat -c %a ~/.config/ig88/sync-tokens.json` → `600`

---

## Sprint 4: Coordinator-rs E2EE Migration (7-10 days)

**Goal:** Replace raw Pantalaimon HTTP with native `matrix-sdk` E2EE. This is the riskiest sprint.

### Dependency addition
```toml
# Cargo.toml
matrix-sdk = { version = "0.9", features = ["e2e-encryption", "sqlite"] }
```

### Architecture change

**From:** `MatrixClient` struct using reqwest raw HTTP → Pantalaimon at `127.0.0.1:8009`
**To:** `MatrixClient` wrapping `matrix_sdk::Client` with native Vodozemac E2EE → `matrix.org` direct

### Files to modify

| File | Change |
|------|--------|
| `Cargo.toml` | Add `matrix-sdk` with `e2e-encryption` + `sqlite` features |
| `src/matrix.rs` (654 lines) | **Major rewrite**: Replace reqwest `MatrixClient` with `matrix_sdk::Client` wrapper. Preserve same public API surface (`send_message`, `sync`, `send_typing`, etc.) |
| `src/config.rs` | Add E2EE config: `homeserver_url`, `state_dir`, `credential_backend`; remove `pantalaimon_url` |
| `src/coordinator.rs` | Update `MatrixClient::new()` calls — password login instead of token; crypto init at startup |
| `src/main.rs` | Startup: init crypto store, login, verify cross-signing before starting sync loop |

### Key implementation decisions

1. **Crypto store:** SQLite-backed (`matrix-sdk` `sqlite` feature) — persistent across restarts, no re-download of room keys
2. **Login flow:** Password login → bootstrap cross-signing → verify device
3. **Credential source:** Environment variables via `mcp-env.sh` (same as matrix-mcp)
4. **Multi-identity:** coordinator-rs uses one identity per agent (4 total). Each gets its own `matrix_sdk::Client` instance with separate SQLite store
5. **Sync approach:** Replace manual `/sync` polling with `matrix_sdk::Client::sync()` or retain manual control via `matrix_sdk::Client::sync_once()`
6. **Memory:** matrix-sdk with SQLite uses less memory than matrix-js-sdk WASM. Expect ~80-150MB for 4 clients

### Verification
1. `cargo build` succeeds (ARM64 cross-compile or native on RP5)
2. `cargo test` passes
3. Coordinator starts: each agent shows crypto init, device verification
4. DM to Boot → response arrives (E2EE room)
5. @mention in Backrooms → multi-agent routing works
6. Approval flow (emoji reactions) works
7. Delegate sessions work
8. `/health`, `/agent list` commands work
9. Element: all agent devices verified
10. Monitor 48h: no message gaps, no crypto errors, no dupes

---

## Sprint 5: Portal Hardening + Pantalaimon Decommission (3-4 days)

**Goal:** Close portal findings; decommission Pantalaimon; reach A- grade.

### Portal hardening

| # | Finding | Action | File |
|---|---------|--------|------|
| 27 | H6a | Add shared-secret auth to GSD sidecar (validate `X-Internal-Auth` header) | `portal/server.py` |
| 28 | H7 | Add CSRF tokens to all state-changing requests (cookie auth already in place from `d5d004d`) | `portal/auth.py` + frontend forms |
| 29 | H8/M7 | Add CSP + `X-Frame-Options: DENY` headers to Caddyfile | `portal/Caddyfile` |
| 30 | M8 | Self-host Inter font or add SRI hashes — eliminate external CSS dependency | `portal/src/styles/` |
| 31 | M9 | Add Zod runtime schema validation for API responses | `portal/src/lib/api.ts` |
| 32 | M10 | Use `pathlib.Path.resolve()` in GSD sidecar PUT — verify resolved path starts with `DATA_ROOT` | `portal/server.py` |
| 33 | N1 | Document Tailscale-as-TLS assumption | `docs/fct/FCT022.md` or README |

### Pantalaimon decommission (after 48h clean operation)

1. `systemctl --user stop pantalaimon && systemctl --user disable pantalaimon`
2. Remove Pantalaimon from coordinator health check service list
3. Remove old `matrix_token_*_pan` entries from `secrets.env.age`
4. Archive `pan.db`: `cp ~/.local/share/pantalaimon/pan.db ~/backups/pan.db.$(date +%F)`
5. Update CLAUDE.md files: remove Pantalaimon references, update architecture diagrams
6. Update `docs/repo-commands.html`: remove Pantalaimon commands

### Post-migration re-verification
- Cross-sign all agent devices from Element (BKX058 automation tool)
- Verify in Element: all agent devices show green checkmark

### Verification
- Portal: CSP header present in responses
- Portal: CSRF token required for mutations
- GSD sidecar: requests without auth header rejected
- Pantalaimon service disabled and not running
- All Matrix communication working without Pantalaimon
- 48h monitoring window clean

---

## Sprint 6 (Future): A to A+ — Not in this sprint cycle

Phase 3 of FCT021 (API key infrastructure, multi-tenant isolation, container sandboxing, secrets rotation API, third-party audit) is a separate epic estimated at 4-6 weeks. Deferred.

---

## Dependency Graph

```
Sprint 0 (quick wins)
    │
    ├──► Sprint 1 (IdentityRegistry)
    │        │
    │        └──► Sprint 2 (matrix-mcp E2EE + security)
    │                 │
    │                 └──► Sprint 5 (portal + decommission)
    │
    └──► Sprint 3 (coordinator-rs security) ◄── can run in parallel with Sprint 1+2
             │
             └──► Sprint 4 (coordinator-rs E2EE)
                      │
                      └──► Sprint 5 (portal + decommission)
```

Sprint 5 gates on both Sprint 2 AND Sprint 4 completing (all Pantalaimon consumers migrated).

---

## Effort Summary

| Sprint | Focus | Effort | Cumulative |
|--------|-------|--------|------------|
| 0 | Quick wins (CRITICALs + worst HIGHs) | 2d | 2d |
| 1 | IdentityRegistry module | 3-4d | 5-6d |
| 2 | matrix-mcp E2EE + MCP security | 4-5d | 9-11d |
| 3 | Coordinator-rs security (parallel) | 5-7d | 9-11d (parallel) |
| 4 | Coordinator-rs E2EE | 7-10d | 16-21d |
| 5 | Portal + decommission | 3-4d | 19-25d |
| **Total** | | **~4-5 weeks** | B- → A- |

---

## Key Files

| File | Sprints | Role |
|------|---------|------|
| `~/dev/matrix-mcp/src/matrix/client.ts` | 2 | Rewrite for IdentityRegistry |
| `~/dev/matrix-mcp/src/matrix/clientCache.ts` | 2 | Replace TTL → registry wrapper |
| `~/dev/matrix-mcp/src/tools/tier1/messaging.ts` | 2 | Delete Pantalaimon fallback |
| `~/dev/matrix-mcp/src/http-server.ts` | 0, 2 | LISTEN_HOST fix + polyfill |
| `~/dev/matrix-mcp/src/utils/server-helpers.ts` | 0, 2 | Homeserver allowlist + simplify |
| `~/dev/matrix-mcp/package.json` | 0, 1 | SDK upgrade + fake-indexeddb |
| `~/dev/factory/coordinator/src/matrix.rs` | 4, 3 | E2EE rewrite + file permissions |
| `~/dev/factory/coordinator/src/coordinator.rs` | 0, 3 | HMAC, RBAC, auto-approve |
| `~/dev/factory/coordinator/src/delegate.rs` | 0, 3 | SSH sanitization, path validation |
| `~/dev/factory/coordinator/src/approval.rs` | 3 | HMAC on reactions |
| `~/dev/factory/coordinator/src/agent.rs` | 3 | kill_on_drop |
| `~/dev/factory/coordinator/src/config.rs` | 3, 4 | Trust level required + E2EE config |
| `~/dev/factory/coordinator/Cargo.toml` | 4 | Add matrix-sdk |
| `~/dev/factory/portal/server.py` | 5 | GSD sidecar auth |
| `~/dev/factory/portal/Caddyfile` | 5 | CSP + X-Frame-Options |
| `~/dev/factory/portal/src/lib/api.ts` | 5 | Zod validation |

---

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| `matrix-sdk` on ARM64 RP5 | Build may fail or perf issues | Test early; Whitebox (M1 Max) is fallback host |
| 4 SDK clients memory on 8GB RP5 | ~200-400MB additional RSS | Monitor; SQLite stores are more efficient than JS WASM; Whitebox has 32GB |
| SSSS restore fails for an agent | That agent can't decrypt history | Test each identity individually in Sprint 1 |
| Message gaps during cutover | Missed agent responses | Run Pantalaimon in parallel until Sprint 5 verified |
| Coordinator sync loop refactor | All agents down | Sprint 4 is last migration; rollback = git revert + re-enable Pantalaimon |
| Cross-signing ceremony | Devices appear unverified | BKX058 automation tool handles bulk signing |
| Cookie auth without CSRF | Session riding attacks | Sprint 5 adds CSRF tokens; network isolation (Tailscale) provides interim protection |
