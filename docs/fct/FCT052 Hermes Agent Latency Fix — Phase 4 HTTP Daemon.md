# FCT052 Hermes Agent Latency Fix — Phase 4 HTTP Daemon

**Date:** 2026-04-08
**Status:** Complete
**Scope:** All three Hermes agents (IG-88, Boot, Kelk) — latency diagnosis and two-phase remediation

---

## Summary

All three Hermes agents were experiencing severe response latency when receiving Matrix messages. IG-88 was timing out at 180s, Boot at 116s, Kelk at 49s. A two-phase fix was deployed on 2026-04-08: configuration corrections (Phase 1) followed by a persistent HTTP daemon architecture (Phase 2, internally "Phase 4" in the coordinator dispatch hierarchy).

## Root Causes

Five distinct issues contributed to the latency:

1. **Hermes approval system blocking headless mode.** `HERMES_INTERACTIVE=1` was set unconditionally in `cli.py` even for `-q` (quiet/headless) mode. Combined with `approvals.mode: auto` (an invalid value that falls through to interactive), this caused a 60s stdin timeout per tool call. Each message involving tool use accumulated 120-180s of dead wait.

2. **40 toolsets loaded by default.** `toolsets: []` in the profile config was interpreted as "load all defaults" by Hermes, including browser (which fails headless), homeassistant, image_gen, and TTS. A failed browser tool triggered fallback to terminal, which then hit the approval timeout chain.

3. **Per-message Python startup and MCP reinit.** Each `hermes chat -q` invocation spawned a fresh Python process, re-imported all modules, and reconnected to all MCP servers. This added approximately 5s overhead per message.

4. **Boot: claudezilla stdio MCP.** Boot's profile included the Claudezilla MCP server configured as stdio transport, spawning a Node.js subprocess per message (5-10s extra).

5. **Boot/Kelk: local MLX model inference.** Both agents were configured with 3-4B parameter local models exhibiting slow inference and `finish_reason=length` retries.

## Phase 1: Configuration Fixes (Immediate)

Changes applied directly to Hermes profile configs:

- `approvals.mode: "off"` in all three profiles (the coordinator has its own approval system, making Hermes-level approvals redundant)
- Explicit toolsets per agent:
  - IG-88: `[terminal, file, code_execution, web]`
  - Boot: `[terminal, file, code_execution]`
  - Kelk: `[terminal, file]`
- `connect_timeout: 10` on all MCP server entries
- Claudezilla disabled in Boot profile
- `--yolo` flag added to coordinator's subprocess spawn as defense-in-depth
- Malformed timer file deleted; duplicate MLX-LM server process killed

**Result:** IG-88 dropped from 185s to 4.6s (simple messages) / 7.2s (messages with tool use).

## Phase 2: Persistent HTTP Daemon

### hermes-serve.py

A new Python daemon (~196 lines) wrapping Hermes's `AIAgent` class. Keeps the agent instance and all MCP connections warm across messages, eliminating per-message startup cost.

- **Endpoints:**
  - `POST /v1/chat/completions` -- OpenAI-compatible chat interface
  - `GET /health` -- Liveness check (returns agent status)
  - `POST /v1/reload` -- Hot-reload profile config without restart
- **Thread model:** `asyncio.Lock` with a single-worker `ThreadPoolExecutor` to serialize agent calls
- **One daemon per agent:** IG-88 on `:41971`, Boot on `:41970`, Kelk on `:41972`

### Coordinator Changes

- `hermes_adapter.rs`: Activated the `HermesHttpClient` path (previously dead code). Added `health_check()` and system prompt support for the HTTP interface.
- `agent.rs`: Implemented Phase 4 HTTP dispatch with automatic subprocess fallback. If the daemon responds healthy at coordinator startup, all messages route via HTTP. If an individual HTTP call fails mid-operation, the coordinator falls back to subprocess for that specific message.

### Deployment

Three launchd plists added:

- `com.bootindustries.hermes-ig88.plist`
- `com.bootindustries.hermes-boot.plist`
- `com.bootindustries.hermes-kelk.plist`

Each runs via `infisical-env.sh factory -- python3 hermes-serve.py --profile <name> --port <N>`. All configured with `RunAtLoad` and `KeepAlive` for self-healing after reboot.

**Result:** IG-88 dropped from 4.6s (subprocess, Phase 1) to 2.0s (HTTP daemon, Phase 2). All three agents connect to their HTTP daemons at coordinator startup.

## Architecture

```
Matrix --> Coordinator-rs --> HermesHttpClient --> hermes-serve.py (persistent)
                                                        |
                                                   AIAgent (warm)
                                                        |
                                                MCP servers (warm connections)
                                                +-- qdrant-mcp (:41460)
                                                +-- research-mcp (:41470)
                                                +-- graphiti (:41440, disabled)
                                                        |
                                                LLM API (OpenRouter / local MLX)
```

Fallback path (if daemon unreachable):

```
Coordinator-rs --> subprocess: hermes chat -q "msg" -Q --source tool --yolo
```

## Performance Summary

| Agent  | Before         | After Phase 1      | After Phase 2      |
|--------|----------------|--------------------|--------------------|
| IG-88  | 180s (timeout) | 4.6s / 7.2s       | 2.0s (measured)    |
| Boot   | 116s           | ~90s (MLX bound)   | ~85s (MLX bound)   |
| Kelk   | 49s            | ~40s               | ~35s               |

Boot and Kelk remain slow due to local MLX model inference. This is a separate optimization target (Phase 3, future work -- likely requires model swap or quantization changes).

## Key Discovery: The Approval Smoking Gun

The root cause was a two-line interaction across separate files in the Hermes codebase.

In `tools/approval.py:641`, headless auto-approval logic exists:

```python
if not is_cli and not is_gateway and not is_ask:
    return {"approved": True, "message": None}  # auto-approve headless
```

But in `cli.py:7934`, the environment is poisoned for all modes:

```python
os.environ["HERMES_INTERACTIVE"] = "1"  # set EVEN for -q mode!
```

This made every `-q` invocation appear interactive to the approval system, triggering approval prompts against null stdin with a 60s timeout per tool call.

## Files Modified

| File | Change |
|------|--------|
| `coordinator/src/agent.rs` | Phase 4 HTTP dispatch logic, `--yolo` flag on subprocess spawn |
| `coordinator/src/hermes_adapter.rs` | Activated `HermesHttpClient`, added `health_check()` and system prompt |
| `scripts/hermes-serve.py` | New persistent HTTP daemon wrapping Hermes AIAgent |
| `plists/com.bootindustries.hermes-ig88.plist` | New launchd service |
| `plists/com.bootindustries.hermes-boot.plist` | New launchd service |
| `plists/com.bootindustries.hermes-kelk.plist` | New launchd service |
| `~/.hermes/profiles/ig88/config.yaml` | approvals, toolsets, connect_timeout |
| `~/.hermes/profiles/boot/config.yaml` | approvals, toolsets, connect_timeout, claudezilla removal |
| `~/.hermes/profiles/kelk/config.yaml` | approvals, toolsets, connect_timeout |

## Commit

`d889ab0` feat(coordinator): add Phase 4 Hermes HTTP daemon mode for agent latency fix

---

*FCT052 -- Factory Documentation*
