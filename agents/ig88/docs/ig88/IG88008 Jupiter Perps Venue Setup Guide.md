---
prefix: IG88008
title: "Jupiter Perps Venue Setup Guide"
status: active
created: 2026-04-06
updated: 2026-04-06
author: Chris + Claude (Opus 4.6)
depends_on: IG88003, IG88007
---

# IG88008 Jupiter Perps Venue Setup Guide

## Overview

Jupiter Perpetuals is IG-88's futures/leverage venue. It is fully on-chain on Solana — no KYC, no exchange account, no geo-restriction. Ontario jurisdiction issues that blocked Kraken Futures and Bybit do not apply. IG-88 trades directly using its self-custody Solana wallet.

**This is the futures capability that Ontario regulations blocked at the CEX level.** Jupiter Perps operates as an AMM-based (pool-backed) perpetuals exchange via the Jupiter Liquidity Pool (JLP), distinct from an orderbook model. This distinction affects fee structure and execution characteristics — see §Fee Structure.

**Active instrument: SOL-PERP only.** BTC and ETH perps are available on Jupiter but excluded from IG-88's mandate due to higher borrow fees, wider pool spreads, and lower JLP liquidity relative to SOL. SOL is the native Solana asset and has the best execution characteristics on this venue.

**Official CLI:** `jup` v0.7.1 — `github.com/jup-ag/cli` (TypeScript/Node, GPL-3.0, official Jupiter org). Installed at `~/.local/bin/jup` on Whitebox and Cloudkicker.

---

## Key Characteristics vs CEX Futures

| Factor | CEX Futures (blocked) | Jupiter Perps |
|---|---|---|
| Jurisdiction | Blocked for Ontario | On-chain, no geo-restriction |
| Custody | Exchange-held | Self-custody (IG-88 wallet) |
| Pricing model | Orderbook | AMM / JLP pool |
| Assets supported | Hundreds | SOL, BTC, ETH (SOL only for IG-88) |
| Leverage | Up to 50x | Up to ~100x (IG-88 cap: 5x) |
| Base round-trip fee | 0.02-0.04% | 0.12% (0.06% open + 0.06% close) |
| Borrow fee | Funding rate | Hourly, pool-utilization based |
| Slippage | Near-zero (liquid pairs) | Pool-depth dependent |
| Execution latency | ~50-200ms | ~400ms (Solana block time) |
| MEV risk | None | Present on Solana |

---

## Fee Structure and Minimum Edge Requirements

Jupiter Perps fees are higher than CEX futures. Every strategy must clear these costs before generating profit.

**Round-trip fee breakdown (SOL-PERP):**

| Component | Rate | Notes |
|---|---|---|
| Open fee | 0.06% of position | Charged at entry |
| Close fee | 0.06% of position | Charged at exit |
| Borrow fee | ~0.004-0.02%/hr | Accumulates continuously; higher during high utilization |
| Price impact | 0.01-0.05% | Depends on position size vs. JLP SOL reserves |
| **Total (4h hold)** | **~0.14-0.22%** | At 5x leverage: ~0.70-1.10% on notional capital |

**Minimum edge requirement:** A Jupiter Perps trade must have an expected directional move of **>0.25% on the notional position** to be worth executing after fees. At 5x leverage, this means an underlying SOL price move of >0.05% in the right direction within the hold period.

**Implication for strategy:** Jupiter Perps is only viable for trades with high-conviction directional signals and reasonable hold times (2+ hours). It is not viable for small intraday scalps or low-conviction regime trades. The Solana DEX narrative momentum strategy (Section 2.2 of IG88001) is a better fit than event-driven macro positioning.

---

## Wallet and Key Management

IG-88's existing Solana wallet (`~/.config/ig88/trading-wallet.json`) is used directly for Jupiter Perps. No separate account is needed — perps positions are tied to the wallet address.

**Key storage:** Same Infisical migration requirement as Polymarket. The flat file at `~/.config/ig88/trading-wallet.json` must migrate to Infisical before any live perps trading. See IG88003 §D7.

**For `jup` authentication:** Use the `vault` keychain backend once Infisical/Vault is live. Do not use `jup keys add --file ~/.config/ig88/trading-wallet.json` in production — that stores the key unencrypted in `~/.config/jup/keys/`. In the interim, use `--private-key` via environment variable injection.

**Interim setup (paper trading phase):**
```bash
# Set wallet for jup without writing key to disk
export JUP_PRIVATE_KEY="$(cat ~/.config/ig88/trading-wallet.json | python3 -c 'import sys,json,base58; d=json.load(sys.stdin); print(base58.b58encode(bytes(d)).decode())')"
jup config set --active-key ig88
```

The long-term approach: `jup keys add ig88 --backend vault --param path=ig88/solana-wallet` once Vault is wired.

---

## CLI Installation (Already Complete)

Both machines have `jup` v0.7.1 installed and checksum-verified.

| Machine | Path | SHA256 |
|---|---|---|
| Whitebox | `~/.local/bin/jup` | `a299776697cd2b5501236e9d3c8b8f7793d2c2a0de252265fe80afd85aeb3b97` |
| Cloudkicker | `~/.local/bin/jup` | same (copied from Whitebox) |

**Do not run `jup update`.** Self-update is disabled until an explicit version upgrade is approved. Pin to v0.7.1 (TeamPCP supply chain caution). Monitor `github.com/jup-ag/cli/releases` for updates; upgrade only after reviewing release notes and re-verifying checksums.

**License:** GPL-3.0. Use `jup` as a subprocess only — do not incorporate its source code into any IG-88 codebase. Subprocess use does not trigger GPL copyleft propagation.

---

## Configuration

```bash
# Set JSON output as default
jup config set --output json

# Verify
jup config list
```

Config is stored at `~/.config/jup/settings.json`.

**Optional API key** (higher rate limits via portal.jup.ag):
```bash
jup config set --api-key <key>
```

Without a key, `jup` hits `lite-api.jup.ag`. With a key it uses `api.jup.ag`. For paper trading, the free tier is sufficient.

---

## Strategy: SOL-PERP Directional Momentum

**When to trade:** SOL-PERP is entered only when:
1. Regime = RISK_ON (per IG88003 regime detection module)
2. A high-conviction SOL directional signal is present (narrative catalyst, on-chain signal, or regime transition)
3. Expected move > 0.25% notional (clears fee threshold)
4. No open SOL-PERP position already exists

**Position parameters:**
- Instrument: SOL-PERP only
- Leverage: 3x default, 5x maximum (never exceeded)
- Position size: Quarter-Kelly of Solana wallet, max 10% of total portfolio
- TP/SL set at entry — not adjusted after open
- Maximum hold: 8 hours (borrow fee accumulation becomes expensive beyond this)
- Minimum hold: 2 hours (prevents fee churn)

**Greed guardrails (hardcoded — same pattern as §4.9 of IG88002):**

| Failure Mode | IG-88 Guardrail |
|---|---|
| Holding past TP | TP triggers automatic close via `jup perps close` |
| Sizing up after wins | Position size = Kelly formula output only |
| Re-entry fever | 2-hour cooldown after any SOL-PERP close |
| Averaging down | Prohibited — losing positions do not add size |
| Borrow bleed | Auto-close if borrow fee accumulation > 50% of initial TP target |
| Daily loss halt | >5% of Solana wallet in a day → halt new perps until next UTC day |

---

## Paper Trading

`jup` has no built-in dry-run for perps execution. Paper trading is enforced at the MCP wrapper layer — the `perps open` command is gated behind a `paper_mode` flag that logs the intended trade without executing it.

**What can be validated in paper mode:**
- Signal generation and regime gating
- Kelly sizing calculations
- TP/SL placement logic
- Fee drag modeling (compare paper P&L to actual price moves minus modeled fees)
- Borrow fee accumulation over hold periods

Paper trading graduation criteria: same as other venues (200 trades, positive expectancy after fees, p < 0.10).

---

## Key CLI Commands for IG-88

| Command | Purpose |
|---|---|
| `jup -f json perps markets` | List all perp markets and current funding rates |
| `jup -f json perps positions` | Current open positions for active wallet |
| `jup -f json perps open --asset SOL --side long --amount 50 --leverage 3 --tp 5 --sl 3` | Open 3x long SOL-PERP, $50 collateral, 5% TP, 3% SL |
| `jup -f json perps open --asset SOL --side short --amount 50 --leverage 3` | Open 3x short SOL-PERP |
| `jup -f json perps set --position <id> --tp 7` | Adjust take-profit on open position |
| `jup -f json perps close --position <id>` | Close specific position |
| `jup -f json perps close` | Close all positions (emergency) |
| `jup -f json perps history --asset SOL --limit 50` | Recent SOL-PERP trade history |
| `jup -f json spot portfolio` | Check SOL balance in wallet |

**Note on `--tp` / `--sl` flags:** These are percentage values relative to entry price. `--tp 5` means take profit at +5% price move. `--sl 3` means stop loss at -3% price move.

---

## MCP Integration

`jup` has no native MCP server. Boot wraps it as a subprocess MCP tool alongside the existing Jupiter MCP server.

**Architecture:**
- Existing Jupiter MCP server: handles spot swaps, price feeds, limit orders, DCA
- `jup` subprocess wrapper: handles perps open/close/set/positions/history, lend/earn

**Tool naming convention in the wrapper:** `jup_perps_open`, `jup_perps_close`, `jup_perps_positions`, `jup_perps_markets`, `jup_lend_deposit`, `jup_lend_withdraw`.

**Paper mode gate:** The wrapper must implement `paper_mode: bool`. When true, `jup_perps_open` logs the trade parameters to Graphiti but does not call `jup perps open`. All other read commands (`positions`, `markets`, `history`) execute normally in both modes.

Boot implementation task: add to W2-3 work queue in IG88003.

---

## Relationship to Solana DEX Strategy

Jupiter Perps and Solana DEX (memecoin trading) are separate strategies sharing the same wallet and regime detection module.

- **Solana DEX:** Narrative momentum on graduated tokens. High variance, requires >$200K liquidity threshold.
- **Jupiter Perps:** Directional SOL positioning on high-conviction signals. Lower variance than memecoins, but higher fee floor.

Both are gated by the same RISK_ON regime signal. In RISK_OFF: both halt. IG-88 should not run both simultaneously in a way that creates correlated directional exposure (e.g., long SOL-PERP while also in a SOL ecosystem memecoin — both lose on a SOL drawdown).

---

## Known Limitations

- Pre-v1 alpha (v0.7.x) — breaking changes between releases expected. Pin version.
- No built-in retry or rate-limit backoff — Boot's MCP wrapper must handle this.
- JLP pool pricing: positions are priced against JLP oracle, not a live orderbook. During extreme volatility, the oracle may lag spot price.
- Borrow fees are variable and can spike during high SOL-PERP open interest periods.
- `jup update` disabled — manual upgrade process only.

---

## References

[1] Jupiter, "Perpetuals Documentation," jup.ag/perps, accessed 2026-04-06.

[2] Jupiter, `jup-ag/cli` repository, github.com/jup-ag/cli, v0.7.1, 2026-04-04.

[3] Jupiter, "JLP Pool Documentation — Fees and Borrow Rates," jup.ag/docs/perps, accessed 2026-04-06.
