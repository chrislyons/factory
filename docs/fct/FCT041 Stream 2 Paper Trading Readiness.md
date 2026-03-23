# FCT041 Stream 2 Paper Trading Readiness

Sprint report for Phase C prep — bridging IG-88 from "has MCP tools" to "can execute a paper trade cycle."

## Context

IG-88's MCP servers (jupiter-mcp, dexscreener-mcp) were deployed on Whitebox in Session 4B (FCT040) but never end-to-end verified. This sprint validates the full chain and adds auto-approval for read-only trading tools — the last prerequisite before IG-88's 100-trade validation sprint (FCT033 §8).

---

## 1. B5 Results — Jupiter Connectivity

### Pre-flight checks (all passed)

| Check | Status | Detail |
|-------|--------|--------|
| jupiter-mcp/dist/index.js | Present | 2358 bytes, 2026-03-23 |
| dexscreener-mcp/dist/index.js | Present | 2134 bytes, 2026-03-23 |
| .mcp.json paths | Correct | Whitebox absolute paths, mcp-env.sh BWS injection |
| Coordinator running | Yes | PID 69099, com.bootindustries.coordinator-rs |
| BWS injection (SSH) | Expected fail | Keychain `-w` blocked over SSH — works locally via launchd |

### Matrix DM test

**Status:** Pending user manual verification.

DM IG-88 with: "Check SOL price using `jupiter_price` (mint: `So11111111111111111111111111111111111111112`)"

Expected outcomes:
- **Success:** Price in ~$120-200 range with timestamp
- **Partial (CoinGecko fallback):** BWS injection failed — check mcp-env.sh
- **Failure (no response):** Coordinator routing issue
- **"Unknown tool":** .mcp.json not loaded by Claude subprocess

---

## 2. AUTO_APPROVE_TOOLS Changes

### 7 tools added (read-only market data)

```rust
// IG-88 trading tools -- read-only market data (jupiter_swap stays OUT)
"mcp__jupiter__jupiter_price",
"mcp__jupiter__jupiter_quote",
"mcp__jupiter__jupiter_portfolio",
"mcp__dexscreener__dex_token_info",
"mcp__dexscreener__dex_token_pairs",
"mcp__dexscreener__dex_search",
"mcp__dexscreener__dex_trending",
```

### 1 tool deliberately excluded

`jupiter_swap` — moves money, requires human approval via approval room.

### Deployment

- Edit applied on Whitebox via python3 (targeted string replacement, not SCP)
- `cargo build --release` — success (22 warnings, 0 errors, 23.6s)
- Coordinator restarted via launchctl
- Same edit applied on Cloudkicker source

**Tool name format:** `mcp__jupiter__jupiter_price` (double-underscore separators matching MCP server name from .mcp.json `"jupiter"` key). To be confirmed via first Matrix DM test — if actual prefix differs (e.g. `mcp__jupiter-mcp__`), entries must be updated.

---

## 3. trades.csv Schema Update

Extended header from 16 to 19 columns:

```
ID,Date,Time,Token,Direction,Entry,SL,TP,Exit,Result,R,Regime_Status,Regime_Conf,Narrative,Narrative_Conv,Notes,regime_label,regime_entry_date,regime_age_days
```

### New fields (per FCT033 §8.3)

| Field | Type | Valid values |
|-------|------|-------------|
| `regime_label` | enum | `RISK_ON_TRENDING`, `RISK_ON_VOLATILE`, `RISK_OFF_RANGING`, `RISK_OFF_DECLINING` |
| `regime_entry_date` | date | YYYY-MM-DD when current regime was first detected |
| `regime_age_days` | int | Days since regime entry date |

Applied on both Cloudkicker (`agents/ig88/.claude/validation/trades.csv`) and Whitebox (created fresh — directory didn't exist on WB).

---

## 4. 25-Trade Checkpoint Framework

Created `agents/ig88/.claude/validation/CHECKPOINT-TEMPLATE.md` per FCT033 §8.5-8.6.

Template covers:
1. Core metrics (win rate, expectancy, max consecutive losses, max drawdown)
2. OOS decay ratio calculation
3. Regime diversity breakdown (4 labels, 15-trade minimum per regime)
4. Kill switch status (6 triggers from §8.4)
5. Coordination tax metrics (4 metrics from §8.6)
6. NO_TRADE cycle log with counterfactuals
7. Prompt change audit trail
8. GO / EXTEND / NO-GO assessment

---

## 5. First Paper Trade Cycle

**Status:** Pending — requires manual Matrix DM to IG-88.

Instructions: DM IG-88 to run full Regime → Scanner → Narrative → Governor cycle. Log output to `cycles/C002.md`. If TRADE signal, log to `trades.csv` as T001 with `dryRun:true`. NO_TRADE is a valid outcome.

---

## 6. Next Steps

1. **Manual verification:** DM IG-88, confirm `jupiter_price` works and auto-approves
2. **Tool name check:** Verify MCP tool name prefix matches `mcp__jupiter__` — adjust if needed
3. **First cycle:** Run full paper trade cycle, produce C002.md
4. **Begin 100-trade sprint:** Per FCT033 §8, first checkpoint at T025

---

## Files Changed

| File | Change |
|------|--------|
| `coordinator/src/coordinator.rs` | +7 tools in AUTO_APPROVE_TOOLS (lines 98-104) |
| `agents/ig88/.claude/validation/trades.csv` | Header extended: +3 regime fields (19 cols) |
| `agents/ig88/.claude/validation/CHECKPOINT-TEMPLATE.md` | New — 25-trade checkpoint report template |
| `docs/fct/FCT041 Stream 2 Paper Trading Readiness.md` | New — this document |

---

*Sprint completed 2026-03-23. Predecessor: FCT040. Next: first 25-trade checkpoint report.*
