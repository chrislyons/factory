# FCT047 Hermes Runtime Integration Phase 3 Implementation

**Created:** 2026-04-02 | **Status:** Implemented | **Phase:** 3 (Evaluate)
**Prereqs:** FCT045 (competitive analysis), FCT046 (architecture + Phase 1-2)

---

## Summary

Phase 3 adds Hermes as an alternative agent runtime in coordinator-rs. Boot is configured as the first Hermes-backed agent for a 48-hour evaluation period. The implementation is fully reversible via a single YAML config change.

## Changes

### New Types (config.rs)

```rust
pub enum RuntimeType { ClaudeCli, Hermes }
```

Added to `AgentConfig`:
- `runtime: RuntimeType` (default: ClaudeCli)
- `hermes_profile: Option<String>` (Hermes profile name)
- `hermes_port: Option<u16>` (Phase 4 HTTP serve port)
- `scoped_env: HashMap<String, String>` (agent-scoped credentials)

All fields use `#[serde(default)]` for zero-migration backward compatibility.

### New Module (hermes_adapter.rs)

- `parse_hermes_output()` — converts plain-text Hermes stdout into `SessionResult`
- `OpenAIUsage` struct — Phase 4 token usage parsing
- `HermesHttpClient` — Phase 4 HTTP client stub for `hermes serve` mode
- 3 unit tests

### Agent Lifecycle (agent.rs)

- `spawn_hermes()` — spawns `hermes --profile {name} chat --non-interactive` with scoped env vars
- `run_hermes_session()` — simplified select loop: stdin writes, stdout reads, no tool approvals
- `agent_task()` branches on `RuntimeType` at the top — Hermes path uses its own spawn/session loop, Claude CLI path unchanged

### Coordinator Wiring (coordinator.rs)

- Runtime selection logged at agent start for Hermes agents
- `AgentConfig` carries all new fields through existing `start_agent_session()` call path — no signature changes needed

### Configuration (agent-config.yaml)

Boot agent configured with:
```yaml
runtime: hermes
hermes_profile: boot
hermes_port: 41970
scoped_env:
  ANTHROPIC_API_KEY: "${BOOT_ANTHROPIC_KEY}"
```

IG-88 and Kelk remain on `claude-cli` (default).

### Port Allocation (ports.csv)

| Port | Service | Status |
|------|---------|--------|
| 41970 | Hermes Boot API | planned |
| 41971 | Hermes IG-88 API | planned |
| 41972 | Hermes Kelk API | planned |

All bound to 127.0.0.1 (Phase 4 only).

## Phase 3 I/O Model

| Aspect | Claude CLI | Hermes (Phase 3) |
|--------|-----------|-------------------|
| Protocol | stream-json (newline-delimited JSON) | Plain text (non-interactive) |
| Session init | `system/init` handshake | None (ephemeral) |
| Resume | `--resume {session_id}` | Not applicable |
| Tool approvals | `InputRequest` on stdout | Disabled |
| Token usage | `ClaudeUsage` in Result | Not available in subprocess mode |

## Rollback

Change `runtime: hermes` to `runtime: claude-cli` in agent-config.yaml. Restart coordinator. No code changes required.

## Decision Gate (Phase 3 -> Phase 4)

Proceed if:
- Hermes latency within 20% of Claude CLI
- Provider failover works correctly
- No new error classes
- Boot + Hermes < 500MB RSS

Abort if:
- >20% latency increase
- Python dependency issues
- hermes_adapter.rs exceeds 300 lines
- Profile isolation insufficient

## Test Results

65 tests passing, 0 failures (including 3 new hermes_adapter tests).

## References

[1] FCT045 Hermes Agent Competitive Analysis
[2] FCT046 Provider Failover Chain and Hermes Integration Architecture
[3] NousResearch/hermes-agent Issue #344: Multi-Agent Architecture
