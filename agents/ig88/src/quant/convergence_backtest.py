"""
convergence_backtest.py — Multi-indicator convergence testing framework.

Tests which indicator combinations improve upon the baseline Ichimoku TK-cross
strategy on SOL 4h (the current edge candidate).

Methodology:
  1. Baseline: Ichimoku TK cross above cloud + RSI > 50 (the existing signal)
  2. For each additional filter, measure: delta_PF, delta_WR, delta_n, delta_p
  3. Rank by information gain (filters that improve PF AND maintain sample size)
  4. Grid search best combinations of top filters
  5. Walk-forward validate winners

Filters tested (each as an add-on to the Ichimoku baseline):
  Trend confirmation:
    - ADX > 20 (trend exists, not ranging)
    - ADX > 25 (strong trend)
    - SuperTrend bullish
    - KAMA slope positive
    - EMA 50 bullish (price > EMA50)
    - Kagi trend = +1

  Momentum confirmation:
    - MACD histogram positive
    - MACD bullish cross (histogram crosses above zero)
    - StochRSI K > 20 (not oversold)
    - StochRSI K > D (bullish)
    - RSI > 55 (stronger threshold)
    - RSI > 60 (even stronger)

  Volume confirmation:
    - OBV trend positive (OBV SMA slope > 0)
    - Klinger bullish (KVO > signal)
    - Volume above 20-period average

  Ichimoku sub-filters (beyond TK cross above cloud):
    - Cloud is bullish (Senkou A > Senkou B)
    - Chikou above price 26 bars ago
    - Cloud thickness increasing
    - Ichimoku composite score >= 3
    - Ichimoku composite score >= 4

  Volatility:
    - BB %B > 0.5 (price in upper half of Bollinger Bands)
    - ATR percentile > 40 (sufficient volatility for trade)
    - Not in Bollinger squeeze (bandwidth > threshold)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.ichimoku_backtest import (
    IchimokuBacktester, build_btc_trend_regime, df_to_arrays, load_binance
)
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade, TradeOutcome
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "kraken_spot"
MAKER_FEE = 0.0016
ATR_STOP = 2.0
ATR_TARGET = 3.0
MIN_HOLD = 2
COOLDOWN = 2
DAILY_HALT = 0.03


# ---------------------------------------------------------------------------
# Pre-compute all indicators for a price series
# ---------------------------------------------------------------------------

class IndicatorCache:
    """Compute and cache all indicators once for a price series."""

    def __init__(self, o, h, l, c, v):
        self.o = o; self.h = h; self.l = l; self.c = c; self.v = v
        n = len(c)

        # Ichimoku (canonical from indicators.py)
        self.ichi = ind.ichimoku(h, l, c)
        self.ichi_score = ind.ichimoku_composite_score(self.ichi, c)
        self.tk_signals = self.ichi.tk_cross_signals()

        # ADX
        adx_r = ind.adx(h, l, c, period=14)
        self.adx = adx_r.adx
        self.plus_di = adx_r.plus_di
        self.minus_di = adx_r.minus_di

        # SuperTrend
        self.st_line, self.st_dir = ind.supertrend(h, l, c, period=10, multiplier=3.0)

        # KAMA (use close)
        self.kama = ind.kama(c, period=6)
        # KAMA slope: positive if current > previous
        self.kama_slope = np.full(n, 0.0)
        for i in range(1, n):
            if not np.isnan(self.kama[i]) and not np.isnan(self.kama[i-1]):
                self.kama_slope[i] = 1.0 if self.kama[i] > self.kama[i-1] else -1.0

        # EMA 50
        self.ema50 = ind.ema(c, 50)

        # Kagi
        self.kagi_line, self.kagi_trend = ind.kagi(c, reversal_pct=0.005)

        # MACD
        macd_r = ind.macd(c, fast_period=12, slow_period=26, signal_period=9)
        self.macd_hist = macd_r.histogram
        self.macd_cross = np.zeros(n)
        for i in range(1, n):
            if (not np.isnan(self.macd_hist[i]) and not np.isnan(self.macd_hist[i-1])):
                if self.macd_hist[i] > 0 and self.macd_hist[i-1] <= 0:
                    self.macd_cross[i] = 1.0   # Bullish histogram cross

        # RSI
        self.rsi = ind.rsi(c, period=14)

        # StochRSI
        self.srsi_k, self.srsi_d = ind.stoch_rsi(c, rsi_period=14, stoch_period=14,
                                                    k_smooth=3, d_smooth=3)

        # OBV
        self.obv = ind.obv(c, v)
        self.obv_ema = ind.ema(self.obv, 20)  # OBV smoothed
        self.obv_slope = np.full(n, 0.0)
        for i in range(1, n):
            if not np.isnan(self.obv_ema[i]) and not np.isnan(self.obv_ema[i-1]):
                self.obv_slope[i] = 1.0 if self.obv_ema[i] > self.obv_ema[i-1] else -1.0

        # Klinger
        klinger_r = ind.klinger(h, l, c, v)
        self.klinger_kvo = klinger_r.kvo
        self.klinger_sig = klinger_r.signal

        # Volume MA
        self.vol_ma20 = ind.sma(v, 20)

        # Bollinger Bands
        bb = ind.bollinger_bands(c, period=20, mult=2.0)
        self.bb_upper = bb.upper
        self.bb_lower = bb.lower
        self.bb_mid = bb.middle
        self.bb_pctb = bb.percent_b
        self.bb_bw = bb.bandwidth

        # ATR
        self.atr_vals = ind.atr(h, l, c, period=14)
        # ATR percentile (rolling 50-bar)
        self.atr_pct = np.full(n, np.nan)
        for i in range(50, n):
            if not np.isnan(self.atr_vals[i]):
                window = self.atr_vals[i-50:i]
                valid = window[~np.isnan(window)]
                if len(valid) > 0:
                    self.atr_pct[i] = np.sum(valid <= self.atr_vals[i]) / len(valid) * 100


# ---------------------------------------------------------------------------
# Filter definitions
# ---------------------------------------------------------------------------

def build_filters(ic: IndicatorCache) -> dict[str, np.ndarray]:
    """
    Return dict of filter_name -> bool array (True = entry allowed).
    Each filter is tested as an add-on to the baseline entry conditions.
    """
    n = len(ic.c)
    filters = {}

    # --- Trend ---
    filters["adx_20"]       = (~np.isnan(ic.adx)) & (ic.adx > 20)
    filters["adx_25"]       = (~np.isnan(ic.adx)) & (ic.adx > 25)
    filters["supertrend"]   = ic.st_dir > 0
    filters["kama_slope"]   = ic.kama_slope > 0
    filters["ema50_bull"]   = (~np.isnan(ic.ema50)) & (ic.c > ic.ema50)
    filters["kagi_bull"]    = ic.kagi_trend > 0

    # --- Momentum ---
    filters["macd_pos"]     = (~np.isnan(ic.macd_hist)) & (ic.macd_hist > 0)
    filters["macd_cross"]   = ic.macd_cross > 0
    filters["srsi_k20"]     = (~np.isnan(ic.srsi_k)) & (ic.srsi_k > 20)
    filters["srsi_kd"]      = (~np.isnan(ic.srsi_k)) & (~np.isnan(ic.srsi_d)) & (ic.srsi_k > ic.srsi_d)
    filters["rsi_55"]       = (~np.isnan(ic.rsi)) & (ic.rsi > 55)
    filters["rsi_60"]       = (~np.isnan(ic.rsi)) & (ic.rsi > 60)

    # --- Volume ---
    filters["obv_slope"]    = ic.obv_slope > 0
    filters["klinger_bull"] = (~np.isnan(ic.klinger_kvo)) & (~np.isnan(ic.klinger_sig)) & (ic.klinger_kvo > ic.klinger_sig)
    filters["vol_above_ma"] = (~np.isnan(ic.vol_ma20)) & (ic.v > ic.vol_ma20)

    # --- Ichimoku sub-conditions ---
    filters["cloud_bull"]   = np.array([d == ind.CloudDirection.BULLISH for d in ic.ichi.cloud_direction])
    filters["chikou_bull"]  = np.array([
        (i >= 25 and ic.c[i] > ic.c[i-25]) for i in range(n)
    ])
    cloud_thick = ic.ichi.cloud_thickness
    filters["cloud_thick"]  = np.array([
        (i >= 1 and not np.isnan(cloud_thick[i]) and not np.isnan(cloud_thick[i-1])
         and cloud_thick[i] > cloud_thick[i-1])
        for i in range(n)
    ])
    filters["ichi_score3"]  = ic.ichi_score >= 3
    filters["ichi_score4"]  = ic.ichi_score >= 4

    # --- Volatility ---
    filters["bb_upper_half"] = (~np.isnan(ic.bb_pctb)) & (ic.bb_pctb > 0.5)
    filters["atr_pct40"]    = (~np.isnan(ic.atr_pct)) & (ic.atr_pct > 40)
    # No Bollinger squeeze: bandwidth > 5% of price
    bw_ratio = np.full(n, np.nan)
    for i in range(n):
        if not np.isnan(ic.bb_mid[i]) and ic.bb_mid[i] > 0:
            bw_ratio[i] = (ic.bb_upper[i] - ic.bb_lower[i]) / ic.bb_mid[i] * 100
    filters["no_bb_squeeze"] = (~np.isnan(bw_ratio)) & (bw_ratio > 4.0)

    return filters


# ---------------------------------------------------------------------------
# Convergence backtester (extends IchimokuBacktester with filter mask)
# ---------------------------------------------------------------------------

class ConvergenceBacktester:
    """
    Like IchimokuBacktester but accepts an explicit boolean entry_mask.
    Entry fires only when: Ichimoku TK cross + above cloud + RSI > 50 + mask[i].
    """

    def __init__(self, initial_capital=10_000.0, bar_interval_hours=4.0,
                 allow_neutral=True):
        self.initial_capital = initial_capital
        self.bar_interval_hours = bar_interval_hours
        self.allow_neutral = allow_neutral
        self.wallet = initial_capital
        self._trade_counter = 0
        self._last_exit_bar = -999
        self._daily_pnl = 0.0
        self._daily_halted = False
        self._current_day = -1

    def _next_id(self):
        self._trade_counter += 1
        return f"CNV-{self._trade_counter:05d}"

    def _check_daily_halt(self, i, ts):
        day = int(ts[i] // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_pnl = 0.0
            self._daily_halted = False
        return self._daily_halted

    def run(self, timestamps, opens, highs, lows, closes, volumes,
            ic: IndicatorCache, regime_states, entry_mask: np.ndarray) -> list[Trade]:
        n = len(timestamps)
        warmup = 60  # enough for Ichimoku (52 + 26 displacement) + other indicators

        min_hold = max(1, int(MIN_HOLD / max(self.bar_interval_hours, 1)))
        cooldown = max(1, int(COOLDOWN / max(self.bar_interval_hours, 1)))

        trades = []
        i = warmup

        while i < n - min_hold - 2:
            if self._check_daily_halt(i, timestamps): i += 1; continue
            if i - self._last_exit_bar < cooldown: i += 1; continue

            # Regime gate
            state = regime_states[i]
            if state == RegimeState.RISK_OFF: i += 1; continue
            if state == RegimeState.NEUTRAL and not self.allow_neutral: i += 1; continue

            # Base entry: TK cross (signal from indicators.py IchimokuCloud)
            if ic.tk_signals[i] != 1: i += 1; continue

            # Price above cloud
            cloud_top = max(ic.ichi.senkou_span_a[i] if not np.isnan(ic.ichi.senkou_span_a[i]) else -np.inf,
                            ic.ichi.senkou_span_b[i] if not np.isnan(ic.ichi.senkou_span_b[i]) else -np.inf)
            if closes[i] <= cloud_top: i += 1; continue

            # RSI > 50 baseline
            if np.isnan(ic.rsi[i]) or ic.rsi[i] <= 50: i += 1; continue

            # Additional filter mask
            if not entry_mask[i]: i += 1; continue

            # ATR for stops
            atr_v = ic.atr_vals[i]
            if np.isnan(atr_v): i += 1; continue

            entry_bar = i + 1
            if entry_bar >= n: break

            entry_price = opens[entry_bar]
            entry_time = datetime.fromtimestamp(timestamps[entry_bar], tz=timezone.utc)
            pos_size = self.wallet * 0.02
            if pos_size < 1.0: i += 1; continue

            stop_p   = entry_price - ATR_STOP * atr_v
            target_p = entry_price + ATR_TARGET * atr_v

            trade = Trade(
                trade_id=self._next_id(), venue=VENUE, strategy="convergence",
                pair="", entry_timestamp=entry_time, entry_price=entry_price,
                position_size_usd=pos_size, regime_state=regime_states[i],
                side="long", leverage=1.0, stop_level=stop_p, target_level=target_p,
                fees_paid=pos_size * MAKER_FEE,
            )

            # Hold loop
            exit_bar = entry_bar; exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n: break
                if lows[bar] <= stop_p:
                    exit_bar = bar; exit_price = stop_p; exit_reason = ExitReason.STOP_HIT; break
                if highs[bar] >= target_p:
                    exit_bar = bar; exit_price = target_p; exit_reason = ExitReason.TARGET_HIT; break
                if regime_states[bar] == RegimeState.RISK_OFF and j >= min_hold:
                    exit_bar = bar; exit_price = closes[bar]; exit_reason = ExitReason.REGIME_EXIT; break
                if j >= min_hold and not np.isnan(ic.ichi.kijun_sen[bar]) and closes[bar] < ic.ichi.kijun_sen[bar]:
                    exit_bar = bar; exit_price = closes[bar]; exit_reason = ExitReason.TIME_STOP; break

            exit_time = datetime.fromtimestamp(timestamps[min(exit_bar, n-1)], tz=timezone.utc)
            trade.close(exit_price, exit_time, exit_reason, fees=pos_size * MAKER_FEE)

            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd
                self._daily_pnl += trade.pnl_usd
                if self._daily_pnl < -(self.initial_capital * DAILY_HALT):
                    self._daily_halted = True

            self._last_exit_bar = exit_bar
            trades.append(trade)
            i = exit_bar + cooldown

        return trades


def run_filter_test(ts, o, h, l, c, v, ic, regime, mask, capital=10_000.0, bh=4.0) -> dict | None:
    bt = ConvergenceBacktester(initial_capital=capital, bar_interval_hours=bh)
    trades = bt.run(ts, o, h, l, c, v, ic, regime, mask)
    if not trades:
        return None
    engine = BacktestEngine(initial_capital=capital)
    engine.add_trades(trades)
    s = engine.compute_stats(venue=VENUE)
    return {
        "n": s.n_trades, "wr": round(s.win_rate, 4),
        "pf": round(s.profit_factor, 4), "sharpe": round(s.sharpe_ratio, 4),
        "dd": round(s.max_drawdown_pct, 4), "pnl_pct": round(s.total_pnl_pct, 4),
        "p": round(s.p_value, 4), "exp_r": round(s.expectancy_r, 4),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("MULTI-INDICATOR CONVERGENCE ANALYSIS")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 72)

    # Load data
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    sol_df = load_binance("SOL/USDT", 240)
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)

    # Build regime
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)

    # Pre-compute all indicators once
    print("\nPre-computing indicators...")
    ic = IndicatorCache(o, h, l, c, v)
    print(f"Done. {n} bars, {np.sum(ic.tk_signals == 1)} raw TK-cross signals")

    # Walk-forward split
    SPLIT = int(n * 0.70)
    print(f"Train: bars 0-{SPLIT-1} ({datetime.fromtimestamp(ts[0], tz=timezone.utc).date()} -> {datetime.fromtimestamp(ts[SPLIT-1], tz=timezone.utc).date()})")
    print(f"Test:  bars {SPLIT}-{n-1} ({datetime.fromtimestamp(ts[SPLIT], tz=timezone.utc).date()} -> {datetime.fromtimestamp(ts[-1], tz=timezone.utc).date()})")

    # Baseline (no additional filter)
    baseline_mask = np.ones(n, dtype=bool)
    baseline_all = run_filter_test(ts, o, h, l, c, v, ic, regime, baseline_mask)
    baseline_train = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                                     c[:SPLIT], v[:SPLIT],
                                     IndicatorCache(o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT]),
                                     regime[:SPLIT], baseline_mask[:SPLIT])
    baseline_test = run_filter_test(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                                    c[SPLIT:], v[SPLIT:],
                                    IndicatorCache(o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:]),
                                    regime[SPLIT:], baseline_mask[SPLIT:])

    print(f"\nBASELINE (Ichimoku TK + above cloud + RSI>50):")
    if baseline_all:
        print(f"  Full:  n={baseline_all['n']:3d} WR={baseline_all['wr']:.1%} PF={baseline_all['pf']:.3f} Sh={baseline_all['sharpe']:+.3f} p={baseline_all['p']:.3f}")
    if baseline_train:
        star = "*" if baseline_train["p"] < 0.10 else ""
        print(f"  Train: n={baseline_train['n']:3d} WR={baseline_train['wr']:.1%} PF={baseline_train['pf']:.3f} Sh={baseline_train['sharpe']:+.3f} p={baseline_train['p']:.3f}{star}")
    if baseline_test:
        star = "*" if baseline_test["p"] < 0.10 else ""
        print(f"  Test:  n={baseline_test['n']:3d} WR={baseline_test['wr']:.1%} PF={baseline_test['pf']:.3f} Sh={baseline_test['sharpe']:+.3f} p={baseline_test['p']:.3f}{star}")

    # Build all filters on full series for pre-selection
    print("\n" + "=" * 72)
    print("SINGLE FILTER ADD-ON TEST (Train period, sorted by PF)")
    print("=" * 72)
    print(f"  {'Filter':<18} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'p':>7}  vs baseline")
    print(f"  {'-'*18} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*7}  -----------")

    all_filters = build_filters(IndicatorCache(o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT]))
    filter_results = {}
    base_pf = baseline_train["pf"] if baseline_train else 1.0
    base_n  = baseline_train["n"]  if baseline_train else 0

    for fname, fmask in all_filters.items():
        r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            IndicatorCache(o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT]),
                            regime[:SPLIT], fmask)
        if r and r["n"] >= 5:  # need at least 5 trades to count
            star = "*" if r["p"] < 0.10 else " "
            delta_pf = r["pf"] - base_pf
            delta_n  = r["n"] - base_n
            print(f"  {fname:<18} {r['n']:>4} {r['wr']:>5.1%} {r['pf']:>7.3f} {r['sharpe']:>7.3f} {r['p']:>7.3f}{star}  PF{delta_pf:+.3f} n{delta_n:+d}")
            filter_results[fname] = r
        elif r:
            print(f"  {fname:<18} {r['n']:>4} (too few trades)")

    # Sort and rank
    ranked = sorted(filter_results.items(), key=lambda x: x[1]["pf"], reverse=True)

    # Top filters for combo search
    top_filters = [name for name, r in ranked if r["pf"] > base_pf][:10]
    print(f"\nTop {len(top_filters)} filters that improve PF over baseline: {top_filters}")

    # -----------------------------------------------------------------------
    # Combination grid search: pairs and triples from top filters
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("COMBINATION SEARCH (Train, pairs from top filters)")
    print("=" * 72)

    combo_results = {}

    # Test all pairs
    print(f"  {'Filters':<35} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'p':>7}")
    print(f"  {'-'*35} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*7}")

    ic_train = IndicatorCache(o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT])
    all_filters_train = build_filters(ic_train)

    for f1, f2 in combinations(top_filters, 2):
        combo_mask = all_filters_train[f1] & all_filters_train[f2]
        r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            ic_train, regime[:SPLIT], combo_mask)
        if r and r["n"] >= 5:
            combo_key = f"{f1}+{f2}"
            combo_results[combo_key] = r
            star = "*" if r["p"] < 0.10 else " "
            print(f"  {combo_key:<35} {r['n']:>4} {r['wr']:>5.1%} {r['pf']:>7.3f} {r['sharpe']:>7.3f} {r['p']:>7.3f}{star}")

    # Best combos
    top_combos = sorted(combo_results.items(), key=lambda x: x[1]["pf"] * (1 - x[1]["p"]), reverse=True)[:5]

    # Test triples for top-3 pairs
    print("\n--- Triples (from best pairs + each remaining top filter) ---")
    top_combo_filters = []
    seen = set()
    for name, _ in top_combos[:3]:
        for f in name.split("+"):
            if f not in seen:
                top_combo_filters.append(f)
                seen.add(f)

    for f1, f2, f3 in combinations(top_combo_filters[:6], 3):
        if f1 not in top_filters or f2 not in top_filters or f3 not in top_filters:
            continue
        combo_mask = all_filters_train[f1] & all_filters_train[f2] & all_filters_train[f3]
        r = run_filter_test(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT], c[:SPLIT], v[:SPLIT],
                            ic_train, regime[:SPLIT], combo_mask)
        if r and r["n"] >= 5:
            combo_key = f"{f1}+{f2}+{f3}"
            combo_results[combo_key] = r
            star = "*" if r["p"] < 0.10 else " "
            print(f"  {combo_key:<35} {r['n']:>4} {r['wr']:>5.1%} {r['pf']:>7.3f} {r['sharpe']:>7.3f} {r['p']:>7.3f}{star}")

    # -----------------------------------------------------------------------
    # Walk-forward validation of top 5 combinations
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("WALK-FORWARD VALIDATION (top candidates, Train -> Test)")
    print("=" * 72)

    all_combos_sorted = sorted(combo_results.items(), key=lambda x: x[1]["pf"] * (1 - x[1]["p"]), reverse=True)

    ic_test = IndicatorCache(o[SPLIT:], h[SPLIT:], l[SPLIT:], c[SPLIT:], v[SPLIT:])
    all_filters_test = build_filters(ic_test)

    wf_results = []
    print(f"  {'Combo':<35} {'Phase':<7} {'n':>4} {'WR':>6} {'PF':>7} {'Sh':>7} {'p':>7}")
    print(f"  {'-'*35} {'-'*7} {'-'*4} {'-'*6} {'-'*7} {'-'*7} {'-'*7}")

    for combo_key, train_r in all_combos_sorted[:8]:
        filters_in_combo = combo_key.split("+")

        # Train result already computed
        t_star = "*" if train_r["p"] < 0.10 else " "
        print(f"  {combo_key:<35} {'TRAIN':<7} {train_r['n']:>4} {train_r['wr']:>5.1%} "
              f"{train_r['pf']:>7.3f} {train_r['sharpe']:>7.3f} {train_r['p']:>7.3f}{t_star}")

        # Test result
        try:
            combo_mask_test = np.ones(len(ts[SPLIT:]), dtype=bool)
            for f in filters_in_combo:
                if f in all_filters_test:
                    combo_mask_test &= all_filters_test[f]

            test_r = run_filter_test(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                                     c[SPLIT:], v[SPLIT:],
                                     ic_test, regime[SPLIT:], combo_mask_test)
            if test_r:
                oos_star = "*" if test_r["p"] < 0.10 else " "
                hold = "+" if test_r["pf"] >= train_r["pf"] * 0.7 else "-"  # OOS within 30% of train
                print(f"  {'':<35} {'TEST':<7} {test_r['n']:>4} {test_r['wr']:>5.1%} "
                      f"{test_r['pf']:>7.3f} {test_r['sharpe']:>7.3f} {test_r['p']:>7.3f}{oos_star} {hold}")
                wf_results.append({
                    "combo": combo_key,
                    "train": train_r,
                    "test": test_r,
                    "oos_holds": test_r["pf"] >= train_r["pf"] * 0.7,
                })
            else:
                print(f"  {'':<35} {'TEST':<7}    0 (no trades)")
        except Exception as e:
            print(f"  {'':<35} TEST error: {e}")

    # -----------------------------------------------------------------------
    # Final ranking and verdict
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("FINAL RANKING — OOS PF > 1.2 AND holds vs train")
    print("=" * 72)

    winners = [r for r in wf_results
               if r["test"]["pf"] > 1.2
               and r["oos_holds"]
               and r["test"]["n"] >= 5]

    if winners:
        winners_sorted = sorted(winners, key=lambda x: x["test"]["pf"] * x["test"]["sharpe"], reverse=True)
        for w in winners_sorted:
            print(f"\n  WINNER: {w['combo']}")
            print(f"    Train: PF={w['train']['pf']:.3f} Sh={w['train']['sharpe']:+.3f} "
                  f"WR={w['train']['wr']:.1%} n={w['train']['n']} p={w['train']['p']:.3f}")
            print(f"    Test:  PF={w['test']['pf']:.3f} Sh={w['test']['sharpe']:+.3f} "
                  f"WR={w['test']['wr']:.1%} n={w['test']['n']} p={w['test']['p']:.3f}")
    else:
        print("  No combo passes OOS PF > 1.2 with OOS stability.")
        best_oos = sorted(wf_results, key=lambda x: x["test"]["pf"], reverse=True)[:3]
        print("  Best OOS results:")
        for r in best_oos:
            print(f"    {r['combo']:<35} OOS PF={r['test']['pf']:.3f} Sh={r['test']['sharpe']:+.3f} n={r['test']['n']}")

    # Save
    out = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "baseline_train": baseline_train,
        "baseline_test": baseline_test,
        "filter_results": filter_results,
        "combo_results": {k: v for k, v in list(combo_results.items())},
        "walk_forward": wf_results,
        "winners": [w["combo"] for w in (winners if winners else [])],
    }
    out_path = DATA_DIR / "convergence_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved: {out_path}")
