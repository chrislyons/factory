# Factory Agents — Topology and Routing

**Updated:** 2026-04-30 (dual SABER, Ornstein deprecated) | **Ref:** FCT078, FCT083

---

## Agent Roster

| Agent | Matrix User | Main Model | Provider | Port | Hermes Profile |
|-------|------------|------------|----------|------|----------------|
| **Boot** | @boot.industries:matrix.org | Gemma-4-E4B-SABER | Local MLX (mlx_lm.server) | :41961 | `~/.hermes/profiles/boot/` |
| **Kelk** | @sir.kelk:matrix.org | Gemma-4-E4B-SABER | Local MLX (mlx_lm.server) | :41962 | `~/.hermes/profiles/kelk/` |
| **IG-88** | @ig88bot:matrix.org | Xiaomi Mimo-v2-Pro | Nous Portal (cloud) | N/A | `~/.hermes/profiles/ig88/` |

---

## Inference Topology

```
                    ┌─────────────────────────────────────┐
                    │       Whitebox (32GB M1 Max)         │
                    │                                        │
  Boot main chat ──▶│ :41961  SABER E4B 6bit    ~50 tok/s │
  Kelk main chat ──▶│ :41962  SABER E4B 6bit    ~50 tok/s │
                    │                                        │
                    │  All inference (main + aux) runs on    │
                    │  SABER — Ornstein deprecated 2026-04-30│
                    └─────────────────────────────────────┘
  IG-88 ────────────▶  Nous Portal (cloud)
                        minimax/minimax-m2.7
```

### Aux Slot Routing (Boot + Kelk)

All aux slots route to SABER on their respective ports. Ornstein 35B was deprecated — the MoE model exceeded 32GB unified memory and caused GPU abort crashes under concurrent load. SABER handles everything including thinking, compression, vision, and session_search.

| Slot | Function | Target | Model |
|------|----------|--------|-------|
| `approval` | Tool call safety check | :41961/:41962 | SABER |
| `compression` | Context summarization | :41961/:41962 | SABER |
| `flush_memories` | Write session memories | :41961/:41962 | SABER |
| `mcp` | MCP server tool calls | :41961/:41962 | SABER |
| `session_search` | Search past sessions | :41961/:41962 | SABER |
| `skills_hub` | Select skills from registry | :41961/:41962 | SABER |
| `thinking` | Deep reasoning consultant | :41961/:41962 | SABER |
| `title_generation` | Generate conversation titles | :41961/:41962 | SABER |
| `vision` | Image analysis | :41961/:41962 | SABER |
| `web_extract` | Extract web content | :41961/:41962 | SABER |

### Performance

| Model | Backend | tok/s | RAM |
|-------|---------|-------|-----|
| SABER E4B 6bit (×2) | mlx_lm.server | ~50 (short) / ~16 (25K ctx) | ~6.3 GB per instance |
| Mimo Pro (IG-88) | Nous cloud | N/A | 0 (cloud) |

---

## Gemma-4-E4B-SABER — Frontdoor Model

Gemma-4-E4B-SABER (GestaltLabs) is an abliterated Gemma4 fine-tune — refusal
behaviors removed via representation engineering. Runs raw (no adapter) with
agent-specific system prompts for Boot vs Kelk differentiation.

### Why SABER?

- 7/8 benchmark score with no adapter (identity, tool_call, autonomy, conciseness)
- Abliterated — decisive, no refusal hedging, executes immediately
- Multimodal — can analyze screenshots and audio
- 5.7 GB disk, ~5.5 GB RAM per instance
- 2× faster training than Qwen3.5-4B (standard attention, no GatedDeltaNet)

### Architecture

- 42 layers, hidden=2560, intermediate=10240
- 8 attention heads, 2 KV heads (GQA)
- 128K context window
- 6-bit quantization (group_size=64)
- Source: google/gemma-4-E4B-it → abliterated → MLX quantized

### Memory Budget

Per FCT078 stress tests (2026-04-30): dual SABER with 4GB cache caps, RSS flat at ~6.3GB per instance under all load conditions including concurrent 25K-token inference. Peak wired memory during concurrent load: ~20GB.

| Component | RAM |
|-----------|-----|
| macOS + system | ~7 GB |
| Boot SABER (:41961) | ~6.3 GB |
| Kelk SABER (:41962) | ~6.3 GB |
| Hermes gateways | ~0.5 GB |
| **Total** | **~20 GB** |
| **Free** | **~12 GB** |

### Deployment

- mlx_lm.server on :41961 (Boot) and :41962 (Kelk)
- mlx-lm 0.31.3 (brew upgrade)
- `--prompt-cache-bytes 4294967296` (4GB cap per server — prevents OOM under concurrent load)
- `--prompt-concurrency 1` (prevents concurrent prefill GPU OOM on 32GB M1 Max)
- No adapter — raw model with system prompt
- Model path: `/Users/nesbitt/models/Gemma-4-E4B-SABER-MLX-6bit`

---

## Ornstein 35B (DEPRECATED — 2026-04-30)

Ornstein3.6-35B-A3B was previously used as a deep reasoning consultant via flash-moe on :41966. It was **deprecated on 2026-04-30** because the MoE model exceeded 32GB unified memory and caused GPU abort crashes during concurrent SABER+Ornstein inference.

See FCT078 for full stress test results. The current architecture runs all inference (including thinking, compression, vision) on SABER E4B.

The binary and model files remain on disk but are not in use:
- Binary: `/Users/nesbitt/dev/vendor/flash-moe-gemma4/target/release/flash-moe`
- Model: `/Users/nesbitt/models/Ornstein3.6-35B-A3B-flash-moe-8bit/`

---

## Qwen3.5-2B + v4v2 Adapter (DEPRECATED)

Replaced by SABER on 2026-04-29. The 2B model collapsed into repetitive loops
with zero tool calls in Matrix sessions. See FCT083 for benchmark details.

---

## Matrix E2EE

All agents connect directly to `https://matrix.org` with native E2EE (python-olm + matrix-nio[e2e]).
Pantalaimon is retired.

### Secrets (Infisical — factory project)

| Variable | Purpose | Runtime? |
|----------|---------|----------|
| `MATRIX_TOKEN_BOOT` | Boot access token | Yes |
| `MATRIX_TOKEN_KELK` | Kelk access token | Yes |
| `MATRIX_TOKEN_IG88` | IG-88 access token | Yes |

Recovery keys and passwords are in the operator's personal vault only. Not in Infisical.

### Cross-Signing

Run from `~/dev/factory/scripts/matrix-cross-sign/`:
```bash
MATRIX_PASSWORD='***' MATRIX_RECOVERY_KEY='...' \
  npx tsx cross-sign.ts sign --user @ig88bot:matrix.org
```
Secrets via short-lived subshell only. Nothing persisted.

---

## Cloud Provider Policy

| Agent | Cloud Access | Rationale |
|-------|-------------|-----------|
| **Boot** | None | Fully local. All cloud API keys scrubbed in wrapper. |
| **Kelk** | None | Fully local. All cloud API keys scrubbed in wrapper. |
| **IG-88** | Nous Portal only | Trading agent needs cloud-grade reasoning. OpenRouter available as fallback. |

---

## Wrapper Scripts

| Script | Agent | Launches |
|--------|-------|----------|
| `scripts/hermes-boot.sh` | Boot | Hermes gateway with Matrix + webhook |
| `scripts/hermes-kelk.sh` | Kelk | Hermes gateway with Matrix + webhook |
| `scripts/hermes-ig88.sh` | IG-88 | Hermes gateway with Matrix + webhook |

## Plists (launchd)

| Plist | Service |
|-------|---------|
| `com.bootindustries.mlx-lm-factory-boot.plist` | SABER on :41961 |
| `com.bootindustries.mlx-lm-factory-kelk.plist` | SABER on :41962 |
| `com.bootindustries.hermes-boot.plist` | Boot Hermes gateway |
| `com.bootindustries.hermes-kelk.plist` | Kelk Hermes gateway |
| `com.bootindustries.hermes-ig88.plist` | IG-88 Hermes gateway |

Note: `mlx-lm-boot` and `mlx-lm-kelk` (per-agent naming) were replaced by `mlx-lm-factory-boot` and `mlx-lm-factory-kelk`. Old plist names retired.

## CLI Aliases

| Alias | What it does |
|-------|-------------|
| `h-boot` | Boot CLI chat session (Infisical factory project, cloud keys scrubbed) |
| `h-kelk` | Kelk CLI chat session (Infisical factory project, cloud keys scrubbed) |
| `h-ig88` | IG-88 CLI chat session (Infisical factory project, Nous auth) |

---

## Shared Infrastructure

### Machines

| Machine | Address | Role |
|---------|---------|------|
| Whitebox | 100.88.222.111 | Mac Studio, 32GB M1 Max — primary inference host |
| Cloudkicker | 100.86.68.16 | chrislyons@cloudkicker — remote deployment target |

### SSH

SSH agent is session-scoped. Must find socket manually in `~/.ssh/agent/`.
ALWAYS `git pull` before making changes on Cloudkicker.

### Secrets

Managed via Infisical (factory project). Machine identity auth.
Key variables: MATRIX_TOKEN_BOOT, MATRIX_TOKEN_KELK, MATRIX_TOKEN_IG88,
NOUS_MIMO_FACTORY_KEY. Recovery keys in operator's personal vault only.

### Launchd Conventions

- `launchctl unload/load` to pick up plist ProgramArguments changes
- `launchctl kickstart` only restarts the process, does NOT reload the plist
- Plists at `~/Library/LaunchAgents/com.bootindustries.*`
- Logs at `~/Library/Logs/factory/`

### mlx_lm.server Conventions

- `--max-tokens` MUST be in plist (server defaults to 512 without it)
- Hermes never passes config.yaml max_tokens to the API (GitHub #4404)
- Thinking tokens count against max_tokens budget
- Use `--prefill-step-size 2048` for all instances
- Model path is full absolute path (not short name)
