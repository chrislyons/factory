# IG88016 First Real-Data Backtest Results and Regime Integration

**Date:** 2026-04-09
**Status:** Complete
**Session:** Proof & Validation Phase — Milestone 1

---

## 1. Summary

This document records the first backtests run on real market data (not synthetic).
Two strategies were tested: H2 (SOL-PERP Mean Reversion) and H3 (Regime Momentum, Kraken Spot).

**Headline finding:** Both strategies show directional promise on real data, but sample sizes
are too small for statistical significance. The null hypothesis (no edge) is not yet falsified.
The path forward is to increase sample size via lower timeframes and longer data windows.

---

## 2. Infrastructure Delivered

### 2.1 data_fetcher.py

New module: `src/quant/data_fetcher.py`

**OHLCV sourcing:**
- Primary: Kraken public REST API (no API key required)
- Supports: BTC/USD, ETH/USD, SOL/USDT, and 12 other pairs
- Intervals: 1m, 5m, 15m, 30m, 60m, 240m, 1440m
- Disk cache: parquet format in `data/`, keyed by symbol + interval
- Cache refresh: automatic when cache age > 0.5x interval

**Regime signal sourcing:**
- Fear & Greed Index: api.alternative.me (no key, reliable)
- BTC 7-day trend: CoinGecko market_chart (accurate 7d delta)
- BTC dominance + Total market cap: CoinGecko /global (batched, 1 call)
- SOL funding rate: Coinglass public endpoint (fallback: 0.0)
- Rate limit handling: 429 exponential backoff, sequential with spacing

**Live regime assessment integrated.** As of this session:
- BTC: $71,945 (+7.5% 7d, +1.1% 24h)
- Fear & Greed: 14 (Extreme Fear)
- BTC Dominance: 57%
- **Regime state: NEUTRAL (score 4.76/10)**

### 2.2 Run Scripts

- `src/quant/run_h3_backtest.py` — H3 Kraken Spot momentum
- `src/quant/run_h2_backtest.py` — H2 Jupiter Perps mean reversion

---

## 3. Current Regime Assessment

| Signal              | Value        | Score/10 | Weight |
|---------------------|--------------|----------|--------|
| BTC 7d trend        | +7.5%        | 7.2      | 0.30   |
| Total mcap 24h      | +0.76%       | 5.0*     | 0.20   |
| Fear & Greed        | 14 (Ex. Fear)| 1.4      | 0.25   |
| SOL funding 8h      | 0.0%         | 5.0*     | 0.10   |
| BTC dominance delta | 0.0 (no hist)| 5.0*     | 0.15   |

*Defaulted to 5.0 (neutral) due to missing/fallback data.

**Composite: 4.76/10 — NEUTRAL**

Interpretation: Price is recovering (+7.5% BTC) but sentiment is destroyed (F&G=14).
The regime engine correctly identifies this as a conflict — not safe enough to deploy
Kraken/Jupiter capital. Polymarket remains active.

---

## 4. H3 Backtest — Regime Momentum (Kraken Spot)

**Data:** 2 years daily OHLCV (Kraken public API). Apr 2024 – Apr 2026. 721 candles.
**Regime proxy:** Price > 20-SMA by 2% = RISK_ON. Price < 20-SMA by 2% = RISK_OFF.
**Initial capital:** $10,000

| Variant                    | n  | WR    | PF    | Sharpe  | MaxDD | PnL%   | p-val |
|----------------------------|----|-------|-------|---------|-------|--------|-------|
| RegimeMomentum BTC daily   | 10 | 30.0% | 1.234 | 1.264   | 0.1%  | +0.03% | 0.408 |
| RegimeMomentum SOL daily   | 12 | 33.3% | 0.845 | -1.090  | 0.2%  | -0.08% | 0.588 |
| RegimeMomentum BTC 4h      | 1  | 0.0%  | 0.000 | 0.000   | 0.0%  | -0.02% | 1.000 |
| EventDriven BTC daily      | 10 | 30.0% | 0.400 | -6.761  | 0.1%  | -0.07% | 0.893 |

**Verdict:** H3 null hypothesis holds. BTC daily technically passes PF > 1.2 (success criterion),
but n=10 makes p=0.408 — statistically noise. The success criterion was set too low for
the available data. Need at minimum 50 trades to begin making inferences.

**Root cause of low trade count:** The RISK_ON regime filter is too restrictive on daily bars.
Only 36% of bars qualify as RISK_ON, and momentum signals within those bars are sparse.
The price-proxy regime (2% SMA deviation) is also likely mis-calibrated for daily crypto.

---

## 5. H2 Backtest — SOL-PERP Mean Reversion (Jupiter Perps)

**Data:** 4h SOL/USDT (Dec 2025 – Apr 2026, 721 4h bars) + daily SOL/USDT (2 years).
**Regime proxy:** Same price-SMA proxy as H3.
**Initial capital:** $5,000. Leverage: 3x.

| Variant             | n | WR    | PF     | Sharpe  | MaxDD | PnL%   | p-val |
|---------------------|---|-------|--------|---------|-------|--------|-------|
| 4h bars, 3x lev     | 3 | 66.7% | 35.772 | 17.248  | 0.0%  | +0.22% | 0.089 |
| Daily bars, 3x lev  | 4 | 50.0% | 0.704  | -2.531  | 0.3%  | -0.09% | 0.600 |

**Verdict:** H2 null hypothesis holds. The 4h Sharpe of 17.2 is almost certainly
overfitting on n=3. At this sample size, any 2/3 win rate looks exceptional.
Daily timeframe fails entirely.

The extreme PF (35.8) on 4h signals a regime mismatch — the backtester is likely
entering on the very few RISK_ON periods in what has been a declining SOL market
and getting lucky on timing. Not a repeatable edge.

---

## 6. Key Diagnostics

### Why So Few Trades?

The Kraken `OHLC` public endpoint returns exactly 720 candles max per call.
- Daily (1440m): 720 days = ~2 years. Generates ~10-12 trades in RISK_ON regime.
- 4h (240m): 720 x 4h candles = ~120 days. Very short window.
- 1h (60m): 720 x 1h candles = ~30 days. Useful for paper trading calibration only.

To get enough trades for statistical inference on daily timeframe:
Need approximately 5 years of daily data at current regime hit rates (~36% RISK_ON, ~5% signal density = ~650 days * 0.36 * 0.05 = 11 trades/year).

**Required data sources for meaningful backtests:**
- Kraken historical data export (CSV, years of OHLCV)
- CoinGecko Pro API (extended history)
- Or switch to 1h timeframe with tighter signal criteria

### Regime Proxy Limitation

The price > 20-SMA proxy regime is a simplification. The real 7-signal regime engine
(fear/greed, dominance, market cap, funding rates) would produce different — and likely
more meaningful — RISK_ON signals. The next backtest iteration should integrate the
live regime engine for historical simulation.

---

## 7. Next Steps (Priority Order)

1. **Increase sample size** — Fetch extended historical OHLCV. Target: 5 years for
   daily, 1 year for 4h. Use Kraken full history export or alternative data source.

2. **Replace price-proxy regime** — Run regime backtests using the 7-signal engine
   applied historically. Requires historical fear/greed data (downloadable from alternative.me).

3. **H3 parameter sensitivity** — Test regime threshold at 1%, 2%, 3% SMA deviation.
   Test MA period (10, 20, 50). Goal: more RISK_ON periods without signal dilution.

4. **H1 Polymarket** — Unblock by creating EVM/Polygon wallet and testing LLM
   probability calibration on 10 real markets.

5. **Paper trading** — Even without statistical significance, begin paper trading
   BTC RegimeMomentum daily to accumulate live trade data for the registry.

---

## 8. Data Files

| File                                  | Contents                              |
|---------------------------------------|---------------------------------------|
| `data/BTC_USD_1440m.parquet`          | 721 daily BTC candles (Apr24-Apr26)   |
| `data/SOL_USDT_1440m.parquet`         | 721 daily SOL candles (Apr24-Apr26)   |
| `data/BTC_USD_240m.parquet`           | 721 4h BTC candles (Dec25-Apr26)      |
| `data/SOL_USDT_240m.parquet`          | 721 4h SOL candles (Dec25-Apr26)      |
| `data/h3_backtest_results.json`       | H3 full results                       |
| `data/h2_backtest_results.json`       | H2 full results                       |

---

*Authored by IG-88 | Proof & Validation Phase | Session 2026-04-09*
