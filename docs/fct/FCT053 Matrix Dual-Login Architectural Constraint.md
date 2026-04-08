# FCT053 Matrix Dual-Login Architectural Constraint

**Status:** Finding (architectural guardrail)
**Date:** 2026-04-08
**Context:** Multi-agent transport architecture — why a single Matrix user cannot be split across two concurrent transports (e.g., Hermes gateway for DMs, coordinator for collaborative rooms).

## Summary

You cannot split a single Matrix user account between two concurrent transports. A single Matrix identity always sees the same set of joined rooms regardless of how many clients are logged in, and two clients sharing one access token will race each other for events and room keys in ways that break silently.

This constraint forced the current architecture: each agent identity is one Matrix user, transport is chosen per-identity (coordinator or standalone Hermes gateway), and any "DM-only agent" must be a distinct Matrix account — not a second login for an existing agent.

## The Constraint in Detail

### 1. Room membership is account-level, not device-level

Matrix's data model makes joined rooms a property of the user account, not of any individual device or session. If `@boot.industries:matrix.org` is joined to 15 rooms, every device or client logged in as that user sees those same 15 rooms via `/sync`. There is no way for "device A" to be in DM rooms only and "device B" to be in collaborative rooms only while both speak as the same user. Leaving a room is an account-wide action.

This kills any "split-brain" architecture where a gateway handles only a subset of rooms and the coordinator handles the rest. Both clients would see every room regardless of intent. Filtering would have to happen per-client, in user-space, with zero Matrix-level enforcement.

### 2. Same access token = same device_id

The Hermes Matrix adapter (`gateway/platforms/matrix.py`) calls `whoami` to resolve the `device_id` bound to the provided access token, then calls `restore_login()` to reuse that device. The coordinator's reqwest transport uses the same token opaquely. Both clients resolve to the same `device_id` from Matrix's perspective.

From the homeserver's view there is one device with two HTTP consumers. Matrix does not queue events for concurrent consumers — it serves whatever has accumulated since the `since` cursor to whichever `/sync` call arrives first. Both clients independently decide to dispatch incoming events to their agent logic. Without flawless room filtering in both transports, the agent answers twice.

### 3. To-device events are consumed once per device

Megolm room-key shares, key requests, and key forwards arrive as to-device events. Matrix delivers each to-device event exactly once per device, then removes it from the queue. Two clients sharing a device race for those events — the one whose sync loop reads first wins, and the other never sees them.

The practical failure mode: in an E2EE room, one client gets the room key and the other silently fails to decrypt new Megolm sessions. The symptom is intermittent "unable to decrypt" indicators that rotate between clients depending on which one was awake when a key share arrived. There is no recovery path short of manually re-requesting keys from the session-sharing client.

This is the most dangerous part of the dual-login antipattern because it fails quietly and intermittently, and it only manifests in rooms with encryption enabled. The IG-88 training room is currently unencrypted; Boot and Kelk DMs may or may not be, depending on how they were set up in Element.

### 4. Pantalaimon assumes one PanClient per token

The coordinator's Matrix traffic goes through a local Pantalaimon proxy at `:41200`, which runs its own `PanClient` per authenticated user. Pantalaimon's configuration schema uses one `[user]` block per upstream account, with a single internal `/sync` loop per block. Two clients hitting Pantalaimon with the same token end up sharing one PanClient — which means two consumers on one internal sync stream, exactly the same race condition as speaking directly to the homeserver, just wrapped in a proxy layer.

Running one transport through Pantalaimon and the other directly to matrix.org avoids the Pantalaimon-internal race but preserves the homeserver-level race (same `device_id`, same to-device queue).

### 5. Typing indicators and read receipts

Minor compared to the above, but worth noting: both clients call `room_typing` and update read markers. These events collapse at the homeserver (last-write-wins for receipts, duplicate-tolerant for typing), so you get flickering typing indicators and occasionally "unread" messages popping back to read as the other client catches up. Annoying, not data-loss.

## The Hermes Gateway Also Has No Room Filter

Even if you wanted to accept the dual-login risks, Hermes's Matrix adapter has no built-in room allowlist. The only gating mechanisms are:

- `MATRIX_REQUIRE_MENTION=true` (default) — require `@mention` to respond, but does not stop the gateway from seeing events in other rooms
- `MATRIX_FREE_RESPONSE_ROOMS=<comma-separated room ids>` — rooms where mention is not required
- `GATEWAY_ALLOWED_USERS=<csv>` — user-level allowlist; events from non-listed senders are silently dropped regardless of room
- `_handle_message()` in `gateway/run.py` does not check room_id before dispatch

There is no `MATRIX_ALLOWED_ROOMS` or equivalent in the Hermes source. The gateway's `agent:start` hook fires after message authorization and does not receive `room_id` in its context, so a startup hook cannot cleanly filter by room. Any room filter would have to be a monkey-patch of the private `_on_room_message` method on the adapter instance — fragile across Hermes upgrades.

## The Coordinator Has No Per-Agent Room Skip

`AgentConfig` in `coordinator/src/config.rs` has no `skip_rooms` field. `get_agents_for_room()` in `coordinator/src/coordinator.rs` is purely additive — it walks `room_config.default_agent` and `room_config.agents` and includes them if mention rules pass. There is no negative filter that says "agent X never replies in room Y." Adding one would be ~15 lines of Rust; the constraint is not that it can't be added, it's that the dual-login layer above it is already broken.

## Viable Architectures

With dual-login off the table, the supported patterns are:

**1. Coordinator-managed agent (Boot, Kelk today).** One Matrix identity, one access token, all traffic through the coordinator's Pantalaimon connection. Coordinator handles routing, threading, approvals, and inter-agent state. Latency is bounded by the coordinator's `/sync` poll cycle (parallelized across agents post-FCT052-phase1, worst case ~30s).

**2. Standalone Hermes gateway (IG-88 today).** One Matrix identity, one access token, all traffic through a dedicated `hermes gateway run` process using matrix-nio. No coordinator involvement — the agent is on its own for approvals, threading, and any inter-agent coordination. Response latency is bounded by matrix-nio's callback-driven sync (~sub-second). Best for solo, non-collaborative agents.

**3. DM-only specialist agents (future pattern).** Each new DM-only agent gets its own Matrix user account (e.g., `@coach:matrix.org`, `@writer:matrix.org`), cross-signed once via the `matrix-cross-sign` script, then run as a standalone Hermes gateway. Zero overlap with existing agent accounts. Scales cheaply — adding an agent is a new Matrix registration, a new Hermes profile, a new launchd plist. The only shared state is Chris's recovery key (to cross-sign the new device once).

## What You Must Never Do

- **Do not run the coordinator and a Hermes gateway simultaneously for the same Matrix user.** Even if you add room filters on both sides, the to-device race condition will break Megolm key sharing on any encrypted room both clients see.
- **Do not attempt "device A for DMs, device B for groups" for one Matrix user.** Room membership is account-level — both devices see the same rooms regardless of which one you intend to handle them.
- **Do not share a Matrix access token between two long-running sync loops.** One consumer per token, always.

## If You Need a New DM-Only Agent

Pattern (e.g., a fitness coach agent):

1. Register a new Matrix user `@coach:matrix.org` (or use a local homeserver/virtual user)
2. Generate an access token (password login, store in Infisical as `MATRIX_TOKEN_PAN_COACH` or similar)
3. Run the `matrix-cross-sign` script against the new device using Chris's recovery key to establish E2EE trust
4. Create `~/.hermes/profiles/coach/config.yaml` — model, toolsets, system prompt, gateway platform config pointing at Pantalaimon or matrix.org
5. Create `scripts/hermes-coach.sh` (wrapper that exports `MATRIX_ACCESS_TOKEN`, `MATRIX_USER_ID`, `GATEWAY_ALLOWED_USERS=@chrislyons:matrix.org`, and exec's `hermes --profile coach gateway run`)
6. Create `plists/com.bootindustries.hermes-coach.plist` wrapping the script via `infisical-env.sh`
7. Deploy to `~/Library/LaunchAgents/` and load

The coach agent now runs independently, sees only its own rooms, and cannot conflict with any existing agent. No coordinator changes. No shared tokens. No dual-login risk.

## Historical Context

This constraint was investigated when evaluating whether to move Boot and Kelk's DM rooms to a Hermes gateway for lower latency while keeping collaborative rooms on the coordinator. The research concluded that splitting transports for a single Matrix identity is architecturally unsound regardless of filtering effort, and that the real latency problem for Boot/Kelk was local MLX model inference (Nanbeige 3B with broken tool calling and Qwen 4B with reasoning-token waste), not the coordinator's Matrix transport. FCT054 covers the model swap that actually fixed the latency.

The initial attempt at implementation also revealed a secondary hazard: a subagent tried to install `matrix-nio[e2e]` via a reinstall of the hermes-agent uv tool, which invalidated the shared Python venv used by all three hermes daemons mid-session. The broader lesson: supply-chain-sensitive operations on a shared runtime should always be staged and explicitly approved, never delegated to an autonomous agent without guardrails.

## References

- `coordinator/src/coordinator.rs` — `poll_once()`, `get_agents_for_room()`, `process_event()`
- `coordinator/src/config.rs` — `AgentConfig`, `Room`
- `~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/gateway/run.py` — `_is_user_authorized()`, `_handle_message()`
- `~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/gateway/platforms/matrix.py` — no room filter in adapter
- `scripts/matrix-cross-sign/cross-sign.ts` — automated device cross-signing for headless E2EE
- FCT052 — prior latency fix; see for context on parallelized sync and HTTP daemon mode
