---
prefix: IG88013
title: "Sprint Report — Backtesting and Paper Trading Build"
status: active
created: 2026-04-07
updated: 2026-04-07
author: Chris + Claude (Opus 4.6)
depends_on: IG88003, IG88011, IG88012
---

# IG88013 Sprint Report — Backtesting and Paper Trading Build

## Summary

Single-session build sprint (2026-04-07) delivering the complete backtesting, paper trading, and technical indicator infrastructure for IG-88's multi-venue trading system. All code tested, committed, and documented. IG-88's memory filesystem initialized and primed for its first Hermes session.

**Deliverables:** 10 new files, ~6,600 lines of production code, 3 git commits, 1 architecture doc (IG88012).

---

## 1. What Was Built

### 1.1 Trading Configuration System

**`config/trading.yaml`** — Master configuration encoding all trading parameters:
- 36 Kraken spot pairs across 3 tiers (majors, large cap, mid cap), sourced from Chris's TradingView watchlists
- 6 macro indicators (TOTAL, TOTAL3, BTC.D, DXY, SPX, GOLD) as regime inputs
- Risk parameters per IG88002/IG88003: quarter-Kelly, 10% max position, 5% daily drawdown halt
- Per-venue config: fees, position limits, guardrails, paper_mode flags
- Graduation criteria (200 trades, p < 0.10, geometric return positive)
- Kill criteria (negative expectancy at 200+, variance drag fail, consecutive halts)

**`src/trading/config.py`** — Typed dataclass loader for the YAML config. Validates regime weight sum, provides convenience methods (`enabled_venues()`, `pairs_for_venue()`).

### 1.2 Regime Detection Module

**`src/quant/regime.py`** — Deterministic, no-LLM regime detection.

Three states (RISK_ON / NEUTRAL / RISK_OFF) computed from 7 weighted signals:

| Signal | Weight | Source |
|--------|--------|--------|
| BTC 7-day trend | 0.25 | CoinGecko / Kraken API |
| Total market cap trend | 0.15 | CoinGecko |
| Fear & Greed Index | 0.20 | api.alternative.me/fng/ |
| Funding rates | 0.15 | Venue APIs |
| Stablecoin flows | 0.10 | DeFiLlama |
| BTC dominance delta | 0.10 | CoinGecko |
| GARCH vol percentile | 0.05 | Internal model |

**Safety properties verified:**
- No signals → RISK_OFF (safe default)
- Partial signals → score from available data, confidence reduced
- Polymarket always allowed (regime-independent)

### 1.3 Backtesting Engine

**`src/quant/backtest_engine.py`** — Universal backtest harness.

- `Trade` dataclass: covers all 4 venues with venue-specific fields (Brier for Polymarket, borrow fees for Perps, narrative category for Solana DEX)
- `BacktestStats`: expectancy, Sharpe, Sortino, max drawdown, profit factor, t-test, p-value, variance drag, per-pair breakdown
- `graduation_check()`: automated pass/fail against IG88003 criteria
- `kelly_size()`: fractional Kelly with position cap
- No scipy dependency — t-test implemented in pure Python/numpy

### 1.4 Venue-Specific Backtesters

| File | Venue | Strategies | Key Features |
|------|-------|-----------|-------------|
| `polymarket_backtest.py` | Polymarket | Calibration arbitrage, base rate audit | Price-blinded LLM simulation, Brier scoring, calibration curves |
| `spot_backtest.py` | Kraken Spot | Event-driven, regime momentum | Walk-forward 70/30 split, ATR stops, 36-pair config loading |
| `perps_backtest.py` | Jupiter Perps | Mean reversion | SOL-PERP enforcement, 3-5x leverage, borrow fee modeling, fee drag check |

All backtesters produce `BacktestStats` via the unified engine. Synthetic data generators included for pipeline testing (real data validates strategies).

### 1.5 Paper Trading Engine

**`src/trading/paper_trader.py`** — Production paper trading system.

- `PaperTrader`: opens/closes positions, enforces all guardrails (regime gate, position limits, drawdown halt, leverage caps, TP/SL, min hold, cooldown)
- `PositionTracker`: in-memory position management, unrealized P&L, daily trade counts
- `DailySummary`: markdown-formatted daily report for Matrix posting
- `compute_variance_drag()`: geometric_return = arithmetic_return - (sigma^2/2)
- `TradeLogger`: append-only JSONL at `data/paper_trades.jsonl`

**Guardrails verified in testing:**
- Overleveraged positions rejected (10x > 5x max → blocked)
- Stop-loss triggers computed correctly
- Daily drawdown halt fires at threshold
- Regime exit triggers position close on gated venues

### 1.6 Technical Indicator Library

**`src/quant/indicators.py`** — 21 modular indicators, 1,490 lines.

Built from Chris's TradingView indicator files (`~/dev/tradingview/indicators/`). Chris's preferred indicator (Ichimoku) implemented as first-class `IchimokuCloud` dataclass with composite scoring.

**From TradingView files:**

| TV File | Indicator Built | Priority |
|---------|----------------|----------|
| `ichimoku.txt` | `ichimoku()` + `IchimokuCloud` dataclass + `ichimoku_composite_score()` | **Primary** |
| `klinger.txt` | `klinger()` — volume-based trend confirmation | High |
| `poc-bands.txt` | `kama()` + `kama_bands()` — adaptive MA with ATR bands | High |
| `vwap.txt` | `vwap()` + `vwap_bands()` — institutional reference | High |
| `autofib.txt` | `auto_fib_levels()` + `fibonacci_retracement/extension()` | Medium |
| `kagi-ol.txt` | `kagi()` — noise-filtering trend overlay | Medium |
| `bat-signal.txt` | Not implemented (lunar cycles — no quantitative edge) | Skipped |

**Standard technicals also built:** RSI, EMA, SMA, WMA, DEMA, ATR, MACD, Bollinger Bands, Donchian Channel, ADX, SuperTrend, Stochastic RSI, OBV.

**Composite:** `multi_indicator_confluence()` — combines Ichimoku (40% weight), MACD, RSI, and Bollinger into a single [-1, +1] signal.

All functions: numpy arrays in, numpy arrays out. Zero external dependencies.

### 1.7 Scan Loop

**`scripts/scan-loop.py`** — Self-perpetuating coordinator timer. Runs regime assessment, scans all enabled venues, writes structured JSON report, and creates the next timer file for the coordinator to fire in 5 minutes.

### 1.8 Memory Filesystem

Initialized `memory/ig88/` with:
- `scratchpad.md` — Primed with full context for first Hermes session
- `fact/trading.md` — Durable trading decisions (venue architecture, inference stack, risk params, regulatory constraints)
- `fact/infrastructure.md` — Runtime, wallet, MCP server, port knowledge
- `index.md` — Navigation map

---

## 2. Git History

| Commit | Description | Files | Lines |
|--------|-------------|-------|-------|
| `201dbf5` | Backtesting engine, regime detection, trading config | 5 | +1,211 |
| `af5324e` | Venue backtesters, paper trader, IG88012 doc | 6 | +4,033 |
| `b108ee1` | Indicator library, scan loop, minor fixes | 5 | +1,654 |
| **Total** | | **16** | **+6,898** |

---

## 3. Test Results

All modules tested with synthetic data. Key observations:

- **Regime detection:** Bullish inputs → RISK_ON (6.58), bearish → RISK_OFF (1.17), no data → RISK_OFF, Polymarket always allowed
- **Backtest engine:** 50 synthetic trades: 68% WR, positive expectancy, Sharpe 6.66, graduation check passes all except min trades (50 < 200)
- **Paper trader:** Correctly rejects overleveraged positions, fires stops, tracks daily P&L, generates markdown summaries
- **Indicators:** All 21 functions produce valid output on 200-bar synthetic data
- **Venue backtesters:** Correctly show no edge on random synthetic data (null hypothesis validated — edge only emerges on real market data)

---

## 4. Dependency Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| scipy dependency | Removed — t-test reimplemented in pure Python | Keeps runtime dependency-free; only numpy + yaml required |
| Config gitignore | Force-added `trading.yaml` despite `agents/ig88/config/` being gitignored | Trading config has no secrets; agent-config.yaml (which does) stays ignored |
| Pair list source | Chris's TradingView watchlists | 3 tiers (majors/large/mid), some may be delisted — backtest data will prune |
| Ichimoku priority | First-class `IchimokuCloud` dataclass | Chris's explicit preference |

---

## 5. What's Ready for IG-88's First Hermes Session

1. **Scratchpad is primed** — IG-88 reads `scratchpad.md` on session start and has full context
2. **Scan loop is ready** — `python3 scripts/scan-loop.py` runs immediately
3. **Polymarket paper trading is unblocked** — regime-independent, can start with synthetic estimates
4. **All other venues need regime data** — connect live APIs before spot/perps paper trading

### IG-88's First Actions (In Order)
1. Read scratchpad + fact files
2. Connect CoinGecko/cfgi.io for live regime data
3. Run backtests on real OHLCV data
4. Start Polymarket paper trading
5. Recommend starting strategy for Decision D3

---

## 6. Open Items

| Item | Status | Owner |
|------|--------|-------|
| D2: Auto-execute threshold | Pending | Chris |
| D3: Polymarket starting strategy | Pending — IG-88 to recommend | IG-88 |
| D5: TradingView indicators | **Resolved** — 21 indicators built | — |
| Manim visualization skill | Exploratory — see IG88014 | IG-88 / Boot |
| Real OHLCV data acquisition | Not started | IG-88 |
| Live regime data sources | Not connected | IG-88 |

---

## References

[1] IG88003, "Trading System Build Schedule and Instructions," 2026-04-04.

[2] IG88011, "Cloud Model Bake-Off Results," 2026-04-06.

[3] IG88012, "Backtesting and Paper Trading Systems," 2026-04-07.
