---
prefix: IG88007
title: "Kraken Venue Setup Guide"
status: active
created: 2026-04-05
updated: 2026-04-05
author: Chris + Claude (Opus 4.6)
depends_on: IG88003
---

# IG88007 Kraken Venue Setup Guide

## Overview

Kraken is IG-88's designated CEX venue for spot trading. It is operated by Payward Canada Inc. and is OSC-registered (MSB No. M19343731), making it the only major CEX that is fully compliant for Ontario retail users [1].

Key operational parameters:

- **Spot trading only** on kraken.com — derivatives are blocked for Canadian retail users under OSC registration conditions
- **Kraken Futures** (futures.kraken.com, operated by Crypto Facilities Ltd, UK FCA) — **BLOCKED for Ontario/Canada.** Confirmed 2026-04-06; see §Kraken Futures below
- Official CLI maintained by the Kraken organisation at github.com/krakenfx/kraken-cli [2]
- CLI ships with a native MCP server (`kraken mcp`) exposing 151 tools over stdio — no separate wrapper required
- Do not use any personal trading account for IG-88; open a dedicated account

---

## Account Setup

1. Sign up at kraken.com using a dedicated email (ig88bot@proton.me or equivalent — not a personal address)
2. Complete **Intermediate verification** (KYC). API trading access requires Intermediate or higher
3. Enable 2FA on the account before generating API keys
4. Do not deposit funds until API keys are generated and verified working

---

## API Key Generation

Navigate to: **Security → API → Create API Key**

Create two keys:

**Read-only key ("IG-88 Read")**

| Permission | Include |
|---|---|
| Query Funds | Yes |
| Query Open Orders & Trades | Yes |
| Query Closed Orders & Trades | Yes |
| Query Ledger Entries | Yes |
| All others | No |

**Trade key ("IG-88 Trade")**

| Permission | Include |
|---|---|
| All Query permissions (as above) | Yes |
| Create & Modify Orders | Yes |
| Cancel & Close Orders | Yes |
| All others | No |

**IP whitelist:** Enable on the trade key. Add Whitebox Tailscale IP `100.88.222.111`. This prevents the trade key from being usable from any other host even if compromised.

**Storage:** Store both key pairs in Bitwarden (Boot Industries org) pending Infisical migration (Decision D7, IG88003). Do not commit to any git repository.

**Environment variables used by CLI and CCXT:**

| Variable | Value |
|---|---|
| `KRAKEN_API_KEY` | Trade key API key |
| `KRAKEN_API_SECRET` | Trade key private key (API secret) |

Futures credentials: not applicable — Ontario/Canada is blocked from Kraken Futures (confirmed 2026-04-06).

---

## CLI Installation (Supply Chain Safe)

The official Kraken CLI is maintained by the Kraken organisation at github.com/krakenfx/kraken-cli [2]. It is written in Rust and distributed as a signed binary with minisign verification.

**Do NOT install via:**
- `brew install` — no formula exists yet; any formula found in third-party taps is unofficial
- `curl | sh` installer scripts

**Safe installation procedure (macOS aarch64, v0.3.0):**

```bash
# 1. Download the release binary and its minisign signature
curl -LO https://github.com/krakenfx/kraken-cli/releases/download/v0.3.0/kraken-aarch64-apple-darwin.tar.gz
curl -LO https://github.com/krakenfx/kraken-cli/releases/download/v0.3.0/kraken-aarch64-apple-darwin.tar.gz.minisig

# 2. Install minisign if not present
brew install minisign

# 3. Verify the signature against the public key published in the GitHub README
#    Substitute <pubkey> with the key from the repo README — do not use a key from any other source
minisign -Vm kraken-aarch64-apple-darwin.tar.gz -P <pubkey>

# 4. Extract and install
tar -xzf kraken-aarch64-apple-darwin.tar.gz
chmod +x kraken
mv kraken ~/bin/kraken

# 5. Confirm
which kraken && kraken --version
```

**Version pinning:** Pin to v0.3.0. Do not upgrade without explicit approval (TeamPCP supply chain policy).

**Agent identification:** Set `KRAKEN_AGENT_CLIENT=ig88` in the environment. Without this, Kraken's telemetry records IG-88's traffic as `claude` (the default Claude Code agent client string), which makes it difficult to distinguish from other Claude sessions in Kraken's access logs.

---

## MCP Configuration

The `kraken mcp` subcommand starts a stdio MCP server. No wrapper is required — the binary handles both CLI and MCP modes.

Add the following entry to the MCP configuration file (location: `~/.mcp.json` on Whitebox, or the coordinator's agent-config.yaml MCP section):

```json
{
  "mcpServers": {
    "kraken": {
      "command": "kraken",
      "args": ["mcp", "-s", "market,account,paper"],
      "env": {
        "KRAKEN_API_KEY": "${KRAKEN_API_KEY}",
        "KRAKEN_API_SECRET": "${KRAKEN_API_SECRET}",
        "KRAKEN_AGENT_CLIENT": "ig88"
      }
    }
  }
}
```

**The `-s` flag selects tool groups exposed to the MCP client:**

| Group | Contents | Include for IG-88 |
|---|---|---|
| `market` | Tickers, orderbooks, OHLCV, trade history | Yes — always |
| `account` | Balance, open orders, trade history, ledger | Yes — always |
| `paper` | Spot paper trading simulation | Yes — always |
| `futures` | Futures trading (317 perpetual contracts) | **Not applicable — Ontario blocked** |
| `futures-paper` | Futures paper trading simulation (no auth) | Safe for mechanics study only |

**WebSocket streaming** is excluded from MCP v1. For live price feeds during active monitoring, use subprocess calls to `kraken market ticker --stream` or integrate the WebSocket API directly.

---

## Funding

Deposit options from Canadian accounts:

- **Interac e-Transfer** — fastest CAD → account conversion; typically settles same day
- **SWIFT** — for larger amounts; 1–3 business days
- **Crypto deposit** — BTC, ETH, SOL, USDC accepted directly; useful if capital is already held on-chain

Starting capital philosophy: the same as Polymarket — deposit the smallest amount you are willing to lose entirely during the paper trading validation phase. Do not size up until 50+ paper trades are validated and IG-88 recommends graduation.

---

## Fee Structure (Spot)

Kraken's spot fees are volume-tiered on a 30-day rolling basis [3]:

| 30-day Volume | Maker | Taker |
|---|---|---|
| $0 – $50K (base tier) | 0.16% | 0.26% |
| $50K – $100K | 0.14% | 0.24% |
| $100K – $250K | 0.12% | 0.22% |
| $250K+ | Continues dropping | Continues dropping |
| High volume | 0.00% | 0.10% |

At IG-88's initial scale, the base tier rates apply. Model 0.16% (maker) or 0.26% (taker) as the operating cost per leg when computing strategy expectancy.

**Practical implication:** Always use limit orders (maker) where fill probability is acceptable. A round-trip taker trade costs 0.52% before any edge — this must be recovered on every trade. At 0.32% for a maker round-trip, the hurdle is materially lower.

**Fee drag guardrail:** If taker fees exceed 15% of gross P&L on a rolling 20-trade basis, enforce limit-order-only mode. This is a hardcoded rule, not a policy.

---

## Spot Trading Strategy

**Instruments:** BTC/USD, ETH/USD, SOL/USD only (to start). Adding pairs requires explicit approval after the base instruments are validated.

**Strategy:** Event-driven spot positioning — enter on identifiable catalysts (protocol upgrades, macro regime shifts, token unlock events, scheduled network milestones), exit systematically at pre-defined targets rather than by feel.

**Regime gating:** Only enter new positions in RISK_ON regime (per IG88003 W1.I.1 regime detection module). No entries in NEUTRAL or RISK_OFF regardless of signal strength.

**Minimum hold:** 4 hours. This prevents round-trip churn through taker fees on positions that would otherwise be opened and closed within a single market session.

**Kelly fraction:** Quarter-Kelly for all trades until 200 validated trades are complete. Position size = Kelly formula output only — never manually overridden upward.

---

## Discipline Guardrails (Hardcoded in IG-88)

These are rules, not guidelines. They are implemented in code and cannot be overridden by LLM reasoning:

| Guardrail | Rule |
|---|---|
| Profit target | Triggers automatic close — no "let it run" path |
| Position sizing | Kelly formula output only; manual upward override is prohibited |
| Re-entry cooldown | 2-hour cooldown after any close on the same instrument |
| Daily loss halt | If spot positions lose >3% of Kraken wallet in a calendar day (UTC), halt new entries until next UTC day |
| Fee drag | If taker fees exceed 15% of gross P&L on rolling 20-trade basis, limit-order-only mode enforced |
| Averaging down | Absolutely prohibited |

---

## Kraken Futures (Ontario: BLOCKED — Confirmed 2026-04-06)

Kraken Futures is operated by Crypto Facilities Ltd, a UK FCA-regulated entity separate from Payward Canada Inc. [4]. Despite this legal separation, Ontario/Canada residents are blocked at the account level. Kraken Support confirmed directly: "Clients residing in Canada cannot trade futures at the moment." [5]

**Why the FCA/Payward Canada separation does not create a loophole:** Crypto Facilities Ltd holds an FCA licence for UK operations only. Serving Canadian residents would require separate CSA registration as a derivatives dealer — which it has not pursued. Kraken enforces the restriction at login since kraken.com and futures.kraken.com share the same account system.

**Public data API is unrestricted.** The `futures.kraken.com/derivatives/api/v4` public endpoints (tickers, orderbooks, funding rates, OHLCV) are not geo-blocked. IG-88 can use Kraken Futures data for analysis and regime detection inputs without any access issues.

**`futures-paper` is available for mechanics study only:**

```bash
# Futures paper simulation — safe, no auth, no funds
kraken futures-paper
```

This simulates the full leverage/margin/liquidation environment using live prices. Useful for IG-88 to model futures mechanics if the regulatory situation ever changes. Not a path to live trading.

**No IG88008 will be created.** Futures remain off the table for Ontario. Revisit only if Crypto Facilities Ltd formally registers with the CSA, or Kraken announces Canada access.

---

## Key CLI Commands for IG-88

| Command | Purpose |
|---|---|
| `kraken -o json market ticker --pair XBT/USD` | BTC spot price |
| `kraken -o json market ticker --pair ETH/USD` | ETH spot price |
| `kraken -o json market ticker --pair SOL/USD` | SOL spot price |
| `kraken -o json market orderbook --pair XBT/USD` | Order book depth |
| `kraken -o json account balance` | Account balances |
| `kraken -o json account open-orders` | Open orders |
| `kraken -o json trade order buy --pair XBT/USD --type limit --price <p> --volume <v>` | Limit buy (paper: route through MCP paper mode) |
| `kraken -o json trade order sell --pair XBT/USD --type limit --price <p> --volume <v>` | Limit sell (paper: route through MCP paper mode) |
| `kraken -o json trade cancel --txid <id>` | Cancel specific order |
| `kraken -o json trade cancel-all` | Emergency cancel all open orders |
| `kraken paper` | Enter spot paper trading mode |
| `kraken futures-paper` | Enter futures paper trading mode (no auth required) |

---

## Known Limitations

**No brew formula.** Install from GitHub Releases only (see §CLI Installation).

**WebSocket streaming excluded from MCP v1.** Live price feeds require subprocess calls or direct WebSocket integration. The MCP server exposes REST-equivalent tooling only.

**Spot derivatives blocked for Ontario.** This is a regulatory constraint, not a Kraken limitation. No workaround is appropriate. Accept it and focus on the strategies that work on spot.

**Futures access from Ontario unconfirmed.** Do not assume access. Verify against the Kraken Futures restricted jurisdictions list before any futures work beyond paper simulation.

---

## References

[1] Ontario Securities Commission, "Payward Canada Inc. (Kraken)," OSC Registration Search, accessed 2026-04-05. MSB No. M19343731.

[2] Kraken, "kraken-cli," GitHub, github.com/krakenfx/kraken-cli, v0.3.0, accessed 2026-04-05.

[3] Kraken, "Fee Schedule," support.kraken.com, accessed 2026-04-05.

[4] Crypto Facilities Ltd, "Kraken Futures — Regulatory Information," futures.kraken.com, accessed 2026-04-05.

[5] Kiki (Kraken Support), reply to "Futures trading in western Canada," r/Kraken, Reddit, Sept. 2023. "Clients residing in Canada cannot trade futures at the moment."
