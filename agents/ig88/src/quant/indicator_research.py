"""
indicator_research.py — Systematic standalone indicator testing.

Each indicator is tested as a PRIMARY entry signal (not a filter on Ichimoku).
This answers: "Which indicators have intrinsic edge on crypto 4h data?"

Methodology:
  - Same walk-forward split as convergence work: 70% train / 30% test
  - Same exit logic throughout: 2× ATR stop, 3× ATR target, Kijun/MA exit
  - Same regime gate: BTC 20-bar trend
  - BTC 4h + SOL 4h + ETH 4h as primary test assets
  - Rank by OOS PF with n >= 5

Indicators tested as primary entries:

MOMENTUM:
  RSI_OB         - RSI crosses above 50 from below (momentum breakout)
  RSI_OS         - RSI < 30 bounce (oversold reversal)
  RSI_BULL       - RSI > 60 + rising (trend following)
  MACD_CROSS     - MACD line crosses above signal line
  MACD_HIST_FLIP - MACD histogram flips from negative to positive
  STOCHRSI_CROSS - StochRSI %K crosses above %D from below 20

TREND:
  SUPERTREND     - Price crosses above SuperTrend line (bullish flip)
  EMA_CROSS      - EMA9 crosses above EMA21
  EMA_STACK      - EMA9 > EMA21 > EMA50 (all aligned bullish)
  KAMA_CROSS     - Price crosses above KAMA from below
  DEMA_CROSS     - DEMA(9) crosses above DEMA(21)
  ADX_TREND      - ADX > 25 AND +DI > -DI AND +DI rising

VOLUME:
  OBV_BREAK      - OBV breaks above its 20-period SMA (accumulation)
  KLINGER_CROSS  - Klinger KVO crosses above signal line
  VOL_SPIKE      - Volume > 2× 20-period average (breakout bar)
  OBV_DIVERGE    - Price makes higher low, OBV makes higher low too (confirmation)

VOLATILITY/BANDS:
  BB_BREAK       - Close breaks above upper Bollinger Band (momentum breakout)
  BB_SQUEEZE     - BB squeeze then expansion above midline (volatility expansion)
  DONCHIAN_BREAK - Close exceeds 20-period Donchian upper (channel breakout)
  KAMA_BANDS     - Price crosses above KAMA upper band

COMPOSITE:
  ICHIMOKU_ALONE - Baseline: TK cross + above cloud (no RSI/score filters)
  MULTI_CONFLU   - Built-in multi_indicator_confluence score > 0.3
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

import src.quant.indicators as ind
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.regime import RegimeState

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE    = "kraken_spot"
MAKER_FEE = 0.0016
ATR_STOP  = 2.0
ATR_TARGET = 3.0
DAILY_HALT = 0.03


# ---------------------------------------------------------------------------
# Universal backtester: signal mask in, trades out
# ---------------------------------------------------------------------------

class SignalBacktester:
    """
    Generic long-only backtester. Entry when signal_mask[i] == True.
    Exit: ATR stop/target or MA-based trend exit.
    Regime-gated via regime_states array.
    """
    def __init__(self, initial_capital=10_000.0, bar_hours=4.0,
                 allow_neutral=True, atr_stop=ATR_STOP, atr_target=ATR_TARGET):
        self.initial_capital = initial_capital
        self.wallet = initial_capital
        self.bar_hours = bar_hours
        self.allow_neutral = allow_neutral
        self.atr_stop = atr_stop
        self.atr_target = atr_target
        self._counter = 0
        self._last_exit = -999
        self._daily_pnl = 0.0
        self._halted = False
        self._day = -1

    def _check_halt(self, i, ts):
        day = int(ts[i] // 86400)
        if day != self._day:
            self._day = day; self._daily_pnl = 0.0; self._halted = False
        return self._halted

    def run(self, ts, o, h, l, c, v, signal_mask, regime, atr_vals,
            exit_ma=None, min_hold=2, cooldown=2) -> list[Trade]:
        """
        ts, o, h, l, c, v: OHLCV arrays
        signal_mask: bool array — True = entry signal on this bar
        regime: RegimeState array
        atr_vals: ATR array (pre-computed)
        exit_ma: optional MA array — exit when close < exit_ma (trend exit)
        """
        n = len(ts)
        min_hold_b = max(1, int(min_hold / max(self.bar_hours, 1)))
        cooldown_b = max(1, int(cooldown / max(self.bar_hours, 1)))
        trades = []
        i = 60  # warmup

        while i < n - min_hold_b - 2:
            if self._check_halt(i, ts): i += 1; continue
            if i - self._last_exit < cooldown_b: i += 1; continue

            state = regime[i]
            if state == RegimeState.RISK_OFF: i += 1; continue
            if state == RegimeState.NEUTRAL and not self.allow_neutral: i += 1; continue

            if not signal_mask[i]: i += 1; continue

            atr_v = atr_vals[i]
            if np.isnan(atr_v) or atr_v <= 0: i += 1; continue

            eb = i + 1
            if eb >= n: break

            ep = o[eb]
            et = datetime.fromtimestamp(ts[eb], tz=timezone.utc)
            pos = self.wallet * 0.02
            if pos < 1.0: i += 1; continue

            stop_p   = ep - self.atr_stop * atr_v
            target_p = ep + self.atr_target * atr_v

            trade = Trade(
                trade_id=f"SIG-{self._counter:05d}", venue=VENUE, strategy="signal_test",
                pair="", entry_timestamp=et, entry_price=ep,
                position_size_usd=pos, regime_state=state,
                side="long", leverage=1.0,
                stop_level=stop_p, target_level=target_p,
                fees_paid=pos * MAKER_FEE,
            )
            self._counter += 1

            xb = eb; xp = ep; xr = ExitReason.TIME_STOP
            for j in range(1, n - eb):
                bar = eb + j
                if bar >= n: break
                if l[bar] <= stop_p:
                    xb = bar; xp = stop_p; xr = ExitReason.STOP_HIT; break
                if h[bar] >= target_p:
                    xb = bar; xp = target_p; xr = ExitReason.TARGET_HIT; break
                if regime[bar] == RegimeState.RISK_OFF and j >= min_hold_b:
                    xb = bar; xp = c[bar]; xr = ExitReason.REGIME_EXIT; break
                if exit_ma is not None and j >= min_hold_b and not np.isnan(exit_ma[bar]):
                    if c[bar] < exit_ma[bar]:
                        xb = bar; xp = c[bar]; xr = ExitReason.TIME_STOP; break

            xt = datetime.fromtimestamp(ts[min(xb, n-1)], tz=timezone.utc)
            trade.close(xp, xt, xr, fees=pos * MAKER_FEE)
            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd
                self._daily_pnl += trade.pnl_usd
                if self._daily_pnl < -(self.initial_capital * DAILY_HALT):
                    self._halted = True

            self._last_exit = xb
            trades.append(trade)
            i = xb + cooldown_b
        return trades


def backtest_signal(ts, o, h, l, c, v, signal_mask, regime, atr_vals,
                    exit_ma=None, capital=10_000.0, bar_hours=4.0) -> dict | None:
    bt = SignalBacktester(initial_capital=capital, bar_hours=bar_hours)
    trades = bt.run(ts, o, h, l, c, v, signal_mask, regime, atr_vals, exit_ma)
    if not trades:
        return None
    eng = BacktestEngine(initial_capital=capital)
    eng.add_trades(trades)
    s = eng.compute_stats(venue=VENUE)
    return {
        "n": s.n_trades, "wr": round(s.win_rate, 4),
        "pf": round(s.profit_factor, 4), "sharpe": round(s.sharpe_ratio, 4),
        "sortino": round(s.sortino_ratio, 4),
        "dd": round(s.max_drawdown_pct, 4),
        "pnl_pct": round(s.total_pnl_pct, 4),
        "exp_r": round(s.expectancy_r, 4),
        "p": round(s.p_value, 4),
        "geo_pos": s.geometric_positive,
    }


# ---------------------------------------------------------------------------
# Signal definitions: each returns (signal_mask, exit_ma)
# ---------------------------------------------------------------------------

def signals_rsi_momentum_cross(c, rsi_period=14):
    """RSI crosses above 50 from below."""
    r = ind.rsi(c, rsi_period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(r[i]) and not np.isnan(r[i-1]):
            mask[i] = r[i] > 50 and r[i-1] <= 50
    return mask, None

def signals_rsi_oversold(c, rsi_period=14, ob_level=30, recover_to=40):
    """RSI was below ob_level, now recovering above recover_to."""
    r = ind.rsi(c, rsi_period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    was_oversold = False
    for i in range(1, n):
        if np.isnan(r[i]): continue
        if r[i] < ob_level: was_oversold = True
        if was_oversold and r[i] > recover_to:
            mask[i] = True
            was_oversold = False
    return mask, None

def signals_rsi_bull_trend(c, rsi_period=14, threshold=60):
    """RSI > threshold AND rising."""
    r = ind.rsi(c, rsi_period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(r[i]) and not np.isnan(r[i-1]):
            mask[i] = r[i] > threshold and r[i] > r[i-1]
    return mask, None

def signals_macd_cross(c):
    """MACD line crosses above signal line."""
    m = ind.macd(c)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(m.macd_line[i]) and not np.isnan(m.signal_line[i]):
            prev_below = m.macd_line[i-1] <= m.signal_line[i-1]
            curr_above = m.macd_line[i]  >  m.signal_line[i]
            mask[i] = prev_below and curr_above
    ema26 = ind.ema(c, 26)
    return mask, ema26

def signals_macd_hist_flip(c):
    """MACD histogram flips from negative to positive."""
    m = ind.macd(c)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(m.histogram[i]) and not np.isnan(m.histogram[i-1]):
            mask[i] = m.histogram[i] > 0 and m.histogram[i-1] <= 0
    ema26 = ind.ema(c, 26)
    return mask, ema26

def signals_stochrsi_cross(c):
    """StochRSI %K crosses above %D from below 30."""
    k, d = ind.stoch_rsi(c)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(k[i]) and not np.isnan(d[i]) and not np.isnan(k[i-1]):
            # %K crosses above %D AND was below 30
            mask[i] = (k[i] > d[i] and k[i-1] <= d[i-1] and k[i-1] < 30)
    return mask, None

def signals_supertrend(h, l, c):
    """Price crosses above SuperTrend (direction flips to bullish)."""
    st, direction = ind.supertrend(h, l, c, period=10, multiplier=3.0)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        mask[i] = direction[i] > 0 and direction[i-1] <= 0
    return mask, st

def signals_ema_cross(c, fast=9, slow=21):
    """Fast EMA crosses above slow EMA."""
    e_fast = ind.ema(c, fast)
    e_slow = ind.ema(c, slow)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(e_fast[i]) and not np.isnan(e_slow[i]):
            mask[i] = e_fast[i] > e_slow[i] and e_fast[i-1] <= e_slow[i-1]
    return mask, e_slow

def signals_ema_stack(c, p1=9, p2=21, p3=50):
    """All three EMAs aligned bullish (EMA9 > EMA21 > EMA50) on this bar but not the prior."""
    e1 = ind.ema(c, p1); e2 = ind.ema(c, p2); e3 = ind.ema(c, p3)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if any(np.isnan(x) for x in [e1[i], e2[i], e3[i], e1[i-1], e2[i-1], e3[i-1]]):
            continue
        now_stack  = e1[i]   > e2[i]   > e3[i]
        prev_stack = e1[i-1] > e2[i-1] > e3[i-1]
        mask[i] = now_stack and not prev_stack  # fresh stack alignment
    return mask, e2

def signals_kama_cross(c):
    """Price crosses above KAMA from below."""
    k = ind.kama(c, period=6)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(k[i]) and not np.isnan(k[i-1]):
            mask[i] = c[i] > k[i] and c[i-1] <= k[i-1]
    return mask, k

def signals_dema_cross(c, fast=9, slow=21):
    """Fast DEMA crosses above slow DEMA."""
    d_fast = ind.dema(c, fast)
    d_slow = ind.dema(c, slow)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(d_fast[i]) and not np.isnan(d_slow[i]):
            mask[i] = d_fast[i] > d_slow[i] and d_fast[i-1] <= d_slow[i-1]
    return mask, d_slow

def signals_adx_trend(h, l, c, adx_thresh=25):
    """ADX > threshold AND +DI crosses above -DI."""
    a = ind.adx(h, l, c, period=14)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if any(np.isnan(x) for x in [a.adx[i], a.plus_di[i], a.minus_di[i],
                                       a.plus_di[i-1], a.minus_di[i-1]]):
            continue
        di_cross = a.plus_di[i] > a.minus_di[i] and a.plus_di[i-1] <= a.minus_di[i-1]
        mask[i] = di_cross and a.adx[i] > adx_thresh
    ema21 = ind.ema(c, 21)
    return mask, ema21

def signals_obv_break(c, v):
    """OBV crosses above its 20-period SMA."""
    o_vals = ind.obv(c, v)
    o_sma  = ind.sma(o_vals, 20)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(o_sma[i]) and not np.isnan(o_sma[i-1]):
            mask[i] = o_vals[i] > o_sma[i] and o_vals[i-1] <= o_sma[i-1]
    return mask, None

def signals_klinger_cross(h, l, c, v):
    """Klinger KVO crosses above signal line."""
    kr = ind.klinger(h, l, c, v)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(kr.kvo[i]) and not np.isnan(kr.signal[i]):
            mask[i] = kr.kvo[i] > kr.signal[i] and kr.kvo[i-1] <= kr.signal[i-1]
    return mask, None

def signals_vol_spike_break(c, v, vol_mult=2.0, price_thresh=0.005):
    """Volume spike (> vol_mult × 20MA) on a positive-close bar (> 0.5% gain)."""
    vol_ma = ind.sma(v, 20)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(vol_ma[i]) or vol_ma[i] <= 0: continue
        vol_ok = v[i] > vol_mult * vol_ma[i]
        price_ok = (c[i] - c[i-1]) / c[i-1] > price_thresh
        mask[i] = vol_ok and price_ok
    return mask, None

def signals_bb_breakout(c, period=20, mult=2.0):
    """Close breaks above upper Bollinger Band."""
    bb = ind.bollinger_bands(c, period=period, mult=mult)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(bb.upper[i]):
            mask[i] = c[i] > bb.upper[i] and c[i-1] <= bb.upper[i-1]
    return mask, bb.middle

def signals_bb_squeeze_expansion(c, period=20, mult=2.0, squeeze_pct=0.03, lookback=10):
    """
    Bollinger squeeze then expansion: bandwidth was < squeeze_pct for lookback bars,
    now expanding and price above midline.
    """
    bb = ind.bollinger_bands(c, period=period, mult=mult)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(lookback + 1, n):
        if np.isnan(bb.bandwidth[i]) or np.isnan(bb.middle[i]): continue
        # Was in squeeze for lookback bars
        squeeze_window = bb.bandwidth[i-lookback:i]
        valid_bw = squeeze_window[~np.isnan(squeeze_window)]
        if len(valid_bw) == 0: continue
        was_squeezed = np.all(valid_bw < squeeze_pct)
        now_expanding = bb.bandwidth[i] > bb.bandwidth[i-1]
        above_mid = c[i] > bb.middle[i]
        mask[i] = was_squeezed and now_expanding and above_mid
    return mask, bb.middle

def signals_donchian_break(h, l, c, period=20):
    """Close exceeds prior period's Donchian upper channel."""
    upper, lower, mid = ind.donchian_channel(h, l, period=period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(upper[i-1]):
            mask[i] = c[i] > upper[i-1]  # close exceeds yesterday's upper
    return mask, mid

def signals_kama_bands_break(h, l, c):
    """Price crosses above KAMA upper band."""
    basis, upper, lower = ind.kama_bands(h, l, c)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(upper[i]) and not np.isnan(upper[i-1]):
            mask[i] = c[i] > upper[i] and c[i-1] <= upper[i-1]
    return mask, basis

def signals_ichimoku_base(h, l, c):
    """Baseline Ichimoku: TK cross above cloud (no RSI/score)."""
    ichi = ind.ichimoku(h, l, c)
    tk   = ichi.tk_cross_signals()
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(n):
        cloud_top = max(
            ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
            ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
        )
        mask[i] = tk[i] == 1 and c[i] > cloud_top
    return mask, ichi.kijun_sen

def signals_multi_confluence(h, l, c, v, threshold=0.3):
    """Built-in multi_indicator_confluence score > threshold."""
    score = ind.multi_indicator_confluence(c, h, l, v)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(score[i]) and not np.isnan(score[i-1]):
            # Cross above threshold
            mask[i] = score[i] > threshold and score[i-1] <= threshold
    return mask, None

def signals_ichimoku_h3a(h, l, c):
    """H3-A: TK cross + above cloud + RSI>55 + ichi_score>=3."""
    ichi  = ind.ichimoku(h, l, c)
    score = ind.ichimoku_composite_score(ichi, c)
    rsi_v = ind.rsi(c, 14)
    tk    = ichi.tk_cross_signals()
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(n):
        cloud_top = max(
            ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
            ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
        )
        mask[i] = (tk[i] == 1 and c[i] > cloud_top
                   and not np.isnan(rsi_v[i]) and rsi_v[i] > 55
                   and score[i] >= 3)
    return mask, ichi.kijun_sen


def signals_cci_breakout(h, l, c, period=20, threshold=100):
    """CCI crosses above +100 (breakout) or below -100 (breakdown)."""
    cci_vals = ind.cci(h, l, c, period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(cci_vals[i]) and not np.isnan(cci_vals[i-1]):
            # Breakout above threshold
            mask[i] = cci_vals[i] > threshold and cci_vals[i-1] <= threshold
    return mask, None


def signals_williams_bounce(h, l, c, period=14, oversold=-80, overbought=-20):
    """Williams %R bounces up from oversold (crosses above -80 from below)."""
    wr = ind.williams_r(h, l, c, period)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(wr[i]) and not np.isnan(wr[i-1]):
            # Cross above oversold level
            mask[i] = wr[i] > oversold and wr[i-1] <= oversold
    return mask, None


def signals_vwap_position(c, v, threshold=0.5):
    """Price crosses above VWAP by threshold percentage."""
    vwap_pos = ind.vwap_position(c, v)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(vwap_pos[i]) and not np.isnan(vwap_pos[i-1]):
            # Cross above threshold
            mask[i] = vwap_pos[i] > threshold and vwap_pos[i-1] <= threshold
    return mask, None


def signals_tema_cross(c, fast=9, slow=21):
    """Fast TEMA crosses above slow TEMA."""
    t_fast = ind.tema(c, fast)
    t_slow = ind.tema(c, slow)
    n = len(c)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(t_fast[i]) and not np.isnan(t_slow[i]):
            mask[i] = t_fast[i] > t_slow[i] and t_fast[i-1] <= t_slow[i-1]
    return mask, t_slow


def signals_aroon_crossover(h, l, period=25):
    """Aroon Up crosses above Aroon Down (bullish crossover)."""
    aroon_result = ind.aroon(h, l, period)
    n = len(h)
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if not np.isnan(aroon_result.aroon_up[i]) and not np.isnan(aroon_result.aroon_down[i]):
            mask[i] = (aroon_result.aroon_up[i] > aroon_result.aroon_down[i] and 
                      aroon_result.aroon_up[i-1] <= aroon_result.aroon_down[i-1])
    return mask, None


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------

def build_all_signals(o, h, l, c, v) -> dict[str, tuple]:
    """Build all signal masks for a price series. Returns {name: (mask, exit_ma)}."""
    signals = {}
    signals["rsi_momentum_cross"]   = signals_rsi_momentum_cross(c)
    signals["rsi_oversold_bounce"]  = signals_rsi_oversold(c)
    signals["rsi_bull_trend"]       = signals_rsi_bull_trend(c)
    signals["macd_line_cross"]      = signals_macd_cross(c)
    signals["macd_hist_flip"]       = signals_macd_hist_flip(c)
    signals["stochrsi_cross"]       = signals_stochrsi_cross(c)
    signals["supertrend_flip"]      = signals_supertrend(h, l, c)
    signals["ema9_21_cross"]        = signals_ema_cross(c, 9, 21)
    signals["ema21_50_cross"]       = signals_ema_cross(c, 21, 50)
    signals["ema_stack_9_21_50"]    = signals_ema_stack(c, 9, 21, 50)
    signals["kama_cross"]           = signals_kama_cross(c)
    signals["dema_9_21_cross"]      = signals_dema_cross(c, 9, 21)
    signals["adx_di_cross"]         = signals_adx_trend(h, l, c)
    signals["obv_sma_cross"]        = signals_obv_break(c, v)
    signals["klinger_cross"]        = signals_klinger_cross(h, l, c, v)
    signals["vol_spike_breakout"]   = signals_vol_spike_break(c, v)
    signals["bb_upper_break"]       = signals_bb_breakout(c)
    signals["bb_squeeze_expand"]    = signals_bb_squeeze_expansion(c)
    signals["donchian_break"]       = signals_donchian_break(h, l, c)
    signals["kama_bands_break"]     = signals_kama_bands_break(h, l, c)
    signals["ichimoku_base"]        = signals_ichimoku_base(h, l, c)
    signals["multi_confluence"]     = signals_multi_confluence(h, l, c, v)
    signals["ichimoku_h3a"]         = signals_ichimoku_h3a(h, l, c)
    # New indicators for expansion research
    signals["cci_breakout"]         = signals_cci_breakout(h, l, c)
    signals["williams_bounce"]      = signals_williams_bounce(h, l, c)
    signals["vwap_position"]        = signals_vwap_position(c, v)
    signals["tema_9_21_cross"]      = signals_tema_cross(c, 9, 21)
    signals["aroon_crossover"]      = signals_aroon_crossover(h, l)
    return signals


def run_asset(symbol: str, interval_min: int, bar_hours: float,
              btc_ts, btc_c, capital=10_000.0) -> dict:
    """Run all signals on one asset. Returns dict of signal_name -> {train, test}."""
    try:
        df = load_binance(symbol, interval_min)
    except FileNotFoundError:
        print(f"  [skip] {symbol} {interval_min}m — no data")
        return {}

    ts, o, h, l, c, v = df_to_arrays(df)
    n = len(ts)
    SPLIT = int(n * 0.70)
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    atr_all = ind.atr(h, l, c, 14)

    results = {}
    print(f"\n  {symbol} {interval_min}m  ({n} bars, split={SPLIT})")
    print(f"  {'Signal':<25} {'Tr-n':>5} {'Tr-PF':>7} {'Tr-p':>7}  {'Te-n':>5} {'Te-PF':>7} {'Te-p':>7}  {'OOS':>5}")
    print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*7}  {'-'*5} {'-'*7} {'-'*7}  {'-'*5}")

    # Build signals on full series (consistent indicators)
    all_sig = build_all_signals(o, h, l, c, v)

    for sig_name, (mask, exit_ma) in all_sig.items():
        tr_exit = exit_ma[:SPLIT] if exit_ma is not None else None
        te_exit = exit_ma[SPLIT:] if exit_ma is not None else None

        tr = backtest_signal(ts[:SPLIT], o[:SPLIT], h[:SPLIT], l[:SPLIT],
                             c[:SPLIT], v[:SPLIT],
                             mask[:SPLIT], regime[:SPLIT], atr_all[:SPLIT],
                             tr_exit, capital, bar_hours)
        te = backtest_signal(ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                             c[SPLIT:], v[SPLIT:],
                             mask[SPLIT:], regime[SPLIT:], atr_all[SPLIT:],
                             te_exit, capital, bar_hours)

        oos_label = ""
        if tr and te and te["n"] >= 5:
            if te["pf"] > 1.5: oos_label = "STRONG"
            elif te["pf"] > 1.2: oos_label = "pass"
            elif te["pf"] < 0.8: oos_label = "fail"

        tr_str = f"{tr['n']:5d} {tr['pf']:7.3f} {tr['p']:7.3f}" if tr else "    0       -       -"
        te_str = f"{te['n']:5d} {te['pf']:7.3f} {te['p']:7.3f}" if te else "    0       -       -"
        star_t = "*" if (tr and tr["p"] < 0.10) else " "
        star_e = "*" if (te and te["p"] < 0.10) else " "

        print(f"  {sig_name:<25} {tr_str}{star_t}  {te_str}{star_e}  {oos_label}")
        results[sig_name] = {"train": tr, "test": te}

    return results


if __name__ == "__main__":
    print("=" * 80)
    print("STANDALONE INDICATOR RESEARCH — Full spectrum test")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    test_assets = [
        ("SOL/USDT", 240,  4.0),
        ("ETH/USDT", 240,  4.0),
        ("BTC/USD",  240,  4.0),
        ("BTC/USD",  1440, 24.0),
        ("ETH/USDT", 1440, 24.0),
    ]

    all_asset_results = {}
    for symbol, interval_min, bar_hours in test_assets:
        label = f"{symbol}_{interval_min}m"
        results = run_asset(symbol, interval_min, bar_hours, btc_ts, btc_c)
        all_asset_results[label] = results

    # -----------------------------------------------------------------------
    # Leaderboard: OOS PF averaged across all assets where n >= 5
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("LEADERBOARD — Average OOS PF (assets with n>=5)")
    print("=" * 80)

    sig_names = list(next(iter(all_asset_results.values())).keys())
    leaderboard = []

    for sig_name in sig_names:
        oos_pfs = []
        pass_count = 0
        for asset_label, asset_results in all_asset_results.items():
            r = asset_results.get(sig_name, {})
            te = r.get("test")
            if te and te["n"] >= 5:
                oos_pfs.append(te["pf"])
                if te["pf"] > 1.2:
                    pass_count += 1

        if oos_pfs:
            avg_pf = np.mean(oos_pfs)
            leaderboard.append({
                "signal": sig_name,
                "avg_oos_pf": round(avg_pf, 3),
                "n_assets_tested": len(oos_pfs),
                "n_assets_pass": pass_count,
                "oos_pfs": {
                    label: (all_asset_results[label].get(sig_name) or {}).get("test", {}) and
                           (all_asset_results[label].get(sig_name) or {}).get("test", {}).get("pf")
                    for label in all_asset_results
                },
            })

    leaderboard.sort(key=lambda x: x["avg_oos_pf"], reverse=True)

    print(f"\n  {'Signal':<25} {'Avg OOS PF':>12} {'Pass':>6} {'SOL4h':>7} {'ETH4h':>7} {'BTC4h':>7} {'BTC1d':>7} {'ETH1d':>7}")
    print(f"  {'-'*25} {'-'*12} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
    for row in leaderboard:
        pfs = row["oos_pfs"]
        def fmt(k):
            v = pfs.get(k)
            return f"{v:7.3f}" if v is not None else "    n/a"
        print(f"  {row['signal']:<25} {row['avg_oos_pf']:>12.3f} "
              f"{row['n_assets_pass']:>3}/{row['n_assets_tested']:<3}"
              f"{fmt('SOL/USDT_240m')}{fmt('ETH/USDT_240m')}"
              f"{fmt('BTC/USD_240m')}{fmt('BTC/USD_1440m')}{fmt('ETH/USDT_1440m')}")

    print(f"\nTop 5 by avg OOS PF:")
    for row in leaderboard[:5]:
        print(f"  {row['signal']:<25} avg_pf={row['avg_oos_pf']:.3f}  "
              f"pass={row['n_assets_pass']}/{row['n_assets_tested']}")

    # Save
    out_path = DATA_DIR / "indicator_research_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at": datetime.now(timezone.utc).isoformat(),
            "leaderboard": leaderboard,
            "all_results": {
                asset: {
                    sig: {"train": r.get("train"), "test": r.get("test")}
                    for sig, r in results.items()
                }
                for asset, results in all_asset_results.items()
            }
        }, f, indent=2)
    print(f"\nFull results saved: {out_path}")
