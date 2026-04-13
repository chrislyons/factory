#!/usr/bin/env python3
"""
h3a_optimizer.py — Systematic optimization for H3-A Ichimoku strategy.

Tests parameter combinations:
- Tenkan periods: [7, 9, 12]
- Kijun periods: [20, 26, 30]
- Cloud shift (displacement): [20, 26, 30]
- Volume threshold: [1.0, 1.2, 1.5] (volume multiplier vs SMA 20)

For each combo, test T1 entry timing (enter at next bar open).
Use Jupiter friction (0.0025).

Output: Best parameter combo per pair, aggregate PF/WR.
"""

from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1]))  # Go up to ig88 directory

import src.quant.indicators as ind
from src.quant.ichimoku_backtest import build_btc_trend_regime, df_to_arrays, load_binance
from src.quant.regime import RegimeState
from src.quant.backtest_engine import BacktestEngine, Trade, ExitReason

# Constants
DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")
VENUE = "jupiter_perps"
FRICTION = 0.0025  # Jupiter friction 0.25%
INITIAL_CAPITAL = 10_000.0
BAR_HOURS = 4.0
ATR_STOP_MULT = 2.0
ATR_TARGET_MULT = 3.0
MIN_HOLD_BARS = 2
COOLDOWN_BARS = 2

# Parameter ranges
TENKAN_PERIODS = [7, 9, 12]
KIJUN_PERIODS = [20, 26, 30]
CLOUD_SHIFTS = [20, 26, 30]  # displacement
VOLUME_THRESHOLDS = [1.0, 1.2, 1.5]

# Available pairs for 4h data
PAIRS = [
    ("BTC/USDT", "BTC_USDT"),
    ("ETH/USDT", "ETH_USDT"),
    ("SOL/USDT", "SOL_USDT"),
    ("AVAX/USDT", "AVAX_USDT"),
    ("LINK/USDT", "LINK_USDT"),
    ("NEAR/USDT", "NEAR_USDT"),
]


def run_h3a_backtest(
    ts, o, h, l, c, v, regime,
    tenkan_period, kijun_period, cloud_shift, volume_threshold,
    bar_hours=BAR_HOURS, initial_capital=INITIAL_CAPITAL
):
    """
    Run H3-A backtest with given parameters.
    Returns (trades, stats_dict) or ([], {}) if no trades.
    """
    n = len(ts)
    
    # Compute Ichimoku
    ichi = ind.ichimoku(h, l, c, 
                       tenkan_period=tenkan_period,
                       kijun_period=kijun_period,
                       senkou_b_period=kijun_period * 2,  # standard: 2 * kijun
                       displacement=cloud_shift)
    
    # Compute other indicators
    rsi_v = ind.rsi(c, 14)
    atr_v = ind.atr(h, l, c, 14)
    vol_ma = ind.sma(v, 20)
    score = ind.ichimoku_composite_score(ichi, c)
    
    # Generate signals
    n = len(c)
    signals = np.zeros(n, dtype=bool)
    
    # Warmup period
    warmup = max(tenkan_period, kijun_period, kijun_period * 2, 20) + 5
    
    for i in range(warmup, n):
        # Check all conditions
        # 1. TK cross (bullish)
        tk_cross = (ichi.tenkan_sen[i] > ichi.kijun_sen[i] and 
                   ichi.tenkan_sen[i-1] <= ichi.kijun_sen[i-1])
        
        # 2. Price above cloud (both SA and SB)
        cloud_top = max(ichi.senkou_span_a[i] if not np.isnan(ichi.senkou_span_a[i]) else -np.inf,
                       ichi.senkou_span_b[i] if not np.isnan(ichi.senkou_span_b[i]) else -np.inf)
        above_cloud = c[i] > cloud_top
        
        # 3. RSI > 55 (momentum confirmation)
        rsi_ok = not np.isnan(rsi_v[i]) and rsi_v[i] > 55
        
        # 4. Volume threshold (volume > threshold * volume MA)
        vol_ok = (not np.isnan(vol_ma[i]) and vol_ma[i] > 0 and 
                 v[i] > volume_threshold * vol_ma[i])
        
        # 5. Ichimoku composite score >= 3
        score_ok = score[i] >= 3
        
        # 6. Regime OK (not RISK_OFF)
        regime_ok = regime[i] != RegimeState.RISK_OFF
        
        # All conditions must be met
        signals[i] = (tk_cross and above_cloud and rsi_ok and 
                     vol_ok and score_ok and regime_ok)
    
    # Backtest with T1 entry timing
    trades = []
    wallet = initial_capital
    last_exit_bar = -999
    
    i = warmup
    while i < n - MIN_HOLD_BARS - 2:
        # Skip if too soon after last exit
        if i - last_exit_bar < COOLDOWN_BARS:
            i += 1
            continue
        
        # Skip if no signal
        if not signals[i]:
            i += 1
            continue
        
        # T1 entry: enter at next bar open
        entry_bar = i + 1
        if entry_bar >= n:
            break
        
        entry_price = o[entry_bar]
        
        # Calculate position size (2% of wallet)
        pos_size = wallet * 0.02
        if pos_size < 1.0:
            i += 1
            continue
        
        # Entry fee (Jupiter friction)
        entry_fee = pos_size * FRICTION
        
        # Stop and target
        atr_now = atr_v[i] if not np.isnan(atr_v[i]) else entry_price * 0.03
        stop_price = entry_price - ATR_STOP_MULT * atr_now
        target_price = entry_price + ATR_TARGET_MULT * atr_now
        
        # Hold loop
        exit_bar = entry_bar
        exit_price = entry_price
        exit_reason = ExitReason.TIME_STOP
        
        for j in range(1, n - entry_bar):
            bar = entry_bar + j
            if bar >= n:
                break
            
            # Stop hit
            if l[bar] <= stop_price:
                exit_bar = bar
                exit_price = stop_price
                exit_reason = ExitReason.STOP_HIT
                break
            
            # Target hit
            if h[bar] >= target_price:
                exit_bar = bar
                exit_price = target_price
                exit_reason = ExitReason.TARGET_HIT
                break
            
            # Regime exit (RISK_OFF flips)
            if j >= MIN_HOLD_BARS and regime[bar] == RegimeState.RISK_OFF:
                exit_bar = bar
                exit_price = c[bar]
                exit_reason = ExitReason.REGIME_EXIT
                break
            
            # Trend exit: close drops below Kijun
            if (j >= MIN_HOLD_BARS and 
                not np.isnan(ichi.kijun_sen[bar]) and 
                c[bar] < ichi.kijun_sen[bar]):
                exit_bar = bar
                exit_price = c[bar]
                exit_reason = ExitReason.TIME_STOP  # trend exit
                break
        
        # Exit fee
        exit_fee = pos_size * FRICTION
        
        # Calculate PnL
        price_change_pct = (exit_price - entry_price) / entry_price
        gross_pnl = pos_size * price_change_pct
        total_fees = entry_fee + exit_fee
        net_pnl = gross_pnl - total_fees
        
        # Update wallet
        wallet += net_pnl
        
        # Create trade record
        trade = Trade(
            trade_id=f"H3A-{len(trades)+1:05d}",
            venue=VENUE,
            strategy="h3a_ichimoku",
            pair="",
            entry_timestamp=None,
            entry_price=entry_price,
            position_size_usd=pos_size,
            regime_state=regime[i],
            side="long",
            leverage=1.0,
            stop_level=stop_price,
            target_level=target_price,
            fees_paid=total_fees,
        )
        trade.close(exit_price, None, exit_reason, fees=total_fees)
        trades.append(trade)
        
        last_exit_bar = exit_bar
        i = exit_bar + COOLDOWN_BARS
    
    # Compute stats
    if not trades:
        return [], {}
    
    engine = BacktestEngine(initial_capital)
    engine.add_trades(trades)
    
    # Calculate metrics manually since compute_stats might need timestamps
    winning_trades = [t for t in trades if t.pnl_usd and t.pnl_usd > 0]
    losing_trades = [t for t in trades if t.pnl_usd and t.pnl_usd <= 0]
    
    total_pnl = sum(t.pnl_usd for t in trades if t.pnl_usd)
    gross_profit = sum(t.pnl_usd for t in winning_trades)
    gross_loss = abs(sum(t.pnl_usd for t in losing_trades))
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    win_rate = len(winning_trades) / len(trades) if trades else 0
    
    stats = {
        "n_trades": len(trades),
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "profit_factor": round(profit_factor, 4),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "final_wallet": round(wallet, 2),
        "return_pct": round((wallet - initial_capital) / initial_capital * 100, 2),
    }
    
    return trades, stats


def optimize_pair(pair_name, pair_symbol):
    """Optimize H3-A parameters for a single pair."""
    print(f"\n{'='*72}")
    print(f"OPTIMIZING: {pair_name} ({pair_symbol})")
    print(f"{'='*72}")
    
    # Load BTC daily for regime
    try:
        btc_df = load_binance("BTC/USD", 1440)
        btc_ts, _, _, _, btc_c, _ = df_to_arrays(btc_df)
    except FileNotFoundError:
        print("  BTC daily data not found, skipping pair")
        return None
    
    # Load pair data
    try:
        df = load_binance(pair_name, 240)
        ts, o, h, l, c, v = df_to_arrays(df)
    except FileNotFoundError:
        print(f"  {pair_name} 4h data not found, skipping")
        return None
    
    # Build regime
    regime = build_btc_trend_regime(btc_c, ts, btc_ts)
    
    # Parameter grid
    param_grid = list(product(TENKAN_PERIODS, KIJUN_PERIODS, CLOUD_SHIFTS, VOLUME_THRESHOLDS))
    total_combos = len(param_grid)
    print(f"  Testing {total_combos} parameter combinations...")
    
    results = []
    best_combo = None
    best_pf = -1
    
    for idx, (t_per, k_per, cloud_shift, vol_thresh) in enumerate(param_grid):
        # Skip invalid combinations
        if k_per <= t_per:
            continue
        
        trades, stats = run_h3a_backtest(
            ts, o, h, l, c, v, regime,
            t_per, k_per, cloud_shift, vol_thresh
        )
        
        if not stats:
            continue
        
        result = {
            "tenkan_period": t_per,
            "kijun_period": k_per,
            "cloud_shift": cloud_shift,
            "volume_threshold": vol_thresh,
            **stats
        }
        results.append(result)
        
        # Update best
        if stats["n_trades"] >= 5 and stats["profit_factor"] > best_pf:
            best_pf = stats["profit_factor"]
            best_combo = result
        
        # Progress
        if (idx + 1) % 20 == 0 or idx == total_combos - 1:
            print(f"  Progress: {idx+1}/{total_combos} combos tested")
    
    if not results:
        print(f"  No valid results for {pair_name}")
        return None
    
    # Sort by profit factor
    results.sort(key=lambda x: x["profit_factor"], reverse=True)
    
    print(f"\n  TOP 5 PARAMETER COMBOS:")
    print(f"  {'#':>2} {'Tenkan':>6} {'Kijun':>6} {'Cloud':>6} {'Vol':>5} {'Trades':>6} {'PF':>8} {'WR':>6} {'PnL':>8}")
    print(f"  {'-'*2} {'-'*6} {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*8} {'-'*6} {'-'*8}")
    
    for i, r in enumerate(results[:5]):
        print(f"  {i+1:>2} {r['tenkan_period']:>6} {r['kijun_period']:>6} {r['cloud_shift']:>6} "
              f"{r['volume_threshold']:>5} {r['n_trades']:>6} {r['profit_factor']:>8.3f} "
              f"{r['win_rate']:>6.1%} {r['total_pnl']:>8.1f}")
    
    pair_result = {
        "pair": pair_name,
        "symbol": pair_symbol,
        "best_combo": best_combo,
        "top_5": results[:5],
        "total_combos_tested": len(results),
        "all_results": results
    }
    
    return pair_result


def main():
    print("=" * 80)
    print("H3-A ICHIMOKU PARAMETER OPTIMIZATION")
    print(f"Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)
    print("\nParameter ranges:")
    print(f"  Tenkan periods: {TENKAN_PERIODS}")
    print(f"  Kijun periods: {KIJUN_PERIODS}")
    print(f"  Cloud shifts: {CLOUD_SHIFTS}")
    print(f"  Volume thresholds: {VOLUME_THRESHOLDS}")
    print(f"\nOther settings:")
    print(f"  Entry timing: T1 (next bar open)")
    print(f"  Friction: {FRICTION:.4f} (Jupiter)")
    print(f"  Capital: ${INITIAL_CAPITAL:,.0f}")
    print(f"  Position size: 2% per trade")
    
    all_results = {}
    aggregate_stats = {
        "total_trades": 0,
        "total_winning": 0,
        "total_losing": 0,
        "total_pnl": 0.0,
        "pairs_tested": 0,
        "pairs_with_trades": 0,
    }
    
    for pair_name, pair_symbol in PAIRS:
        result = optimize_pair(pair_name, pair_symbol)
        if result:
            all_results[pair_name] = result
            aggregate_stats["pairs_tested"] += 1
            
            if result["best_combo"]:
                aggregate_stats["pairs_with_trades"] += 1
                aggregate_stats["total_trades"] += result["best_combo"]["n_trades"]
                aggregate_stats["total_winning"] += result["best_combo"]["winning_trades"]
                aggregate_stats["total_losing"] += result["best_combo"]["losing_trades"]
                aggregate_stats["total_pnl"] += result["best_combo"]["total_pnl"]
    
    # Calculate aggregate metrics
    if aggregate_stats["total_trades"] > 0:
        aggregate_stats["win_rate"] = round(
            aggregate_stats["total_winning"] / aggregate_stats["total_trades"], 4
        )
        aggregate_stats["avg_pnl_per_trade"] = round(
            aggregate_stats["total_pnl"] / aggregate_stats["total_trades"], 2
        )
    else:
        aggregate_stats["win_rate"] = 0
        aggregate_stats["avg_pnl_per_trade"] = 0
    
    # Print aggregate summary
    print(f"\n{'='*80}")
    print("AGGREGATE SUMMARY")
    print(f"{'='*80}")
    print(f"Pairs tested: {aggregate_stats['pairs_tested']}")
    print(f"Pairs with trades: {aggregate_stats['pairs_with_trades']}")
    print(f"Total trades (best combos): {aggregate_stats['total_trades']}")
    print(f"Win rate: {aggregate_stats['win_rate']:.1%}")
    print(f"Total PnL: ${aggregate_stats['total_pnl']:,.2f}")
    print(f"Avg PnL per trade: ${aggregate_stats['avg_pnl_per_trade']:,.2f}")
    
    # Save results
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "parameters_tested": {
            "tenkan_periods": TENKAN_PERIODS,
            "kijun_periods": KIJUN_PERIODS,
            "cloud_shifts": CLOUD_SHIFTS,
            "volume_thresholds": VOLUME_THRESHOLDS,
        },
        "settings": {
            "entry_timing": "T1 (next bar open)",
            "friction": FRICTION,
            "initial_capital": INITIAL_CAPITAL,
            "position_size_pct": 2.0,
        },
        "aggregate_stats": aggregate_stats,
        "pair_results": all_results,
    }
    
    output_path = DATA_DIR / "h3a_optimization_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults saved to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())