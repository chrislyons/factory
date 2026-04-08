---
prefix: IG88012
title: "Backtesting and Paper Trading Systems"
status: active
created: 2026-04-07
updated: 2026-04-07
author: Chris + Claude (Opus 4.6)
depends_on: IG88001, IG88003, IG88011
---

# IG88012 Backtesting and Paper Trading Systems

## Purpose

This document describes the backtesting engine, paper trading system, and venue-specific strategy backtesters built for IG-88's multi-venue trading operation. These systems are the validation layer between strategy design and live execution — no strategy graduates to live trading without passing through them.

**Design principles:**
- **Deterministic where possible.** Regime detection and position sizing are hardcoded math, not LLM inference.
- **Statistically rigorous.** Every strategy must prove positive expectancy at p < 0.10 over 200+ trades before graduation.
- **Minimal dependencies.** Runtime code uses stdlib + numpy only. No scipy, pandas, or external packages required.
- **Config-driven.** All parameters (pairs, thresholds, fees, guardrails) live in `config/trading.yaml`. No hardcoded magic numbers.

---

## 1. Architecture

```
config/trading.yaml          <- Master config (pairs, risk, regime, fees, graduation)
    |
src/trading/config.py        <- Config loader (typed dataclasses)
    |
    ├── src/quant/regime.py              <- Regime detection (deterministic)
    |       |
    ├── src/quant/backtest_engine.py     <- Unified backtest harness
    |       |
    |       ├── src/quant/polymarket_backtest.py  <- Calibration arb + base rate
    |       ├── src/quant/spot_backtest.py        <- Kraken event-driven + momentum
    |       └── src/quant/perps_backtest.py       <- Jupiter SOL-PERP
    |
    └── src/trading/paper_trader.py      <- Paper trading engine
            |
            └── data/paper_trades.jsonl  <- Trade log (append-only)
```

---

## 2. Trading Configuration (`config/trading.yaml`)

### Pair Lists

Sourced from Chris's TradingView watchlists (2026-04-07). Organized into tiers:

| Tier | Count | Examples | Position Sizing |
|------|-------|----------|-----------------|
| Majors | 3 | BTC/USD, ETH/USDT, SOL/USDT | Full Kelly fraction |
| Large cap | 15 | LINK, NEAR, UNI, AVAX, TAO, RENDER | 75% Kelly fraction |
| Mid cap | 18 | JUP, WIF, BONK, MOODENG, ORDI | 50% Kelly fraction |

**Macro indicators** (regime inputs, not tradeable): TOTAL, TOTAL3, BTC.D, DXY, SPX, GOLD.

### Risk Parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| Kelly fraction (0-200 trades) | Quarter-Kelly (0.25) | IG88002 |
| Kelly fraction (200+ trades) | Half-Kelly (0.50) | IG88002 |
| Max position | 10% of venue wallet | IG88001 |
| Daily drawdown halt | 5% | IG88003 |
| Auto-execute threshold | $50 | Decision D2 (pending) |

### Venue Configuration

Each venue has: enabled flag, paper_mode (must be true until graduation), strategy list, fee schedule, position limits, and venue-specific guardrails.

---

## 3. Regime Detection (`src/quant/regime.py`)

**Three states:** RISK_ON (score 7-10), NEUTRAL (4-6), RISK_OFF (0-3).

**Seven weighted signals:**

| Signal | Weight | Scoring |
|--------|--------|---------|
| BTC 7-day trend | 0.25 | -10% → 0, +10% → 10, linear between |
| Total market cap trend | 0.15 | Same mapping as BTC |
| Fear & Greed Index | 0.20 | 0-100 → 0-10 direct mapping |
| Aggregate funding rates | 0.15 | -0.05% → 0, +0.05% → 10 |
| Stablecoin flows | 0.10 | -500M → 0, +500M → 10 |
| BTC dominance delta | 0.10 | Rising dom → lower score (inverted) |
| GARCH vol percentile | 0.05 | Low vol → high score |

**Safety properties:**
- Missing signals: score computed from available signals only, confidence reduced proportionally
- No signals available: defaults to RISK_OFF (safe)
- Polymarket runs in all regimes (event outcomes uncorrelated with crypto)
- All other venues require RISK_ON for new positions

---

## 4. Backtesting Engine (`src/quant/backtest_engine.py`)

### Trade Dataclass

Universal trade record across all venues:
- Core: trade_id, venue, strategy, pair, side, leverage, entry/exit prices and timestamps
- Risk: stop_level, target_level, regime_state
- Outcome: pnl_usd, pnl_pct, r_multiple, outcome (win/loss/breakeven), exit_reason
- Venue-specific: llm_estimate and brier_score (Polymarket), narrative_category (Solana DEX), borrow_fees (Jupiter Perps)

### BacktestStats

Comprehensive statistical summary:
- **Core:** n_trades, win_rate, expectancy (per-trade and in R-multiples), total P&L
- **Risk-adjusted:** Sharpe ratio (annualized), Sortino ratio, max drawdown, profit factor
- **Statistical tests:** t-statistic, p-value (one-sided: is expectancy > 0?)
- **Variance drag:** arithmetic_return, geometric_return, drag magnitude, pass/fail
- **Per-pair breakdown:** trade count, win rate, total P&L per instrument

### Graduation Check

Automated pass/fail against IG88003 graduation criteria:
- ≥ 200 trades
- Positive expectancy (E > 0 after costs)
- Statistical significance (p < 0.10)
- Geometric return positive (variance drag check)
- Max drawdown < 15%
- Brier score < 0.20 (Polymarket only)
- Chris approval (always requires manual ✅)

### Kelly Position Sizing

`f_kelly = (b × p - q) / b` where b = avg_win/avg_loss, p = win_rate, q = 1-p.

Applied as fractional Kelly (quarter or half) and capped at max_position_pct of venue wallet.

---

## 5. Venue-Specific Backtesters

### 5.1 Polymarket (`src/quant/polymarket_backtest.py`)

**Calibration Arbitrage:** Exploits favourite-longshot bias. Markets priced <15% resolve YES less often than implied; markets priced >85% resolve YES more often. Price-blinded LLM assessment provides independent probability estimate.

**Base Rate Audit:** Historical base rate for event category diverges from market price. If |base_rate - market_price| exceeds threshold, trade the direction of the base rate.

Both strategies track Brier score per trade and support calibration curve analysis.

### 5.2 Kraken Spot (`src/quant/spot_backtest.py`)

**Event-Driven:** Regime-gated entries on catalyst events. Spot only, no leverage. Fee-aware (0.16% maker / 0.26% taker). Prefers limit orders. Min hold 4 hours.

**Regime Momentum:** Enters when price crosses above 20-period MA during RISK_ON. ATR-based stops. Same fee and guardrail structure.

### 5.3 Jupiter Perps (`src/quant/perps_backtest.py`)

**SOL-PERP only.** Regime-gated. 3x default / 5x max leverage. Models borrow fees (hourly, utilization-based). TP/SL required on every position. Fee drag check: expected_move × leverage must exceed 0.25%. Borrow fee auto-close at 50% of TP target.

---

## 6. Paper Trading System (`src/trading/paper_trader.py`)

### Components

- **PaperTrader:** Opens/closes paper positions, enforces all guardrails, checks stops/targets on price updates
- **PositionTracker:** Manages open positions, computes unrealized P&L, detects daily drawdown halt
- **DailySummary:** Markdown-formatted daily report for Matrix posting
- **VarianceDragCalculator:** geometric_return = arithmetic_return - (sigma²/2)
- **TradeLogger:** Appends to `data/paper_trades.jsonl` (JSONL format)

### Data Flow

```
Price update → PositionTracker.update_prices()
    → Check stops/targets → Auto-close if hit
    → Check daily drawdown → Halt if exceeded
    → Check borrow fees (perps) → Auto-close if threshold hit

New signal → PaperTrader.open_position()
    → Check regime → Reject if not RISK_ON (except Polymarket)
    → Check position limits → Reject if exceeded
    → Check daily trade count → Reject if exceeded
    → Check min hold / cooldown → Reject if too soon
    → Check fee drag (perps) → Reject if insufficient
    → Create Trade, log to JSONL, report to Matrix
```

### JSONL Format

Each line in `data/paper_trades.jsonl` is a JSON dict from `Trade.to_dict()`. This file is append-only and never modified. It is the canonical paper trading record.

---

## 7. Hermes Integration

IG-88 runs on Hermes runtime (port 41971, OpenRouter). The backtesting and paper trading systems are Python modules callable from Hermes sessions via Bash tool.

### Scan Loop (Coordinator Timer)

```json
{
  "timer_id": "ig88_scan_loop",
  "agent": "ig88",
  "due_at": "<5 minutes from now>",
  "message": "Run scan cycle: check regime, scan venues, evaluate candidates, log results",
  "room": "!zRnHwXlrVdCfdNbNOx:matrix.org"
}
```

The scan loop is self-perpetuating — each cycle writes the next timer.

### Available Commands

```bash
# Run regime assessment
python3 -c "from src.quant.regime import assess_regime; ..."

# Run backtest on synthetic data
python3 -m src.quant.polymarket_backtest
python3 -m src.quant.spot_backtest
python3 -m src.quant.perps_backtest

# Check paper trading stats
python3 -c "from src.trading.paper_trader import PaperTrader; ..."
```

---

## 8. File Inventory

| File | Lines | Purpose |
|------|-------|---------|
| `config/trading.yaml` | ~180 | Master config |
| `src/trading/__init__.py` | 2 | Package init |
| `src/trading/config.py` | ~170 | Config loader |
| `src/quant/regime.py` | ~200 | Regime detection |
| `src/quant/backtest_engine.py` | ~400 | Unified backtest harness |
| `src/quant/polymarket_backtest.py` | ~300 | Polymarket strategies |
| `src/quant/spot_backtest.py` | ~300 | Kraken spot strategies |
| `src/quant/perps_backtest.py` | ~300 | Jupiter Perps |
| `src/trading/paper_trader.py` | ~400 | Paper trading engine |
| `data/paper_trades.jsonl` | 0+ | Trade log (runtime) |

---

## References

[1] IG88001, "Multi-Venue Trading Action Plan," 2026-04-04.

[2] IG88003, "Trading System Build Schedule and Instructions," 2026-04-04.

[3] IG88011, "Cloud Model Bake-Off Results," 2026-04-06.

[4] hanakoxbt, "How Claude Extracts Consistent Edge From Prediction Markets," research-vault TX260330.

[5] RohOnChain, "Institutional Prediction Market Hedge Fund Operations," research-vault TX260306.
