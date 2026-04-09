"""
ichimoku_backtest.py — Ichimoku Cloud momentum strategy backtester.

Regime: macro-derived (BTC trend direction, not price-SMA).
Entry signal: Ichimoku TK cross above cloud (bullish), RSI confirmation.
Exit: price drops below cloud, or ATR stop/target hit.

This replaces the price-SMA proxy with a proper technical signal, decoupled
from the regime filter to avoid the circular dependency in RegimeMomentumBacktester.

Ichimoku components:
  Tenkan-sen (T): (9-period high + 9-period low) / 2  — conversion line
  Kijun-sen  (K): (26-period high + 26-period low) / 2 — base line
  Senkou A (SA):  (T + K) / 2, plotted 26 bars ahead
  Senkou B (SB):  (52-period high + 52-period low) / 2, plotted 26 bars ahead
  Chikou (C):     Close shifted 26 bars back

Entry conditions (all must hold):
  1. T crosses above K (TK bullish cross)
  2. Close is above the cloud (above both SA and SB, looking at cloud 26 bars back)
  3. RSI > 50 (momentum confirmation)
  4. Regime is RISK_ON or NEUTRAL (not RISK_OFF)

Exit conditions (first hit):
  1. Close drops below Kijun-sen (trend weakening)
  2. ATR stop (2.0x ATR below entry)
  3. ATR target (3.0x ATR above entry)

Venue: Kraken spot (no leverage, long-only)
Fees: 0.16% maker (limit orders)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np
import pandas as pd

from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade, TradeOutcome
from src.quant.regime import RegimeState

VENUE        = "kraken_spot"
MAKER_FEE    = 0.0016   # 0.16%
ATR_STOP     = 2.0
ATR_TARGET   = 3.0
MIN_HOLD     = 2        # bars
COOLDOWN     = 2        # bars
DAILY_HALT   = 0.03     # 3% daily loss


# ---------------------------------------------------------------------------
# Ichimoku computation
# ---------------------------------------------------------------------------

def ichimoku(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
             t_period: int = 9, k_period: int = 26, s_period: int = 52,
             displacement: int = 26
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute Ichimoku Cloud components.
    Returns (tenkan, kijun, senkou_a, senkou_b, chikou).
    All arrays are same length as input; future-dated values (SA, SB) are
    stored at the current bar for comparison purposes (not projected forward).
    """
    n = len(closes)
    tenkan  = np.full(n, np.nan)
    kijun   = np.full(n, np.nan)
    senkou_a = np.full(n, np.nan)
    senkou_b = np.full(n, np.nan)
    chikou  = np.full(n, np.nan)

    for i in range(n):
        # Tenkan-sen
        if i >= t_period - 1:
            tenkan[i] = (np.max(highs[i - t_period + 1:i + 1]) +
                         np.min(lows[i - t_period + 1:i + 1])) / 2

        # Kijun-sen
        if i >= k_period - 1:
            kijun[i] = (np.max(highs[i - k_period + 1:i + 1]) +
                        np.min(lows[i - k_period + 1:i + 1])) / 2

        # Senkou B (52-period)
        if i >= s_period - 1:
            senkou_b[i] = (np.max(highs[i - s_period + 1:i + 1]) +
                           np.min(lows[i - s_period + 1:i + 1])) / 2

        # Chikou: current close reflected 26 bars back
        back = i - displacement
        if back >= 0:
            chikou[back] = closes[i]

    # Senkou A: average of tenkan and kijun
    for i in range(n):
        if not np.isnan(tenkan[i]) and not np.isnan(kijun[i]):
            senkou_a[i] = (tenkan[i] + kijun[i]) / 2

    return tenkan, kijun, senkou_a, senkou_b, chikou


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
        period: int = 14) -> np.ndarray:
    n = len(highs)
    tr = np.empty(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    result = np.full(n, np.nan)
    if n >= period:
        result[period - 1] = np.mean(tr[:period])
        alpha = 1.0 / period
        for i in range(period, n):
            result[i] = result[i - 1] * (1 - alpha) + tr[i] * alpha
    return result


def rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result
    deltas = np.diff(closes)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_g  = np.mean(gains[:period])
    avg_l  = np.mean(losses[:period])
    result[period] = 100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period, len(deltas)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        result[i + 1] = 100 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return result


# ---------------------------------------------------------------------------
# Macro-derived regime series from BTC trend
# ---------------------------------------------------------------------------

def build_btc_trend_regime(
    btc_closes: np.ndarray,
    asset_timestamps: np.ndarray,
    btc_timestamps: np.ndarray,
    trend_period: int = 20,
    bull_threshold: float = 0.05,
    bear_threshold: float = -0.05,
) -> np.ndarray:
    """
    Build regime series for an asset based on BTC's trend.
    Uses rolling 20-bar return on BTC daily to classify regime.
    Aligns timestamps for non-BTC assets.

    bull_threshold: BTC must be up > 5% over trend_period to be RISK_ON
    bear_threshold: BTC down > 5% -> RISK_OFF
    """
    n = len(asset_timestamps)
    regime = np.full(n, RegimeState.NEUTRAL, dtype=object)

    # Pre-compute BTC regime at each BTC bar
    n_btc = len(btc_closes)
    btc_regime = np.full(n_btc, RegimeState.NEUTRAL, dtype=object)
    for i in range(trend_period, n_btc):
        ret = (btc_closes[i] - btc_closes[i - trend_period]) / btc_closes[i - trend_period]
        if ret > bull_threshold:
            btc_regime[i] = RegimeState.RISK_ON
        elif ret < bear_threshold:
            btc_regime[i] = RegimeState.RISK_OFF

    # Map BTC regime to asset timestamps (forward-fill nearest BTC bar)
    btc_ts_arr = np.array(btc_timestamps)
    for j, ts in enumerate(asset_timestamps):
        # Find nearest BTC bar <= ts
        idx = np.searchsorted(btc_ts_arr, ts, side="right") - 1
        if idx >= 0 and idx < n_btc:
            regime[j] = btc_regime[idx]

    return regime


# ---------------------------------------------------------------------------
# Ichimoku backtester
# ---------------------------------------------------------------------------

class IchimokuBacktester:
    """
    Ichimoku Cloud + RSI entry, BTC trend regime filter, ATR stop/target exit.
    Long-only, Kraken spot fees.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        bar_interval_hours: float = 24.0,
        t_period: int = 9,
        k_period: int = 26,
        s_period: int = 52,
        rsi_period: int = 14,
        rsi_threshold: float = 50.0,
        atr_period: int = 14,
        atr_stop_mult: float = ATR_STOP,
        atr_target_mult: float = ATR_TARGET,
        allow_neutral_regime: bool = True,   # True: trade in NEUTRAL; False: RISK_ON only
    ):
        self.initial_capital     = initial_capital
        self.wallet              = initial_capital
        self.bar_interval_hours  = bar_interval_hours
        self.t_period            = t_period
        self.k_period            = k_period
        self.s_period            = s_period
        self.rsi_period          = rsi_period
        self.rsi_threshold       = rsi_threshold
        self.atr_period          = atr_period
        self.atr_stop_mult       = atr_stop_mult
        self.atr_target_mult     = atr_target_mult
        self.allow_neutral_regime = allow_neutral_regime

        self._trade_counter = 0
        self._last_exit_bar = -999
        self._daily_pnl     = 0.0
        self._daily_halted  = False
        self._current_day   = -1

    def _next_id(self) -> str:
        self._trade_counter += 1
        return f"ICH-{self._trade_counter:05d}"

    def _check_daily_halt(self, i: int, timestamps: np.ndarray) -> bool:
        day = int(timestamps[i] // 86400)
        if day != self._current_day:
            self._current_day = day
            self._daily_pnl = 0.0
            self._daily_halted = False
        return self._daily_halted

    def _allowed_regime(self, state) -> bool:
        if state == RegimeState.RISK_OFF:
            return False
        if state == RegimeState.NEUTRAL and not self.allow_neutral_regime:
            return False
        return True

    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        regime_states: np.ndarray | None = None,
        pair: str = "BTC/USD",
    ) -> list[Trade]:
        n = len(timestamps)
        warmup = self.s_period + self.k_period + 5

        if regime_states is None:
            regime_states = np.full(n, RegimeState.NEUTRAL, dtype=object)

        # Compute indicators
        T, K, SA, SB, C = ichimoku(highs, lows, closes,
                                    self.t_period, self.k_period, self.s_period)
        atr_vals = atr(highs, lows, closes, self.atr_period)
        rsi_vals  = rsi(closes, self.rsi_period)

        min_hold = max(1, int(MIN_HOLD / max(self.bar_interval_hours, 1)))
        cooldown  = max(1, int(COOLDOWN / max(self.bar_interval_hours, 1)))

        trades: list[Trade] = []
        i = warmup

        while i < n - min_hold - 2:
            # Halt checks
            if self._check_daily_halt(i, timestamps):
                i += 1; continue
            if i - self._last_exit_bar < cooldown:
                i += 1; continue
            if not self._allowed_regime(regime_states[i]):
                i += 1; continue

            # All indicators must be valid
            if any(np.isnan(x) for x in [T[i], T[i-1], K[i], K[i-1],
                                           SA[i], SB[i], atr_vals[i], rsi_vals[i]]):
                i += 1; continue

            # === Entry signal ===
            # 1. TK cross: T crosses above K
            tk_cross = (T[i] > K[i]) and (T[i - 1] <= K[i - 1])

            # 2. Price above cloud (both SA and SB from current bar)
            cloud_top = max(SA[i], SB[i])
            above_cloud = closes[i] > cloud_top

            # 3. RSI confirmation
            rsi_ok = rsi_vals[i] > self.rsi_threshold

            if not (tk_cross and above_cloud and rsi_ok):
                i += 1; continue

            # Entry next bar open
            entry_bar = i + 1
            if entry_bar >= n:
                break

            entry_price = opens[entry_bar]
            entry_time  = datetime.fromtimestamp(timestamps[entry_bar], tz=timezone.utc)
            pos_size    = self.wallet * 0.02  # 2% of wallet per trade (fixed fraction, no Kelly bootstrap)
            if pos_size < 1.0:
                i += 1; continue

            entry_fee = pos_size * MAKER_FEE
            stop_p    = entry_price - self.atr_stop_mult * atr_vals[i]
            target_p  = entry_price + self.atr_target_mult * atr_vals[i]

            trade = Trade(
                trade_id=self._next_id(),
                venue=VENUE,
                strategy="ichimoku_cloud",
                pair=pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side="long",
                leverage=1.0,
                stop_level=stop_p,
                target_level=target_p,
                fees_paid=entry_fee,
            )

            # Hold loop
            exit_bar    = entry_bar
            exit_price  = entry_price
            exit_reason = ExitReason.TIME_STOP

            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break

                # Stop hit
                if lows[bar] <= stop_p:
                    exit_bar    = bar
                    exit_price  = stop_p
                    exit_reason = ExitReason.STOP_HIT
                    break

                # Target hit
                if highs[bar] >= target_p:
                    exit_bar    = bar
                    exit_price  = target_p
                    exit_reason = ExitReason.TARGET_HIT
                    break

                # Regime exit (RISK_OFF flips)
                if regime_states[bar] == RegimeState.RISK_OFF and j >= min_hold:
                    exit_bar    = bar
                    exit_price  = closes[bar]
                    exit_reason = ExitReason.REGIME_EXIT
                    break

                # Trend exit: close drops below Kijun
                if j >= min_hold and not np.isnan(K[bar]) and closes[bar] < K[bar]:
                    exit_bar    = bar
                    exit_price  = closes[bar]
                    exit_reason = ExitReason.TIME_STOP  # trend_exit
                    break

            exit_fee  = pos_size * MAKER_FEE
            exit_time = datetime.fromtimestamp(timestamps[min(exit_bar, n - 1)], tz=timezone.utc)
            trade.close(exit_price, exit_time, exit_reason, fees=exit_fee)

            if trade.pnl_usd is not None:
                self.wallet += trade.pnl_usd
                self._daily_pnl += trade.pnl_usd
                if self._daily_pnl < -(self.initial_capital * DAILY_HALT):
                    self._daily_halted = True

            self._last_exit_bar = exit_bar
            trades.append(trade)
            i = exit_bar + cooldown

        return trades


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def load_binance(symbol: str, interval_min: int) -> pd.DataFrame:
    DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
    safe = symbol.replace("/", "_")
    p = DATA_DIR / f"binance_{safe}_{interval_min}m.parquet"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_parquet(p)


def df_to_arrays(df: pd.DataFrame):
    ts = df.index.astype("int64").values / 1e9
    return ts, df["open"].values.astype(float), df["high"].values.astype(float), \
           df["low"].values.astype(float), df["close"].values.astype(float), \
           df["volume"].values.astype(float)


if __name__ == "__main__":
    DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

    print("=" * 70)
    print("ICHIMOKU CLOUD BACKTEST — H3 with proper signal decoupling")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # Load BTC daily for regime construction
    btc_df = load_binance("BTC/USD", 1440)
    btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)

    results = []

    test_cases = [
        # (symbol, interval_min, bar_hours, allow_neutral, label)
        ("BTC/USD",  1440, 24.0, True,  "BTC daily, neutral OK"),
        ("BTC/USD",  1440, 24.0, False, "BTC daily, RISK_ON only"),
        ("ETH/USDT", 1440, 24.0, True,  "ETH daily, neutral OK"),
        ("SOL/USDT", 1440, 24.0, True,  "SOL daily, neutral OK"),
        ("BTC/USD",  240,  4.0,  True,  "BTC 4h, neutral OK"),
        ("BTC/USD",  240,  4.0,  False, "BTC 4h, RISK_ON only"),
        ("SOL/USDT", 240,  4.0,  True,  "SOL 4h, neutral OK"),
        ("SOL/USDT", 240,  4.0,  False, "SOL 4h, RISK_ON only"),
        ("BTC/USD",  60,   1.0,  True,  "BTC 1h, neutral OK"),
        ("SOL/USDT", 60,   1.0,  True,  "SOL 1h, neutral OK"),
    ]

    for sym, itvl, bh, allow_neutral, label in test_cases:
        try:
            df = load_binance(sym, itvl)
        except FileNotFoundError:
            print(f"  [skip] {label} — no data")
            continue

        ts, o, h, l, c, v = df_to_arrays(df)

        # Build BTC-trend regime for this asset
        regime = build_btc_trend_regime(btc_c, ts, btc_ts,
                                         trend_period=20,
                                         bull_threshold=0.05,
                                         bear_threshold=-0.05)

        risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / len(regime) * 100
        neutral_pct = np.sum(regime == RegimeState.NEUTRAL) / len(regime) * 100

        bt = IchimokuBacktester(
            initial_capital=10_000.0,
            bar_interval_hours=bh,
            allow_neutral_regime=allow_neutral,
        )
        trades = bt.run(ts, o, h, l, c, v, regime_states=regime, pair=sym)

        if not trades:
            print(f"  [0 trades] {label}  RISK_ON={risk_on_pct:.0f}% NEUTRAL={neutral_pct:.0f}%")
            continue

        engine = BacktestEngine(initial_capital=10_000.0)
        engine.add_trades(trades)
        stats = engine.compute_stats(venue=VENUE)

        star = "*" if stats.p_value < 0.10 else " "
        print(f"  {label:<30}  n={stats.n_trades:4d} WR={stats.win_rate:.1%} "
              f"PF={stats.profit_factor:.3f} Sh={stats.sharpe_ratio:+.3f} "
              f"DD={stats.max_drawdown_pct:.1f}% PnL={stats.total_pnl_pct:+.2f}% "
              f"p={stats.p_value:.3f}{star}")

        results.append({
            "label": label,
            "symbol": sym,
            "interval_min": itvl,
            "allow_neutral": allow_neutral,
            "n_trades": stats.n_trades,
            "win_rate": round(stats.win_rate, 4),
            "profit_factor": round(stats.profit_factor, 4),
            "sharpe": round(stats.sharpe_ratio, 4),
            "sortino": round(stats.sortino_ratio, 4),
            "max_dd_pct": round(stats.max_drawdown_pct, 4),
            "total_pnl_pct": round(stats.total_pnl_pct, 4),
            "expectancy_r": round(stats.expectancy_r, 4),
            "p_value": round(stats.p_value, 4),
            "risk_on_pct": round(risk_on_pct, 1),
        })

    print("\n" + "=" * 70)
    print("SIGNIFICANT (p < 0.10)")
    print("=" * 70)
    sig = [r for r in results if r["p_value"] < 0.10]
    if sig:
        for r in sorted(sig, key=lambda x: x["p_value"]):
            print(f"  {r['label']:<30}  PF={r['profit_factor']:.3f}  "
                  f"Sh={r['sharpe']:.3f}  p={r['p_value']:.4f}  n={r['n_trades']}")
    else:
        print("  None")

    out_path = DATA_DIR / "ichimoku_backtest_results.json"
    with open(out_path, "w") as f:
        json.dump({"run_at": datetime.now(timezone.utc).isoformat(), "results": results}, f, indent=2)
    print(f"\nSaved: {out_path}")

    # Verdict
    pass_cases = [r for r in results if r["profit_factor"] > 1.2 and r["p_value"] < 0.10]
    if pass_cases:
        best = max(pass_cases, key=lambda x: x["profit_factor"])
        print(f"\nH3 EDGE CANDIDATE: {best['label']}  PF={best['profit_factor']:.3f}  "
              f"Sh={best['sharpe']:.3f}  p={best['p_value']:.4f}")
        print("Next step: walk-forward validation, then paper trade")
    else:
        print("\nH3 null hypothesis holds with Ichimoku signal.")
        if results:
            best = max(results, key=lambda x: x["profit_factor"])
            print(f"Best result: {best['label']}  PF={best['profit_factor']:.3f}  "
                  f"Sh={best['sharpe']:.3f}  p={best['p_value']:.4f}  n={best['n_trades']}")
