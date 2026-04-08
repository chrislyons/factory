# FCT054 Local E4B Model Consolidation — All Agents on Gemma 4 E4B 6-bit

**Status:** Implemented
**Date:** 2026-04-08
**Depends on:** FCT052 (Hermes HTTP daemon), FCT053 (Matrix dual-login constraint), IG88011 (Cloud model bake-off)

## Summary

All three Hermes agents (Boot, Kelk, IG-88) now run inference against local Gemma 4 E4B 6-bit via dedicated `mlx_vlm` HTTP servers on Whitebox. Two server instances split the workload by tenancy class: a shared "factory" server for Chris-facing conversational agents (Boot, Kelk) and a dedicated "ig88" server for IG-88's autonomous trading workloads. This consolidation retires three problematic models — Nanbeige4.1-3B (broken tool calling), Qwen3.5-4B-MLX-8bit (excessive reasoning-token waste), and Gemma 4 31B via OpenRouter (32s tool-call latency, cloud dependency) — replacing them with a single uniform model surface that has native, correct tool calling at 49 tok/s generation and ~500 tok/s prefill.

## Why E4B 6-bit

The decision tree compressed from a long arc of false starts:

1. **OpenRouter Gemma 4 26B-A4B (MoE)** was selected mid-session for IG-88 because it claimed "fast + tool use" — but IG88011's bake-off explicitly placed it in a dead zone (Brier 0.20, "worse than both E4B and 31B") and we had ignored that. Reverted.
2. **OpenRouter Gemma 4 31B Dense** was the IG88011-sanctioned T2 model, but tool-call latency measured at 32s for a single trade-cycle turn versus 2.2s on the 26B MoE. Acceptable for batch T2 work, painful for interactive DM-style use.
3. **Local Gemma 4 E4B-it 6-bit** was already on disk (`/Users/nesbitt/models/gemma-4-e4b-it-6bit`, 6.6 GB) and proven to support tool calling natively via `mlx_vlm.server`. Direct test showed 49 tok/s generation, 110 tok/s prefill, peak memory ~8.1 GB per active generation, correct OpenAI-format `tool_calls` emission. This is the IG88011 Tier 1 reference model.
4. **8-bit was considered** (`gemma-4-e4b-it-8bit`, 8.4 GB) but the only copy was symlinked to an external SSD (`/Volumes/CL T04`). Decision: stay on 6-bit until quality proves insufficient, then copy 8-bit to internal disk and swap.

E4B 6-bit gives all three agents the same capability profile, eliminates cloud dependency for IG-88 (TOS-compliant boundary preserved), and runs comfortably within the 32 GB RAM budget on Whitebox.

## Architecture

```
                                                    ┌─────────────────────┐
                            Boot DMs ────────────► hermes-boot daemon ──►
                            (factory mcp servers)   port 41970            │
                                                                          │
                                                                          ├──► mlx-vlm-factory :41961
                                                                          │    gemma-4-e4b-it-6bit
                                                    ┌─────────────────────┤    (shared, 1 instance)
                            Kelk DMs ────────────► hermes-kelk daemon ──►
                            (factory mcp servers)   port 41972            │
                                                                          │
                                                                          ┘

                            IG-88 trading room ──► hermes-ig88 gateway ──► mlx-vlm-ig88 :41988
                            (matrix-nio direct)    standalone process       gemma-4-e4b-it-6bit
                                                   (no HTTP daemon)         (dedicated instance)
```

**Tenancy split rationale:** Boot and Kelk serve Chris's interactive DMs — single-user, low concurrency, no autonomous load. They share one mlx_vlm instance because Chris has one brain and types in one conversation at a time. IG-88 runs autonomous scan loops, backtest cycles, and trade execution that can burst concurrently with whatever else is happening. Giving IG-88 its own server prevents its scan-loop bursts from delaying Chris's DM responses, and prevents Chris's DMs from starving IG-88's scheduled work.

## Memory Math

| Component | RAM (steady) | RAM (peak generation) |
|-----------|--------------|------------------------|
| mlx-vlm-factory (E4B 6-bit weights) | ~5.0 GB | +3 GB KV cache |
| mlx-vlm-ig88 (E4B 6-bit weights) | ~5.0 GB | +3 GB KV cache |
| Wired (OS, Metal, GPU drivers) | 3.1 GB | — |
| hermes-boot, hermes-kelk daemons | ~0.2 GB | — |
| hermes-ig88 gateway | ~0.1 GB | — |
| coordinator-rs | ~0.05 GB | — |
| Pantalaimon, MCP servers, misc | ~1.5 GB | — |
| **Total worst case (both gen peak)** | | **~21 GB** |

32 GB total — leaves ~11 GB headroom even at peak. Comfortable.

## Plists (gitignored — canonical record below)

The `factory/plists/` directory is gitignored per FCT040. The two new plists are reproducible from this section.

### `plists/com.bootindustries.mlx-vlm-factory.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>Label</key>
    <string>com.bootindustries.mlx-vlm-factory</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/python3</string>
        <string>-m</string>
        <string>mlx_vlm.server</string>
        <string>--model</string>
        <string>/Users/nesbitt/models/gemma-4-e4b-it-6bit</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>41961</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/Users/nesbitt/Library/Logs/factory/mlx-vlm-factory.log</string>
    <key>StandardOutPath</key>
    <string>/Users/nesbitt/Library/Logs/factory/mlx-vlm-factory.log</string>
    <key>ThrottleInterval</key>
    <integer>15</integer>
</dict>
</plist>
```

### `plists/com.bootindustries.mlx-vlm-ig88.plist`

Identical to above except:
- `Label`: `com.bootindustries.mlx-vlm-ig88`
- `--port`: `41988`
- `StandardOutPath` / `StandardErrorPath`: `/Users/nesbitt/Library/Logs/factory/mlx-vlm-ig88.log`

## Hermes Profile Changes

The three Hermes profiles at `~/.hermes/profiles/{boot,kelk,ig88}/config.yaml` were updated. Profiles live outside the factory repo and are not under version control — record below is canonical.

### `~/.hermes/profiles/boot/config.yaml`

```yaml
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
base_url: http://127.0.0.1:41961/v1
provider: custom
```

(All other fields unchanged from the existing profile — toolsets, MCP server list, approvals mode, etc.)

### `~/.hermes/profiles/kelk/config.yaml`

```yaml
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
base_url: http://127.0.0.1:41961/v1
provider: custom
```

### `~/.hermes/profiles/ig88/config.yaml`

```yaml
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
base_url: http://127.0.0.1:41988/v1
provider: custom
```

### The `provider: custom` requirement

This was the most subtle bug of the swap. Hermes's `runtime_provider.py` will only honor a config-specified `base_url` when either `requested_provider == "auto"` AND `cfg_provider` is empty/`auto`, OR `requested_provider == "custom"` AND `cfg_provider == "custom"`. If `OPENROUTER_API_KEY` is in the environment (which IG-88 had via Infisical), Hermes auto-detects the requested provider as `"openrouter"`, neither branch matches, and the config `base_url` is ignored — Hermes silently sends requests to OpenRouter instead of the local server.

The fix is to set `provider: custom` explicitly in the profile. With both `requested_norm == "custom"` (via the normalized provider chain) and `cfg_provider == "custom"`, the local `base_url` is honored.

This was added to all three profiles as a defense-in-depth measure even though Boot and Kelk don't have OPENROUTER_API_KEY in their scoped env — the explicit setting documents intent and prevents future env-var leakage from re-introducing the bug.

## Retired Components

### Models
- `Nanbeige4.1-3B-8bit` — broken tool calling (emits `<think>` tags as raw text instead of structured tool_calls), retired from Boot. Remove from disk per Chris's instruction.
- `Qwen3.5-4B-MLX-8bit` — wastes 50-70% of token budget on reasoning before answering, hits `finish_reason=length` on simple queries with default `max_tokens`. Retired from Kelk.
- `google/gemma-4-31b-it` (OpenRouter) — 32s tool-call latency, IG-88 acceptable for batch T2 only. Retired from interactive use; remains documented in IG88011 as Tier 2 fallback for high-stakes calibration tasks.
- `google/gemma-4-26b-a4b-it` (OpenRouter) — never should have been chosen, IG88011 Brier 0.20 puts it in a dead zone.

### Servers
- `mlx_lm.server` running Nanbeige on `:41961` — orphaned (not under launchd), killed.
- `mlx_lm.server` running Qwen3.5 on `:41962` — orphaned, killed. Port `:41962` now retired (no service runs there post-swap).
- `mlx_vlm.server` on `:41130` — orphaned development instance, killed. Port `:41130` now retired.

### Plists
- `plists/com.bootindustries.mlx-lm-41961.plist` — stale, points at Qwen3.5-4B which is no longer used. Deleted in this session's cleanup.
- `plists/com.bootindustries.mlx-lm-41962.plist` — stale, points at LFM2.5-1.2B. Deleted.
- `plists/com.bootindustries.hermes-ig88.plist` (the old hermes-serve HTTP daemon) — superseded by gateway, replaced with the gateway plist of the same canonical name.

## Performance

| Path | Wall time |
|------|-----------|
| Cold first request to mlx_vlm (model load from disk) | ~18s |
| Warm simple request (10 tokens out) | **0.7s** |
| Warm tool-call request (E4B emits structured tool_calls) | ~0.9s |
| End-to-end through hermes-serve daemon (Boot/Kelk, ~3.4k token system prompt) | ~9s first response, then warm |
| End-to-end through hermes gateway (IG-88, 63-char response) | **~3s** |

The hermes-serve daemon's overhead vs direct mlx_vlm comes from the ~3,400-token Hermes system prompt + tool schema being prefilled on every request. Future optimization: shrink the system prompt and toolset list per profile.

## Verification

System state at 2026-04-08 ~01:35:

```
$ launchctl list | grep -E "hermes|mlx-vlm|coordinator"
25251   0  com.bootindustries.mlx-vlm-factory
26694   0  com.bootindustries.mlx-vlm-ig88
34873   0  com.bootindustries.hermes-boot
34885   0  com.bootindustries.hermes-kelk
34897   0  com.bootindustries.hermes-ig88
83925  -9  com.bootindustries.coordinator-rs

$ curl -s http://127.0.0.1:41961/health
{"status":"healthy","loaded_model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","loaded_adapter":null}

$ curl -s http://127.0.0.1:41988/health
{"status":"healthy","loaded_model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","loaded_adapter":null}

$ curl -s http://127.0.0.1:41970/health  # hermes-boot daemon
{"status":"ok","profile":"boot","model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","uptime_seconds":276}

$ curl -s http://127.0.0.1:41972/health  # hermes-kelk daemon
{"status":"ok","profile":"kelk","model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","uptime_seconds":274}
```

IG-88 gateway log shows successful Matrix message dispatch through the local mlx_vlm pipeline (no OpenRouter 400 errors after the `provider: custom` fix landed).

## Future Work

1. **Quality validation.** This session installed the architecture but did not run extended quality checks. Send Boot, Kelk, and IG-88 a battery of representative prompts and compare responses against the previous (Nanbeige/Qwen/31B) baselines. Particular attention to: Boot's code-related queries, Kelk's reflective conversational depth, IG-88's calibration on probability-estimation tasks.
2. **8-bit upgrade path.** If 6-bit quality is insufficient, copy `gemma-4-e4b-it-8bit` from external SSD to `/Users/nesbitt/models/gemma-4-e4b-it-8bit/`, swap profile model paths, restart servers. Memory math allows this.
3. **System prompt slimming.** The 3,400-token Hermes baseline prompt is the dominant per-request latency cost. Audit which toolsets and identity instructions are actually exercised; trim the rest.
4. **IG-88 fine-tuning loop.** Per tuning-wizard (TWZ005), the long-term path is a fine-tuned Nanbeige4.1-3B with proper tool calling — but only after the wizard's eval datasets are reviewed and the training pass actually runs. E4B 6-bit is the interim until that lands.
5. **Live observation.** mlx_vlm has no built-in metrics endpoint. If we want per-request latency tracking, we'd need to add it to hermes-serve.py or wrap mlx_vlm with a thin Prometheus exporter.

## References

- `~/.hermes/profiles/{boot,kelk,ig88}/config.yaml` — current profile state
- `plists/com.bootindustries.mlx-vlm-{factory,ig88}.plist` — server definitions (gitignored, recorded above)
- `~/Library/Logs/factory/mlx-vlm-factory.log`, `mlx-vlm-ig88.log` — server stdout/stderr
- `~/.hermes/profiles/ig88/logs/gateway.log` — gateway operational log (per-profile)
- `~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/runtime_provider.py:340-389` — the `_resolve_openrouter_runtime` function whose conditional was the source of the `provider: custom` requirement
- IG88011 — bake-off data underlying the model selection
- FCT052 — prior latency fix (HTTP daemon mode)
- FCT053 — Matrix dual-login constraint (why IG-88 is on a separate gateway, not coordinator-managed)
