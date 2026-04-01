# FCT040 Red-Team Security Audit — Auth, Coordinator, and Infrastructure

> **Note (2026-03-31):** Port assignments referenced in this document (MLX-LM on 41960–41963, F-18 finding) are superseded by the 2026-03-31 MLX re-plumb sprint and the subsequent infrastructure re-plumb. Current MLX assignments: Boot→41961, Kelk→41962, Nan→41963, IG-88→41988, Reasoning→41966, Coordinator reserved→41960. Current infra ports: Pantalaimon→41200, FalkorDB→41430, Graphiti MCP→41440, Qdrant HTTP→41450, Qdrant gRPC→41455, Qdrant MCP→41460, Research MCP→41470, Matrix MCP Coord→41400, Matrix MCP Boot→41401. The F-18 finding (services bound to 0.0.0.0) remains open — the specific port list has changed. See FCT002 section 2.3 and infra/ports.csv for the authoritative port tables.

**Session:** Red-Team Audit — Three Independent Agents
**Date:** 2026-03-24
**Scope:** Full-stack security review of the factory multi-agent system (auth layer, coordinator-rs internals, and infrastructure/supply chain)
**Auditors:** rt-auth (auth and routing surface), rt-coordinator (coordinator internals and agent trust), rt-infra (infrastructure, secrets, and supply chain)
**Status:** Complete

---

## Executive Summary

A three-agent red-team exercise audited the factory system across its auth layer, coordinator-rs internals, and deployment infrastructure. Each agent operated independently with minimal context, then findings were consolidated and deduplicated. The audit surfaced **2 Critical**, **7 High**, and **9 Medium** severity findings across 24 total unique issues.

The most severe exposure is a combination attack: the Caddy auth gate validates cookie *presence* but not *signature*, meaning any request with `factory_session=anything` bypasses the login redirect entirely — the HMAC-verified auth sidecar is never consulted for protected routes. This is compounded by the GSD sidecar silently disabling authentication when `GSD_AUTH_SECRET` is unset, making unauthenticated writes to job and task data possible from within the network. Separately, BWS secret UUIDs committed to git across all six plist files map the entire secret inventory to publicly discoverable identifiers. A compromised machine account token (which has already leaked once, 2026-03-23) resolves all UUIDs to live secret values.

Within coordinator-rs, the delegate symlink bypass and the `--permission-mode auto` invisibility gap represent structural bypasses of the approval pipeline rather than configuration weaknesses — they require code-level fixes. The frozen harness enforcement, inter-agent routing privilege escalation, and budget non-enforcement compound the trust model risk for autonomous agents.

The system has a solid foundation in several areas: HMAC-signed approvals, identity drift detection, circuit breakers, and allowlist-based Matrix access control are all well-implemented. The remediation priority below addresses the auth bypass chain first, secrets hygiene second, and coordinator structural fixes in a third pass.

---

## Consolidated Findings Table

| ID | Severity | Title | Agent(s) |
|----|----------|-------|---------|
| F-01 | CRITICAL | BWS secret UUIDs committed to git in plist files | rt-infra |
| F-02 | CRITICAL | Hardcoded bcrypt hash in source code | rt-auth |
| F-03 | HIGH | Caddy validates cookie presence, not signature | rt-auth, rt-infra |
| F-04 | HIGH | Delegate Edit/Write path traversal via symlinks | rt-coordinator |
| F-05 | HIGH | Frozen harness bypass via shell obfuscation | rt-coordinator |
| F-06 | HIGH | `--permission-mode auto` makes tool calls invisible to coordinator | rt-coordinator |
| F-07 | HIGH | Session cookie missing Secure flag | rt-auth |
| F-08 | HIGH | GSD sidecar auth silently disabled when `GSD_AUTH_SECRET` unset | rt-auth |
| F-09 | MEDIUM | Filesystem approval `request_id` path traversal | rt-auth |
| F-10 | MEDIUM | Inter-agent routing bypasses allowlist and trust levels | rt-auth, rt-coordinator |
| F-11 | MEDIUM | Login redirect parameter reflected into DOM without sanitization | rt-auth |
| F-12 | MEDIUM | Approval reactions accepted from any room member | rt-coordinator |
| F-13 | MEDIUM | Shell metachar regex missing newline characters | rt-coordinator |
| F-14 | MEDIUM | Budget enforcement advisory-only (soft limit, no circuit-breaker) | rt-coordinator |
| F-15 | MEDIUM | Filesystem approval directory writable — HMAC oracle exposure | rt-coordinator |
| F-16 | MEDIUM | JSON injection in watchdog Matrix alerts | rt-infra |
| F-17 | MEDIUM | SSH with `StrictHostKeyChecking=no` in watchdog | rt-infra |
| F-18 | MEDIUM | 11 services bound to 0.0.0.0, MLX-LM unauthenticated | rt-infra |
| F-19 | MEDIUM | curl-pipe-bash installs without integrity checks | rt-infra |
| F-20 | LOW | CSRF layer inert due to Caddy never calling forward_auth | rt-auth |
| F-21 | LOW | `routing_hop_counts` HashMap grows unboundedly | rt-auth |
| F-22 | LOW | `glob_match` cannot handle multi-star deny patterns | rt-coordinator |
| F-23 | LOW | DM routing returns all agents (fragile design) | rt-coordinator |
| F-24 | LOW | Docker `:latest` tag without digest pinning | rt-infra |
| F-25 | LOW | Remote `npm install` without lockfile enforcement | rt-infra |

---

## Full Findings Detail

### CRITICAL

#### F-01 — BWS Secret UUIDs Committed to Git
**Files:** `plists/com.bootindustries.coordinator-rs.plist` (lines 10–17), `plists/com.bootindustries.matrix-mcp-boot.plist` (line 12), `plists/com.bootindustries.matrix-mcp-coord.plist` (line 12), `plists/com.bootindustries.factory-auth.plist` (lines 12–13), `plists/com.bootindustries.qdrant-mcp.plist` (line 12), `plists/com.bootindustries.research-mcp.plist` (line 12)
**Agent:** rt-infra

All 12 plist files in `plists/` are tracked by git. The `plists/` directory is absent from `.gitignore`. These plists pass Bitwarden Secrets Manager UUIDs as arguments to `mcp-env.sh`. The coordinator plist alone references 7 UUIDs covering all 4 Matrix agent tokens, the Graphiti auth token, the OpenRouter API key, and the Anthropic API key. At least two commits (`d4197cd`, `157e5ac`) have baked these UUIDs into git history.

UUIDs are lookup keys, not secrets themselves, but they map the entire secret inventory. Combined with a compromised BWS machine account access token — which already leaked once on 2026-03-23 — an attacker resolves every UUID to its live secret value.

**Remediation:** Add `plists/` to `.gitignore`. Run `git rm --cached plists/\*.plist`. Purge history with BFG Repo Cleaner or `git filter-repo`. Regenerate any secrets whose UUIDs are now public, evaluate whether rotation of the machine account token is warranted given history.

---

#### F-02 — Hardcoded bcrypt Hash in Source Code
**File:** `portal/auth.py:29`
**Agent:** rt-auth

The bcrypt password hash is hardcoded as the default fallback for `AUTH_BCRYPT_HASH`. This hash is committed to git. If `AUTH_BCRYPT_HASH` is not set at deploy time, this hardcoded hash IS the production credential. An attacker with repo access can run hashcat or john offline against the `$2a$14$` hash. Cost factor 14 is reasonable but provides no protection once the hash is in version control.

**Attack scenario:** Clone the repo, run an offline brute-force against the committed hash, authenticate to the portal as `nesbitt`.

**Remediation:** Remove the hardcoded fallback entirely. Make `AUTH_BCRYPT_HASH` a required env var; fail startup with a clear error if unset. Rotate the password if it has been deployed without the env var set. Purge the hash from git history.

---

### HIGH

#### F-03 — Caddy Validates Cookie Presence, Not Signature
**Files:** `portal/Caddyfile:36–43`
**Agents:** rt-auth, rt-infra

Caddy's `@no_session` matcher uses a regex that checks whether a cookie named `factory_session` exists (`.+`). It does not validate the cookie's HMAC signature or expiry. The actual validation lives in the auth sidecar on port 41914, but the Caddyfile never calls `forward_auth` to that sidecar for protected routes — the `/auth/*` handle proxies to 41914, but protected routes only check `@has_session` (presence only).

**Attack scenario:** Set `factory_session=anything` in the browser. Caddy's `@no_session` matcher does not match, so the redirect-to-login gate is bypassed. The attacker accesses `/jobs.json`, `/tasks.json`, `/status/*`, and all portal pages with no valid credential. The auth sidecar has correct HMAC verification but is never consulted for access control on protected routes.

Note (from MEMORY.md): "Caddy does NOT have `forward_auth` module on this build (v2.11.2)" — the mitigation requires a design change at the Caddy layer, not a module upgrade.

**Remediation:** Rewrite the Caddyfile gate as a Caddy `request_header` → `reverse_proxy` subrequest pattern or replace the cookie check with a Lua/exec plugin that calls the auth sidecar. Alternatively, migrate cookie validation into a Caddy middleware script. Until resolved, treat the portal as unauthenticated on the network.

---

#### F-04 — Delegate Edit/Write Path Traversal via Symlinks
**File:** `coordinator/src/delegate.rs:314–325`
**Agent:** rt-coordinator

The delegate auto-approval logic for `Edit` and `Write` tools checks only for the literal string `..` in `file_path`. It does not resolve symlinks or canonicalize the path before checking containment. An agent can request an Edit on a symlink that points outside its working directory — the path contains no `..` and passes the check.

**Attack scenario:** A compromised Claude agent creates a symlink inside its working directory pointing to `~/.ssh/authorized_keys` or `~/.config/ig88/mcp-env.sh`, then issues a Write tool call targeting the symlink path. The coordinator auto-approves and overwrites the target file.

**Remediation:** Use `std::fs::canonicalize()` on both the `file_path` and the `working_dir` before the containment check, and verify the canonical path still falls within the canonical working directory.

---

#### F-05 — Frozen Harness Bypass via Shell Obfuscation
**File:** `coordinator/src/coordinator.rs:1349–1362`
**Agent:** rt-coordinator

Frozen harness enforcement uses a naive substring match (`cmd.contains(frozen.as_str())`). This is bypassed by multiple shell techniques:

- Variable indirection: `DIR=tests; echo 'bad' > $DIR/test_file.py`
- Glob: `echo 'bad' > t?sts/test_file.py`
- String concatenation: `"te""sts/file.py"`
- Absolute path when frozen path is relative: `/home/nesbitt/dev/factory/tests/file.py`
- Directory change: `cd tests && rm -rf .`

**Remediation:** Replace substring matching with shell AST parsing (or a strict allowlist of permitted commands). Consider rejecting any Bash invocation that contains `cd`, variable assignments, glob characters, or string concatenation when a frozen harness is active.

---

#### F-06 — `--permission-mode auto` Makes Tool Calls Invisible to Coordinator
**File:** `coordinator/src/agent.rs:614–615`
**Agent:** rt-coordinator

Claude subprocesses are spawned with `--permission-mode auto`. In `auto` mode, Claude Code auto-approves a class of tool calls (Read, Glob, Grep, and others) without emitting an `input_request` event to the coordinator. The coordinator's `AUTO_APPROVE_TOOLS` list and `should_auto_approve()` logic only processes tools that actually surface as `input_request` events. Tools auto-approved by Claude Code internally are completely invisible to the approval pipeline.

**Impact:** Trust level enforcement (e.g., L1 Observer restricted to read-only tools) is partially illusory for tools in Claude Code's internal auto-approve set. If that set expands in a future Claude Code release, new tools bypass the coordinator without any config change.

**Remediation:** Spawn agents with `--permission-mode ask` or `--permission-mode default` so all tool requests surface as `input_request` events. Accept performance cost in exchange for complete visibility. Alternatively, maintain an explicit audit of which tools Claude Code auto-approves per version and ensure they are all read-only.

---

#### F-07 — Session Cookie Missing Secure Flag
**File:** `portal/auth.py:71–80`
**Agent:** rt-auth

The `make_session_cookie()` function sets `HttpOnly` and `SameSite=Strict` but does not set the `Secure` flag. The portal is served over plain HTTP. Without `Secure`, the session cookie is transmitted in cleartext on every request.

**Attack scenario:** On the same Tailscale network, passive sniffing or ARP spoofing captures the cookie value. Combined with F-03, even an invalid cookie value would bypass Caddy. Mitigating factor: the portal binds to the Tailscale IP, limiting the network segment.

**Remediation:** Enable HTTPS on the Caddy frontend (Tailscale certificates or self-signed with pinning). Add `Secure` to the cookie attributes in `make_session_cookie()`. In the interim, add `Secure` to the cookie even under HTTP — browsers will still send it, and the flag reduces misconfigurations if TLS is added later.

---

#### F-08 — GSD Sidecar Auth Silently Disabled When `GSD_AUTH_SECRET` Unset
**File:** `portal/server.py:31–33`
**Agent:** rt-auth

```python
def _check_auth(self) -> bool:
    if not GSD_AUTH_SECRET:
        return True
```

When `GSD_AUTH_SECRET` is not set (the default), all authentication is skipped. The sidecar accepts PUT requests to `tasks.json`, `jobs.json`, and `status/*.json` from any caller. The sidecar binds to `127.0.0.1:41911`, but Caddy proxies external Tailscale traffic to it from port 41910. Combined with F-03, an attacker can PUT arbitrary JSON to job and task files without credentials.

**Remediation:** Remove the silent bypass. Require `GSD_AUTH_SECRET` to be set and fail startup with a clear error message if absent. Add it to the BWS secret roster and inject via `mcp-env.sh`.

---

### MEDIUM

#### F-09 — Filesystem Approval `request_id` Path Traversal
**File:** `coordinator/src/approval.rs:196`
**Agent:** rt-auth

```rust
let path = format!("{}/{}.response", approval_dir, request_id);
fs::write(&path, format!("{}:{}", decision, sig))?;
```

The `request_id` field from a `.request` JSON file is used directly in a file path with no sanitization. A `.request` file with `request_id: "../../etc/cron.d/backdoor"` causes the coordinator to write a `.response` file at an arbitrary path.

**Remediation:** Validate that `request_id` contains only alphanumeric characters and hyphens before constructing the path. Use `PathBuf::file_name()` to strip any directory components.

---

#### F-10 — Inter-Agent Routing Bypasses Allowlist and Trust Levels
**Files:** `coordinator/src/coordinator.rs:2901–2975`
**Agents:** rt-auth, rt-coordinator

When an agent's response starts with `>> @agentname`, the coordinator injects a message directly into the target agent's `message_tx` channel without calling `is_allowlisted()` or checking trust levels. A low-trust agent (L1 Observer) can route commands to a high-trust agent (L4 Autonomous). The hop limit (8) and `[Routed from @agent]` prefix are mitigations but do not enforce access control.

**Remediation:** Apply allowlist and trust-level checks to routing targets before injecting. Define a routing permission matrix — e.g., agents may only route to agents at the same or lower trust level unless explicitly permitted. Add rate limiting per originating agent on the routing path.

---

#### F-11 — Login Redirect Parameter Reflected into DOM Without Sanitization
**File:** `portal/pages/login.html:172–175`
**Agent:** rt-auth

```javascript
const redirect = params.get("redirect");
if (redirect) {
  document.getElementById("redirect").value = redirect;
}
```

The `redirect` query parameter is injected into a hidden form input's `value` attribute without sanitization. Server-side validation requires redirect starts with `/` and not `//`, and a CSP limits exploitation, but DOM-based attribute injection is possible with quote characters in the parameter value.

**Remediation:** Sanitize the redirect value before DOM injection: strip or encode quote characters, verify the path starts with `/` client-side as well, and use `setAttribute` with explicit encoding rather than direct `.value` assignment from raw URL parameters.

---

#### F-12 — Approval Reactions Accepted from Any Room Member
**File:** `coordinator/src/coordinator.rs:1585–1590`
**Agent:** rt-coordinator

The reaction-based approval flow checks `event.sender == approval_owner` (correct), but the fallback path that posts approvals to the agent's own room (not solely `COORD_APPROVAL_ROOM`) means any room member whose Matrix ID matches `approval_owner` could approve tools from that room. HMAC verification prevents forged approval message content but not approval source room manipulation.

**Remediation:** Restrict approval reaction processing to events originating from `COORD_APPROVAL_ROOM` only. Log and discard reactions originating from other rooms.

---

#### F-13 — Shell Metachar Regex Missing Newline Characters
**File:** `coordinator/src/coordinator.rs:56`
**Agent:** rt-coordinator

The `SHELL_METACHARS` regex does not match newline (`\n`). A multi-line command using newlines instead of semicolons bypasses the check:

```
ls /safe/path\nrm -rf /dangerous/path
```

If an `auto_approve_patterns` entry matches `ls *`, `glob_match` returns true for the full multi-line string, the shell metachar check passes, and both commands execute.

**Remediation:** Add `\n` and `\r` to the `SHELL_METACHARS` pattern. Consider rejecting any command string that spans multiple lines entirely.

---

#### F-14 — Budget Enforcement Advisory-Only
**File:** `coordinator/src/budget.rs:119–207`
**Agent:** rt-coordinator

`BudgetTracker::deduct_and_check()` returns `BudgetCheckResult::Paused` when budget exceeds 100%, but the coordinator only logs this result. No blocking, session termination, or circuit-breaker engagement occurs on budget exhaustion. An agent can exhaust its monthly invocation budget and continue operating indefinitely.

**Remediation:** On `BudgetCheckResult::Paused`, suspend the agent's dispatch loop (stop sending new tasks) and post a Matrix alert. Require an operator `!budget resume` command to re-enable the agent. This is the circuit-breaker pattern described in FCT007 #7.

---

#### F-15 — Filesystem Approval Directory Writable — HMAC Oracle Exposure
**File:** `coordinator/src/coordinator.rs:1834–2078`
**Agent:** rt-coordinator

`scan_filesystem_approvals()` reads `.request` JSON files from `~/.config/ig88/approvals/`. Any process with write access to this directory can create a forged `.request` file with a known `session_id` and set `tool_name` to an auto-approved tool. The coordinator processes it and writes a signed `.response` — providing the attacker with HMAC oracle access for chosen plaintexts.

**Remediation:** Restrict directory permissions to `700` (coordinator process owner only). Consider a signed `.request` format so forged requests are rejected before HMAC signing.

---

#### F-16 — JSON Injection in Watchdog Matrix Alerts
**File:** `scripts/watchdog.sh:26`
**Agent:** rt-infra

`send_matrix()` constructs JSON via string interpolation: `"{\"msgtype\":\"m.text\",\"body\":\"$msg\"}"`. If `$code` from a monitored service returns crafted HTTP status text, it can inject into the JSON payload. Impact is message corruption or monitoring DoS.

**Remediation:** Use `jq` for JSON construction (as already done in `run-cycle.sh:73`):
```bash
jq -n --arg body "$msg" '{"msgtype":"m.text","body":$body}'
```

---

#### F-17 — SSH with `StrictHostKeyChecking=no` in Watchdog
**File:** `scripts/watchdog.sh:74,88`
**Agent:** rt-infra

Both SSH commands pass `-o StrictHostKeyChecking=no`. A compromised Tailscale hostname resolution could MITM the SSH connection, potentially leaking the SSH private key or allowing command injection in the cron-run watchdog.

**Remediation:** Replace with `-o StrictHostKeyChecking=accept-new` and pre-populate `~/.ssh/known_hosts` with the target host key during initial bootstrap. Or pin the host key explicitly with `-o HostKeyAlgorithms=ssh-ed25519` and a `KnownHostsFile` entry.

---

#### F-18 — 11 Services Bound to 0.0.0.0, MLX-LM Unauthenticated
**Files:** `infra/ports.csv`, `plists/com.bootindustries.mlx-lm-*.plist`
**Agent:** rt-infra

Services bound to all interfaces (post-re-plumb ports): Qdrant HTTP (41450), Qdrant gRPC (41455), Matrix MCP Coord (41400), Qdrant MCP (41460), Research MCP (41470), Graphiti MCP (41440), Matrix MCP Boot (41401), Portal Caddy (41910), MLX-LM x5 (41961–41963, 41966, 41988). The MLX-LM inference servers pass `--host 0.0.0.0` and carry no authentication. If Whitebox is on any shared or misconfigured network segment, all services are reachable without credentials.

Correctly bound to 127.0.0.1: GSD sidecar (41911), auth sidecar (41914), Pantalaimon (41200), FalkorDB (41430).

**Remediation:** Bind all non-portal services to the Tailscale interface IP rather than 0.0.0.0. For MLX-LM, add a reverse proxy with token auth or bind to 127.0.0.1 and access via SSH tunnel or Tailscale-only routing.

---

#### F-19 — curl-pipe-bash Installs Without Integrity Checks
**Files:** `agents/ig88/scripts/rp5-bootstrap.sh:228,246,472`, `agents/ig88/deploy/rp5/setup.sh:32`
**Agent:** rt-infra

Four `curl | sh` patterns install NodeSource, Claude Code, Tailscale, and Docker without checksum verification, all with `sudo -E bash -`. DNS poisoning or MITM during bootstrap delivers arbitrary root-level code.

**Remediation:** Pin installation scripts by SHA-256: download, verify checksum, then execute. Use official package manager repositories with GPG-verified keys (NodeSource APT, Tailscale APT) rather than curl-pipe-bash where possible.

---

### LOW

#### F-20 — CSRF Layer Inert Due to Caddy Not Calling forward_auth
**Files:** `portal/auth.py:106`, `portal/Caddyfile`
**Agent:** rt-auth

CSRF validation runs inside `do_GET` on forward_auth subrequests for mutating methods. Since Caddy never calls forward_auth for protected routes (see F-03), the CSRF layer never executes. CSRF protection is implemented correctly in code but is operationally unreachable.

**Remediation:** Resolves automatically when F-03 is fixed and Caddy is updated to call the auth sidecar for protected routes.

---

#### F-21 — `routing_hop_counts` HashMap Grows Unboundedly
**File:** `coordinator/src/coordinator.rs:2930`
**Agent:** rt-auth

The `routing_hop_counts` map is keyed by `event_id` with no eviction policy. Over a long-running coordinator lifetime, an attacker who can send many routing events causes unbounded memory growth.

**Remediation:** Bound the map size (e.g., LRU with a 10,000-entry cap) or evict entries older than a configurable TTL (e.g., 1 hour).

---

#### F-22 — `glob_match` Cannot Handle Multi-Star Deny Patterns
**File:** `coordinator/src/coordinator.rs:2585–2592`
**Agent:** rt-coordinator

`glob_match` uses `splitn(2, '*')` and handles only zero or one `*` wildcard. A deny pattern like `cargo *test*` treats the second `*` as a literal character. Complex deny patterns in `always_require_approval` may silently fail to match, letting commands through that should require approval.

**Remediation:** Replace the hand-rolled glob with a proper glob crate (e.g., `glob` or `globset`).

---

#### F-23 — DM Routing Returns All Agents (Fragile Design)
**File:** `coordinator/src/coordinator.rs:443–447`
**Agent:** rt-coordinator

`get_dm_agent()` returns all agents for DM rooms, relying on a downstream filter at line 1073 to ensure only the syncing agent processes the event. The design is currently correct but fragile: if the filter logic changes, cross-agent message leakage can occur silently.

**Remediation:** `get_dm_agent()` should return the specific agent for a DM room (keyed by the DM partner's Matrix ID) rather than all agents, moving the routing logic to the correct abstraction layer.

---

#### F-24 — Docker `:latest` Tag Without Digest Pinning
**File:** `agents/ig88/deploy/rp5/docker-compose.yml:7`
**Agent:** rt-infra

`falkordb/falkordb:latest` uses a mutable tag. A supply chain compromise of the FalkorDB Docker Hub account delivers a malicious image on the next `docker compose pull`.

**Remediation:** Pin to a specific digest: `falkordb/falkordb@sha256:<digest>`. Record the expected digest in the repo and verify after pull.

---

#### F-25 — Remote `npm install` Without Lockfile Enforcement
**File:** `agents/ig88/scripts/deploy-to-rp5.sh:51–56`
**Agent:** rt-infra

Runs `npm install` on the remote host rather than `npm ci`. Without lockfile integrity enforcement, a compromised npm registry can serve malicious transitive dependencies during deployment.

**Remediation:** Replace `npm install` with `npm ci` in all remote deployment scripts. Ensure `package-lock.json` is committed to the repo.

---

## What Is Well-Defended

The following controls were identified across all three agents as correctly implemented:

- **HMAC signing on approval messages** — prevents forged Matrix approval injection; the signature check is consistent across coordinator and auth paths
- **Approval reaction sender enforcement** — `sender == approval_owner` is verified against Matrix server-signed fields, not self-reported content
- **Rate limiting on approval requests and slash commands** — prevents flooding attacks on the approval pipeline
- **Circuit breaker for crashed agents** — prevents runaway agent loops from escalating without operator intervention
- **Delegate parameter validation via `safe_param_re`** — prevents SSH shell injection through coordinator-delegated commands
- **Identity drift detection** — tampered agent identity files are caught before agent dispatch
- **`dev.ig88.coordinator_generated` message flag** — prevents self-loops in coordinator-generated Matrix messages
- **`yaml.safe_load` usage** — no unsafe YAML deserialization; `FullLoader` is not used
- **Path traversal protection in `server.py:79`** — `is_relative_to` check correctly blocks directory escape in the GSD sidecar file handler
- **CSRF protection implementation** — correctly implemented in `auth.py` (becomes effective once F-03 is resolved)
- **Content-Security-Policy headers** — set in the Caddyfile, limiting XSS exploitation surface
- **Loop spec path traversal check** — `..` components in loop spec paths are rejected
- **Allowlist model for Matrix access** — only authorized Matrix user IDs can trigger agent actions; open DM attacks are blocked
- **Docker Compose `no-new-privileges:true`** — container privilege escalation is constrained
- **`.env` files properly gitignored** — no plaintext secrets in the repo working tree

---

## Recommended Remediation Priority

### P0 — Immediate (before next agent run)

| ID | Action |
|----|--------|
| F-03 | Rewrite Caddy auth gate to call the auth sidecar for all protected routes (or use a middleware that validates the HMAC signature directly in Caddy). Until fixed, the portal has no effective authentication. |
| F-08 | Require `GSD_AUTH_SECRET`; fail startup if unset. Add to BWS and inject via `mcp-env.sh`. |
| F-02 | Remove hardcoded bcrypt hash fallback from `auth.py`. Make `AUTH_BCRYPT_HASH` required. Purge hash from git history. |
| F-01 | Add `plists/` to `.gitignore`, `git rm --cached plists/\*.plist`, purge from history. Evaluate machine account token rotation. |

### P1 — This Sprint

| ID | Action |
|----|--------|
| F-04 | Canonicalize paths in delegate auto-approval using `std::fs::canonicalize()` before containment check. |
| F-06 | Change agent spawn to `--permission-mode ask` to make all tool calls visible to the coordinator approval pipeline. |
| F-05 | Replace frozen harness substring match with an AST-based or strict allowlist approach. |
| F-10 | Apply trust level and allowlist checks to inter-agent routing targets; define routing permission matrix. |
| F-14 | Engage circuit-breaker on budget exhaustion: suspend agent dispatch and require operator resume. |
| F-07 | Enable HTTPS on Caddy (Tailscale certs); add `Secure` flag to session cookie. |
| F-15 | Restrict `~/.config/ig88/approvals/` to `700` permissions. |
| F-18 | Bind MCP and MLX-LM services to Tailscale interface IP rather than 0.0.0.0. |

### P2 — Backlog

| ID | Action |
|----|--------|
| F-09 | Sanitize `request_id` in `approval.rs` before path construction. |
| F-13 | Add `\n`/`\r` to `SHELL_METACHARS` regex. |
| F-16 | Use `jq` for JSON construction in `watchdog.sh`. |
| F-17 | Replace `StrictHostKeyChecking=no` with `accept-new` and pre-populated known_hosts. |
| F-19 | Pin bootstrap scripts by SHA-256 checksum. |
| F-11 | Sanitize `redirect` parameter before DOM injection in `login.html`. |
| F-12 | Restrict approval reaction processing to `COORD_APPROVAL_ROOM` only. |
| F-20 | Resolves automatically with F-03 fix. |
| F-21 | Add LRU eviction to `routing_hop_counts` map. |
| F-22 | Replace hand-rolled `glob_match` with `globset` crate. |
| F-23 | Refactor `get_dm_agent()` to return a specific agent rather than all agents. |
| F-24 | Pin FalkorDB Docker image to SHA-256 digest. |
| F-25 | Replace `npm install` with `npm ci` in remote deployment scripts. |

---

## References

No external standards or publications were cited in this audit. Findings are based on direct source code inspection by the three red-team agents against the factory codebase as of 2026-03-24.

---

*Audit conducted 2026-03-24. Three independent agents: rt-auth, rt-coordinator, rt-infra. Consolidated and deduplicated by prefix-agent.*


---

# Plan: FCT040 Security Remediation

**Date:** 2026-03-24
**Source:** FCT040 Red-Team Audit
**Machines:** Cloudkicker (source), Whitebox (deploy target), Blackbox/RP5 (watchdog)

---

## Context

The red-team audit found 25 vulnerabilities. Two are immediately exploitable without credentials:
1. Any Tailscale peer sets `Cookie: factory_session=x` → bypasses Caddy gate (cookie presence ≠ validity)
2. auth.py has a hardcoded bcrypt hash committed to git as a fallback default

This plan covers all feasible in-scope fixes. Breaking/architectural changes are flagged as OUT OF SCOPE with handoff notes.

---

## OUT OF SCOPE (hand forward)

| Finding | Why deferred | Handoff note |
|---------|-------------|--------------|
| Caddy auth gate (cookie presence ≠ validity) | Caddy v2.11.2 lacks `forward_auth` module; upgrading Caddy or switching proxies is architectural | Root cause of 3 findings (F-02, F-08, F-04). Schedule dedicated Caddy upgrade session. |
| `Secure` cookie flag | Requires HTTPS on Whitebox first; adding `Secure` to HTTP-only portal breaks login immediately | Do after Caddy TLS is enabled. |
| GSD `AUTH_SECRET` env var injection | Partial mitigation only — Caddy doesn't forward `Authorization` header; needs forward_auth to be useful | Do in same session as Caddy fix. |
| `approval.rs` request_id path traversal | Rust change + `cargo build` + Whitebox deploy | Single targeted fix: sanitize `request_id` with `Path::new(id).file_name()` check before use. |
| Inter-agent routing trust bypass | Architectural — needs trust propagation model decision (FCT038) | Deferred to conversational room behavior session. |
| `routing_hop_counts` unbounded map | Rust change + rebuild | Add `retain` eviction keyed on event age. |
| `glob_match` single-star only | Rust change + rebuild | Replace with `glob` crate or implement multi-star split. |
| `--permission-mode auto` invisible to coordinator | Requires Claude Code internals investigation | Architectural concern for FCT038. |
| 0.0.0.0 binding (MLX-LM, MCP servers) | Live Whitebox plist edits + service restarts; must be done on Whitebox directly | Bind to `100.88.222.111` (Tailscale IP) in each plist. See infra/ports.csv for current port list. Do in next Whitebox maintenance window. |
| Budget enforcement (soft limit) | Rust change + rebuild | Add `return Err` or session pause on `BudgetCheckResult::Paused`. |
| Delegate symlink traversal | Rust change + rebuild | Use `canonicalize()` before the `..` check. |
| Frozen harness substring bypass | Rust change + rebuild | Replace substring match with proper path canonicalization. |
| rp5-bootstrap.sh curl-pipe-bash | Bootstrap script for archived RP5 setup; low urgency | Pin checksums or use package manager directly. |

---

## IN SCOPE — 7 clean fixes, delegated to subagents

Implementation uses coordinated subagents. Team lead collects results and commits.

---

### Fix 1 — CRITICAL: Remove hardcoded bcrypt hash fallback (auth.py)

**File:** `portal/auth.py:27-30`
**Current:**
```python
BCRYPT_HASH = os.environ.get(
    "AUTH_BCRYPT_HASH",
    "$2a$14$EpVwjmAQzSbVuQwxr3MFhunjzx2HnUqRJBgjC8qKVC5GOb9.ypEKm",
)
```
**Change:** Remove the hardcoded default. Fail-closed if env var is unset — same pattern as `AUTH_SECRET` at lines 32-36:
```python
BCRYPT_HASH = os.environ.get("AUTH_BCRYPT_HASH", "")
if not BCRYPT_HASH:
    import sys
    print("FATAL: AUTH_BCRYPT_HASH environment variable is required.", file=sys.stderr)
    sys.exit(1)
```
**Deploy:** git pull on Whitebox → launchctl kickstart `com.bootindustries.factory-auth` (BWS already injects `AUTH_BCRYPT_HASH` via `factory-auth.plist` — confirmed safe).
**Cross-machine:** Whitebox only. Cloudkicker is source.

---

### Fix 2 — CRITICAL: Purge plists/ from git tracking

**Files:** `.gitignore`, all `plists/*.plist`
**Steps:**
1. Add `plists/` to `.gitignore` (append line)
2. `git rm --cached plists/*.plist` — untracks files, leaves them on disk
3. Commit: `chore(security): untrack plists/ — contains BWS UUIDs`
4. **History purge (separate step, requires coordination):** `git filter-repo --path plists/ --invert-paths --force` then force-push `main`. Whitebox must `git fetch --force && git reset --hard origin/main` after. Flag this step to user — it rewrites history and requires Whitebox sync.

**Note:** BWS UUIDs are lookup keys, not secret values — but they map the entire secret inventory. Combined with the 2026-03-23 BWS token leak, purging git history is correct hygiene. The plists themselves stay on Whitebox's filesystem unaffected.

---

### Fix 3 — HIGH: Fix login.html redirect client-side sanitization

**File:** `portal/pages/login.html:172-175`
**Current:**
```javascript
const redirect = params.get("redirect");
if (redirect) {
  document.getElementById("redirect").value = redirect;
}
```
**Change:** Mirror server-side validation from `auth.py:133-135`:
```javascript
const redirect = params.get("redirect");
if (redirect && redirect.startsWith("/") && !redirect.startsWith("//")) {
  document.getElementById("redirect").value = redirect;
}
```
**Deploy:** `make sync` from `portal/` pushes to Whitebox :41910.

---

### Fix 4 — MEDIUM: Fix watchdog.sh SSH StrictHostKeyChecking

**File:** `scripts/watchdog.sh:74,88`
**Current:** Both SSH calls use `-o StrictHostKeyChecking=no`
**Change:** Replace with `-o StrictHostKeyChecking=accept-new` on both lines (74 and 88). TOFU: accepts key on first connect, rejects if it changes.
**Deploy:** watchdog.sh runs on Blackbox/RP5. Script must be synced to `/home/nesbitt/scripts/watchdog.sh` on Blackbox. Use `ssh blackbox "cat > ~/scripts/watchdog.sh" < scripts/watchdog.sh` or via the existing Blackbox-to-Whitebox SSH chain.

---

### Fix 5 — MEDIUM: Fix watchdog.sh JSON injection via jq

**File:** `scripts/watchdog.sh:26`
**Current:**
```bash
-d "{\"msgtype\":\"m.text\",\"body\":\"$msg\"}"
```
**Change:** Use `jq -n` for safe JSON construction:
```bash
local body
body=$(jq -n --arg m "$msg" '{"msgtype":"m.text","body":$m}')
```
And pass `"$body"` to `-d`. Requires `jq` on Blackbox (standard, almost certainly present).
**Deploy:** Same as Fix 4 — sync to Blackbox `/home/nesbitt/scripts/watchdog.sh`.
**Note:** Fixes 4 and 5 are both in watchdog.sh — apply in one edit, one sync.

---

### Fix 6 — LOW: Pin Docker image digest

**File:** `agents/ig88/deploy/rp5/docker-compose.yml:7`
**Current:** `image: falkordb/falkordb:latest`
**Change:** Pin to current digest. Subagent must fetch digest via:
```bash
docker manifest inspect falkordb/falkordb:latest | jq -r '.manifests[0].digest // empty'
```
or from Docker Hub API. Replace `:latest` with `@sha256:<digest>`.
**Note:** This file is for the archived RP5/Blackbox Graphiti stack — Graphiti now runs on Whitebox. Low urgency but correct practice.

---

### Fix 7 — LOW: npm install → npm ci in deploy script

**File:** `agents/ig88/scripts/deploy-to-rp5.sh`
**Change:** Find `npm install` calls in the remote deploy steps and replace with `npm ci`.
**Note:** Same caveat — archived RP5 deploy script. Low urgency.

---

## Execution Plan (subagent delegation)

**Team lead (this session):** Orchestrates, reviews diffs, commits.

**Subagent A — portal fixes:**
- Fix 1: `portal/auth.py` (bcrypt fail-closed)
- Fix 3: `portal/pages/login.html` (redirect sanitize)
- Report exact diffs back for review before commit.

**Subagent B — infra/scripts fixes:**
- Fix 4 + 5: `scripts/watchdog.sh` (SSH host key + jq JSON)
- Fix 6: `agents/ig88/deploy/rp5/docker-compose.yml` (Docker digest — must fetch live digest)
- Fix 7: `agents/ig88/scripts/deploy-to-rp5.sh` (npm ci)
- Report exact diffs back for review before commit.

**Team lead handles Fix 2** (git untracking + .gitignore) directly — git operations should not be delegated.

---

## Commit Plan

```
chore(security): untrack plists/ from git, add to .gitignore
fix(auth): fail-closed if AUTH_BCRYPT_HASH env var unset
fix(portal): sanitize login redirect param client-side
fix(watchdog): StrictHostKeyChecking=accept-new, jq JSON body
fix(infra): pin falkordb Docker digest, use npm ci in deploy
```

History purge of `plists/` from git log is a separate force-push step — confirm with user before executing.

---

## Verification

| Fix | Test |
|-----|------|
| Fix 1 | On Whitebox: temporarily rename env var, restart auth sidecar → should exit 1 with FATAL message |
| Fix 2 | `git ls-files plists/` → empty. `cat .gitignore` → contains `plists/` |
| Fix 3 | Visit `/login?redirect=%22injected` → hidden input value should be empty (not `"injected`) |
| Fix 4 | `grep StrictHostKeyChecking scripts/watchdog.sh` → `accept-new` on both lines |
| Fix 5 | `grep 'jq' scripts/watchdog.sh` → jq body construction present |
| Fix 6 | `grep 'sha256' agents/ig88/deploy/rp5/docker-compose.yml` → digest present |
| Fix 7 | `grep 'npm ci' agents/ig88/scripts/deploy-to-rp5.sh` → present |

---

## Whitebox Deploy Steps (post-commit)

1. `ssh whitebox "cd ~/dev/factory && git pull"`
2. `launchctl kickstart -k gui/501/com.bootindustries.factory-auth` — picks up auth.py fix
3. `make sync` from `portal/` — pushes login.html fix to Caddy static root
4. Sync watchdog.sh to Blackbox: `ssh blackbox "cat > ~/scripts/watchdog.sh" < scripts/watchdog.sh`

---

## Deferred Handoff Summary (for next session doc)

The root-cause auth issue (**Caddy cookie presence ≠ validity**) requires a dedicated session to resolve. Options:
- Upgrade Caddy to a build with `forward_auth` (xcaddy build)
- Replace Caddy with nginx + `auth_request` module
- Implement a Caddy `handle_errors` approach that redirects non-200 from auth.py

Until resolved, the portal relies on Tailscale network isolation as its primary access control. All services bound to `0.0.0.0` should also be moved to `100.88.222.111` in the same Whitebox maintenance window. See infra/ports.csv for the current port list.

---

## Remediation Status (2026-03-24)

8 of 25 findings remediated in this session. Commits: `fix(auth)` x2, `fix(portal)`, `fix(watchdog)`, `fix(infra)`, `chore(security)`.

| ID | Finding | Status | Commit scope |
|----|---------|--------|-------------|
| F-01 | BWS UUIDs in git | ✅ Untracked (history purge pending) | `chore(security)` |
| F-02 | Hardcoded bcrypt hash | ✅ Fixed — fail-closed | `fix(auth)` |
| F-11 | Login redirect DOM injection | ✅ Fixed — client-side path check | `fix(portal)` |
| F-16 | JSON injection in watchdog | ✅ Fixed — jq construction | `fix(watchdog)` |
| F-17 | StrictHostKeyChecking=no | ✅ Fixed — accept-new | `fix(watchdog)` |
| F-24 | Docker :latest tag | ✅ Fixed — sha256 pinned | `fix(infra)` |
| F-25 | npm install (no lockfile) | ✅ Fixed — npm ci | `fix(infra)` |
| F-03 | Caddy cookie bypass → forward_auth | ✅ Fixed — xcaddy build + Caddyfile rewrite | `fix(auth)` |
| F-04 | Delegate symlink traversal | ⏳ Deferred — Rust + rebuild | — |
| F-05 | Frozen harness bypass | ⏳ Deferred — Rust + rebuild | — |
| F-06 | --permission-mode auto | ⏳ Deferred — architectural | — |
| F-07 | Cookie Secure flag | ⏳ Deferred — needs TLS first | — |
| F-08 | GSD auth silent disable | ⏳ Deferred — needs F-03 first | — |
| F-09 | approval.rs path traversal | ⏳ Deferred — Rust + rebuild | — |
| F-10 | Inter-agent routing trust | ⏳ Deferred — architectural (FCT038) | — |
| F-12 | Approval reactions any member | ⏳ Deferred — Rust + rebuild | — |
| F-13 | SHELL_METACHARS missing \n | ⏳ Deferred — Rust + rebuild | — |
| F-14 | Budget enforcement soft-only | ⏳ Deferred — Rust + rebuild | — |
| F-15 | Approval dir writable | ⏳ Deferred — permissions on Whitebox | — |
| F-18 | Services on 0.0.0.0 | ⏳ Deferred — Whitebox plist edits | — |
| F-19 | curl-pipe-bash installs | ⏳ Deferred — archived RP5 scripts | — |
| F-20 | CSRF layer inert | ⏳ Resolves with F-03 | — |
| F-21 | routing_hop_counts unbounded | ⏳ Deferred — Rust + rebuild | — |
| F-22 | glob_match single-star | ⏳ Deferred — Rust + rebuild | — |
| F-23 | DM routing fragile design | ⏳ Deferred — architectural | — |

**History purge (F-01):** Deferred — `git filter-repo` rewrites all commit SHAs on main, breaking clones on Whitebox and any other checkouts. Risk is low (BWS UUIDs are lookup keys, not secrets; machine account token was already rotated 2026-03-23). Plists are untracked going forward.

**Caddy binary (F-03):** Whitebox now runs `~/bin/caddy-forward-auth` (xcaddy-built, includes `forward_auth` directive). Plist `com.bootindustries.portal-caddy` updated to point to this binary. Original Homebrew caddy at `/opt/homebrew/bin/caddy` kept as rollback.
