# Factory Agents — Topology and Routing

**Updated:** 2026-04-14 | **Ref:** FCT067

---

## Agent Roster

| Agent | Matrix User | Main Model | Provider | Port | Hermes Profile |
|-------|------------|------------|----------|------|----------------|
| **Boot** | @boot.industries:matrix.org | Gemma 4 E4B 6-bit | Local MLX (mlx-vlm) | :41961 | `~/.hermes/profiles/boot/` |
| **Kelk** | @sir.kelk:matrix.org | Gemma 4 E4B 6-bit | Local MLX (mlx-vlm) | :41962 | `~/.hermes/profiles/kelk/` |
| **IG-88** | @ig88bot:matrix.org | Xiaomi Mimo-v2-Pro | Nous Portal (cloud) | N/A | `~/.hermes/profiles/ig88/` |

---

## Inference Topology

```
                    ┌─────────────────────────────┐
                    │     Whitebox (32GB M1 Max)    │
                    │                               │
  Boot main chat ──▶│  :41961  E4B 6-bit (mlx-vlm) │  ~7.5GB RAM
                    │                               │
  Kelk main chat ──▶│  :41962  E4B 6-bit (mlx-vlm) │  ~7.5GB RAM
                    │                               │
  Boot+Kelk aux ───▶│  :41966  26B-A4B 6-bit        │  ~3GB resident
                    │          (flash-moe SSD stream) │  experts from SSD
                    └─────────────────────────────┘

  IG-88 ───────────▶  Nous Portal (cloud)
                       xiaomi/mimo-v2-pro (free tier)
```

### Aux Slot Routing (Boot + Kelk)

All auxiliary subsystems route to the 26B on :41966:

| Slot | Function | Port |
|------|----------|------|
| compression | Summarizes old turns when context grows | :41966 |
| session_search | Searches past sessions for context | :41966 |
| skills_hub | Selects skills from registry | :41966 |
| vision | Processes images | :41966 |
| web_extract | Extracts content from web pages | :41966 |
| approval | Evaluates tool call safety | :41966 |
| mcp | MCP server tool calls | :41966 |
| flush_memories | Writes session memories | :41966 |

### Performance

| Model | Backend | tok/s | RAM |
|-------|---------|-------|-----|
| E4B (main chat) | mlx-vlm | ~30 | ~7.5GB |
| 26B-A4B (aux) | flash-moe SSD | ~5.4 | ~3GB resident |
| Mimo Pro (IG-88) | Nous cloud | N/A | 0 (cloud) |

---

## SSD Expert Streaming (flash-moe)

The 26B-A4B model (20GB at 6-bit) is split into:
- **Resident weights** (2.88GB): embeddings, attention, norms, routing — always in Metal GPU RAM
- **Expert ECB files** (30 layers x 618MB): memory-mapped from internal SSD, only active experts paged in per token

Split model location: `/Users/nesbitt/models/gemma-4-26b-a4b-it-6bit-split/`
Binary: `/Users/nesbitt/dev/vendor/flash-moe-gemma4/target/release/flash-moe`
HTTP wrapper: `/Users/nesbitt/dev/factory/scripts/flash-moe-server.py`

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
MATRIX_PASSWORD='...' MATRIX_RECOVERY_KEY='...' \
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
| `scripts/hermes-boot.sh` | Boot | Gateway with Matrix + webhook |
| `scripts/hermes-kelk.sh` | Kelk | Gateway with Matrix + webhook |
| `scripts/hermes-ig88.sh` | IG-88 | Gateway with Matrix + webhook |
| `scripts/flash-moe-server.py` | Shared | 26B aux server on :41966 |

## Plists (launchd)

| Plist | Service |
|-------|---------|
| `com.bootindustries.hermes-boot.plist` | Boot Hermes gateway |
| `com.bootindustries.hermes-kelk.plist` | Kelk Hermes gateway |
| `com.bootindustries.hermes-ig88.plist` | IG-88 Hermes gateway |
| `com.bootindustries.mlx-vlm-boot.plist` | Boot E4B on :41961 |
| `com.bootindustries.mlx-vlm-kelk.plist` | Kelk E4B on :41962 |
| `com.bootindustries.flash-moe-26b.plist` | 26B aux on :41966 |

## CLI Aliases

| Alias | What it does |
|-------|-------------|
| `h-boot` | Boot CLI chat session (Infisical factory project, cloud keys scrubbed) |
| `h-kelk` | Kelk CLI chat session (Infisical factory project, cloud keys scrubbed) |
| `h-ig88` | IG-88 CLI chat session (Infisical factory project, Nous auth) |
