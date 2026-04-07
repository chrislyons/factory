# Bake-Off Prerequisites Checklist

Human blockers that must be resolved before the bake-off can produce valid results.

## Status (2026-04-05)

All 4 models scored 0/25 due to HTTP 401 authentication failures.
Root cause: API keys in Bitwarden were invalidated during the 2026-03-23
secret rotation but **new keys were never saved back into the vault**.

- Anthropic API: `"invalid x-api-key"` (sonnet-4.6, opus-4.6)
- OpenRouter API: `"User not found."` (gemini-3.1-pro, o4-mini)

---

## Checklist

### 1. BW_SESSION must be active on Whitebox

The bake-off runner resolves keys at runtime via `~/.config/mcp-env.sh`,
which requires an unlocked Bitwarden vault.

**Verify:**
```bash
launchctl getenv BW_SESSION 2>/dev/null | wc -c
# Should be >0 (typically ~89 chars)
```

**Fix (if expired):**
```bash
export BW_SESSION=$(bw unlock --raw)
launchctl setenv BW_SESSION "$BW_SESSION"
```

### 2. ANTHROPIC_API_KEY must be valid in Bitwarden (BLOCKING)

The key stored under `anthropic-api-key` in Bitwarden returns HTTP 401
("invalid x-api-key") from the Anthropic Messages API.

**Fix:**
1. Generate a new API key at https://console.anthropic.com/settings/keys
2. Update the `anthropic-api-key` entry in Bitwarden (web vault)
3. Run `bw sync` on Whitebox to pull the updated value

**Verify (after fix):**
```bash
export BW_SESSION=$(launchctl getenv BW_SESSION)
# Use mcp-env.sh to resolve the key, then curl the Anthropic API
# A 200 response confirms the key is valid
~/.config/mcp-env.sh ANTHROPIC_API_KEY -- \
  curl -s -o /dev/null -w '%{http_code}' \
  https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-sonnet-4-20250514","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}'
```

### 3. OPENROUTER_API_KEY must be valid in Bitwarden (BLOCKING)

The key stored under `openrouter-api-key` returns HTTP 401
("User not found.") from the OpenRouter API.

**Fix:**
1. Generate a new API key at https://openrouter.ai/settings/keys
2. Update the `openrouter-api-key` entry in Bitwarden (web vault)
3. Run `bw sync` on Whitebox to pull the updated value

**Verify (after fix):**
```bash
export BW_SESSION=$(launchctl getenv BW_SESSION)
~/.config/mcp-env.sh OPENROUTER_API_KEY -- \
  curl -s -o /dev/null -w '%{http_code}' \
  https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
# Should return 200
```

### 4. Anthropic per-key spend limit (recommended)

Set a spend limit on the new Anthropic key to cap bake-off costs.
The full run is 50 Anthropic calls (sonnet-4.6 + opus-4.6, 25 markets each).
Expected cost: <$1.00 total.

**Set at:** https://console.anthropic.com/settings/keys (edit key -> spend limit)

---

## Re-Running the Bake-Off

Once all blockers are resolved:

```bash
cd ~/dev/factory/agents/ig88
./scripts/run-bakeoff.sh
```

Results are written to `evals/results/bakeoff_YYYYMMDD_HHMMSS.jsonl`.
The summary table prints Brier scores, schema compliance, anchoring
correlation, latency, and cost for each model.

---

## Key Resolution Flow

```
run-bakeoff.sh
  -> launchctl getenv BW_SESSION (fallback if not in env)
  -> mcp-env.sh ANTHROPIC_API_KEY OPENROUTER_API_KEY -- python3 bakeoff.py
       -> resolves keys from Bitwarden personal vault via BW_SESSION
       -> exports as env vars, exec's bakeoff.py
```

The `bw` CLI resolves from the Bitwarden personal vault (not BWS machine account).
