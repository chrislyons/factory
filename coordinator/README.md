# coordinator-rs

Rust orchestration binary for the factory multi-agent system. Runs on Whitebox as a launchd service, routing messages between Matrix rooms and Claude agent subprocesses via Pantalaimon (E2EE proxy).

## Architecture

```
Matrix rooms (matrix.org)
    ↕ E2EE
Pantalaimon (:41200)
    ↕ HTTP
coordinator-rs
    ↕ stdin/stdout JSON
claude CLI subprocesses (boot, ig88, kelk)
```

**Key responsibilities:**
- Matrix sync loop (3 agents, long-poll via Pantalaimon)
- Message routing: room → agent dispatch, agent response → room
- Approval workflow: HMAC-signed gate, reaction-based decisions
- Status HUD: live agent health in the coordinator status room
- Circuit breaker, budget tracking, task leases, identity drift detection

## Build & Run

```bash
cargo build --release
cargo test
```

Config: `agents/ig88/config/agent-config.yaml`

Secrets injected via `~/.config/ig88/mcp-env.sh` (BWS → env vars):
- `MATRIX_TOKEN_PAN_{BOOT,COORD,IG88,KELK}` — Pantalaimon tokens
- `ANTHROPIC_API_KEY` — Claude API key
- `OPENROUTER_API_KEY` — OpenRouter fallback
- `GRAPHITI_AUTH_TOKEN` — Graphiti memory service

## Service Management

```bash
# Status
launchctl list com.bootindustries.coordinator-rs

# Restart
launchctl stop com.bootindustries.coordinator-rs   # KeepAlive auto-restarts

# Logs
tail -f ~/Library/Logs/factory/coordinator.log
```

Plist: `~/Library/LaunchAgents/com.bootindustries.coordinator-rs.plist`
(`RunAtLoad: true`, `KeepAlive: true`, `ThrottleInterval: 15`)

## Network Resilience

The coordinator tracks network health via `sync_consecutive_failures` and `last_sync_success`:

- **Sync backoff**: exponential 1s→2s→4s→8s→16s on consecutive failures
- **Error relay filtering**: auth errors (401/403/invalid API key) suppressed during network degradation, flushed as single summary on recovery; non-auth errors always relay immediately
- **Recovery**: first clean sync resets failure count and clears suppression state

## Dependencies

All services must be running for full functionality:

| Service | Port | Required for |
|---------|------|-------------|
| Pantalaimon | :41200 | All Matrix operations |
| Graphiti MCP | :41440 | Agent memory |
| Qdrant MCP | :41460/:41470 | Project/research vault |

On cold reboot, `KeepAlive` retries until dependencies are available. No `WaitForDependencies` configured — coordinator will log sync errors until Pantalaimon is ready (typically <30s).

## Tests

```bash
cargo test               # 41 tests
cargo test -- --nocapture
```

## Docs

- `docs/fct/FCT037` — Phase D stabilization sprint
- `docs/fct/FCT039` — Stream 2 agent readiness sprint
- `docs/fct/FCT040` — Red-team security audit
- `docs/fct/FCT041` — Power outage post-mortem and resilience hardening
