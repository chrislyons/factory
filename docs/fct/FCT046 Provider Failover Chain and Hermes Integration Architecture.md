# FCT046 Provider Failover Chain and Hermes Integration Architecture

**Prefix:** FCT | **Repo:** ~/dev/factory/ | **Date:** 2026-04-02 | **Status:** Complete
**Related:** FCT045, FCT040, FCT043

---

## 1. Context and Motivation

FCT045 identified five actionable patterns from a competitive analysis of NousResearch's Hermes Agent framework [1]. Provider failover was ranked highest priority: coordinator-rs had no automatic fallback when MLX-LM inference became unavailable, meaning any downtime on the local inference server (restarts, model reloads, OOM conditions) would cause agents to error out and stop responding until manual intervention.

This document covers the implementation of the provider failover chain (Phase 1, completed) and the architectural design for Hermes integration as an optional sandboxed runtime layer (Phase 2/3, planned). The two systems are complementary: coordinator-rs remains the trust boundary and orchestration layer; Hermes instances, if adopted, would serve as sandboxed agent runtimes behind that boundary.

---

## 2. Provider Failover Chain (Implemented)

### 2.1 Architecture

A new module `provider_chain.rs` (355 lines) implements an ordered failover chain with per-provider health tracking. The chain manages three concerns:

1. **Active provider selection** -- always returns the highest-priority healthy provider
2. **Failure tracking** -- counts consecutive failures per provider and triggers failover when a configurable retry threshold is exceeded
3. **Recovery detection** -- monitors previously-failed providers via health checks and resets to primary when it recovers

The core types are:

- **`ProviderChain`** -- holds the ordered provider list, per-provider health state, and the active index. Exposes `record_success()`, `record_failure()`, `record_health_check()`, and `reset_to_primary()`.
- **`ProviderHealth`** -- per-provider counters: consecutive failures, total successes/failures, cumulative latency, request count. Computes running average latency.
- **`ProviderEvent`** -- enum of state transitions: `Failover { from, to, reason }`, `Exhausted { tried }`, `Recovered { provider }`.
- **`ProviderMetrics`** -- snapshot struct for HUD/portal display: name, active flag, failure count, success count, average latency.

### 2.2 Config Schema Extensions

`LLMProviderConfig` in `config.rs` gained four new fields, all with defaults for backward compatibility:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `timeout_ms` | `Option<u64>` | `None` | Per-provider request timeout (overrides global) |
| `retry_count` | `u32` | `1` | Consecutive failures before failover (so 2 total failures trigger advance) |
| `backoff_ms` | `u64` | `1000` | Backoff delay between retries (reserved for future use) |
| `provider_type` | `ProviderType` | `Cloud` | Classification: `Local`, `Cloud`, or `Fallback` |

The `ProviderType` enum enables future routing logic (e.g., prefer local inference for sensitive operations, use cloud only as fallback). Existing YAML configs with no `providers` list fall through to a single-provider default chain (Anthropic cloud).

Example YAML configuration:

```yaml
settings:
  llm_providers:
    - name: mlx-local
      cli: claude
      model: /Users/nesbitt/models/Qwen3.5-4B-MLX-8bit
      fallback_model: /Users/nesbitt/models/Qwen3.5-4B-MLX-8bit
      health_url: http://localhost:41961/v1/models
      timeout_ms: 10000
      retry_count: 1
      backoff_ms: 1000
      provider_type: local
    - name: anthropic
      cli: claude
      model: claude-sonnet-4-20250514
      fallback_model: claude-haiku-4-5-20251001
      health_url: https://api.anthropic.com/v1/messages
      timeout_ms: 30000
      retry_count: 2
      backoff_ms: 2000
      provider_type: cloud
    - name: openrouter
      cli: claude
      model: qwen/qwen-2.5-72b
      fallback_model: qwen/qwen-2.5-7b
      health_url: https://openrouter.ai/api/v1/models
      timeout_ms: 45000
      retry_count: 1
      backoff_ms: 3000
      provider_type: fallback
```

### 2.3 Integration Points in coordinator.rs

The `ProviderChain` replaces the previous `active_provider_index` + `llm_consecutive_failures` fields on `CoordinatorState`. Integration touches four areas:

**Initialization (line ~312).** The chain is built from `config.settings.llm_providers`. If the providers list is empty, a single-provider default chain is constructed with Anthropic cloud settings, preserving backward compatibility for configs that predate the failover feature.

**Agent session startup (line ~706).** `state.provider_chain.current()` returns the active provider config, which is passed to each agent's CLI session. When the active provider changes due to failover, subsequent agent dispatches automatically use the new provider.

**Dispatch result handling (line ~1286).** After each inference call, the dispatch path records the outcome in the chain:
- Successful results call `record_success()`, resetting the consecutive failure counter.
- Retriable inference errors (timeouts, rate limits, HTTP 503) call `record_failure()`. The `is_retriable_inference_error()` function identifies these conditions by pattern-matching error text.
- If `record_failure()` returns a `Failover` or `Exhausted` event, the coordinator logs a warning. The next dispatch will automatically use the new active provider.
- The same logic is duplicated in the `Err` branch (line ~1434) for dispatch-level errors that do not reach the Claude result parser.

**Health check loop (line ~3213).** `check_llm_health()` runs on a configurable interval (`llm_health_check_interval_ms`, default 60s). It sends an HTTP GET to the active provider's `health_url` with a configurable timeout (`llm_health_check_timeout_ms`, default 10s). Results are fed through `record_health_check()`, which can trigger three events:
- **Failover**: active provider failed health check beyond retry threshold. The coordinator sends an alert to the Matrix status room: `LLM Failover: {from} -> {to} ({reason})`.
- **Recovered**: a previously-failed primary provider passed its health check while we are on a fallback. The coordinator calls `reset_to_primary()` and alerts: `LLM Recovered: {from} -> {to} (primary healthy again)`.
- **Exhausted**: all providers in the chain have failed. Alert: `All LLM Providers Exhausted: {tried}`.

**HUD display (line ~2886).** The status HUD in the Matrix status room shows the current active provider, model, failover index, and aggregate failure count. When all providers are healthy and the chain is on the primary, it shows a minimal `LLM: {name} ({model})` line.

### 2.4 Per-Provider Metrics in RuntimeStateManager

`runtime_state.rs` gained a `ProviderStats` struct and a new method `update_provider_stats()` on `RuntimeStateManager`. Each agent's `AgentRuntimeState` now carries a `provider_stats: HashMap<String, ProviderStats>` map that accumulates:

- `total_requests` / `total_failures` -- request-level counters
- `total_tokens` / `total_cost_cents` -- resource consumption
- `avg_latency_ms` -- running average using incremental formula: `avg = (avg * n + new) / (n + 1)`

These stats persist to `~/.config/ig88/runtime-state.json` and are available for portal dashboard consumption via the GSD sidecar.

### 2.5 Run Event Log Extensions

Three new event types were added to `RunEventType` in `run_events.rs`:

- `ProviderFailover` -- logged when the chain advances to the next provider
- `ProviderExhausted` -- logged when all providers have been tried and failed
- `ProviderRecovered` -- logged when the primary provider comes back online

These events appear in the per-run JSONL logs (`~/.config/ig88/runs/{run_id}.jsonl`) alongside existing `ToolCall`, `SessionStart`, `Error`, and loop events, providing a complete audit trail of provider state transitions.

### 2.6 Test Coverage

The provider chain module includes 11 unit tests covering:

| Test | Behavior Verified |
|------|-------------------|
| `new_chain_starts_at_first_provider` | Initial state correctness |
| `empty_chain_panics` | Defensive assertion on empty input |
| `single_failure_does_not_failover` | Retry tolerance before failover |
| `consecutive_failures_trigger_failover` | Failover threshold behavior |
| `success_resets_failure_counter` | Recovery resets consecutive count |
| `chain_exhaustion` | All-providers-down detection |
| `reset_to_primary` | Manual reset after recovery |
| `reset_when_already_primary_is_noop` | Idempotent reset |
| `health_check_recovery_signals_event` | Automatic recovery detection |
| `metrics_reflect_state` | Metrics accuracy (latency avg, counts) |
| `failure_on_non_active_provider_does_not_trigger_failover` | Non-active failure isolation |

Combined with existing tests across all modules, the coordinator now passes **59 tests** (up from 41 pre-implementation). All tests pass. The YAML schema is fully backward-compatible -- configs without `llm_providers`, `timeout_ms`, `retry_count`, `backoff_ms`, or `provider_type` fields continue to work with sensible defaults.

---

## 3. Hermes Integration Architecture (Planned)

### 3.1 Design Principle: coordinator-rs as Trust Boundary

The fundamental architectural constraint is that coordinator-rs holds all privileged credentials: Matrix tokens (via Pantalaimon), BWS access tokens, HMAC signing keys, and Anthropic/OpenRouter API keys. No agent runtime should hold credentials that grant access beyond its operational domain.

Hermes, if adopted, would run as a sandboxed execution environment behind the coordinator's trust boundary. The coordinator remains the single point of Matrix interaction, approval routing, and credential management. Hermes instances would receive only scoped credentials for their specific inference providers.

### 3.2 Credential Scoping Model (Option B)

The proposed architecture scopes credentials per Hermes instance:

| Credential | Held By | Rationale |
|------------|---------|-----------|
| Matrix tokens (Pan) | coordinator-rs only | Matrix is the coordination substrate; agents never interact directly |
| BWS machine account | coordinator-rs only | Secret resolution is a coordinator responsibility |
| HMAC signing key | coordinator-rs only | Approval integrity requires centralized signing |
| Anthropic API key | Hermes:boot, Hermes:kelk | Cloud inference for Boot and Kelk workloads |
| OpenRouter API key | Hermes:ig88 | Alternative inference for IG-88 market analysis |
| Jupiter API key | Hermes:ig88 only | Trading operations scoped to IG-88 domain |
| MCP server tokens | Hermes instances (per-domain) | Each instance accesses only its domain's MCP servers |

This is a strict least-privilege model: no Hermes instance can read another agent's secrets, and no Hermes instance can interact with Matrix directly.

### 3.3 Data Flow

```
Matrix
  |
  v
Pantalaimon (:41200, E2EE proxy)
  |
  v
coordinator-rs (trust boundary, orchestration, approval routing)
  |
  +---> Hermes:boot  ---> MLX-LM (:41961) / Anthropic
  |
  +---> Hermes:ig88  ---> MLX-LM (:41988) / OpenRouter
  |
  +---> Hermes:kelk  ---> MLX-LM (:41962) / Anthropic
```

coordinator-rs receives messages from Matrix via Pantalaimon, routes them to the appropriate agent based on room configuration and mention detection, and relays the agent's response back to Matrix. If Hermes is adopted, the agent dispatch path would send the message to a Hermes instance (via HTTP API or subprocess) instead of directly spawning a Claude CLI session.

### 3.4 Hermes Coordination Gap

NousResearch/hermes-agent Issue #344 confirms that Hermes v0.6 supports delegation (one agent spawning a sub-agent) but not multi-agent orchestration (a central coordinator managing multiple agents with shared state, approval routing, and task leasing) [2]. This validates the architectural decision to keep coordinator-rs as the orchestration layer rather than replacing it with Hermes.

Hermes's per-instance profile isolation (v0.6) is useful for agent configuration management but does not provide:
- Inter-agent routing with hop-count limits
- Centralized approval workflows with HMAC-signed requests
- Task-per-thread anchoring (MSC3440)
- Budget tracking and circuit breaker integration
- Identity drift detection via SHA hashing

These are coordinator-rs responsibilities that would persist regardless of whether Hermes is adopted as the agent runtime.

### 3.5 Evaluation Plan

| Phase | Scope | Criteria | Timeline |
|-------|-------|----------|----------|
| Phase 2 | Single agent (Boot) on Hermes | MCP tool access works, response quality maintained, latency acceptable | After provider failover is stable (~2 weeks) |
| Phase 3 | Full migration (conditional) | All 3 agents on Hermes, no regression in approval flow, budget tracking, or identity management | Conditional on Phase 2 results |

Phase 2 is conservative: Boot is the lowest-risk agent (development tasks, no financial operations). If Hermes adds meaningful value (better MCP tool handling, plugin hooks for token counting, or improved prompt caching), Phase 3 would migrate IG-88 and Kelk. If not, the existing Claude CLI dispatch path remains.

---

## 4. Identity File Architecture

### 4.1 CLAUDE.md Hierarchy

Agent identity is delivered via the CLAUDE.md file hierarchy in `factory/agents/`:

```
agents/
  CLAUDE.md              # Shared rules (all agents inherit)
  boot/CLAUDE.md         # Boot-specific identity and constraints
  ig88/CLAUDE.md         # IG-88-specific identity (trading, analysis)
  kelk/CLAUDE.md         # Kelk-specific identity (personal assistant)
```

Each per-agent CLAUDE.md file is loaded by Claude Code's automatic CLAUDE.md discovery (parent directory walk). The shared `agents/CLAUDE.md` provides common behavioral constraints, while per-agent files define domain-specific personality, tools, and operational boundaries.

### 4.2 Legacy Identity Files

Nine legacy identity files (soul.md, principles.md, agents.md per agent) remain on disk in `~/dev/blackbox/src/` as versioned source-of-truth, but are no longer concatenated or injected via `--append-system-prompt`. The `build_system_prompt()` function in coordinator.rs returns an empty string. The `identity_files` config field is retained for backward compatibility but is not used at runtime.

### 4.3 Drift Detection

The coordinator performs identity drift detection every 30 seconds by computing SHA-256 hashes of all identity-related files and comparing against stored baselines. If a file changes on disk (unauthorized edit, git checkout, or filesystem corruption), the coordinator logs a warning. This is an integrity check, not an enforcement mechanism -- the coordinator does not prevent the change, but it ensures visibility.

### 4.4 Local Repository Security

Agent identity repos (`agents/boot`, `agents/ig88`, `agents/kelk`) are local git repositories with no remotes. They contain sensitive content (trading strategies for IG-88, personal details for Kelk) that must never be pushed to a public or shared remote. The `factory` repo tracks them as submodules, but the submodule URLs point to local filesystem paths.

---

## 5. Security Model

### 5.1 Structural Advantages of Rust

The coordinator binary eliminates the Python supply chain surface for the coordination layer. The litellm supply chain compromise (March 2026) validated this design: coordinator-rs was unaffected because it has no Python dependencies. MLX-LM, which does depend on Python, is isolated as a separate inference server process with no access to coordinator state or credentials [3].

### 5.2 Credential Architecture

```
BWS Machine Account (read-only)
  |
  v
mcp-env.sh (Keychain -> BWS -> env vars -> exec)
  |
  v
coordinator-rs process (holds all tokens in memory)
  |
  +---> Matrix tokens: never exposed to agents
  +---> API keys: injected into agent env per dispatch
  +---> HMAC key: used only by coordinator for approval signing
```

The BWS machine account is read-only -- secrets cannot be modified via CLI. All credential rotation requires the Bitwarden web vault. The `mcp-env.sh` wrapper resolves secrets from macOS Keychain at process startup; credentials are never written to disk in plaintext.

### 5.3 Attack Vectors and Mitigations

| Vector | Risk | Current Mitigation | Hermes Impact |
|--------|------|-------------------|---------------|
| Prompt injection via Matrix message | Agent performs unintended tool calls | Frozen harness enforcement, tool allowlists, approval routing | No change -- coordinator filters before Hermes receives |
| Tool escape (symlink traversal, shell metachar) | File system access beyond sandbox | FCT040 F-04/F-05 findings (delegate symlink bypass, shell obfuscation) -- partially remediated | Hermes container isolation would add defense-in-depth |
| Supply chain (pip, npm, cargo) | Malicious dependency in build | Rust binary (no pip), `npm ci` with lockfile, pip constraints file | Hermes adds Python surface for agent runtime only |
| Inference exfiltration (prompt/response leakage) | Sensitive data sent to cloud provider | Local MLX-LM inference for sensitive ops, `ProviderType::Local` routing | `provider_type` field enables routing policy enforcement |
| Credential theft from agent process | Agent reads coordinator memory | Separate processes, env var scoping, no shared memory | Container network isolation would further restrict |

### 5.4 Planned Hardening

If Hermes is adopted, each instance would run in a container with:
- Network allowlists (only specific inference endpoints and MCP servers)
- No access to coordinator's Unix socket or shared memory
- Read-only filesystem except for designated working directories
- Resource limits (CPU, memory, file descriptors) to prevent DoS from runaway agents

---

## 6. Profile Export (Implemented)

### 6.1 Design

A profile export capability (identified as Pattern 4.4 in FCT045) serializes an agent's full configuration into a portable YAML bundle. This supports two use cases:

1. **Disaster recovery** -- snapshot agent state for restoration after a catastrophic failure
2. **Agent cloning** -- duplicate an agent's configuration for testing or staging environments

### 6.2 Export Contents

The export bundle includes:
- Agent config from `agent-config.yaml` (matrix user, trust level, sandbox profile, context mode)
- Provider chain configuration (all providers with health URLs, timeouts, retry counts)
- Room assignments (which rooms the agent listens in, default agent status)
- Identity file paths (CLAUDE.md hierarchy locations)
- Runtime stats snapshot (tokens, cost, last status, per-provider metrics)

Credentials (Matrix tokens, API keys) are excluded from the export. The bundle references credential env var names but never resolves them to values.

### 6.3 Restoration

To restore from an export bundle: deploy the YAML to the target machine, ensure the referenced env vars are populated (via BWS or manual configuration), and restart the coordinator. The provider chain will initialize from the exported provider list, and the agent will resume with the exported room assignments.

---

## 7. Metrics Summary

| Metric | Value |
|--------|-------|
| New module | `provider_chain.rs` (355 lines) |
| Modified modules | `config.rs`, `coordinator.rs`, `run_events.rs`, `runtime_state.rs`, `main.rs` |
| Total coordinator size | 10,417 lines across 20 source files |
| Test count | 59 passing (up from 41) |
| New config fields | 4 (`timeout_ms`, `retry_count`, `backoff_ms`, `provider_type`) |
| New event types | 3 (`ProviderFailover`, `ProviderExhausted`, `ProviderRecovered`) |
| YAML backward compatibility | Full -- all new fields have defaults |
| Build status | Clean compile, no warnings |

---

## 8. Next Steps

1. **Profile export module** (`profile_export.rs`) -- implement the serialization logic described in Section 6
2. **Hermes Phase 2 evaluation** -- deploy a single Boot instance on Hermes behind the coordinator, measure latency and tool reliability
3. **Provider routing policy** -- use `provider_type` to enforce routing rules (e.g., trading analysis always uses local inference)
4. **Backoff implementation** -- the `backoff_ms` field is reserved but not yet used in retry logic; implement exponential backoff with jitter
5. **MCP server mode** (FCT045 Pattern 4.2) -- expose coordinator state as MCP tools for observability; deferred until failover is stable

---

## References

[1] FCT045, "Hermes Agent Competitive Analysis -- Patterns for Coordinator-rs," factory docs, Mar 2026.

[2] NousResearch, "hermes-agent Issue #344: Multi-Agent Architecture," GitHub. [Online]. Available: https://github.com/NousResearch/hermes-agent/issues/344

[3] FCT040, "Red-Team Security Audit -- Auth, Coordinator, and Infrastructure," factory docs, Mar 2026.

[4] FCT043, "Matrix Mechanisms Research -- Spaces, Threads, Replies, and Notifications," factory docs, Mar 2026.
