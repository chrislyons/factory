# FCT021 Security Hardening Roadmap — B- to A+

**Date:** 2026-03-21
**Basis:** FCT020 Factory Security Audit — Red-Hat Team Assessment
**Current Grade:** B-
**Target Grade:** A+

---

## Assessment Summary

Factory's architecture is sound. Trust levels, approval gates, HMAC signing, circuit breakers, shell metacharacter detection, and audit logging are already in place. No hardcoded secrets exist anywhere in the codebase. The gap from B- to A+ is not a redesign — it is finishing enforcement that the architecture already supports, hardening the matrix-mcp flank, and adding the multi-tenant/public-release layer.

---

## Phase 1: B- to A- (Immediate Fixes)

**Effort:** ~2 days focused work
**Outcome:** Eliminates all 4 CRITICAL and worst HIGH findings

| # | Finding | Action | Component | Effort |
|---|---------|--------|-----------|--------|
| 1 | C3 | Upgrade `@modelcontextprotocol/sdk` to >= 1.26.0 | matrix-mcp | 15min |
| 2 | C4/H11 | Default `LISTEN_HOST` to `127.0.0.1`; add shared-secret auth for non-OAuth HTTP mode | matrix-mcp | 2h |
| 3 | H9 | Validate `homeserverUrl` against allowlist; ignore headers in non-OAuth mode | matrix-mcp | 1h |
| 4 | H10 | Remove `matrixAccessToken` from MCP tool input schemas | matrix-mcp | 30min |
| 5 | H12 | Run `npm audit fix` — resolve all 5 high-severity dependency vulns | matrix-mcp | 15min |
| 6 | H1 | Sanitize `repo`/`model` in delegate SSH command — alphanumeric+hyphen+slash whitelist | coordinator | 1h |
| 7 | H2 | Make HMAC signer mandatory; fail closed (deny) when signer is unavailable | coordinator | 2h |
| 8 | H3/H4 | Remove `send-message`, `send-direct-message`, `send-reaction`, `add_memory` from `AUTO_APPROVE_TOOLS` | coordinator | 30min |

**Verification:** After completing Phase 1, re-run the secrets scan and npm audit to confirm clean results. All 4 CRITICALs and 5 HIGHs should be resolved.

---

## Phase 2: A- to A (Sprint-Level Hardening)

**Effort:** ~2 weeks
**Outcome:** Closes all remaining HIGH and MEDIUM findings; establishes defense-in-depth

### Coordinator Hardening

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 9 | C1 | Implement per-command RBAC on slash commands — map trust levels to command permissions | 1d |
| 10 | C2 | Extend HMAC verification to Matrix reaction-based approval path | 1d |
| 11 | H5 | Add path validation to delegate `Edit`/`Write` auto-approve — verify file paths are within delegate working directory | 2h |
| 12 | M2 | Change agent subprocesses to `kill_on_drop(true)` — prevent unsupervised orphans | 30min |
| 13 | M3 | Require explicit `trust_level` in agent config — fail startup if any agent lacks it | 1h |
| 14 | M1 | Restrict `/loop start` spec paths to a configured directory — prevent path traversal | 1h |
| 15 | M5 | Add rate limiting to slash commands (especially `/delegate`) | 2h |
| 16 | M6 | Fail startup if `whoami()` fails — remove `@coord:matrix.org` fallback | 30min |
| 17 | M16 | Add `..` to glob_match metacharacter deny regex | 30min |
| 18 | L2 | Install `cargo-audit`; add to CI/pre-commit | 30min |
| 19 | L5 | Use absolute paths for system commands in infra health checks | 1h |
| 20 | M4/L6 | Write sync token file and session IDs with mode `0600` | 30min |

### Matrix MCP Hardening

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 21 | M12 | Implement room allowlist per agent identity — restrict which rooms each agent can access | 4h |
| 22 | M13 | Include access token hash in client cache key — prevent session hijack | 1h |
| 23 | M14 | Default `NODE_ENV` to `production` in startup; tighten `ALLOW_SELF_SIGNED_CERTS` guard | 30min |
| 24 | M15 | Block `m.*` type writes in `set-account-data` — implement prefix allowlist | 1h |
| 25 | L10 | Add test suite for security-critical paths (token exchange, access control, input validation) | 1d |
| 26 | L9 | Add LRU eviction to client cache with max size | 1h |

### Portal & Network Hardening

| # | Finding | Action | Effort |
|---|---------|--------|--------|
| 27 | H6/H6a | Add authentication to GSD sidecar (server.py) — shared secret or token validation | 4h |
| 28 | H7 | Add CSRF tokens to all state-changing portal requests | 4h |
| 29 | H8/M7 | Add CSP + `X-Frame-Options` headers to Caddy config | 2h |
| 30 | M8 | Self-host Inter font or add SRI hashes — eliminate external CSS dependency | 2h |
| 31 | M9 | Add Zod runtime schema validation for API responses in portal | 4h |
| 32 | M10 | Use `pathlib.Path.resolve()` in GSD sidecar PUT handler — verify resolved path starts with `DATA_ROOT` | 1h |
| 33 | N1 | Document Tailscale-as-TLS assumption; add TLS termination config for non-Tailscale deployments | 2h |

**Verification:** Full re-audit after Phase 2. All HIGH and MEDIUM findings should be resolved. Run `cargo audit`, `npm audit`, and manual slash-command permission testing.

---

## Phase 3: A to A+ (Public-Release Hardening)

**Effort:** ~4-6 weeks
**Outcome:** Production-grade security for multi-tenant public deployment

### API Key Infrastructure

| # | Action | Effort |
|---|--------|--------|
| 34 | Implement bearer token authentication for all API endpoints (per Paperclip pattern) | 3d |
| 35 | Hash API keys at rest in database — store hash + salt, never plaintext | 1d |
| 36 | Per-agent key management — generate, revoke, rotate via API | 2d |
| 37 | Rate limiting on all authenticated endpoints | 1d |

### Multi-Tenant Isolation

| # | Action | Effort |
|---|--------|--------|
| 38 | Add `company_id` / `tenant_id` scoping to all domain entities (agents, jobs, loops, budgets) | 3d |
| 39 | Enforce tenant access checks at every route entry point | 2d |
| 40 | Unique constraints on `(tenant_id, identifier)` for cross-tenant isolation | 1d |
| 41 | Tenant-scoped audit logging | 1d |

### Container Sandboxing

| # | Action | Effort |
|---|--------|--------|
| 42 | Implement Docker-based agent execution with `cap_drop: ALL`, `no-new-privileges: true` | 2d |
| 43 | tmpfs `/tmp` with size limits for agent workspaces | 4h |
| 44 | Volume isolation — dedicated home/work directories per agent | 4h |
| 45 | Network policy — restrict agent container egress to approved endpoints only | 1d |

### Secrets & Configuration

| # | Action | Effort |
|---|--------|--------|
| 46 | Programmatic secrets management service — pluggable providers, rotation API, audit trail | 3d |
| 47 | Configuration versioning with JSONB snapshots and rollback support | 2d |
| 48 | Complete Bitwarden migration for Blackbox (currently uses age encryption) | 4h |

### Observability & Compliance

| # | Action | Effort |
|---|--------|--------|
| 49 | Extend activity audit logging across all services (portal, sidecar, matrix-mcp — not just coordinator) | 2d |
| 50 | Sanitize all log output — ensure no credentials appear in tracing/JSON logs | 1d |
| 51 | Implement log retention and rotation policy | 4h |
| 52 | Commission independent third-party security audit | External |

---

## Grading Criteria

| Grade | Criteria | Status |
|-------|----------|--------|
| **B-** | No hardcoded secrets; good architectural patterns; specific exploitable gaps in auth, injection, and auto-approve | **Current** |
| **B+** | All CRITICALs resolved; no unauthenticated write endpoints; HMAC mandatory | After Phase 1 |
| **A-** | All CRITICALs and HIGHs resolved; defense-in-depth on all services | After Phase 1 + coordinator/portal hardening |
| **A** | All MEDIUM findings resolved; test coverage on security paths; CSP/CSRF/SRI in place; room allowlists enforced | After Phase 2 |
| **A+** | Multi-tenant isolation; API key auth; container sandboxing; secrets rotation API; third-party audit passed | After Phase 3 |

---

## Key Insight

The gap from B- to A- is ~2 days because the architecture already supports the fixes — trust levels exist but aren't enforced on commands, HMAC signing exists but falls back to unsigned, auto-approve lists just need entries removed. The gap from A to A+ is the multi-tenant/public-release layer which is new construction, not bug-fixing. The hardest part is already built.

---

*Derived from FCT020 Red-Hat Team Assessment (9 coordinated subagents, 2026-03-21)*

*Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>*
