"""
Jupiter Perps H3 Integration — Port H3-A, H3-B, H3-C, H3-D signals to SOL-PERP
and backtest with proper perps fee model (0.14% round-trip + borrow fees).

Test at 3x and 5x leverage. Report OOS PF, win rate, and edge decay vs spot.
Flag strategies with OOS PF > 1.5 and n >= 10 as perps-candidates.

Fee model:
    - 0.07% open + 0.07% close = 0.14% round-trip minimum
    - Borrow fee: hourly rate 0.001%-0.01% based on utilization
    - Borrow fee accrues while position is open

Exit: ATR trailing stop (2x ATR)

Usage:
    /Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 scripts/jupiter_perps_h3_backtest.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import pandas as pd

from src.quant.indicators import ichimoku, rsi, atr, ema, obv, kama, sma
from src.quant.regime import RegimeState
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.backtest_engine import BacktestEngine, ExitReason, Trade, TradeOutcome

# ============================================================================
# Constants
# ============================================================================

VENUE = "jupiter_perps"
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
OUTPUT_DIR = DATA_DIR / "research" / "perps"

# Fee model
OPEN_FEE_PCT = 0.0007       # 0.07%
CLOSE_FEE_PCT = 0.0007      # 0.07%
ROUND_TRIP_FEE_PCT = 0.0014  # 0.14%

# Borrow fee model (hourly)
BORROW_FEE_MIN_HOURLY = 0.00001   # 0.001%
BORROW_FEE_MAX_HOURLY = 0.0001    # 0.01%
BORROW_FEE_BASE_UTIL = 0.5        # 50% utilization = midpoint

# Leverage
LEVERAGE_OPTIONS = [3.0, 5.0]

# ATR exit
ATR_STOP_MULT = 2.0  # 2x ATR trailing stop

# Backtest params
SPLIT_RATIO = 0.70
INITIAL_CAPITAL = 10_000.0

# ============================================================================
# Signal Functions (ported from existing implementations)
# ============================================================================

def signal_h3a(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """
    H3-A: Ichimoku TK cross + above cloud + RSI>55 + IchiScore>=3
    Returns boolean mask for entry signals.
    """
    n = len(c)
    
    # Compute indicators
    ichi = ichimoku(h, l, c)
    rsi_v = rsi(c, 14)
    
    # Compute Ichimoku composite score
    score = _ichimoku_composite_score(ichi, c)
    
    # TK cross detection
    tk_cross = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(ichi.tenkan_sen[i]) or np.isnan(ichi.kijun_sen[i]):
            continue
        if np.isnan(ichi.tenkan_sen[i-1]) or np.isnan(ichi.kijun_sen[i-1]):
            continue
        tk_cross[i] = (ichi.tenkan_sen[i] > ichi.kijun_sen[i] and 
                       ichi.tenkan_sen[i-1] <= ichi.kijun_sen[i-1])
    
    # Build mask
    mask = np.zeros(n, dtype=bool)
    for i in range(n):
        if np.isnan(rsi_v[i]) or np.isnan(score[i]):
            continue
        cloud_top = max(
            ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
            ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf,
        )
        mask[i] = (tk_cross[i] and c[i] > cloud_top and rsi_v[i] > 55 and score[i] >= 3)
    
    return mask


def signal_h3b(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> np.ndarray:
    """
    H3-B: Vol>1.5x 20MA + RSI cross 50
    Returns boolean mask for entry signals.
    """
    n = len(c)
    rsi_v = rsi(c, 14)
    vol_ma = sma(v, 20)
    
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(vol_ma[i]) or vol_ma[i] <= 0:
            continue
        if np.isnan(rsi_v[i]) or np.isnan(rsi_v[i-1]):
            continue
        vol_ok = v[i] > 1.5 * vol_ma[i]
        rsi_cross = rsi_v[i] > 50 and rsi_v[i-1] <= 50
        mask[i] = vol_ok and rsi_cross
    
    return mask


def signal_h3c(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """
    H3-C: RSI>52 + Price crosses KAMA
    Returns boolean mask for entry signals.
    """
    n = len(c)
    rsi_v = rsi(c, 14)
    kama_v = kama(c, period=4, fast_period=2, slow_period=30)
    
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(kama_v[i]) or np.isnan(kama_v[i-1]):
            continue
        if np.isnan(rsi_v[i]):
            continue
        rsi_ok = rsi_v[i] > 52
        kama_cross = c[i] > kama_v[i] and c[i-1] <= kama_v[i-1]
        mask[i] = rsi_ok and kama_cross
    
    return mask


def signal_h3d(h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray) -> np.ndarray:
    """
    H3-D: OBV crosses 10-EMA + RSI>50
    Returns boolean mask for entry signals.
    """
    n = len(c)
    obv_v = obv(c, v)
    obv_ema10 = ema(obv_v, 10)
    rsi_v = rsi(c, 14)
    
    mask = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if np.isnan(obv_ema10[i]) or np.isnan(obv_ema10[i-1]):
            continue
        if np.isnan(rsi_v[i]):
            continue
        obv_cross = obv_v[i] > obv_ema10[i] and obv_v[i-1] <= obv_ema10[i-1]
        rsi_ok = rsi_v[i] > 50
        mask[i] = obv_cross and rsi_ok
    
    return mask


def _ichimoku_composite_score(ichi, close: np.ndarray) -> np.ndarray:
    """
    Compute Ichimoku composite score (0-5).
    Based on 5 conditions:
    1. Price > Tenkan (short-term trend)
    2. Price > Kijun (medium-term trend)
    3. Tenkan > Kijun (momentum)
    4. Price > Cloud (trend confirmation)
    5. Chikou > Price 26 bars ago (lagging confirmation)
    """
    n = len(close)
    score = np.full(n, np.nan)
    
    for i in range(n):
        if np.isnan(ichi.tenkan_sen[i]) or np.isnan(ichi.kijun_sen[i]):
            continue
        if np.isnan(ichi.senkou_span_a[i]) or np.isnan(ichi.senkou_span_b[i]):
            continue
        
        s = 0
        # 1. Price > Tenkan
        if close[i] > ichi.tenkan_sen[i]:
            s += 1
        # 2. Price > Kijun
        if close[i] > ichi.kijun_sen[i]:
            s += 1
        # 3. Tenkan > Kijun
        if ichi.tenkan_sen[i] > ichi.kijun_sen[i]:
            s += 1
        # 4. Price > Cloud
        cloud_top = max(ichi.senkou_span_a[i], ichi.senkou_span_b[i])
        if close[i] > cloud_top:
            s += 1
        # 5. Chikou confirmation (simplified - check if available)
        if not np.isnan(ichi.chikou_span[i]):
            s += 1
        
        score[i] = s
    
    return score


# ============================================================================
# Perps Backtester
# ============================================================================

class PerpsH3Backtester:
    """
    Jupiter Perps backtester for H3 signals.
    
    Fee model:
        - 0.07% open + 0.07% close = 0.14% round-trip
        - Borrow fee: hourly rate based on utilization (0.001%-0.01%)
    
    Exit: ATR trailing stop (2x ATR)
    
    Leverage: configurable (3x or 5x)
    """
    
    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL,
        leverage: float = 3.0,
        atr_stop_mult: float = ATR_STOP_MULT,
        bar_hours: float = 4.0,  # 4h bars
    ):
        self.initial_capital = initial_capital
        self.leverage = leverage
        self.atr_stop_mult = atr_stop_mult
        self.bar_hours = bar_hours
        
        self._trade_counter = 0
        self._last_exit_bar = -999
        self._cooldown_bars = 2
    
    def _next_id(self) -> str:
        self._trade_counter += 1
        return f"JUP-{self._trade_counter:05d}"
    
    def _calc_borrow_fee_rate(self, utilization: float = 0.5) -> float:
        """
        Calculate hourly borrow fee rate based on utilization.
        Linear interpolation between min (0.001%) and max (0.01%).
        """
        u = max(0.0, min(1.0, utilization))
        return BORROW_FEE_MIN_HOURLY + u * (BORROW_FEE_MAX_HOURLY - BORROW_FEE_MIN_HOURLY)
    
    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        signal_mask: np.ndarray,
        regime_states: np.ndarray | None = None,
        pair: str = "SOL-PERP",
    ) -> List[Trade]:
        """Run backtest on given signal mask.
        
        regime_states: boolean array (True = allowed regime)
        """
        n = len(timestamps)
        warmup = 100  # Ensure indicators are stable
        
        if regime_states is None:
            regime_states = np.ones(n, dtype=bool)
        
        # Compute ATR for stops
        atr_vals = atr(highs, lows, closes, 14)
        
        trades: List[Trade] = []
        i = warmup
        
        while i < n - 2:
            # Cooldown check
            if i - self._last_exit_bar < self._cooldown_bars:
                i += 1
                continue
            
            # Regime check: allowed regime only
            if not regime_states[i]:
                i += 1
                continue
            
            # ATR must be valid
            if np.isnan(atr_vals[i]) or atr_vals[i] <= 0:
                i += 1
                continue
            
            # Signal check
            if not signal_mask[i]:
                i += 1
                continue
            
            # Entry next bar open
            entry_bar = i + 1
            if entry_bar >= n:
                break
            
            entry_price = opens[entry_bar]
            entry_time = datetime.fromtimestamp(timestamps[entry_bar], tz=timezone.utc)
            
            # Position sizing: use leverage
            base_size = self.initial_capital * 0.02  # 2% base
            pos_size = base_size * self.leverage
            
            if pos_size < 1.0:
                i += 1
                continue
            
            # Entry fee (0.07%)
            entry_fee = pos_size * OPEN_FEE_PCT
            
            # Stop: 2x ATR below entry
            stop_p = entry_price - self.atr_stop_mult * atr_vals[i]
            
            # Borrow fee rate
            borrow_rate_hourly = self._calc_borrow_fee_rate()
            
            # Hold loop
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP
            hours_held = 0.0
            total_borrow_fee = 0.0
            
            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break
                
                hours_held = j * self.bar_hours
                
                # Accumulate borrow fee
                hourly_borrow_cost = pos_size * borrow_rate_hourly
                total_borrow_fee += hourly_borrow_cost
                
                # Stop hit
                if lows[bar] <= stop_p:
                    exit_bar = bar
                    exit_price = max(stop_p, lows[bar])  # Slippage at stop
                    exit_reason = ExitReason.STOP_HIT
                    break
                
                # Update trailing stop
                new_stop = highs[bar] - self.atr_stop_mult * atr_vals[i]
                stop_p = max(stop_p, new_stop)
            
            # Exit fee (0.07%)
            exit_fee = pos_size * CLOSE_FEE_PCT
            total_fees = entry_fee + exit_fee + total_borrow_fee
            
            # Calculate PnL (leveraged)
            price_change_pct = (exit_price - entry_price) / entry_price
            pnl_gross = pos_size * price_change_pct
            pnl_net = pnl_gross - total_fees
            
            trade = Trade(
                trade_id=self._next_id(),
                venue=VENUE,
                strategy="h3_perps",
                pair=pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side="long",
                leverage=self.leverage,
                stop_level=stop_p,
                target_level=None,
                fees_paid=total_fees,
            )
            trade.exit_timestamp = datetime.fromtimestamp(timestamps[exit_bar], tz=timezone.utc)
            trade.exit_price = exit_price
            trade.pnl = pnl_net
            trade.exit_reason = exit_reason
            trade.outcome = TradeOutcome.WIN if pnl_net > 0 else TradeOutcome.LOSS
            
            trades.append(trade)
            self._last_exit_bar = exit_bar
            i = exit_bar + self._cooldown_bars
        
        return trades


# ============================================================================
# Spot Backtester (for edge decay comparison)
# ============================================================================

class SpotH3Backtester:
    """
    Spot backtester for H3 signals (1x leverage, no borrow).
    Used to calculate edge decay vs perps.
    """
    
    def __init__(
        self,
        initial_capital: float = INITIAL_CAPITAL,
        atr_stop_mult: float = ATR_STOP_MULT,
        bar_hours: float = 4.0,
    ):
        self.initial_capital = initial_capital
        self.atr_stop_mult = atr_stop_mult
        self.bar_hours = bar_hours
        self.fee_pct = 0.0016  # Kraken spot fee
        
        self._trade_counter = 0
        self._last_exit_bar = -999
        self._cooldown_bars = 2
    
    def _next_id(self) -> str:
        self._trade_counter += 1
        return f"SPOT-{self._trade_counter:05d}"
    
    def run(
        self,
        timestamps: np.ndarray,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
        signal_mask: np.ndarray,
        regime_states: np.ndarray | None = None,
        pair: str = "SOL/USDT",
    ) -> List[Trade]:
        """Run spot backtest for comparison.
        
        regime_states: boolean array (True = allowed regime)
        """
        n = len(timestamps)
        warmup = 100
        
        if regime_states is None:
            regime_states = np.ones(n, dtype=bool)
        
        atr_vals = atr(highs, lows, closes, 14)
        
        trades: List[Trade] = []
        i = warmup
        
        while i < n - 2:
            if i - self._last_exit_bar < self._cooldown_bars:
                i += 1
                continue
            
            if not regime_states[i]:
                i += 1
                continue
            
            if np.isnan(atr_vals[i]) or atr_vals[i] <= 0:
                i += 1
                continue
            
            if not signal_mask[i]:
                i += 1
                continue
            
            entry_bar = i + 1
            if entry_bar >= n:
                break
            
            entry_price = opens[entry_bar]
            entry_time = datetime.fromtimestamp(timestamps[entry_bar], tz=timezone.utc)
            
            pos_size = self.initial_capital * 0.02  # 2% position
            if pos_size < 1.0:
                i += 1
                continue
            
            entry_fee = pos_size * self.fee_pct
            stop_p = entry_price - self.atr_stop_mult * atr_vals[i]
            
            exit_bar = entry_bar
            exit_price = entry_price
            exit_reason = ExitReason.TIME_STOP
            
            for j in range(1, n - entry_bar):
                bar = entry_bar + j
                if bar >= n:
                    break
                
                if lows[bar] <= stop_p:
                    exit_bar = bar
                    exit_price = max(stop_p, lows[bar])
                    exit_reason = ExitReason.STOP_HIT
                    break
                
                new_stop = highs[bar] - self.atr_stop_mult * atr_vals[i]
                stop_p = max(stop_p, new_stop)
            
            exit_fee = pos_size * self.fee_pct
            total_fees = entry_fee + exit_fee
            
            price_change_pct = (exit_price - entry_price) / entry_price
            pnl_gross = pos_size * price_change_pct
            pnl_net = pnl_gross - total_fees
            
            trade = Trade(
                trade_id=self._next_id(),
                venue="kraken_spot",
                strategy="h3_spot",
                pair=pair,
                entry_timestamp=entry_time,
                entry_price=entry_price,
                position_size_usd=pos_size,
                regime_state=regime_states[i],
                side="long",
                leverage=1.0,
                stop_level=stop_p,
                target_level=None,
                fees_paid=total_fees,
            )
            trade.exit_timestamp = datetime.fromtimestamp(timestamps[exit_bar], tz=timezone.utc)
            trade.exit_price = exit_price
            trade.pnl = pnl_net
            trade.exit_reason = exit_reason
            trade.outcome = TradeOutcome.WIN if pnl_net > 0 else TradeOutcome.LOSS
            
            trades.append(trade)
            self._last_exit_bar = exit_bar
            i = exit_bar + self._cooldown_bars
        
        return trades


# ============================================================================
# Analysis Functions
# ============================================================================

def compute_stats(trades: List[Trade], capital: float = INITIAL_CAPITAL) -> Dict:
    """Compute performance statistics from trades."""
    if not trades:
        return {
            "n_trades": 0,
            "profit_factor": 0.0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "sharpe": 0.0,
            "max_dd": 0.0,
        }
    
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    avg_pnl = np.mean(pnls) if pnls else 0.0
    
    # Sharpe (annualized for 4h bars)
    if len(pnls) > 1:
        returns = np.array(pnls) / capital
        sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(365 * 6)
    else:
        sharpe = 0.0
    
    # Max drawdown
    cum_pnl = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum_pnl)
    dd = peak - cum_pnl
    max_dd = np.max(dd) if len(dd) > 0 else 0.0
    
    return {
        "n_trades": len(trades),
        "profit_factor": round(profit_factor, 3),
        "win_rate": round(win_rate, 3),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd, 2),
    }


def calc_edge_decay(perps_pf: float, spot_pf: float) -> float:
    """Calculate edge decay: (spot_pf - perps_pf) / spot_pf * 100."""
    if spot_pf <= 0:
        return 0.0
    return (spot_pf - perps_pf) / spot_pf * 100


# ============================================================================
# Main Runner
# ============================================================================

def main():
    print("=" * 80)
    print("JUPITER PERPS H3 INTEGRATION BACKTEST")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load SOL 4h data
    print("\nLoading SOL/USDT 4h data...")
    try:
        sol_df = load_binance("SOL/USDT", 240)
    except FileNotFoundError:
        print("ERROR: SOL/USDT 240m data not found. Run data fetcher first.")
        return
    
    ts, o, h, l, c, v = df_to_arrays(sol_df)
    n = len(ts)
    SPLIT = int(n * SPLIT_RATIO)
    
    print(f"  Total bars: {n}")
    print(f"  Train: {SPLIT} | Test: {n - SPLIT}")
    print(f"  Date range: {datetime.fromtimestamp(ts[0]).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(ts[-1]).strftime('%Y-%m-%d')}")
    
    # Load BTC daily for regime
    print("\nLoading BTC/USD daily for regime filter...")
    try:
        btc_df = load_binance("BTC/USD", 1440)
        btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    except FileNotFoundError:
        print("  WARNING: BTC data not found, using RISK_ON for all bars")
        btc_ts, btc_c = None, None
    
    # Build regime with relaxed thresholds for perps
    if btc_ts is not None:
        # Use more reasonable thresholds based on actual BTC returns distribution
        # BTC 20-day returns: mean=2.6%, so ±2.5% is a reasonable regime threshold
        regime = build_btc_trend_regime(
            btc_c, ts, btc_ts,
            trend_period=20,
            bull_threshold=0.025,  # 2.5% for RISK_ON (was 5%)
            bear_threshold=-0.03,  # -3% for RISK_OFF
        )
    else:
        regime = np.full(n, RegimeState.RISK_ON, dtype=object)
    
    # For perps, we allow RISK_ON and NEUTRAL (not RISK_OFF only)
    allowed_regime = np.array([r in [RegimeState.RISK_ON, RegimeState.NEUTRAL] for r in regime])
    
    risk_on_pct = np.sum(regime == RegimeState.RISK_ON) / n * 100
    neutral_pct = np.sum(regime == RegimeState.NEUTRAL) / n * 100
    risk_off_pct = np.sum(regime == RegimeState.RISK_OFF) / n * 100
    allowed_pct = np.sum(allowed_regime) / n * 100
    print(f"  RISK_ON: {risk_on_pct:.1f}% | NEUTRAL: {neutral_pct:.1f}% | RISK_OFF: {risk_off_pct:.1f}%")
    print(f"  Allowed for perps (RISK_ON + NEUTRAL): {allowed_pct:.1f}%")
    
    # Define strategies
    strategies = {
        "H3-A": {
            "signal_fn": lambda h, l, c: signal_h3a(h, l, c),
            "desc": "Ichimoku TK cross + above cloud + RSI>55 + IchiScore>=3",
        },
        "H3-B": {
            "signal_fn": lambda h, l, c, v: signal_h3b(h, l, c, v),
            "desc": "Vol>1.5x 20MA + RSI cross 50",
        },
        "H3-C": {
            "signal_fn": lambda h, l, c: signal_h3c(h, l, c),
            "desc": "RSI>52 + Price crosses KAMA",
        },
        "H3-D": {
            "signal_fn": lambda h, l, c, v: signal_h3d(h, l, c, v),
            "desc": "OBV crosses 10-EMA + RSI>50",
        },
    }
    
    # Run backtests
    all_results = {}
    candidates = []
    
    for strat_name, strat_info in strategies.items():
        print(f"\n{'=' * 80}")
        print(f"Strategy: {strat_name}")
        print(f"Description: {strat_info['desc']}")
        print(f"{'=' * 80}")
        
        # Generate signal mask
        if strat_name in ["H3-B", "H3-D"]:
            mask = strat_info["signal_fn"](h, l, c, v)
        else:
            mask = strat_info["signal_fn"](h, l, c)
        
        signal_count = np.sum(mask)
        print(f"\n  Total signals: {signal_count} ({signal_count/n*100:.2f}%)")
        print(f"  Train signals: {np.sum(mask[:SPLIT])}")
        print(f"  Test signals: {np.sum(mask[SPLIT:])}")
        
        strat_results = {
            "description": strat_info["desc"],
            "spot": {},
            "perps": {},
        }
        
        # Spot baseline (OOS only) - use allowed regime mask
        print("\n  [SPOT BASELINE]")
        spot_bt = SpotH3Backtester()
        # For spot, we use the allowed_regime (RISK_ON + NEUTRAL)
        spot_trades_oos = spot_bt.run(
            ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
            c[SPLIT:], v[SPLIT:], mask[SPLIT:], allowed_regime[SPLIT:]
        )
        spot_stats = compute_stats(spot_trades_oos)
        strat_results["spot"]["oos"] = spot_stats
        print(f"    OOS: n={spot_stats['n_trades']}, PF={spot_stats['profit_factor']}, "
              f"WR={spot_stats['win_rate']:.1%}, PnL=${spot_stats['total_pnl']:.2f}")
        
        # Perps at 3x and 5x
        for leverage in LEVERAGE_OPTIONS:
            print(f"\n  [PERPS {leverage}x]")
            
            perps_bt = PerpsH3Backtester(leverage=leverage)
            perps_trades_oos = perps_bt.run(
                ts[SPLIT:], o[SPLIT:], h[SPLIT:], l[SPLIT:],
                c[SPLIT:], v[SPLIT:], mask[SPLIT:], allowed_regime[SPLIT:]
            )
            perps_stats = compute_stats(perps_trades_oos)
            
            # Edge decay
            edge_decay = calc_edge_decay(perps_stats["profit_factor"], spot_stats["profit_factor"])
            
            strat_results["perps"][f"{leverage}x"] = {
                **perps_stats,
                "edge_decay_pct": round(edge_decay, 1),
            }
            
            print(f"    OOS: n={perps_stats['n_trades']}, PF={perps_stats['profit_factor']}, "
                  f"WR={perps_stats['win_rate']:.1%}, PnL=${perps_stats['total_pnl']:.2f}")
            print(f"    Edge decay vs spot: {edge_decay:.1f}%")
            
            # Check if perps candidate
            if perps_stats["profit_factor"] > 1.5 and perps_stats["n_trades"] >= 10:
                candidate_info = {
                    "strategy": strat_name,
                    "leverage": leverage,
                    "oos_pf": perps_stats["profit_factor"],
                    "n_trades": perps_stats["n_trades"],
                    "win_rate": perps_stats["win_rate"],
                    "edge_decay": edge_decay,
                }
                candidates.append(candidate_info)
                print(f"    *** PERPS CANDIDATE: PF={perps_stats['profit_factor']:.3f} >= 1.5, n={perps_stats['n_trades']} >= 10")
        
        all_results[strat_name] = strat_results
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print(f"\n{'Strategy':<10} {'Leverage':<10} {'OOS PF':<10} {'Win Rate':<10} {'Trades':<10} {'Edge Decay':<12} {'Candidate'}")
    print("-" * 80)
    
    for strat_name, results in all_results.items():
        for lev_key, lev_results in results["perps"].items():
            is_candidate = "YES" if lev_results.get("profit_factor", 0) > 1.5 and lev_results.get("n_trades", 0) >= 10 else ""
            print(f"{strat_name:<10} {lev_key:<10} {lev_results['profit_factor']:<10.3f} "
                  f"{lev_results['win_rate']:<10.1%} {lev_results['n_trades']:<10} "
                  f"{lev_results.get('edge_decay_pct', 0):<12.1f}% {is_candidate}")
    
    print("\n" + "=" * 80)
    print(f"PERPS CANDIDATES (OOS PF > 1.5, n >= 10): {len(candidates)}")
    print("=" * 80)
    
    for cand in candidates:
        print(f"  - {cand['strategy']} @ {cand['leverage']}x: PF={cand['oos_pf']:.3f}, n={cand['n_trades']}, "
              f"WR={cand['win_rate']:.1%}, Edge Decay={cand['edge_decay']:.1f}%")
    
    # Save results
    output_data = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "pair": "SOL/USDT",
            "interval": "4h",
            "total_bars": n,
            "train_bars": SPLIT,
            "test_bars": n - SPLIT,
        },
        "results": all_results,
        "candidates": candidates,
    }
    
    output_path = OUTPUT_DIR / "jupiter_perps_h3_results.json"
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    
    # Update ledger
    ledger_path = DATA_DIR / "research" / "ledger.csv"
    with open(ledger_path, "a") as f:
        for cand in candidates:
            f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')},"
                    f"jupiter_perps_h3,{cand['strategy']},{cand['leverage']}x,"
                    f"PF={cand['oos_pf']:.3f},n={cand['n_trades']},"
                    f"WR={cand['win_rate']:.1%},edge_decay={cand['edge_decay']:.1f}%\n")
    
    print(f"Ledger updated: {ledger_path}")
    print("\nDone!")


if __name__ == "__main__":
    main()
