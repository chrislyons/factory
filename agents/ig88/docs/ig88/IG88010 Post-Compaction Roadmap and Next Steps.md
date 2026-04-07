---
prefix: IG88010
title: "Post-Compaction Roadmap and Next Steps"
status: active
created: 2026-04-06
updated: 2026-04-06
author: Chris + Claude (Opus 4.6)
depends_on: IG88003, IG88009
---

# IG88010 Post-Compaction Roadmap and Next Steps

## Purpose

This document establishes the sequenced roadmap for the IG-88 trading system build following the 2026-04-04 to 2026-04-06 planning sprint. It consolidates all pending actions from IG88003 and IG88009 into an ordered execution plan with clear ownership and dependencies.

**Session context:** Nine PREFIX docs (IG88001-IG88009) were produced covering strategy, review, build schedule, model evaluation, four venue setup guides, and Infisical secrets management. All three trading CLIs are installed and pinned on both machines. Infisical is operational at eu.infisical.com with two projects (IG88, Factory). This document picks up from that point.

---

## Security Constraints (Non-Negotiable)

1. **No secrets on disk.** No private key, API key, or credential is written to any file, ever. Infisical is the only secrets store for project/agent use.
2. **No secrets in conversation.** Claude never prints, echoes, or includes secret values in tool output or responses. Use `<placeholder>` notation.
3. **BWS full purge.** Bitwarden Secrets Manager is being decommissioned across both machines. After migration, Bitwarden reverts to Chris's personal password manager only. See IG88009 §BWS Decommissioning.
4. **Supply chain caution.** No package installs without pre-verification (source, checksums, licence) AND Chris's express permission. `brew` or `uv` only. No `curl | sh`. No auto-updates.

---

## Phase 1: Infisical + Account Setup (Chris — This Week)

These are sequential, human-only tasks. Claude provides guidance but Chris executes directly.

### Step 1.1: Create IG-88 Machine Identity

**Where:** eu.infisical.com → IG88 project → Access Control → Machine Identities

1. Click **Create Machine Identity**
2. Name: `ig88-whitebox`
3. Auth method: **Universal Auth**
4. Role: **Reader** (read-only — IG-88 never writes secrets)
5. Note the `client_id` and `client_secret` that are generated
6. **Do NOT paste these into chat.** Set them directly in Whitebox environment:

```bash
# On Whitebox — set persistent env vars via launchctl
launchctl setenv INFISICAL_CLIENT_ID "<paste-client-id-here>"
launchctl setenv INFISICAL_CLIENT_SECRET "<paste-client-secret-here>"
launchctl setenv INFISICAL_API_URL "https://eu.infisical.com"
```

7. Verify the env vars are set:
```bash
echo $INFISICAL_CLIENT_ID  # should show the value (in terminal only, not in chat)
```

8. **Optional:** Repeat for Cloudkicker if IG-88 sessions will run there. Add to `~/.zshrc`:
```bash
export INFISICAL_CLIENT_ID="<paste>"
export INFISICAL_CLIENT_SECRET="<paste>"
export INFISICAL_API_URL="https://eu.infisical.com"
```

### Step 1.2: Verify Infisical CLI Authentication

```bash
# Test that the Machine Identity can authenticate
infisical login --method=universal-auth \
  --client-id=$INFISICAL_CLIENT_ID \
  --client-secret=$INFISICAL_CLIENT_SECRET

# Test secret retrieval (assumes at least one secret exists in IG88 project)
infisical secrets list --projectId=<ig88-project-id> --env=production
```

**If this works:** Infisical is wired. Proceed to Step 1.3.
**If this fails:** Check that `INFISICAL_API_URL` is set to `https://eu.infisical.com` (not the default US endpoint).

### Step 1.3: Kraken Account Setup (W1.C.2)

1. **Sign up** at kraken.com with a dedicated email (not personal)
2. **Complete Intermediate KYC** (required for API trading)
3. **Enable 2FA** before generating any API keys
4. **Generate two API key pairs** (see IG88007 §API Key Generation for exact permissions):
   - "IG-88 Read" — query-only permissions
   - "IG-88 Trade" — query + create/modify/cancel orders
5. **IP whitelist** the trade key to Whitebox Tailscale IP `100.88.222.111`
6. **Add all four values to Infisical** (IG88 project, production environment):
   - `KRAKEN_API_KEY` (trade key)
   - `KRAKEN_API_SECRET` (trade secret)
   - `KRAKEN_READ_API_KEY` (read key)
   - `KRAKEN_READ_API_SECRET` (read secret)

### Step 1.4: Verify Kraken via Infisical

```bash
infisical run --projectId=<ig88-project-id> --env=production \
  -- kraken -o json ticker XBTUSD
```

**Expected:** JSON ticker data for BTC/USD. This proves: Infisical auth works, Kraken API key is valid, the `infisical run --` wrapper pattern is operational.

### Step 1.5: Polymarket Wallet Setup (W1.C.1)

1. **Generate a new EVM wallet** (EOA) for Polymarket programmatic trading. This is a dedicated wallet — not a personal wallet.
   - Use any secure method: MetaMask, `cast wallet new`, or hardware wallet derivation
   - The wallet needs to operate on **Polygon** (not Ethereum mainnet)
2. **Add the private key to Infisical** (IG88 project):
   - Secret name: `POLYMARKET_PRIVATE_KEY`
   - Value: hex-encoded private key (with or without `0x` prefix)
3. **Connect the wallet at polymarket.com:**
   - Import the wallet into MetaMask or equivalent
   - Connect to Polymarket and complete any required onboarding
   - The wallet needs **USDC on Polygon** to trade
4. **Fund with a small amount of USDC on Polygon** for paper trading validation

### Step 1.6: Solana Wallet Migration

The existing IG-88 Solana wallet at `~/.config/ig88/trading-wallet.json` must migrate to Infisical. See IG88009 §Solana Wallet Migration for detailed steps.

**Summary:**
1. Extract private key as base58 (use the python3 snippet in IG88009)
2. Add as `SOLANA_WALLET_PRIVATE_KEY` in Infisical IG88 project
3. Verify public key matches
4. Verify `infisical run -- jup -f json spot portfolio` returns correct wallet data
5. **Only after verification:** `shred -u ~/.config/ig88/trading-wallet.json`

### Step 1.7: Fund Accounts (W1.C.3)

- **Kraken:** Deposit smallest amount you're willing to lose. CAD via Interac e-Transfer (fastest) or crypto deposit.
- **Polymarket:** USDC on Polygon into the new programmatic wallet.
- **Jupiter:** SOL already in the existing wallet (verify balance after migration).

**Do not size up until paper trading validation is complete (200 trades per venue, positive expectancy after fees).**

---

## Phase 2: BWS Decommissioning (Chris + Claude — After Phase 1)

**Prerequisite:** All 13 BWS secrets verified present in Infisical (see IG88009 §BWS Decommissioning for the full inventory).

### Step 2.1: Migrate BWS Secrets to Infisical

Chris adds each secret value to the correct Infisical project via the web UI. The 13-secret mapping table is in IG88009. Trading secrets go to the IG88 project; infrastructure secrets go to the Factory project.

### Step 2.2: Replace mcp-env.sh References

Claude updates these files to use the `infisical run --` pattern:

| File | Current | New |
|---|---|---|
| `agents/ig88/.mcp.json` | `mcp-env.sh JUPITER_API_KEY=... -- node ...` | `infisical run --projectId=<id> --env=production -- node ...` |
| `agents/ig88/scripts/run-bakeoff.sh` | `mcp-env.sh ANTHROPIC_API_KEY=... -- python3 ...` | `infisical run --projectId=<id> --env=production -- python3 ...` |
| Coordinator launchd plists | BWS-injected env vars | Infisical-injected env vars |

### Step 2.3: Update Coordinator Config

The coordinator currently injects Matrix tokens and API keys via BWS/mcp-env.sh. These plists need updating to use `infisical run --` as the command wrapper, or to set env vars from Infisical before starting the coordinator.

### Step 2.4: Purge BWS Artifacts

After all services are verified working with Infisical:

```bash
# Delete macOS Keychain entry (Whitebox)
security delete-generic-password -s "bws-factory-agents" -a "factory-agents"

# Uninstall bws CLI (Whitebox)
brew uninstall bws

# Uninstall bws CLI (Cloudkicker, if installed)
ssh chrislyons@100.86.68.16 '/opt/homebrew/bin/brew uninstall bws'

# Delete mcp-env.sh scripts
rm ~/.config/mcp-env.sh
rm ~/.config/ig88/mcp-env.sh
```

### Step 2.5: Archive BWS Project

In Bitwarden web vault: archive the `factory-agents` BWS project (do not delete — audit trail). Bitwarden reverts to Chris's personal password manager only.

---

## Phase 3: MCP Server Wiring (Boot — Week 2-3)

**Prerequisites:** Infisical working (Phase 1), secrets populated.

### 3.1: Kraken MCP (W2-3.B.2) — Hours, Not Weeks

Kraken CLI ships with a native MCP server. No wrapper build needed.

**MCP config (using Infisical injection):**
```json
{
  "mcpServers": {
    "kraken": {
      "command": "infisical",
      "args": [
        "run",
        "--projectId", "<ig88-project-id>",
        "--env", "production",
        "--",
        "kraken", "mcp", "-s", "market,account,paper"
      ],
      "env": {
        "KRAKEN_AGENT_CLIENT": "ig88",
        "INFISICAL_CLIENT_ID": "<from-env>",
        "INFISICAL_CLIENT_SECRET": "<from-env>"
      }
    }
  }
}
```

**Verify:** MCP client connects, `market_ticker` tool returns data.

### 3.2: Polymarket MCP Wrapper (W2-3.B.1)

Build a subprocess MCP server wrapping the `polymarket` CLI. Key requirements:
- `paper_mode: bool` gate — when true, logs trade intent to Graphiti but does not execute
- All read commands (`clob markets`, `clob book`, `user positions`) execute in both modes
- USDC balance checks before any trade execution
- Maker-order preference (zero fees) over taker orders

### 3.3: Jupiter Perps MCP Wrapper (W2-3.B.4)

Build a subprocess MCP server wrapping the `jup` CLI. Key requirements:
- `paper_mode: bool` gate — same pattern as Polymarket
- **SOL-PERP only** — reject any other asset
- Leverage cap: 5x maximum, 3x default
- TP/SL required at open (no naked positions)
- 2-hour cooldown after any close
- Borrow fee auto-close at 50% of TP target

### 3.4: Jupiter Spot/DCA MCP Update

Update existing Jupiter MCP server config (`agents/ig88/.mcp.json`) to use Infisical instead of `mcp-env.sh`.

---

## Phase 4: IG-88 Strategy Work (Week 1-2, Parallel)

These can proceed in parallel with Phases 1-3 as they are research/design tasks.

### 4.1: Regime Detection Criteria (W1.I.1)

Define the RISK_ON / NEUTRAL / RISK_OFF scoring model. Inputs: BTC dominance, total market cap trend, VIX proxy, stablecoin flows, funding rates. Output: three-state regime with confidence score.

### 4.2: Polymarket Starting Strategy Selection (W1.I.2)

Choose between Base Rate Audit and Calibration Arbitrage as the first Polymarket strategy. Both validated in research; pick based on current market opportunity.

### 4.3: Narrative Classification Taxonomy (W1.I.3)

Define the Solana DEX narrative categories for memecoin classification. Required before any Solana DEX observation phase begins.

---

## Phase 5: Paper Trading Validation (Week 4+)

**Prerequisites:** MCP servers wired (Phase 3), strategies defined (Phase 4), accounts funded (Phase 1).

- **Polymarket:** 200 paper trades, Brier score < 0.20 at 50 trades, < 0.15 at 200
- **Kraken Spot:** 200 paper trades, positive expectancy after 0.32% maker round-trip
- **Jupiter Perps:** 200 paper trades, positive expectancy after 0.14-0.22% round-trip + borrow
- **Graduation:** Each venue graduates independently. No live trading until that venue's paper validation is complete.

---

## Open Decisions (from IG88003)

| ID | Decision | Status | Blocking |
|---|---|---|---|
| D2 | Auto-execute threshold (recommended: $50 Polymarket, $100 Kraken) | Pending — Chris | Phase 5 |
| D3 | Polymarket starting strategy | Pending — IG-88 (W1.I.2) | Phase 5 |
| D4 | Kraken pairs: BTC/ETH only or add SOL? | Pending — Chris | Phase 3.1 |
| D5 | TradingView indicator set | Deferred | Not blocking |
| D6 | Graphiti group_id schema for trade storage | Pending — Boot | Phase 3 |
| D7 | Infisical migration complete | **In progress** — see Phase 1-2 | All live trading |

---

## Dependency Graph

```
Phase 1 (Chris: accounts + Infisical)
  ├── Step 1.1: Machine Identity ──► Step 1.2: Verify CLI auth
  ├── Step 1.3: Kraken KYC ──► Step 1.4: Verify Kraken via Infisical
  ├── Step 1.5: Polymarket wallet ──► Fund (Step 1.7)
  └── Step 1.6: Solana wallet migration ──► Fund (Step 1.7)

Phase 2 (BWS purge) ◄── Phase 1 complete
  └── All 13 secrets in Infisical ──► Replace mcp-env.sh ──► Update coordinator ──► Purge BWS

Phase 3 (MCP wiring) ◄── Phase 1 complete (Infisical working)
  ├── 3.1: Kraken MCP (fastest — native, hours)
  ├── 3.2: Polymarket MCP wrapper (build needed)
  ├── 3.3: Jupiter Perps MCP wrapper (build needed)
  └── 3.4: Jupiter spot MCP update

Phase 4 (Strategy) ◄── No hard dependencies (parallel with 1-3)
  ├── 4.1: Regime detection
  ├── 4.2: Polymarket strategy
  └── 4.3: Narrative taxonomy

Phase 5 (Paper trading) ◄── Phase 3 + Phase 4 complete
  └── 200 trades per venue ──► Graduation to live
```

---

## Immediate Next Actions (Sorted by Priority)

| # | Action | Owner | Depends On | Est. Effort |
|---|---|---|---|---|
| 1 | Create IG-88 Machine Identity in Infisical | Chris | — | 10 min |
| 2 | Set `INFISICAL_CLIENT_ID/SECRET` in Whitebox env | Chris | #1 | 5 min |
| 3 | Verify `infisical login` + `infisical secrets list` | Chris + Claude | #2 | 5 min |
| 4 | Start Kraken KYC (may take 1-3 days for verification) | Chris | — | 15 min + wait |
| 5 | Generate Polymarket EVM wallet | Chris | — | 10 min |
| 6 | Add Polymarket private key to Infisical | Chris | #1, #5 | 5 min |
| 7 | Migrate Solana wallet to Infisical | Chris + Claude | #1, #3 | 15 min |
| 8 | Generate Kraken API keys (after KYC approved) | Chris | #4 | 10 min |
| 9 | Add Kraken keys to Infisical | Chris | #1, #8 | 5 min |
| 10 | Verify `infisical run -- kraken -o json ticker XBTUSD` | Chris + Claude | #9 | 5 min |
| 11 | Migrate remaining BWS secrets to Infisical | Chris | #1 | 20 min |
| 12 | Replace `mcp-env.sh` with Infisical pattern | Claude | #11 | 30 min |
| 13 | Purge BWS from both machines | Chris + Claude | #12 verified | 15 min |
| 14 | Wire Kraken MCP server | Boot | #10 | 2 hrs |
| 15 | Build Polymarket MCP wrapper | Boot | #6 | 1-2 days |
| 16 | Build Jupiter Perps MCP wrapper | Boot | #7 | 1-2 days |

---

## References

[1] IG88003, "Trading System Build Schedule and Instructions," 2026-04-04.

[2] IG88009, "Infisical Secrets Management Setup," 2026-04-06.

[3] FCT035, "Phase B Sprint Report — BWS Setup and Secret Rotation," 2026-03-23.
