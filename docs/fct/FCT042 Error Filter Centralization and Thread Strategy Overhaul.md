# FCT042 Error Filter Centralization and Thread Strategy Overhaul

**Date:** 2026-03-24
**Repo:** factory / coordinator-rs
**Commit:** `6bce92d`
**Status:** Complete

---

## Summary

This session resolved two persistent coordinator reliability issues. First, "Invalid API key" errors originating from Claude CLI initialization were leaking into Matrix DMs despite earlier suppression attempts — the existing guards covered only some output paths, allowing the errors through on others. Second, a class of MSC3440 threading violations was causing coordinator responses to fail in rooms where incoming events carried existing `m.relates_to` relations, because the coordinator was attempting to thread off those relation events rather than their thread roots. Both problems were addressed in a single coordinated pass against `coordinator/src/coordinator.rs`.

---

## Changes Made

### Part 1: Centralized Error Filter (`is_suppressed_error()`)

The pre-existing suppression logic was scattered across individual output paths with inconsistent pattern coverage. The fix extracts a single `is_suppressed_error(text: &str) -> bool` function that serves as the canonical gate for all CLI auth and initialization error text.

Patterns matched (case-insensitive substring):
- `"invalid api key"`
- `"invalid_api_key"`
- `"authentication_error"`
- `"fix external api key"`
- 401 status combined with `"unauthorized"`

The function was applied to all four output paths in the coordinator:

| Path | Location | Prior state |
|------|----------|-------------|
| Ok result path | ~line 1313 | No filter — errors with subtype=success passed through |
| subtype=error path | ~line 1277 | Partial filter — bypassed by network-degraded logic |
| Activity drain text_blocks | ~line 1893 | Inline list — diverged from other paths over time |
| Timer result path | ~line 3009 | No filter at all |

Each suppression emits a `warn!` log entry recording the agent name and error text, making it straightforward to verify in production that suppressions are firing correctly and not silently swallowing legitimate output.

### Part 2: Thread Strategy Overhaul (MSC3440 Compliance)

Matrix MSC3440 defines a threading model where events that already carry an `m.relates_to` relation cannot themselves become thread roots — attempting to create a thread off such an event produces a server-side error. The coordinator was not inspecting incoming events for existing relations before deciding how to thread responses.

Changes by room type:

**DM rooms:** Threading disabled entirely. `current_thread_root_event_id` is set to `None` for all DM room responses. Replies are sent as plain messages. This matches user expectations for 1:1 conversations and eliminates the threading failure mode in the most common interaction path.

**Group rooms:** MSC3440-compliant threading logic:
- If the incoming event carries `m.relates_to`, the existing thread root is extracted from that relation and used as the thread target.
- If the incoming event has no relation, its `event_id` is used as the thread root directly (existing behavior, preserved).

**Activity drain (tool activity posts):** Skipped entirely for DM rooms. Tool activity threads are appropriate in group/project rooms where multiple agents post, but add noise in 1:1 conversations.

### Part 3: Test Coverage

The first `#[cfg(test)] mod tests` block in `coordinator.rs` was added as part of this session. Two tests cover the new filter function:

- `suppressed_error_catches_invalid_api_key` — confirms the function returns `true` for representative auth error strings
- `suppressed_error_allows_normal_text` — confirms the function returns `false` for valid assistant output

Test suite result: **43 passed** (41 pre-existing + 2 new).

---

## Files Modified

| File | Change summary |
|------|---------------|
| `coordinator/src/coordinator.rs` | Centralized error filter, 4-path application, DM threading disable, MSC3440 group room fix, test module — net +102/-18 lines |
| `CLAUDE.md` | Resilience notes updated to reflect coordinator error relay behavior |

---

## Security Note

During this session, environment variable inspection via `ps -E` revealed that seven secrets were visible in process environment listings on Whitebox:

- `ANTHROPIC_API_KEY`
- `OPENROUTER_API_KEY`
- `GRAPHITI_AUTH_TOKEN`
- `MATRIX_TOKEN_PAN_BOOT`, `MATRIX_TOKEN_PAN_COORD`, `MATRIX_TOKEN_PAN_IG88`, `MATRIX_TOKEN_PAN_KELK`

Manual rotation via the Bitwarden web vault is required. The exposure vector is `mcp-env.sh` injecting secrets into the coordinator process environment, which is then readable by any local user via `/proc` or `ps`. Mitigation options (e.g., secret files, systemd `LoadCredential`) are deferred to the next security pass.

---

## Verification Steps

1. `cargo test` in `coordinator/` — expect 43 passed, 0 failed
2. `cargo build --release` — expect clean compile
3. On Whitebox: `git pull` in factory repo, then restart coordinator via launchctl
4. Send a message to Boot in a DM room — confirm no "Invalid API key" text appears in the Matrix room
5. Tail coordinator log and confirm "Suppressed CLI error" entries appear when auth errors are generated
6. In a group room, send a message that already has a thread relation — confirm coordinator response threads correctly to the existing root rather than erroring

---

## Next Steps

- Rotate the 7 exposed secrets via Bitwarden web vault (manual, not in this session)
- Investigate `ps -E` exposure vector; evaluate `LoadCredential` or secret file pattern for launchd services
- Wire `CircuitBreaker` to the send path (deferred from FCT041)
- Task lease persistence across restarts (deferred from FCT041)
