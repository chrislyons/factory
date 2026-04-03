# FCT048 Agent Console Tmux Bridge

**Created:** 2026-04-03 | **Status:** Implemented | **Sprint:** April W1
**Prereqs:** FCT047 (Hermes runtime integration)

---

## Summary

The Agent Console inverts the coordinator's I/O model. Instead of agents existing solely behind Matrix message polling, each agent now gets a dedicated tmux session that serves as a shared terminal view. Matrix becomes one of several clients that can interact with an agent. The tmux pty serializes all input naturally — no collision between coordinator dispatch and human terminal users.

This is an observability and debugging feature, not a replacement for the stream-json protocol. The pty is a rendered view of agent activity, not the agent's actual I/O channel.

## Architecture

```
                          ┌──────────────────┐
                          │  Matrix (polling) │
                          └────────┬─────────┘
                                   │
                                   v
┌─────────────────┐     ┌──────────────────────┐     ┌───────────────────┐
│ SSH terminal    │────>│    coordinator-rs     │<───>│  Claude/Hermes    │
│ (Tailnet user)  │     │                      │     │  (stream-json)    │
└─────────────────┘     └──────────┬───────────┘     └───────────────────┘
                                   │
                          write_to_agent_console()
                                   │
                                   v
                        ┌──────────────────────┐
                        │  tmux: agent-<name>  │
                        │  (pty view layer)    │
                        └──────────────────────┘
                                   ^
                                   │ attach / watch
                          ┌────────┴─────────┐
                          │ Any Tailnet SSH   │
                          │ client            │
                          └──────────────────┘
```

Key properties:

- Each agent gets a named tmux session (`agent-<name>`) created at spawn time
- Coordinator communicates with agents via stream-json pipes (unchanged)
- Coordinator renders attributed input/output lines to the tmux session
- Any Tailnet SSH client can attach to observe or interact
- The pty is a view layer only — it does not sit in the I/O path between coordinator and agent

## Configuration

Two new fields added to `Settings` in `config.rs`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `agent_console_enabled` | `bool` | `false` | Opt-in feature gate |
| `agent_tmux_socket_dir` | `Option<String>` | `/tmp/tmux-nesbitt` | Socket directory for tmux sessions |

Both use `#[serde(default)]` for zero-migration backward compatibility. Existing deployments are unaffected until the flag is explicitly enabled.

## Components

### 1. config.rs — Settings Fields

```rust
pub agent_console_enabled: bool,          // default false
pub agent_tmux_socket_dir: Option<String>, // default /tmp/tmux-nesbitt
```

### 2. agent.rs — Session Lifecycle

- `ensure_tmux_session()` — creates or reuses a named tmux session (`agent-<name>`) at spawn time; idempotent across agent restarts
- New field `tmux_session_name: Option<String>` on `AgentSession` — populated when console is enabled, `None` otherwise

### 3. coordinator.rs — I/O Rendering

- `write_to_agent_console()` — helper that writes attributed lines to the agent's tmux pane via `tmux send-keys`
- Input attribution in `dispatch_to_agent()` — Matrix messages rendered as `[HH:MM] matrix/sender message`
- Output rendering in `drain_agent_activity()` — tool calls and response text written to the pty with coordinator attribution

Attribution format by source:

| Source | Format |
|--------|--------|
| Matrix user | `[14:32] matrix/@alice message text` |
| Terminal user | `[14:32] terminal/user@host message text` |
| Coordinator | `[14:32] coordinator: action description` |

### 4. scripts/agent-console.sh — CLI Manager

Shell script for managing tmux console sessions:

```bash
agent-console.sh <agent> --attach    # read-write session
agent-console.sh <agent> --watch     # read-only (observer mode)
agent-console.sh --list              # list all agent sessions
agent-console.sh <agent> --create    # manually create session
```

### 5. plists/com.bootindustries.agent-console-boot.plist — launchd Persistence

LaunchAgent plist that ensures Boot's tmux session survives reboots. Uses `RunAtLoad: true` consistent with the resilience model established in FCT041.

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Network | Tailscale ACLs — only Tailnet members can reach Whitebox |
| Authentication | SSH key-based auth required to attach |
| Socket permissions | `/tmp/tmux-nesbitt/` directory is `chmod 700` (owner-only) |
| Attribution | All input sources are labeled in the pty scrollback |
| Credential isolation | No credentials appear in pty output — agent I/O is rendered, not piped |

Observer mode (`--watch`) attaches with tmux's read-only flag, preventing accidental input from monitoring sessions.

## Usage

From any machine on the Tailnet:

```bash
# Attach to boot's console (read-write)
ssh nesbitt@whitebox ~/dev/factory/scripts/agent-console.sh boot --attach

# Watch boot's activity (read-only observer)
ssh nesbitt@whitebox ~/dev/factory/scripts/agent-console.sh boot --watch

# List all active agent sessions
ssh nesbitt@whitebox ~/dev/factory/scripts/agent-console.sh --list
```

## What Does NOT Change

- Stream-json I/O between coordinator and Claude/Hermes processes
- Matrix polling, approval flows, circuit breaker, trust levels
- Standalone sessions (Claude Code interactive, Hermes loops)
- All existing launchd plists (12 bootindustries agents + pantalaimon)
- Agent spawn logic — `ensure_tmux_session()` is additive, gated behind `agent_console_enabled`

## Verification Checklist

| # | Check | Method |
|---|-------|--------|
| 1 | Live conversation visible | `agent-console.sh boot --attach` shows Matrix messages flowing |
| 2 | Input attribution correct | Matrix message appears as `[HH:MM] matrix/sender ...` in pty |
| 3 | Observer mode is read-only | `--watch` prevents keyboard input |
| 4 | SSH disconnect is non-destructive | Disconnect and reattach — session and scrollback intact |
| 5 | Socket permissions locked | `stat /tmp/tmux-nesbitt` shows `drwx------` (700) |
| 6 | Feature gate works | `agent_console_enabled: false` skips all tmux operations |

## Implementation

4 commits, approximately 320 lines added:

| Commit | Scope | Description |
|--------|-------|-------------|
| `4b3cdac` | config.rs | Add `agent_console_enabled` and `agent_tmux_socket_dir` settings fields |
| `81f63b7` | coordinator.rs | Add `write_to_agent_console()` with input/output attribution rendering |
| `d83ccf9` | agent.rs | Add `ensure_tmux_session()` lifecycle and `tmux_session_name` on `AgentSession` |
| `1bf3fc3` | scripts/ | Add `agent-console.sh` tmux session manager with attach/watch/list modes |

## References

[1] FCT041 Resilience Hardening — Power Outage and Self-Healing
[2] FCT043 Matrix Mechanisms — Spaces, Threads, Replies, and Notifications
[3] FCT047 Hermes Runtime Integration Phase 3 Implementation
