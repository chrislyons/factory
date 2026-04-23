# IG88078 — Session Log: Jupiter Executor, Paper Trader v3, Polymarket Spread Tool

**Date:** 2026-04-18
**Branch:** main
**Commit:** 57f2de8

---

## Summary

Built three new production scripts and committed a major strategy update. Expanded paper trading from 2-asset to 8-asset portfolio with regime filtering, discovered Jupiter API endpoint changes, and built Polymarket spread analysis infrastructure.

---

## 1. Jupiter Executor (`scripts/jupiter_executor.py`)

**Purpose:** Signal generation + position management + Jupiter API execution layer.

**Architecture:**
- SignalEngine: computes ATR breakout signals for 8 assets
- PositionManager: tracks open positions, manages exits (trailing stop, hard stop, force-close)
- JupiterExecutor: calls `api.jup.ag/swap/v1/quote` for execution

**Key discovery:** Jupiter API endpoints changed since last review.
- `perp.jupiter.com` — does NOT resolve (DNS failure)
- `tokens.jup.ag` — does NOT resolve
- `api.jup.ag/v6` — returns 404
- `api.jup.ag/swap/v1/quote` — **WORKS** for SOL→USDC quotes

**Limitation:** True Jupiter Perps require on-chain program interaction (Solana RPC), not REST API. Current executor uses spot swap API for signal generation. Full perps integration needs `solana-py` or `solders` library (blocked by disk space).

**Signal output:** Ran `--mode signal`, generated 13 position signals across 8 assets.

**Cron job:** `ig88-jupiter-scan` (job_id: `501c09a41cfe`) — needs update to hourly recurring schedule.

---

## 2. Paper Trader v3 (`scripts/atr_paper_trader_v3.py`)

**Purpose:** 8-asset portfolio paper trader with regime filtering.

**Assets:** ETH, AVAX, SOL, LINK, NEAR, OP, WLD, SUI

**Strategy:**
- LONG: ATR breakout + SMA100 regime filter + 1.0% trailing stop
- SHORT: ATR breakdown + SMA100 regime filter (anti-trend) + 2.5% trailing stop

**Backtest results (60m data, full history):**
- 3,382 total trades
- LONG: 64% WR, all 8 assets profitable
- SOL LONG: +1702% ann
- AVAX LONG: +1700% ann
- SHORT trades: moderate edge, improved by regime filtering

**Regime filter impact:**
- SMA100 filter on LONG: +0.04-0.22 PF improvement across assets
- SHORT trades: don't benefit from trend filtering (anti-trend strategy)

**Position sizing:**
- LONG trades: 1.0 weight
- SHORT trades: 0.5 weight (half capital allocation)
- Max 15% per asset, 90% max portfolio exposure

---

## 3. Polymarket Spread Tool (`scripts/pm_spread_history.py`)

**Purpose:** Wolf Hour spread analysis — tracks spread magnitude by hour of day.

**Discovery:** Polymarket public API does NOT expose historical trade-level data.
- `gamma-api.polymarket.com/events` — works for current market data
- `clob.polymarket.com/markets` — works for orderbook
- Historical trade data — requires authentication, not publicly available

**Workaround:** Built live polling accumulator that stores spread snapshots over time to build historical dataset organically.

---

## 4. Strategy Registry Update (v5)

Updated `data/strategy_registry.json`:
- Trailing stop: 1.5% → 1.0% (grid search + walk-forward confirmed optimal)
- Added regime filter: SMA100 on LONG entries
- Updated backtest metrics with re-verified results

---

## 5. IG88077 Comprehensive System Review

Independently re-implemented all strategy backtests from scratch. Key findings:

### Confirmed
- ATR Breakout edge: PF 1.72-2.02 on ETH/AVAX/LINK/NEAR
- Portfolio diversification: 8 assets → 5.9% DD vs single-asset 25-39%
- Jupiter spot API works for quotes

### Discovered
- Optimal trailing stop is 1.0%, not 1.5% (leaving 0.5% on the table)
- SMA100 regime filter improves PF on LONG entries
- SHORT edge is real but needs regime filtering
- Polymarket lacks public historical data

### Rejected (re-confirmed)
- RSI standalone: PF ~1.0 (no edge)
- MACD standalone: PF ~1.0
- EMA crossover: PF ~1.0
- Bollinger mean reversion: PF ~1.0
- Session timing filters: no improvement
- Funding rate arbitrage: insufficient spread

---

## Pending Work

1. **Fix cron to hourly** — `ig88-jupiter-scan` is "once" repeat, needs `0 * * * *`
2. **Install Solana SDK** — blocked by disk space (100% full on root volume)
3. **True Jupiter Perps** — needs on-chain program calls via solana-py/solders
4. **Wolf Hour backtest** — need accumulated spread data from live polling
5. **BTC Up/Down strategy** — three-leg Polymarket strategy (pending spread data)

---

## Files Created/Modified

| File | Action |
|------|--------|
| `scripts/jupiter_executor.py` | NEW — signal engine + execution |
| `scripts/atr_paper_trader_v3.py` | NEW — 8-asset portfolio paper trader |
| `scripts/pm_spread_history.py` | NEW — Polymarket spread analysis |
| `data/strategy_registry.json` | MODIFIED — v5 with 1.0% trail |
| `docs/ig88/IG88077 Comprehensive System Review...md` | NEW — full analysis |
| `memory/ig88/scratchpad.md` | MODIFIED — session notes |
