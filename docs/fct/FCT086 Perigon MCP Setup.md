# FCT086 Perigon MCP Setup

**Date:** 2026-05-01
**Status:** Implemented
**Refs:** https://www.perigon.io/docs/api/mcp

---

## Summary

Added Perigon News API as a native MCP server to all four Hermes profiles (Gonzo, Boot, Kelk, IG-88). Perigon provides real-time news data including articles, stories, journalists, sources, people, companies, and Wikipedia information.

## API Key Routing

| Agent | Infisical Project | Env Var | Config Key |
|-------|-------------------|---------|------------|
| Gonzo | `bootindu` | `PERIGON_API_KEY_NESBITT` | `perigon` (gonzo profile) |
| Boot | `factory` | `PERIGON_API_KEY_FACTORY` | `perigon` (boot profile) |
| Kelk | `factory` | `PERIGON_API_KEY_FACTORY` | `perigon` (kelk profile) |
| IG-88 | `ig88` | `PERIGON_API_KEY_IG88` | `perigon` (ig88 profile) |

## Architecture

**Transport:** stdio via `mcp-remote` (npx subprocess)
**Remote endpoint:** `https://mcp.perigon.io/v1/sse`
**Auth:** Bearer token passed via `--header "Authorization: Bearer ${PERIGON_API_KEY_XXX}"` to mcp-remote
**Env injection:** Shell env var expansion in npx args; vars sourced from Infisical at gateway startup

```
Hermes gateway (PID)
  └─ npx mcp-remote@latest https://mcp.perigon.io/v1/sse
        --header "Authorization: Bearer ${PERIGON_API_KEY}"
      (env inherited from parent process)
```

**Tool naming:** `mcp_perigon_<tool_name>`

## Config Changes

All four profiles updated: `~/.hermes/profiles/{gonzo,boot,kelk,ig88}/config.yaml`

```yaml
mcp_servers:
  perigon:
    command: npx
    args:
    - --yes
    - mcp-remote@latest
    - https://mcp.perigon.io/v1/sse
    - --header
    - "Authorization: Bearer ${PERIGON_API_KEY_XXX}"
    connect_timeout: 30
    timeout: 180
    enabled: true
```

Where `PERIGON_API_KEY_XXX` is `NESBITT`, `FACTORY`, or `IG88` per profile.

## Shell Alias Update

**File:** `~/.zshrc`

`h-gonzo` alias updated to inject from both `bootindu` (NESBITT) and `factory` (FACTORY) Infisical projects:

```bash
alias h-gonzo='HERMES_STREAM_READ_TIMEOUT=600 HERMES_STREAM_STALE_TIMEOUT=600 HERMES_AGENT_TIMEOUT=7200 eval "$(~/dev/factory/scripts/infisical-env.sh bootindu -- printenv 2>/dev/null)" && ~/dev/factory/scripts/infisical-env.sh factory -- env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u OPENAI_BASE_URL -u OPENAI_API_BASE -u OPENROUTER_API_KEY hermes -p gonzo chat'
```

The `eval "$(infisical-env.sh bootindu -- printenv 2>/dev/null)"` step runs first and exports all bootindu secrets into the shell environment before `infisical-env.sh factory --` is evaluated.

## Env Injection Path Per Profile

| Profile | Launcher | Env Source |
|---------|----------|------------|
| gonzo | `h-gonzo` alias | `bootindu` (NESBITT) + `factory` (other secrets) |
| boot | `com.bootindustries.hermes-boot.plist` → launchd | `factory` project via `infisical-env.sh factory` |
| kelk | `com.bootindustries.hermes-kelk.plist` → launchd | `factory` project via `infisical-env.sh factory` |
| ig88 | `com.bootindustries.hermes-ig88.plist` → launchd | `ig88` project via `infisical-env.sh ig88` |

## Perigon MCP Endpoint

- **SSE endpoint:** `https://mcp.perigon.io/v1/sse` (used by mcp-remote)
- **HTTP Streamable endpoint:** `https://mcp.perigon.io/v1/mcp` (alternate, not currently used)
- **Auth:** Bearer token — API key from Perigon dashboard
- **Playground:** https://app.perigon.io/mcp/playground

## Enabling Perigon MCP Per Profile

The MCP is `enabled: true` in all profiles by default. To toggle:

```yaml
mcp_servers:
  perigon:
    enabled: false   # true to enable, false to disable
```

Restart the gateway to pick up changes.

## Restart Commands

After any config change, restart the relevant gateway:

```bash
# Gonzo (CLI session — start new session)
# Boot
launchctl kickstart -kp gui/$(id -u)/com.bootindustries.hermes-boot
# Kelk
launchctl kickstart -kp gui/$(id -u)/com.bootindustries.hermes-kelk
# IG-88
launchctl kickstart -kp gui/$(id -u)/com.bootindustries.hermes-ig88
```

Or use `hermes doctor` to check MCP server status.

## Limitations

- mcp-remote runs as a long-lived npx subprocess; first invocation may take a few seconds to download/cache
- Bearer token in npx args is visible in process listings (`ps aux | grep mcp-remote`) — acceptable for internal use behind a company VPN
- If `PERIGON_API_KEY_XXX` is not set in the environment, the mcp-remote subprocess will fail with an auth error — check `hermes doctor` output
