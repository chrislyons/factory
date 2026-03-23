# FCT035 Phase B Sprint Report — BWS Setup and Secret Rotation

**Date:** 2026-03-23
**Session:** 2 of 4 (FCT033 execution)
**Scope:** Phase B (Jupiter API Wiring) + Phase 2c.1 (BWS Setup)

---

## Summary

Bitwarden Secrets Manager is operational on Whitebox. The `mcp-env.sh` wrapper script fetches secrets from BWS via macOS Keychain and injects them as env vars — the critical-path prerequisite for Session 3's coordinator migration. All 13 BWS secrets were rotated mid-session due to an accidental plaintext exposure during `bws secret list` output handling.

## Completed

### Part 1 — Solana Wallets (Phase B)

- **Three wallets generated** on Whitebox: trading, funding, alt
- **BIP39 passphrases applied** during generation — JSON files alone are not sufficient to derive keys
- **Seed phrases, passphrases, and pubkeys** stored in BW (`solana-keypair-ig88`)
- **JSON files deleted** from Whitebox — no private key material on disk
- **B4 (funding) deferred** until paper trading training program completes
- **B5 (Jupiter connectivity) deferred** to Session 3 (requires coordinator on Whitebox)

**Trading wallet pubkey:** `Hc2KPpfAdHQAKRJ5QnhBwXaNQmBNa6bWDrwDYtXUrPDa`
**Funding wallet pubkey:** `9dffit3nZhVGMf2bc1YWqbgC8pYQyb6wdevLpHFdxMS7`
**Alt wallet pubkey:** `Ex3NsJt3cW44rsAn5koTJv5tPFawiVZqHUgQ8MizHhuX`

### Part 2 — BWS Setup (Phase 2c.1)

- **BWS project:** `factory-agents` (Boot Industries org, vault.bitwarden.eu)
- **Machine account:** `factory-agents` (read-only access to project)
- **Access token:** stored in Whitebox macOS Keychain (service: `bws-factory-agents`, account: `factory-agents`)
- **bws CLI:** pre-installed at `/opt/homebrew/bin/bws`
- **EU server required:** all `bws` commands need `--server-url https://vault.bitwarden.eu`
- **Keychain access restriction:** SSH sessions cannot retrieve `-w` values from macOS Keychain — agents must run locally on Whitebox (this is the intended design)

### mcp-env.sh

- **Location:** `~/.config/ig88/mcp-env.sh` on Whitebox
- **Usage:** `mcp-env.sh VAR_NAME=UUID [VAR_NAME=UUID ...] -- command [args...]`
- **Chain:** Keychain → BWS_ACCESS_TOKEN → `bws secret get` → env var export → exec
- **Smoke tested:** verified full chain produces correct output

### Secret Rotation Incident

**What happened:** `bws secret list` outputs secret **values** in plaintext JSON. Claude incorrectly stated it would only show names/metadata, then read the full output via SCP. All 11 secret values present at the time were exposed through the Anthropic API.

**Remediation:** All 11 secrets rotated:
- 4 Matrix Pan tokens (re-authenticated via Pantalaimon on Blackbox)
- anthropic-api-key (regenerated at console.anthropic.com)
- 2 LunarCrush API keys (regenerated)
- graphiti-auth-token (regenerated)
- qdrant-api-key (regenerated)
- auth-secret (regenerated)
- auth-bcrypt (regenerated)

**Prevention:** Memory rule added — `bws secret list` exposes values. Never pipe, redirect, or display its output. Extract UUIDs only via `jq` filtering.

## UUID Mapping (13 secrets)

| BWS Key | UUID |
|---|---|
| `matrix-token-pan-boot` | `8e9bcc76-a4fc-4b7f-88c2-b416011f40cb` |
| `matrix-token-pan-coord` | `31d23df6-f50f-43d3-99c0-b416011f7024` |
| `matrix-token-pan-ig88` | `3ad5ea9f-de29-4f5e-ab6f-b416011f7e0e` |
| `matrix-token-pan-kelk` | `0fe1c283-a1ef-42ea-b645-b416011f928b` |
| `graphiti-auth-token` | `99e55357-7977-4925-8671-b416011fac6a` |
| `qdrant-api-key` | `3f9dcc24-7137-4cf2-916f-b416011fbc03` |
| `anthropic-api-key` | `8a2fa4cc-4e98-40eb-90e6-b416011fd909` |
| `auth-bcrypt` | `a574a840-bb94-44a7-bf15-b416011fe96f` |
| `auth-secret` | `297da199-6348-4ba4-b368-b416011ffbc0` |
| `lunarcrush-api-key-ig88` | `d7593a81-00dc-46fe-bebd-b416012058a1` |
| `lunarcrush-api-key-boot` | `38c84ce1-db9b-4903-b37f-b41601206c82` |
| `openrouter-api-key` | `ee959bd0-ee17-4328-a4eb-b416012d217f` |
| `jupiter-api-key` | `73358c05-1887-4bca-a0a3-b416012d53d4` |

## Server Config Updates (Deferred)

The following configs need updating with rotated values — deferred to Session 3 (Whitebox migration):
- Graphiti config: new `graphiti-auth-token`
- Qdrant config: new `qdrant-api-key`
- auth.py on Blackbox: new `auth-secret` and `auth-bcrypt` (will be replaced by Whitebox deployment)

## Deferred to Session 3

- B5: Jupiter connectivity verification (needs IG-88 on Matrix via Whitebox coordinator)
- Agent Matrix verification (needs coordinator on Whitebox with BWS-injected tokens)
- Coordinator migration + launchd plists
- Server config updates with rotated values
- `agent-config.yaml` schema update (`token_file` → `token_env`)

## Pre-Flight Notes for Session 3

1. MLX-LM servers (:8080-8083) were DOWN during this session — not needed but should be restarted before Session 3
2. `bws` requires `--server-url https://vault.bitwarden.eu` on every invocation
3. Keychain entries cannot be read over SSH — all BWS-dependent services must run locally on Whitebox
4. The `mcp-env.sh` script unsets `BWS_ACCESS_TOKEN` before exec-ing the wrapped command (no token leakage to child processes)
5. `coingecko-api-key` was mentioned in the Session 2 handoff prompt but NOT added to BWS — add if needed
6. Two BWS secret names may still be snake_case (`graphiti_auth_token`, `qdrant_api_key`) — verify and rename to kebab-case if so
