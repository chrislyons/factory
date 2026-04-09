# FCT057 Kelk Local MLX Bootstrap — mlx-vlm Port Split and Model Path Fix

**Status:** Partial — server operational, keychain issue blocking CLI
**Date:** 2026-04-09
**Depends on:** FCT054 (E4B consolidation), FCT055 (routing hardening)

## Summary

Session to get @Kelk operational on local Gemma 4 E4B-it 6-bit via mlx_vlm on
Whitebox. Discovered that the infrastructure was mostly in place (launchd plists,
venv, model weights) but two configuration bugs prevented Hermes from completing
inference requests. Both fixed. A pre-existing keychain locking issue then
surfaced, blocking the `h-kelk` CLI alias — this is a macOS security agent
problem, not a Hermes or mlx_vlm issue.

## Findings

### 1. mlx_vlm vs mlx_lm

Gemma 4 is a vision-language model (`model_type: gemma4`,
`Gemma4ForConditionalGeneration`). It requires **mlx_vlm.server**, not
mlx_lm.server. The mlx_lm server will bind the port but fail on inference
requests.

- mlx_vlm venv: `/Users/nesbitt/dev/vendor/mlx-vlm/.venv/` (v0.4.4, Python 3.14)
- Server binary: `/Users/nesbitt/dev/vendor/mlx-vlm/.venv/bin/mlx_vlm.server`
- mlx_vlm.server does NOT support `--use-default-chat-template` (mlx_lm-only flag)

### 2. Model name in API requests must be full local path

When mlx_vlm.server receives a `model` field in a chat/completions request, it
compares it against the currently loaded model. If the name doesn't match, it
treats it as a **new model load request** and attempts to resolve it from
HuggingFace — failing with a 401 auth error for gated/private models.

**Bare name** (`gemma-4-e4b-it-6bit`): triggers HF download → 401 error
**Full path** (`/Users/nesbitt/models/gemma-4-e4b-it-6bit`): matches preloaded model → works

This is the root cause of Kelk's inference failures. The Hermes profile had
`model: gemma-4-e4b-it-6bit` (bare name) which caused every request to attempt
a HF download instead of using the already-loaded local model.

### 3. Port split (FCT061 design, previously undocumented)

FCT054 documented Kelk sharing the factory server on `:41961` with Boot. At some
point between FCT054 and this session, Kelk was split to its own dedicated server
on `:41962` (referenced as "FCT061" in code comments but no doc existed).

Current port assignments:

| Port  | Service                          | Launchd Label                      |
|-------|----------------------------------|------------------------------------|
| 41961 | mlx-vlm-factory (Boot shared)    | com.bootindustries.mlx-vlm-factory |
| 41962 | mlx-vlm-kelk (Kelk dedicated)   | com.bootindustries.mlx-vlm-kelk    |
| 41988 | mlx-vlm-ig88 (IG-88 dedicated)  | com.bootindustries.mlx-vlm-ig88    |

All three serve gemma-4-e4b-it-6bit from `/Users/nesbitt/models/gemma-4-e4b-it-6bit`,
bound to `127.0.0.1`.

## Changes Made

### `~/.hermes/profiles/kelk/config.yaml` (on Whitebox)

Changed all `model:` references from bare name to full local path:

```
- model: gemma-4-e4b-it-6bit
+ model: /Users/nesbitt/models/gemma-4-e4b-it-6bit
```

Applied to: top-level model field and all 9 auxiliary slots (vision, web_extract,
compression, session_search, skills_hub, approval, mcp, flush_memories, and
compression summary_model).

Backup at: `config.yaml.bak-model-path`

### `~/dev/factory/scripts/hermes-kelk.sh` (on Whitebox)

Updated preflight health check from stale factory port to Kelk's dedicated port:

```
- MLX_VLM_HEALTH_URL="http://127.0.0.1:41961/health"
+ MLX_VLM_HEALTH_URL="http://127.0.0.1:41962/health"
```

Also updated associated comments to reference `mlx-vlm-kelk` instead of
`mlx-vlm-factory`.

Backup at: `hermes-kelk.sh.bak-port`

### Hermes-kelk gateway restart

Restarted via `launchctl kickstart -k gui/$(id -u)/com.bootindustries.hermes-kelk`
to pick up profile and script changes. Gateway started successfully, Infisical
injected 16 secrets, no preflight errors.

## Verification

```
# Server healthy
$ curl -s http://127.0.0.1:41962/health
{"status":"healthy","loaded_model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","loaded_adapter":null}

# Inference works with full path
$ curl -s http://127.0.0.1:41962/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","messages":[{"role":"user","content":"Say hello"}],"max_tokens":20}'
{"model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"Hello! How can I help you today?","tool_calls":[]}}],"usage":{"prompt_tps":8.4,"generation_tps":40.3,"peak_memory":7.12}}

# Kelk persona works
$ curl -s http://127.0.0.1:41962/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"/Users/nesbitt/models/gemma-4-e4b-it-6bit","messages":[{"role":"system","content":"You are Kelk."},{"role":"user","content":"Are you there?"}],"max_tokens":30}'
→ "Yes."
```

## Blocking Issue: macOS Keychain

The `h-kelk` (and `h-boot`, `h-ig88`) CLI aliases stopped working over SSH
during this session. All three use `infisical-env.sh` which reads Infisical
Machine Identity credentials from the macOS login keychain.

**Error:** `security: SecKeychainCopySettings: User interaction is not allowed.`

**Root cause:** The macOS login keychain locked during the session. When locked,
`security find-generic-password -w` returns exit code 36 and empty output. The
`.zshrc` exports that populate `INFISICAL_FACTORY_CLIENT_ID` etc. silently fail,
and `infisical-env.sh` finds no credentials via either path (keychain direct or
env var fallback).

**Resolution:** Unlock the keychain from the Whitebox GUI (Terminal.app, Screen
Sharing, or physical access):

```
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

To prevent future auto-locking:

```
security set-keychain-settings ~/Library/Keychains/login.keychain-db
```

(No `-t` flag = no timeout, no lock on sleep.)

**Note:** The launchd-managed gateway services (com.bootindustries.hermes-kelk
etc.) are unaffected because they authenticated before the lock and hold valid
Infisical tokens. Only new interactive shells are blocked.

## Important: Boot and IG-88 Profile Check

Boot and IG-88 profiles may have the same bare-model-name bug. Before moving
them to local models (or if they're already on local), verify their
`config.yaml` files use the full path:

```yaml
# Correct
model: /Users/nesbitt/models/gemma-4-e4b-it-6bit

# Wrong — triggers HuggingFace download on every request
model: gemma-4-e4b-it-6bit
```

## Files on Cloudkicker (not deployed)

The `plists/com.bootindustries.mlx-lm-41962.plist` file in the factory repo on
Cloudkicker was modified during early debugging (wrong server binary, wrong
model, wrong paths). This file is gitignored and was not deployed. The canonical
plist on Whitebox (`~/Library/LaunchAgents/com.bootindustries.mlx-vlm-kelk.plist`)
is correct and unchanged.

## References

- FCT054 — E4B consolidation (original architecture)
- FCT055 — Hermes routing hardening (provider: custom requirement)
- `~/Library/LaunchAgents/com.bootindustries.mlx-vlm-kelk.plist` — server plist
- `~/Library/LaunchAgents/com.bootindustries.hermes-kelk.plist` — gateway plist
- `~/.hermes/profiles/kelk/config.yaml` — Hermes profile (model path fix)
- `~/dev/factory/scripts/hermes-kelk.sh` — wrapper script (port fix)
- `~/Library/Logs/factory/mlx-vlm-kelk.log` — server log
- `~/Library/Logs/factory/hermes-kelk.log` — gateway log
