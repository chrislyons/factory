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

## Post-Implementation Observations (2026-04-08, log review)

**Corrected finding — "Verification" section above is aspirational, not confirmed.**

The verification block captured the system state at ~01:35 on 2026-04-08 immediately after the FCT054 cutover. Subsequent log review against `~/.hermes/profiles/*/logs/errors.log` reveals the following discrepancies from the documented "confirmed working" state:

### Boot: Nanbeige path still active at 01:00

`~/.hermes/profiles/boot/logs/errors.log:21` shows:
```
2026-04-08 01:00:40 ERROR root: API call failed after 3 retries. Connection error. | provider= model=/Users/nesbitt/models/Nanbeige4.1-3B-8bit
```
Boot's Hermes daemon was still referencing the retired Nanbeige model at 01:00 on 2026-04-08 — hours after the FCT054 gemma config was written. The daemon was running stale config from before the swap. **The daemon must be explicitly restarted after profile edits; it does not hot-reload.**

### Kelk: Provider routing failures persist well into afternoon

`~/.hermes/profiles/kelk/logs/errors.log` shows gemma-path HTTP 400s at:
- 02:04 (pre-auxiliary fix, expected)
- 11:43, 11:46×2 (before auxiliary routing fix at ~13:00)
- **12:35, 12:47, 13:07, 13:19** — all after the auxiliary routing fix documented in FCT058 §3.11 was applied

The last Kelk error at 13:19 is 19 minutes after FCT058's documented "fix landed." Either the daemon was not restarted after the auxiliary block was written, or the auxiliary fix does not fully cover all call paths. **The auxiliary routing fix in FCT058 §3.11 is incomplete or the daemon restart failed to apply it.**

### IG-88: 600s timeouts recurring after FCT055 workaround

The streaming-off workaround (`display.streaming: false`) was applied around 10:48. Despite this, IG-88 hit 600s agent-execution timeouts at:
- 03:01 (pre-fix, expected — the documented overnight failure)
- **13:13 and 13:39** — both after the workaround was applied and after multiple daemon restarts

This suggests either (a) the `display.streaming: false` config was not picked up by the running daemon at those times, or (b) the streaming-off path is not sufficient to prevent the dead-loop — the `finish_reason="stop"` bug (PR #964) affects both streaming and non-streaming paths (see FCT055 §10.3 notes on PR #964: "both server.py:1182 and server.py:1264 hardcode finish_reason='stop'"). **The streaming-off workaround may not fully resolve RC-2.**

### Summary of what actually worked vs. what was documented

| Claim in FCT054 "Verification" | Actual state per logs |
|---|---|
| Boot daemon running gemma-4-e4b | Boot daemon still running Nanbeige at 01:00 — stale daemon |
| Kelk routing to local :41961 | Kelk still routing to OpenRouter through 13:19 |
| No OpenRouter 400s after `provider: custom` fix | IG-88 had 600s timeouts at 13:13 and 13:39 after all fixes |
| System confirmed healthy at ~01:35 | Confirmation window was too narrow; failures resumed within hours |

**Action required:** Explicit daemon restart verification after any config change (read PID before and after, confirm new process picks up config). Add daemon restart to the post-config checklist in FCT055 Phase 1.

## Addendum — 2026-04-09: v0.8.0 CLI validation fix, Kelk divergence, model roster

Added during the FCT061/FCT062 Hermes v0.8.0 migration sprint. Three concerns surfaced that affect the FCT054 contract and need to be recorded here rather than buried in the migration docs.

### 1. mlx_vlm `/v1/models` was empty — broke Hermes v0.8.0 interactive CLI

Hermes v0.8.0 introduced pre-flight provider validation in the `hermes model` wizard and in the interactive CLI's auth-resolution path. Both now probe `GET /v1/models` against any custom endpoint and refuse to register the provider when the response contains an empty `data` array.

Upstream `mlx_vlm.server` (vendored at `~/dev/vendor/mlx-vlm/`) implements `/v1/models` by calling `huggingface_hub.scan_cache_dir()` and filtering for repos that look like MLX models. This only returns models inside the HuggingFace cache directory (`~/.cache/huggingface/hub/`). The FCT054 canonical model at `/Users/nesbitt/models/gemma-4-e4b-it-6bit` lives outside that cache, so `/v1/models` returned `{"object":"list","data":[]}` — and Hermes CLI rejected the provider.

**Why FCT054 gateway mode still worked under the same broken endpoint:** the gateway path posts directly to `/v1/chat/completions` with whatever `body.model` was configured and does not pre-validate. Only the v0.8.0 interactive CLI added the `/v1/models` probe. So the FCT054 verification block (gateway only) passed, but any interactive `hermes -p <profile> chat` session failed to resolve the custom provider.

**Patch landed in-tree at `~/dev/vendor/mlx-vlm/mlx_vlm/server.py`**, in the `models_endpoint()` function around line 1302. The change appends the currently-loaded model (from `model_cache["model_path"]`, the same global the `/health` endpoint already reads) to the `/v1/models` response as a basename slug. De-duped against any HF-cache entries. Approximately 15 added lines, clearly marked with `# FCT054 patch:` comments.

```python
# FCT054 patch: include the currently loaded model from model_cache.
# Hermes v0.8.0 CLI validates providers by requiring a non-empty
# /v1/models list. For models loaded via absolute path (not the HF
# cache), scan_cache_dir() returns [], so we must expose model_cache.
loaded_path = model_cache.get("model_path")
if loaded_path:
    loaded_id = os.path.basename(os.path.normpath(loaded_path))
    seen_ids = {m["id"] for m in models}
    if loaded_id not in seen_ids and loaded_path not in seen_ids:
        try:
            mtime = int(os.path.getmtime(loaded_path))
        except OSError:
            mtime = int(time.time())
        models.append({"id": loaded_id, "object": "model", "created": mtime})
```

**Verification after patch:**

```
$ curl -s http://127.0.0.1:41962/v1/models
{"object":"list","data":[{"id":"gemma-4-e4b-it-6bit","object":"model","created":1775583073}]}
```

**Vendor-fork risk:** the patch lives in a clone at `~/dev/vendor/mlx-vlm/`. If that clone is ever `git pull`ed from upstream without carrying the patch forward, the patch will be lost and all mlx-vlm-backed agents will silently stop working in the v0.8.0 interactive CLI (gateway mode unaffected). Mitigations, in order of robustness: (a) fork the upstream repo and track the patch on a branch; (b) keep a copy of the diff in `factory/patches/fct054-mlx-vlm-v1-models.diff`; (c) at minimum, leave the `# FCT054 patch:` markers in place so grep finds it. Decided for now: (c) only, revisit if the patch survives a month.

**Upstream ticket opportunity:** this is a clean upstream PR candidate — the fix is small, the behavior is clearly a bug (endpoints claim to be OpenAI-compatible but don't report their loaded model), and any local-model user who tries to use an absolute `--model` path is affected. Worth filing at `Blaizzy/mlx-vlm`.

### 2. Model slug format changed: full path → basename

Before this sprint, Kelk's profile `model:` field was the absolute path `/Users/nesbitt/models/gemma-4-e4b-it-6bit`. After the patch above, `/v1/models` reports the **basename** `gemma-4-e4b-it-6bit`. Hermes v0.8.0's CLI compares the configured model against the `/v1/models` response when resolving the active provider, so the config must use the basename to match.

```yaml
# ~/.hermes/profiles/kelk/config.yaml — 2026-04-09 format
model: gemma-4-e4b-it-6bit               # basename slug, not absolute path
provider: custom
base_url: http://127.0.0.1:41962/v1
```

FCT054 §Hermes Profile Changes originally showed the absolute path form, which still worked in v0.7.x because the v0.7.x CLI did no `/v1/models` validation. Both forms will work in the gateway path (body.model is forwarded verbatim and mlx_vlm doesn't validate), but **the basename is the only form that works for the interactive CLI under v0.8.0**.

Boot and IG-88 profiles should be updated to the basename form when they come back to local inference (they are temporarily on OpenRouter — see next section).

### 3. Planned divergence: Boot and IG-88 on OpenRouter, Kelk on dedicated :41962

The FCT054 tenancy split was "Boot+Kelk share `:41961` factory, IG-88 dedicated `:41988`." As of 2026-04-09 that has temporarily broken for independent reasons and is being worked around rather than restored.

**Current live state:**

| Agent | Provider | Model | Endpoint |
|---|---|---|---|
| Boot | `openrouter` | `google/gemma-4-31b-it` | `https://openrouter.ai/api/v1` |
| Kelk | `custom` | `gemma-4-e4b-it-6bit` | `http://127.0.0.1:41962/v1` |
| IG-88 | `openrouter` | `google/gemma-4-31b-it` | `https://openrouter.ai/api/v1` |

**Why the divergence exists:**

- Hermes v0.8.0's credential-pool auto-harvest (`credential_pool.py` lines 1045-1085 ish) reads any `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` in the process env and forces the active provider to whichever cloud credential is first on the priority list — overriding `provider: custom` in config.yaml. This is a different trap than the FCT054 `_resolve_openrouter_runtime()` conditional we fixed with `provider: custom`; the v0.8.0 credential pool bypasses that branch entirely.
- The factory Infisical project legitimately provides both `OPENROUTER_API_KEY` and `ANTHROPIC_API_KEY` — they're needed for Boot's and IG-88's auxiliary MCP calls that aren't locally served. Stripping them at the Hermes level means stripping them for everything.
- Short-term workaround: Boot and IG-88 have `provider: openrouter` in config.yaml and route to cloud for primary inference. Kelk's `h-kelk` alias in `~/.zshrc` uses `env -u OPENROUTER_API_KEY -u ANTHROPIC_API_KEY` to strip both keys before exec'ing Hermes, so the credential pool comes up empty and Kelk's `provider: custom` config is actually honored.
- Kelk gets its own `:41962` MLX-VLM slot (new plist `com.bootindustries.mlx-vlm-kelk`) separate from the FCT054 shared factory `:41961`. The FCT054 retired-port note said `:41962` had been retired after the LFM2.5 cleanup; it is now un-retired for this purpose. The shared factory `:41961` server continues to run but is idle — nobody currently routes to it while Boot is on OpenRouter.

**Restoration plan** (when ready to reverse the divergence and return to FCT054 architecture):

1. Resolve the v0.8.0 credential-pool auto-harvest bug — either file upstream and wait, or patch it locally in the installed `credential_pool.py`.
2. Once cloud credentials can coexist with `provider: custom`, revert Boot and IG-88 profiles to the FCT054 canonical form (`provider: custom`, `base_url: http://127.0.0.1:4196[18]/v1`, `model: gemma-4-e4b-it-6bit`).
3. Restart all three Hermes launchd services.
4. Retire `:41962` again (bootout `com.bootindustries.mlx-vlm-kelk`) once Kelk is back on the shared factory `:41961`.
5. Or alternately: keep Kelk on its own slot permanently if the tenancy-split benefits outweigh the RAM cost. E4B at 6-bit is ~5 GB steady; running two instances steady is within the 32 GB budget per the FCT054 Memory Math table.

Until restoration, **use `factory-mlx-switch.sh` to manage `:41962`** — see §4.

### 4. Model roster expansion: Hermes-4-14B and Harmonic-Hermes-9B as alternates

While Gemma 4 E4B 6-bit remains the FCT054 canonical model, two additional models were added to Kelk's `:41962` experimentation slot during this sprint as switchable alternates. They are NOT replacements — they are for A/B testing and for use cases where Gemma's 4B-active-params limit is insufficient.

| Tag | Model | Size | Loader | Architecture | Notes |
|---|---|---|---|---|---|
| `gemma-e4b` | `gemma-4-e4b-it-6bit` | 6.6 GB | `mlx_vlm.server` | gemma4 | **FCT054 canonical.** Only mlx_vlm loads gemma4. |
| `hermes4-14b` | `Hermes-4-14B-6bit` | 11 GB | `mlx_lm.server` | qwen3 | Nous Hermes 4 namesake. mlx-lm required (mlx-vlm doesn't load qwen3). |
| `harmonic-9b` | `Harmonic-Hermes-9B-MLX-8bit` | 8.9 GB | `mlx_lm.server` | qwen3_5 | Instruction-tuned, 8-bit. mlx-lm required. |

All three plists target the same port `:41962`, so **only one can be bootstrapped into launchd at a time**. Switching is managed by `scripts/factory-mlx-switch.sh`:

```
factory-mlx-switch.sh list           # show tags
factory-mlx-switch.sh status         # show currently active
factory-mlx-switch.sh gemma-e4b      # switch to Gemma 4 E4B 6-bit (default)
factory-mlx-switch.sh hermes4-14b    # switch to Hermes-4-14B
factory-mlx-switch.sh harmonic-9b    # switch to Harmonic-Hermes-9B
```

The script:
1. Identifies which of the three labels is currently bootstrapped
2. `launchctl bootout`s it
3. Copies the target plist from repo to `~/Library/LaunchAgents/`
4. `launchctl bootstrap`s the new label
5. Waits up to 20 s for `/v1/models` to return a populated list
6. Rewrites `~/.hermes/profiles/kelk/config.yaml` `model:` to the correct basename slug
7. Prints the active model for confirmation

Next step for the user after a switch: relaunch `h-kelk` in a fresh TTY — the interactive CLI caches config at startup and does not hot-reload.

**New plist files** (all three in `factory/plists/`, gitignored per FCT040, canonical record below):

- `com.bootindustries.mlx-vlm-kelk.plist` — already documented above (Gemma 4 E4B via mlx_vlm)
- `com.bootindustries.mlx-lm-hermes4-14b.plist` — Hermes-4-14B via mlx_lm
- `com.bootindustries.mlx-lm-harmonic-9b.plist` — Harmonic-Hermes-9B via mlx_lm

The two mlx-lm plists are structurally identical to the mlx-vlm plist (same `EnvironmentVariables`, `KeepAlive`, `RunAtLoad`, `ThrottleInterval`, log path pattern) except:
- `Label` — `com.bootindustries.mlx-lm-{hermes4-14b,harmonic-9b}`
- `ProgramArguments[2]` — `mlx_lm.server` instead of `mlx_vlm.server`
- `ProgramArguments[4]` — target model path
- `StandardOutPath` / `StandardErrorPath` — `~/Library/Logs/factory/mlx-lm-{tag}.log`

### 5. mlx-lm vs mlx-vlm loader compatibility reference

Not every model architecture loads under every loader. Learned during this sprint:

| Architecture | mlx_vlm.server | mlx_lm.server | Notes |
|---|---|---|---|
| `gemma4` (Gemma 4 E4B/E2B) | ✅ | ❌ (`ValueError: Model type gemma4 not supported`) | mlx-lm is still on Gemma 3 internally |
| `qwen3` (Hermes-4-14B) | untested | ✅ | mlx-lm native |
| `qwen3_5` (Harmonic-Hermes-9B, Qwen3.5 family) | untested | ✅ | mlx-lm handles it |
| `lfm2` (LFM2.5 family) | untested | ✅ | mlx-lm supports |
| `smollm3` (lmstudio-community) | untested | likely ✅ | standard causal LM |
| Any 1-bit quant (e.g. `Bonsai-4B-mlx-1bit`) | untested | ❌ (`quantize: 1 is not supported`) | mlx-lm supports 2,3,4,5,6,8 bits only |

Rule of thumb: Gemma 4 stays on mlx-vlm; everything else uses mlx-lm. `factory-mlx-switch.sh` encodes this mapping in the `loader_for()` function and picks the right invocation automatically.

### 6. Action items carried forward from this addendum

1. **File upstream PR against `Blaizzy/mlx-vlm`** with the `/v1/models` patch. Likely 20-line PR, clear problem statement ("absolute `--model` path results in empty /v1/models list, breaking OpenAI-compatible clients that validate providers"), likely accepted.
2. **Track the patch** in `factory/patches/fct054-mlx-vlm-v1-models.diff` if upstream declines or stalls.
3. **Restore Boot and IG-88 to local FCT054 architecture** once the v0.8.0 credential-pool auto-harvest issue is resolved (patched locally or fixed upstream).
4. **Update FCT054 §Hermes Profile Changes** (lines 114-138) to use basename slugs instead of absolute paths when the full restoration happens. Leaving them as-is for now so the historical record matches what was actually in the file on 2026-04-08.
5. **Rename `:41962` in the port scheme documentation** — `factory/CLAUDE.md §Port Scheme` lists `:41961-41963, :41966, :41988` as agent MLX slots, so `:41962` is allocated but was marked retired in the original FCT054. Update the port notes to reflect its current use as Kelk's switchable slot.

## References

- `~/.hermes/profiles/{boot,kelk,ig88}/config.yaml` — current profile state
- `plists/com.bootindustries.mlx-vlm-{factory,ig88}.plist` — server definitions (gitignored, recorded above)
- `~/Library/Logs/factory/mlx-vlm-factory.log`, `mlx-vlm-ig88.log` — server stdout/stderr
- `~/.hermes/profiles/ig88/logs/gateway.log` — gateway operational log (per-profile)
- `~/.local/share/uv/tools/hermes-agent/lib/python3.12/site-packages/hermes_cli/runtime_provider.py:340-389` — the `_resolve_openrouter_runtime` function whose conditional was the source of the `provider: custom` requirement
- IG88011 — bake-off data underlying the model selection
- FCT052 — prior latency fix (HTTP daemon mode)
- FCT053 — Matrix dual-login constraint (why IG-88 is on a separate gateway, not coordinator-managed)
