# FCT063 Local Model Restoration and Routing Guide

**Created:** 2026-04-08
**Status:** Active
**Confidence:** High
**Relates to:** FCT059, FCT060, FCT061

---

## 1. Summary
This document provides the operational procedure for restoring local MLX inference for Hermes agents on Whitebox. It ensures that agents use local models as their primary engine while preventing "cloud-routing poisoning" (the silent fallback to OpenRouter that produces HTTP 400 errors).

## 2. The Local Architecture
The system uses a decoupled inference architecture where models run as standalone servers and the Hermes agents act as OpenAI-compatible clients.

| Component | Role | Port |
|----------|------|------|
| `mlx-vlm-factory` | Model Server (Gemma-4-E4B) | :41961 |
| `mlx-vlm-ig88` | Model Server (Nanbeige/Gemma) | :41988 |
| `hermes gateway` | Agent Logic & Matrix Bridge | Varies |

## 3. Restoration Procedure

### Step 1: Verify Inference Servers
Before launching agents, ensure the MLX servers are healthy.
```bash
# Check if the servers are listening
lsof -i :41961
lsof -i :41988

# Verify health endpoints
curl -sf http://127.0.0.1:41961/health
curl -sf http://127.0.0.1:41988/health
```

### Step 2: Verify Agent Gateway Wrappers
Ensure the agent launch scripts (e.g., `~/dev/factory/scripts/hermes-boot.sh`) contain the following structural defenses:

1. **Provider Pinning:** `export HERMES_INFERENCE_PROVIDER=custom`
2. **Env Cleaning:** `unset OPENROUTER_API_KEY` and `unset OPENAI_API_KEY`
3. **Endpoint Routing:** The profile `config.yaml` must point `openai_base_url` to `http://127.0.0.1:41961/v1`.

### Step 3: Restart Agent Gateways
Reload the agents via `launchctl` to apply any configuration changes.
```bash
launchctl bootout gui/$(id -u) /Users/nesbitt/Library/LaunchAgents/com.bootindustries.hermes-boot.plist
launchctl bootstrap gui/$(id -u) /Users/nesbitt/Library/LaunchAgents/com.bootindustries.hermes-boot.plist
```

## 4. Critical Pitfalls (The "Sabotage" List)

### The Cloud-Route Trap (FCT055/FCT061)
If `OPENROUTER_API_KEY` is present in the environment and the profile is NOT pinned to `provider: custom`, Hermes will ignore the local `openai_base_url` and attempt to send the local filesystem path (e.g., `/Users/nesbitt/models/...`) as the model ID to OpenRouter.
**Result:** Immediate `HTTP 400 Bad Request`.

### The Coordinator Dispatch Conflict (FCT059)
Ensure `hermes_port` is **commented out** in `agent-config.yaml`. 
* **Wrong:** Coordinator $\rightarrow$ HTTP (:41970) $\rightarrow$ Agent.
* **Right:** Matrix $\rightarrow$ Pantalaimon $\rightarrow$ Hermes Gateway.

## 5. Collaboration Mode (31B Bus)
To utilize a higher-reasoning model (like Gemma-4-31B) while maintaining local primary operations:
1. **Primary:** Standard `@boot` interaction via local MLX.
2. **Collaborator:** Use a specific tool or secondary profile that explicitly sets `provider: openrouter` and provides the necessary API keys, bypassing the `unset` logic in the main gateway wrapper.
