---
prefix: IG88006
title: "Polymarket Venue Setup Guide"
status: active
created: 2026-04-05
updated: 2026-04-05
author: Chris + Claude (Opus 4.6)
depends_on: IG88003
---

# IG88006 Polymarket Venue Setup Guide

## Overview

Polymarket is a decentralised prediction market operating on the Polygon network. Unlike traditional exchange accounts, there is no username/password account to create — trading identity is a Polygon wallet address. Email (ig88bot@proton.me) is used for notifications only and does not represent a trading identity.

Key characteristics relevant to IG-88's setup:

- All trades are on-chain (Polygon/MATIC), permanently public
- Collateral is USDC (native Circle USDC as of 2026, not bridged USDC.e)
- Order matching uses Polymarket's Central Limit Order Book (CLOB) off-chain, settlement is on-chain
- No KYC required; no derivatives regulation applies (binary event contracts only)
- Geographic restrictions apply to some market categories — not a concern from Ontario

---

## Wallet Setup

IG-88 uses a **programmatic EOA (Externally Owned Account)** wallet — not MetaMask, not a hardware wallet, not a proxy contract. An EOA wallet is a simple secp256k1 keypair where the private key is used to sign CLOB orders directly. This is the correct choice for automated trading.

### Key Generation Options

Any of the following methods produces a valid Polygon-compatible EOA private key:

```bash
# Option 1: polymarket-cli (after CLI install — see below)
polymarket wallet create

# Option 2: foundry/alloy cast tool
cast wallet new

# Option 3: openssl (no external dependencies)
openssl ecparam -name secp256k1 -genkey -noout -out /dev/stdout | \
  openssl ec -in /dev/stdin -outform DER 2>/dev/null | tail -c +8 | head -c 32 | xxd -p -c 32
```

### Key Storage

**Private key must be stored in Infisical, not on disk.** This is a hard requirement and is tracked as Decision D7 (IG88003 §Week 6+ prerequisite). Until Infisical migration is complete:

- Hold the private key in Bitwarden (Boot Industries org) as a secure note
- Do NOT write it to any file on disk — not `~/.config/polymarket/`, not a dotenv file, not a scratch file
- The key will be migrated to Infisical and injected as `POLYMARKET_PRIVATE_KEY` at runtime once D7 is resolved

The public key (wallet address) is safe to share. It is required for account connection at polymarket.com and for the MCP server configuration.

### Account Connection

After generating the keypair, visit polymarket.com and connect the wallet to establish account identity. This is a one-time signed message (no gas required). Once connected, the wallet address is the trading identity.

---

## CLI Installation (Supply Chain Safe)

The official Polymarket CLI is maintained by the Polymarket organisation at github.com/Polymarket/polymarket-cli [1]. It is written in Rust, licensed MIT, and distributed as a single statically-linked binary.

**Do NOT install via:**
- `brew install` — the formula lags one version behind and pulls updates automatically, which is a supply chain risk
- `curl | sh` installer scripts — unacceptable for any production tooling

**Safe installation procedure:**

```bash
# 1. Download the specific release binary (macOS aarch64, v0.1.5)
curl -LO https://github.com/Polymarket/polymarket-cli/releases/download/v0.1.5/polymarket-aarch64-apple-darwin

# 2. Verify SHA256 checksum against the value published in the GitHub release notes
#    before proceeding — abort if they do not match
shasum -a 256 polymarket-aarch64-apple-darwin

# 3. Install to ~/bin
chmod +x polymarket-aarch64-apple-darwin
mv polymarket-aarch64-apple-darwin ~/bin/polymarket

# 4. Confirm ~/bin is in PATH
which polymarket
```

**Version pinning:** Pin to v0.1.5. Do not upgrade without explicit approval. This is the TeamPCP supply chain policy — version upgrades require a deliberate review of the release diff, not an automatic pull.

No system dependencies are required. The binary links everything statically.

---

## Configuration

Polymarket CLI is configured via a combination of environment variables and an auto-generated config file.

| Variable | Value | Notes |
|---|---|---|
| `POLYMARKET_PRIVATE_KEY` | Injected from Infisical at runtime | Never hardcoded; never in config file |
| `POLYMARKET_RPC_URL` | `https://polygon.drpc.org` | Acceptable default; swap to dedicated RPC if rate limits become an issue |
| `POLYMARKET_SIGNATURE_TYPE` | `eoa` | Direct signing; do not use proxy contract signature type |

The config file at `~/.config/polymarket/config.json` is created automatically on first run. Permissions should be `0600`. It stores derived session data but not the private key — the key must arrive via environment variable.

**Test the connection after setup:**
```bash
polymarket -o json clob ok
```
A healthy response returns `{"ok": true}` or equivalent. Any auth error indicates the private key or signature type is misconfigured.

---

## Funding

Polymarket requires USDC deposited on the **Polygon network**. Sending USDC on Ethereum mainnet results in permanently lost funds — the two networks are distinct and Polymarket cannot retrieve mainnet deposits.

As of 2026, Polymarket uses **native USDC** (Circle's canonical USDC contract on Polygon, established through Circle's partnership announcement). This replaced the bridged USDC.e token that Polymarket used previously [2]. The practical consequence: on first deposit, a one-time "Activate Funds" transaction may appear in the Polymarket UI — this is a permit/approval step for the native USDC contract, not a fee.

**Starting capital:** Deposit the smallest amount you are willing to lose entirely during the paper trading validation phase. The suggested range is $50–200 USDC. Paper trading mode in the MCP layer does not move funds, but having a funded wallet is required to establish full account identity and verify the signing flow end-to-end.

**Order size minimums:**
- Market orders: $1 minimum
- Limit orders: 5 shares minimum

---

## CLOB API Access

Polymarket's trading API is a Central Limit Order Book with two authentication tiers [3]:

**L1 API key** (derived from wallet signature):
- Generated via: `polymarket clob create-api-key`
- Sufficient for all paper trading and early live trading phases
- Rate limits: 15,000 requests/10s global; 3,500/10s for `POST /order`

**L2 API key** (higher rate limits, requires builder programme acceptance):
- Apply at the Polymarket developer portal once L1 limits become a constraint
- Not required for initial phases

During paper trading, L1 is sufficient. Rate limits are unlikely to be a constraint at IG-88's scan frequency of ~50 markets every 5 minutes.

---

## Paper Trading Note

The polymarket-cli binary has **no dry-run or paper mode**. Every command that touches the CLOB (order creation, cancellation, position queries) operates against the live system.

**Paper trading for IG-88 is implemented in the MCP wrapper layer** — this is Boot's responsibility per IG88003 W2-3.B.1. When `paper_mode: true` is set in the MCP server, orders are logged locally and reported to Matrix but not submitted to the CLOB. The `polymarket clob create-order` command and related commands must not be called directly until live trading is approved by Chris.

Do not run any `create-order` or `market-order` CLI commands during the paper trading phase.

---

## Fee Structure

Polymarket's fee model rewards maker behaviour and penalises takers [3]:

| Role | Fee | Notes |
|---|---|---|
| Maker (GTC limit orders) | Zero + rebate | Rebate = 20–25% of taker fees collected on that market, proportional to maker liquidity provided |
| Taker (FOK/IOC market orders) | Dynamic, up to ~1.56% | Scales with probability — highest near 50%, lower at extremes |
| Geopolitics markets | Zero fees | Fee-free category regardless of order type |

**IG-88 strategy implication:** Post GTC limit orders at or near fair value wherever the spread permits. The maker rebate effectively means being a liquidity provider on Polymarket generates positive fee income. Taker orders should be used only when entering a position that would otherwise close before the limit order fills.

---

## Key CLI Commands for IG-88

| Command | Purpose |
|---|---|
| `polymarket -o json markets list --active --limit 50` | Scan open markets |
| `polymarket -o json clob book <token_id>` | Order book depth for a market |
| `polymarket -o json clob price <token_id>` | Current mid-market price |
| `polymarket -o json clob balance --asset-type collateral` | USDC balance |
| `polymarket -o json clob orders` | Open orders |
| `polymarket -o json data positions` | Open positions |
| `polymarket -o json clob create-order --token-id <id> --price <p> --size <s> --order-type GTC` | Place limit order (paper trading: do not use directly — route through MCP) |
| `polymarket -o json clob cancel-all` | Emergency cancel all open orders |

The `-o json` flag on all commands ensures machine-parseable output for the MCP wrapper.

---

## Known Limitations

**No WebSocket streaming.** The CLI and CLOB REST API are polling-only. Real-time price feeds require direct integration with the Polymarket WebSocket API (separate from the CLOB REST endpoint). For IG-88's 5-minute scan cycles this is not a constraint, but it is relevant if sub-minute monitoring becomes necessary.

**Single primary maintainer.** The v0.1.x series is explicitly marked experimental by the maintainer. The codebase is small and moves quickly — pin the version and review release notes before any upgrade.

**Private key handling in config.** CLI versions prior to the planned PR #57 (encrypted vault support) store a derived session token in the config file; the private key itself is only passed via environment variable. Until PR #57 lands, continue using `POLYMARKET_PRIVATE_KEY` via environment injection and do not allow the CLI to write anything sensitive to `~/.config/polymarket/`.

**No paper/dry-run mode.** All CLI commands are live. Paper trading must be enforced at the MCP wrapper layer (see §Paper Trading Note above).

---

## Resolution and Counterparty Risk

Polymarket uses the **UMA Optimistic Oracle** for market resolution. A proposer posts an outcome with a bond; a challenge window allows disputers to contest [4]. Key figures for operational awareness:

- Historical dispute rate: approximately 1.3% of markets
- MOOV2 upgrade (August 2025): resolution proposals restricted to whitelisted addresses with a verified accuracy record of 95%+, substantially reducing invalid resolution risk
- Smart contracts audited by ChainSecurity — no major exploit to date

**Markets to avoid:** Any market with subjective or ambiguous resolution criteria (e.g., "Will X be considered a success?"). These carry elevated dispute risk that is difficult to model. Prefer markets with objective, verifiable resolution criteria (election outcomes, price crossings, scheduled events with clear yes/no conditions).

---

## References

[1] Polymarket, "polymarket-cli," GitHub, github.com/Polymarket/polymarket-cli, accessed 2026-04-05.

[2] Circle and Polymarket, "Polymarket Integrates Native USDC on Polygon," Circle Blog, 2026 (approximate). Verify current deposit instructions at docs.polymarket.com before depositing.

[3] Polymarket, "CLOB API Documentation," docs.polymarket.com, accessed 2026-04-05.

[4] UMA Protocol, "Optimistic Oracle," docs.uma.xyz, accessed 2026-04-05.
