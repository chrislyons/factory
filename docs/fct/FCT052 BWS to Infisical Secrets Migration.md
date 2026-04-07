# FCT052 BWS to Infisical Secrets Migration

**Date:** 2026-04-07
**Status:** In-progress (plists updated, services not yet reloaded)
**Supersedes:** FCT035 (BWS Setup and Secret Rotation)

---

## Summary

Bitwarden Secrets Manager (BWS) is decommissioned and replaced by Infisical (eu.infisical.com) as the secrets backend for all Factory agent and coordinator secret injection. The migration introduces three separate Infisical projects with Machine Identity authentication, a new wrapper script (`infisical-env.sh`), SCREAMING_SNAKE_CASE secret naming for direct env var injection, and updated launchd plists across six services.

This session also stood up IG-88's trading infrastructure: Polymarket CLOB credentials, Kraken API keys, and a Jupiter/Solana trading wallet — all injected via the new Infisical pipeline.

---

## 1. Migration Context

BWS served Factory since 2026-03-23 (FCT035 [1]) using a single project (`factory-agents`) with kebab-case secret names and a `bws secret get` wrapper. Several limitations motivated the move:

- **Single project/identity** — all agents shared one BWS machine account, violating least-privilege
- **Kebab-case naming** — secrets required remapping to env vars at injection time
- **EU server flag** — every `bws` invocation needed `--server-url https://vault.bitwarden.eu`
- **CLI ergonomics** — `bws secret get <UUID>` required maintaining a UUID mapping table

Infisical resolves all four: per-project machine identities, native env var naming, region-aware config, and `infisical run --` for direct injection without UUID lookups.

---

## 2. Architecture

### 2.1 Infisical Projects

Three projects on eu.infisical.com, each with a dedicated Machine Identity using Universal Auth:

| Machine Identity | Infisical Project | Secrets | Scope |
|-----------------|-------------------|---------|-------|
| `factory` | Factory | 13 | Matrix tokens, Anthropic API key, Qdrant/Graphiti auth, portal auth, infra |
| `bootindu` | Boot Industries | 8 | Cloudflare credentials, Stripe keys, portal deploy tokens, domain config |
| `ig88` | IG88 | 17 | Trading venue API keys, CLOB credentials, wallet references |

### 2.2 Authentication Chain

```
macOS Keychain (client-id + client-secret per identity)
  → infisical login --method=universal-auth
    → short-lived access token
      → infisical run --projectId=<ID> --env=prod -- <command>
```

Machine Identity credentials are stored in macOS Keychain, one entry per identity. The wrapper script retrieves them, authenticates, and exec's the target process with secrets injected as environment variables.

### 2.3 Secret Naming Convention

All secrets renamed from kebab-case to SCREAMING_SNAKE_CASE to enable direct env var injection without post-processing:

| BWS (old) | Infisical (new) |
|-----------|-----------------|
| `anthropic-api-key` | `ANTHROPIC_API_KEY` |
| `matrix-pan-token-coord` | `MATRIX_PAN_TOKEN_COORD` |
| `qdrant-api-key` | `QDRANT_API_KEY` |
| `auth-bcrypt` | `AUTH_BCRYPT_HASH` |

This eliminates the shell-level `VAR_NAME=UUID` remapping that `mcp-env.sh` required.

---

## 3. Wrapper Script

**Location:** `~/.config/factory/scripts/infisical-env.sh`
**Replaces:** `~/.config/mcp-env.sh`

### Design

The script is parameterized by project identity:

```
infisical-env.sh <identity> [RENAME:OLD=NEW ...] -- command [args...]
```

**Execution flow:**

1. Accept identity name as first argument (`factory`, `bootindu`, `ig88`)
2. Retrieve `client-id` and `client-secret` from macOS Keychain (service: `infisical-<identity>`)
3. Authenticate via `infisical login --method=universal-auth`
4. Process optional `RENAME:` prefixed arguments for env var renaming (e.g., `RENAME:MATRIX_PAN_TOKEN_COORD=PANTALAIMON_TOKEN`)
5. Execute `infisical run --projectId=<ID> --env=prod -- <command>`

### RENAME Prefix

Some consuming services expect env var names that differ from the canonical Infisical name. The `RENAME:` mechanism handles this without modifying Infisical:

```bash
infisical-env.sh factory RENAME:AUTH_BCRYPT_HASH=AUTH_BCRYPT -- python3 auth.py
```

---

## 4. Plist Updates

Six launchd plists updated to use `infisical-env.sh` instead of `mcp-env.sh`:

| Plist | Identity | Service |
|-------|----------|---------|
| `com.bootindustries.coordinator-rs.plist` | `factory` | Coordinator-rs |
| `com.bootindustries.matrix-mcp-boot.plist` | `factory` | Matrix MCP (Boot) |
| `com.bootindustries.matrix-mcp-coord.plist` | `factory` | Matrix MCP (Coordinator) |
| `com.bootindustries.qdrant-mcp.plist` | `factory` | Qdrant MCP |
| `com.bootindustries.research-mcp.plist` | `factory` | Research MCP |
| `com.bootindustries.factory-auth.plist` | `factory` | Auth sidecar |

All six retain `RunAtLoad` and `KeepAlive` properties established in FCT041 [2]. The `ProgramArguments` array now invokes `infisical-env.sh factory --` instead of `mcp-env.sh`.

**Status:** Plists are updated on disk but services have not been reloaded. A coordinated restart is required:

```bash
launchctl unload ~/Library/LaunchAgents/com.bootindustries.*.plist
launchctl load ~/Library/LaunchAgents/com.bootindustries.*.plist
```

---

## 5. Project Secret Inventory

### 5.1 Factory (13 secrets)

Matrix Pan tokens (4: coord, boot, ig88, kelk), Anthropic API key, LunarCrush API keys (2), Graphiti auth token, Qdrant API key, auth secret, auth bcrypt hash, and two infra-related credentials.

### 5.2 Boot Industries (8 secrets)

Cloudflare API token, Cloudflare zone ID, Stripe secret key, Stripe publishable key, portal deploy token, portal webhook secret, domain verification token, CDN purge key.

### 5.3 IG88 (17 secrets)

Polymarket CLOB credentials (4: API key, secret, passphrase, proxy wallet address), Kraken API credentials (2: key, secret), Jupiter/Solana wallet reference, and 10 additional venue-specific keys for planned integrations.

---

## 6. IG-88 Trading Infrastructure

Set up during the same session as the Infisical migration.

### 6.1 Polymarket

- **Wallet:** Cairo — gen-1 EOA wallet (city naming convention for wallet generations)
- **Generation:** Created via Foundry (`cast wallet new`) for EVM-compatible Polygon signing
- **CLOB API:** Key, secret, and passphrase registered at Polymarket; stored in Infisical `ig88` project
- **Proxy wallet:** Separate deposit address for on-chain operations; linked to Cairo EOA
- **Browser wallet:** Phantom wallet connected to Polymarket (Phantom supports Polygon EVM in addition to Solana)

### 6.2 Kraken

- **KYC:** Complete (personal verification)
- **API keys:** Two pairs provisioned — read-only (balance/position queries) and trade-capable (order placement)
- **WebSocket:** Configured for 25 trading pairs via Kraken's v2 WebSocket API
- **Credentials:** Stored in Infisical `ig88` project

### 6.3 Jupiter (Solana)

- **Wallet:** Solana keypair generated with BIP39 passphrase
- **On-disk:** `~/.config/ig88/trading-wallet.json` (chmod 600, owner-only read/write)
- **Passphrase:** Stored in personal Bitwarden vault (not in Infisical — see Security Decisions)

---

## 7. Security Decisions

### 7.1 Key Separation Principle

IG-88 receives only API credentials (key/secret pairs) through Infisical. Private keys and seed phrases are never injected into agent processes:

- **Polymarket:** IG-88 uses CLOB API credentials for order placement; the Cairo EOA private key remains in personal Bitwarden
- **Kraken:** API keys with scoped permissions (read, trade); withdrawal requires 2FA not available to agents
- **Jupiter:** The on-disk wallet JSON requires a BIP39 passphrase stored separately in personal Bitwarden; IG-88 cannot sign transactions without both components

Future architecture will introduce a signing service that agents request signatures from, rather than holding key material directly.

### 7.2 Wallet Generation

- **Cairo** is the gen-1 naming convention (cities) for wallet generations — enables tracking wallet lineage across rotations
- **Foundry (cast)** installed on Whitebox for EVM wallet generation; avoids web-based generators

### 7.3 Infisical vs BWS Security Posture

- Per-project machine identities enforce least-privilege (BWS used a single shared identity)
- Universal Auth tokens are short-lived (BWS access tokens were long-lived)
- macOS Keychain storage unchanged — SSH sessions still cannot retrieve Keychain values, enforcing local-only execution

---

## 8. BWS Cleanup

Decommission steps (to be executed after Infisical services are verified):

1. `shred -u ~/.config/mcp-env.sh` — securely delete the BWS wrapper script
2. Delete Keychain entry: `security delete-generic-password -s bws-factory-agents`
3. Uninstall CLI: `brew uninstall bws`
4. Archive BWS project in Bitwarden admin console (do not delete — retain for audit trail)
5. Remove BWS-related memory rules from agent configurations

---

## 9. Remaining Work

- [ ] Reload all six launchd services with new plists
- [ ] Smoke-test each service post-reload (Matrix connectivity, Qdrant queries, auth flow)
- [ ] Execute BWS cleanup steps (section 8)
- [ ] Update FCT040 [3] security audit findings to reflect new secrets backend
- [ ] Provision `bootindu` and `ig88` identity plists for future Boot and IG-88 standalone services
- [ ] Wire IG-88 trading agent to consume Kraken WebSocket and Polymarket CLOB via injected credentials

---

## References

[1] FCT035, "Phase B Sprint Report — BWS Setup and Secret Rotation," 2026-03-23.
[2] FCT041, "Resilience Notes — Power Outage Hardening," 2026-03-24.
[3] FCT040, "Red-Team Security Audit — Auth, Coordinator, and Infrastructure," 2026-03-24.
[4] IG88010, "IG-88 Trading Roadmap."
[5] IG88006–IG88008, "Venue Integration Guides (Polymarket, Kraken, Jupiter)."
