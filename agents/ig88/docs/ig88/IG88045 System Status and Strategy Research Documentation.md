# IG88045: System Status and Strategy Research Documentation

**Author:** IG-88  
**Date:** 2026-04-14  
**Purpose:** Comprehensive documentation for external agent collaboration  
**Status:** Active Research Phase - No Validated Edge Found

---

## Executive Summary

IG-88 is an autonomous trading agent tasked with finding statistically validated trading edges across crypto markets (Kraken spot, Jupiter perpetuals) and prediction markets (Polymarket). After extensive systematic testing, **no trading strategy has passed strict statistical validation** (p < 0.05, 95% CI excludes zero). However, several strategies show promising but unproven positive returns. Paper trading is now active to gather real-world data.

---

## 1. System Architecture

### 1.1 Workspace Location
```
/Users/nesbitt/dev/factory/agents/ig88/
```

### 1.2 Key Directories
| Directory | Purpose |
|-----------|---------|
| `src/quant/` | Backtesting framework and indicators |
| `scripts/` | Test runners, scanners, paper traders |
| `data/` | Backtest results, paper trade logs |
| `memory/ig88/` | Session memory and facts |
| `docs/ig88/` | Documentation (IG88### files) |

### 1.3 Python Environment
```bash
# Correct interpreter (has pandas/numpy/scipy):
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3

# NEVER use bare python3 - it lacks dependencies
```

### 1.4 Data Sources
| Source | Method | Status |
|--------|--------|--------|
| Binance (OHLCV) | Public REST API | Working |
| Polymarket | gamma-api.polymarket.com | Working (slugs have suffixes like `-926`) |
| Kraken | Private API (requires auth) | Not yet configured |
| Jupiter | RPC + Jupiter API | Wallet not yet funded |

---

## 2. Backtesting Framework

### 2.1 Core Framework
**Location:** `src/quant/backtest_framework.py`

The framework provides a `Backtester` class and `Strategy` base class with:
- Recursive indicator calculations (no look-ahead bias)
- Position tracking with leverage support
- Comprehensive metrics (PnL, PF, Sharpe, drawdown)

### 2.2 Indicator Library
Available in `Strategy` base class:
- `sma(prices, period)` - Simple Moving Average
- `ema(prices, period)` - Exponential Moving Average
- `rsi(prices, period)` - Relative Strength Index
- `atr(highs, lows, closes, period)` - Average True Range

### 2.3 Critical Bug Fixed
**Issue:** `np.convolve(mode='same')` was used for EMA calculation, causing look-ahead bias.

**Impact:** Generated false positive signals with PF > 15 that were entirely artifacts.

**Fix:** All indicators now use recursive bar-by-bar calculation.

---

## 3. Strategy Research Results

### 3.1 Strategies Tested

| Strategy | Description | Status |
|----------|-------------|--------|
| Donchian Breakout | Price breaks N-period channel | **Best candidate** |
| Double MA Crossover | Fast/slow moving average cross | Tested |
| RSI Mean Reversion | Buy oversold, sell overbought | Tested |
| VWAP Bounce | Price bounce off VWAP | Tested |
| ATR Channel | ATR-based channel breakout | Tested |
| Momentum RSI | RSI oversold bounce entry | Tested |
| Bollinger Bands | BB squeeze/breakout | Tested |
| Volume Momentum | High volume + price momentum | Tested |

### 3.2 Top Results (10,000 bars = 416 days)

**Donchian_20 (period=20, hold=10 bars) on 1H timeframe:**

| Pair | Trades | Total PnL | PF | Win Rate | Max DD |
|------|--------|-----------|-----|----------|--------|
| AVAXUSDT | 215 | +65.1% | 1.30 | 52.1% | 3.7% |
| LINKUSDT | 216 | +64.2% | 1.31 | 51.9% | 6.1% |
| NEARUSDT | 232 | +63.5% | 1.27 | 47.0% | 4.3% |
| UNIUSDT | 210 | +59.7% | 1.24 | 50.0% | 6.3% |
| ETHUSDT | 208 | +53.2% | 1.31 | 51.0% | 4.8% |
| BTCUSDT | 230 | +9.7% | 1.09 | 46.0% | 5.1% |
| SOLUSDT | 241 | -10.8% | 0.96 | 48.0% | 7.3% |
| INJUSDT | 227 | -18.6% | 0.94 | 47.0% | 9.7% |

### 3.3 Statistical Validation Results

**Bootstrap Confidence Intervals (10,000 iterations):**

| Pair | Mean Trade PnL | 95% CI | Excludes Zero? |
|------|----------------|--------|----------------|
| AVAXUSDT | +0.30% | [-0.10%, +0.70%] | **No** |
| LINKUSDT | +0.30% | [-0.10%, +0.69%] | **No** |
| NEARUSDT | +0.27% | [-0.14%, +0.69%] | **No** |
| ETHUSDT | +0.26% | [-0.10%, +0.61%] | **No** |

**One-Sample T-Tests (H0: mean PnL = 0):**

| Pair | t-statistic | p-value | Significant (p<0.05)? |
|------|-------------|---------|----------------------|
| AVAXUSDT | 1.45 | 0.1487 | **No** |
| LINKUSDT | 1.45 | 0.1477 | **No** |
| NEARUSDT | 1.27 | 0.2058 | **No** |
| ETHUSDT | 1.40 | 0.1631 | **No** |

**Walk-Forward Validation (5 splits):**

| Pair | Profitable Splits | Avg WF PnL | Status |
|------|-------------------|------------|--------|
| AVAXUSDT | 3/5 | +1.5% | Mixed |
| LINKUSDT | 1/5 | -2.2% | Failing |
| NEARUSDT | 3/5 | +7.4% | Mixed |
| ETHUSDT | 2/5 | +1.2% | Mixed |

### 3.4 Honest Assessment

**What the data shows:**
- Positive backtest PnL across multiple pairs
- 200+ trades provides reasonable sample size
- Win rates ~50% with slight edge on risk/reward
- PF of 1.25-1.31 is modest but potentially real

**Why statistical tests fail:**
- Mean trade PnL (~0.3%) is small relative to trade-to-trade variance
- 95% CI includes zero, meaning the edge could be noise
- Walk-forward performance is inconsistent across time periods

**What this means:**
- The edge, IF it exists, is very small
- It may be real but undetectable with current sample sizes
- It may not survive transaction costs and slippage
- Paper trading will provide ground truth

---

## 4. Paper Trading Status

### 4.1 Active Paper Trades

**Crypto Donchian Breakout (Tracking Script: `scripts/paper_trade_runner.py`)**
- State file: `data/paper_trades/current_state.json`
- Pairs: AVAXUSDT, NEARUSDT, LINKUSDT, ETHUSDT
- Strategy: Donchian_20 on 1H
- Status: Waiting for entry signals (price breaks 20-period upper channel)

**Polymarket Correlated Arb (Tracking Script: `scripts/poly_paper_runner.py`)**
- State file: `data/paper_trades/polymarket_state.json`
- Thesis: GTA VI implied late 2026+, but "impossible events" priced at ~50%

| Market | Direction | Entry YES | Current YES | Position |
|--------|-----------|-----------|-------------|----------|
| Jesus returns before GTA VI | BUY NO | 48.5% | 48.5% | $100 |
| Rihanna album before GTA VI | BUY NO | 58.5% | 58.5% | $100 |
| Trump out before GTA VI | BUY NO | 52.0% | 52.0% | $75 |

### 4.2 Paper Trading Protocol

Run paper traders:
```bash
cd /Users/nesbitt/dev/factory/agents/ig88
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/paper_trade_runner.py
/Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/poly_paper_runner.py
```

---

## 5. What Has NOT Been Tested

### 5.1 Kraken Spot
- Private API authentication not configured
- Need Infisical secrets: `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`
- See: `docs/ig88/IG88024 Kraken API Documentation.md`

### 5.2 Jupiter Perpetuals
- Wallet created but not funded
- Public key: Check `~/.config/ig88/trading-wallet.json`
- Need SOL for gas and margin

### 5.3 Regime-Gated Strategies
- ADX-based regime detection exists in `src/quant/regime.py`
- Haven't tested: "Only trade Donchian when ADX > 25" etc.
- This is a high-priority research direction

### 5.4 Multi-Indicator Combinations
- Haven't tested: Donchian + RSI confirmation
- Haven't tested: Donchian + volume filter
- Haven't tested: Adaptive parameters based on volatility

---

## 6. Key Files Reference

### 6.1 Source Code
| File | Purpose |
|------|---------|
| `src/quant/backtest_framework.py` | Core backtester and strategy base class |
| `src/quant/regime.py` | Market regime detection (ADX-based) |
| `scripts/deep_scan.py` | Comprehensive strategy scanner |
| `scripts/paper_trade_runner.py` | Crypto paper trader |
| `scripts/poly_paper_runner.py` | Polymarket paper tracker |

### 6.2 Data Files
| File | Purpose |
|------|---------|
| `data/systematic/deep_scan_results.json` | Full scan results |
| `data/systematic/final_validation.json` | Statistical test results |
| `data/paper_trades/current_state.json` | Crypto paper state |
| `data/paper_trades/polymarket_state.json` | Polymarket paper state |

### 6.3 Memory Files
| File | Purpose |
|------|---------|
| `memory/ig88/scratchpad.md` | Working session notes |
| `memory/ig88/fact/trading.md` | Durable trading decisions |
| `memory/ig88/fact/infrastructure.md` | System knowledge |

### 6.4 Documentation
| File | Purpose |
|------|---------|
| `docs/ig88/IG88045 System Status...` | This file |
| `docs/ig88/IG88024 Kraken API...` | Kraken auth docs |
| `CLAUDE.md` | IG-88 identity and rules |

---

## 7. Questions for External Agents

### 7.1 Research Questions

1. **Statistical Power:** With mean trade PnL of 0.3% and typical trade variance, how many trades are needed to achieve 80% power at p<0.05?

2. **Regime Detection:** Can ADX or other regime filters improve the Donchian breakout edge by filtering out losing market conditions?

3. **Transaction Costs:** Given the small edge (~0.3% per trade), what's the realistic impact of Kraken's ~0.26% taker fee?

4. **Alternative Approaches:** Are there strategy types that inherently have higher per-trade edge (reducing sample size requirements)?

### 7.2 Implementation Questions

5. **Polymarket Execution:** What's the optimal approach for executing correlated arb trades on Polymarket with EOA wallet signing?

6. **Position Sizing:** Given the unproven edge, what's the appropriate risk per trade? (Currently $1000 per backtest trade)

7. **Walk-Forward Design:** Is 5-split walk-forward appropriate, or should we use expanding window?

---

## 8. Next Steps

### 8.1 Immediate (This Week)
- [ ] Run paper traders for 2+ weeks
- [ ] Collect 20+ paper trades on crypto
- [ ] Track Polymarket positions until GTA VI release window clarity

### 8.2 Research (Needs Help)
- [ ] Regime-gated Donchian (ADX filter)
- [ ] Multi-indicator confirmation (Donchian + RSI + Volume)
- [ ] Statistical power analysis for sample size requirements
- [ ] Adaptive parameter optimization

### 8.3 Future (After Validation)
- [ ] Configure Kraken API authentication
- [ ] Fund Jupiter wallet for perps trading
- [ ] Implement autonomous trade execution
- [ ] Build portfolio-level risk management

---

## 9. Constraints and Notes

### 9.1 Risk Limits
- First live trade after validation gap >7 days requires Chris approval
- Auto-execute threshold: ≤$500 position size
- Regime must be RISK_ON for live trading

### 9.2 Known Issues
- Polymarket API slugs have numeric suffixes (e.g., `-926`, `-665`)
- Binance API rate limits may require throttling for large scans
- Paper trading state is file-based (not persistent across system restarts)

### 9.3 User Preferences
- Chris values empirical evidence over speculation
- Thorough validation before live deployment
- Wants to see actual PnL, not just backtest numbers
- Prefers honest assessment of edge quality

---

## 10. Contact and Context

**IG-88 Identity:** Autonomous trading agent on Whitebox (Mac Studio)  
**Operator:** Chris (nesbitt)  
**Session Model:** OpenRouter (google/gemma-4-31b-it)  
**Trust Level:** L3 Operator (market analysis, trading execution within thresholds)

**Communication:**
- Primary channel: IG-88 Training Matrix room
- Can be reached via @ig88 mentions
- Responds to direct questions about market analysis and trading

---

*Document created for external agent collaboration. All code, data, and state files are in `/Users/nesbitt/dev/factory/agents/ig88/`.*
