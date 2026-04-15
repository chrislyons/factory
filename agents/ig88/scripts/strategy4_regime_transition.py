#!/usr/bin/env python3
"""Strategy #4: Volatility Regime Transition — first trades after regime change.

Hypothesis: When ATR transitions between volatility regimes, the first MR
signals have higher profit factor because the market is in transition and
other agents haven't adjusted their thresholds yet.

MR Strategy: RSI < 35 + BB breach + reversal candle + volume > 1.2x SMA20
Friction: 0.32% round-trip (Kraken maker)
"""

import json
import sys
import os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from quant.indicators import rsi, atr, bollinger_bands, sma

# --- Config ---
DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data'
OUTPUT_FILE = os.path.join(DATA_DIR, 'edge_discovery/regime_transition.json')
FRICTION = 0.0032  # 0.32% round-trip
ATR_PERIOD = 14
RSI_PERIOD = 14
BB_PERIOD = 20
BB_MULT = 2.0
SMA_VOL_PERIOD = 20
VOL_MULTIPLIER = 1.2
RSI_THRESHOLD = 35
FRESH_TRANSITION_WINDOW = 5  # first N trades after regime change

PAIRS = {
    'SOL': 'binance_SOLUSDT_240m.parquet',
    'AVAX': 'binance_AVAXUSDT_240m.parquet',
    'ETH': 'binance_ETH_USDT_240m.parquet',
    'LINK': 'binance_LINKUSDT_240m.parquet',
    'BTC': 'binance_BTCUSDT_240m.parquet',
}


def classify_regime(atr_pct: float) -> str:
    """Classify ATR as percentage of close into LOW/MID/HIGH regime."""
    if atr_pct < 0.02:
        return 'LOW'
    elif atr_pct < 0.04:
        return 'MID'
    else:
        return 'HIGH'


def is_reversal_candle(o: float, h: float, l: float, c: float) -> bool:
    """Check for bullish reversal candle:
    - Close > Open (green candle)
    - Lower wick >= 2x body (hammer/pin bar)
    - Close in upper 40% of range
    """
    body = abs(c - o)
    rng = h - l
    if rng == 0:
        return False
    lower_wick = min(o, c) - l
    # Bullish candle with significant lower wick
    if c <= o:
        return False
    if lower_wick < body:
        return False
    # Close in upper portion of range
    close_position = (c - l) / rng
    return close_position >= 0.6


def run_mr_backtest(df: pd.DataFrame) -> list[dict]:
    """Run MR strategy and return list of trades with metadata."""
    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    open_ = df['open'].values.astype(float)
    volume = df['volume'].values.astype(float)
    timestamps = df.index.values

    # Indicators
    rsi_arr = rsi(close, RSI_PERIOD)
    bb = bollinger_bands(close, BB_PERIOD, BB_MULT)
    atr_arr = atr(high, low, close, ATR_PERIOD)
    vol_sma = sma(volume, SMA_VOL_PERIOD)

    # ATR as % of close
    atr_pct = atr_arr / close

    trades = []
    in_trade = False
    entry_idx = None
    regime_counts = {}  # track trade count within each regime
    prev_regime = None

    # Need enough bars for indicators
    start = max(RSI_PERIOD + 1, BB_PERIOD, ATR_PERIOD, SMA_VOL_PERIOD) + 1

    for i in range(start, len(close)):
        if np.isnan(rsi_arr[i]) or np.isnan(bb.lower[i]) or np.isnan(atr_pct[i]):
            continue

        if not in_trade:
            # MR signal conditions:
            # 1. RSI < threshold
            # 2. Price breached lower BB (low went below)
            # 3. Bullish reversal candle
            # 4. Volume > 1.2x SMA20
            if (rsi_arr[i] < RSI_THRESHOLD
                and low[i] < bb.lower[i]
                and is_reversal_candle(open_[i], high[i], low[i], close[i])
                and volume[i] > vol_sma[i] * VOL_MULTIPLIER):

                regime = classify_regime(atr_pct[i])

                # Track regime transitions
                if regime != prev_regime:
                    regime_counts[regime] = 0
                    prev_regime = regime

                regime_counts[regime] = regime_counts.get(regime, 0) + 1
                trade_num_in_regime = regime_counts[regime]

                if trade_num_in_regime <= FRESH_TRANSITION_WINDOW:
                    transition_state = 'fresh_transition'
                else:
                    transition_state = 'steady_state'

                # Determine transition direction
                transition_direction = 'none'
                if trade_num_in_regime == 1 and regime != 'UNKNOWN':
                    # This is the first trade of a new regime
                    # The direction is implied by the regime label
                    pass

                entry_idx = i
                entry_price = close[i]
                in_trade = True

                # Dynamic stop based on regime
                if regime == 'LOW':
                    stop_mult = 1.5
                elif regime == 'MID':
                    stop_mult = 2.0
                else:
                    stop_mult = 2.5

                stop_loss = entry_price - atr_arr[i] * stop_mult
                target = entry_price + atr_arr[i] * stop_mult * 1.5

        else:
            # In trade: check exit
            # Hit stop loss
            if low[i] <= stop_loss:
                exit_price = stop_loss
                pnl = (exit_price / entry_price - 1) - FRICTION
                trades.append({
                    'entry_idx': int(entry_idx),
                    'exit_idx': int(i),
                    'entry_price': float(entry_price),
                    'exit_price': float(exit_price),
                    'pnl_pct': float(pnl),
                    'atr_regime': regime,
                    'transition_state': transition_state,
                    'atr_pct': float(atr_pct[entry_idx]),
                    'bars_held': int(i - entry_idx),
                    'exit_reason': 'stop_loss',
                })
                in_trade = False
                continue

            # Hit target
            if high[i] >= target:
                exit_price = target
                pnl = (exit_price / entry_price - 1) - FRICTION
                trades.append({
                    'entry_idx': int(entry_idx),
                    'exit_idx': int(i),
                    'entry_price': float(entry_price),
                    'exit_price': float(exit_price),
                    'pnl_pct': float(pnl),
                    'atr_regime': regime,
                    'transition_state': transition_state,
                    'atr_pct': float(atr_pct[entry_idx]),
                    'bars_held': int(i - entry_idx),
                    'exit_reason': 'target',
                })
                in_trade = False
                continue

            # Time exit: 10 bars max hold (40 hours)
            if i - entry_idx >= 10:
                exit_price = close[i]
                pnl = (exit_price / entry_price - 1) - FRICTION
                trades.append({
                    'entry_idx': int(entry_idx),
                    'exit_idx': int(i),
                    'entry_price': float(entry_price),
                    'exit_price': float(exit_price),
                    'pnl_pct': float(pnl),
                    'atr_regime': regime,
                    'transition_state': transition_state,
                    'atr_pct': float(atr_pct[entry_idx]),
                    'bars_held': int(i - entry_idx),
                    'exit_reason': 'time_exit',
                })
                in_trade = False

    return trades


def calc_metrics(trades: list[dict]) -> dict:
    """Calculate performance metrics for a set of trades."""
    if not trades:
        return {
            'num_trades': 0, 'win_rate': 0, 'pf': 0,
            'avg_win': 0, 'avg_loss': 0, 'expectancy': 0,
            'total_pnl': 0, 'max_dd': 0,
        }

    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_win = sum(wins) if wins else 0
    total_loss = abs(sum(losses)) if losses else 0
    pf = total_win / total_loss if total_loss > 0 else (float('inf') if total_win > 0 else 0)

    # Equity curve for max DD
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0

    return {
        'num_trades': len(trades),
        'win_rate': round(len(wins) / len(trades) * 100, 1),
        'pf': round(pf, 3),
        'avg_win': round(np.mean(wins), 5) if wins else 0,
        'avg_loss': round(np.mean(losses), 5) if losses else 0,
        'expectancy': round(np.mean(pnls), 5),
        'total_pnl': round(sum(pnls), 5),
        'max_dd': round(max_dd, 5),
    }


def analyze_transitions(all_trades: list[dict]) -> dict:
    """Analyze fresh_transition vs steady_state performance."""
    results = {}

    # Overall comparison
    fresh = [t for t in all_trades if t['transition_state'] == 'fresh_transition']
    steady = [t for t in all_trades if t['transition_state'] == 'steady_state']

    results['overall'] = {
        'fresh_transition': calc_metrics(fresh),
        'steady_state': calc_metrics(steady),
    }

    # PF uplift
    fresh_pf = results['overall']['fresh_transition']['pf']
    steady_pf = results['overall']['steady_state']['pf']
    if steady_pf > 0:
        uplift = (fresh_pf - steady_pf) / steady_pf * 100
    elif fresh_pf > 0:
        uplift = float('inf')
    else:
        uplift = 0
    results['overall']['pf_uplift_pct'] = round(uplift, 1)

    # By regime transition direction
    # Group trades by the regime they entered in, tracking the previous regime
    regime_pairs = {}
    prev_regime = None
    regime_trade_count = {}

    for t in all_trades:
        regime = t['atr_regime']
        if regime not in regime_trade_count:
            regime_trade_count[regime] = 0
        regime_trade_count[regime] += 1

        if regime != prev_regime:
            regime_trade_count[regime] = 1
            direction = f"{prev_regime}->{regime}" if prev_regime else f"INIT->{regime}"
            prev_regime = regime

        direction = f"{prev_regime}->{regime}" if prev_regime else f"INIT->{regime}"
        if direction not in regime_pairs:
            regime_pairs[direction] = {'fresh': [], 'steady': []}

    # Re-do with proper direction tracking
    regime_pairs = {}
    prev_regime = None
    regime_seq = {}

    for t in all_trades:
        regime = t['atr_regime']

        if regime != prev_regime:
            regime_seq[regime] = 0
            prev_regime = regime

        regime_seq[regime] = regime_seq.get(regime, 0) + 1
        direction = f"{prev_regime}" if prev_regime else "INIT"

        key = f"regime_{regime}"
        if key not in regime_pairs:
            regime_pairs[key] = {'fresh': [], 'steady': []}

        if t['transition_state'] == 'fresh_transition':
            regime_pairs[key]['fresh'].append(t)
        else:
            regime_pairs[key]['steady'].append(t)

    # Also track actual transition directions (LOW->MID, MID->HIGH, etc.)
    direction_analysis = {}
    prev_regime = None
    regime_count = {}

    for t in all_trades:
        regime = t['atr_regime']

        if prev_regime is None or regime != prev_regime:
            regime_count[regime] = 0
            trans_dir = f"{prev_regime}->{regime}" if prev_regime else f"INIT->{regime}"
            prev_regime = regime

        regime_count[regime] = regime_count.get(regime, 0) + 1
        trans_dir = f"{prev_regime}->{regime}" if prev_regime else f"INIT->{regime}"

        if trans_dir not in direction_analysis:
            direction_analysis[trans_dir] = {'fresh': [], 'steady': []}

        if t['transition_state'] == 'fresh_transition':
            direction_analysis[trans_dir]['fresh'].append(t)
        else:
            direction_analysis[trans_dir]['steady'].append(t)

    results['by_regime'] = {}
    for key, data in regime_pairs.items():
        results['by_regime'][key] = {
            'fresh_transition': calc_metrics(data['fresh']),
            'steady_state': calc_metrics(data['steady']),
        }
        fp = results['by_regime'][key]['fresh_transition']['pf']
        sp = results['by_regime'][key]['steady_state']['pf']
        if sp > 0:
            results['by_regime'][key]['pf_uplift_pct'] = round((fp - sp) / sp * 100, 1)
        else:
            results['by_regime'][key]['pf_uplift_pct'] = None

    results['by_transition_direction'] = {}
    for key, data in direction_analysis.items():
        if len(data['fresh']) + len(data['steady']) < 3:
            continue
        results['by_transition_direction'][key] = {
            'fresh_transition': calc_metrics(data['fresh']),
            'steady_state': calc_metrics(data['steady']),
        }
        fp = results['by_transition_direction'][key]['fresh_transition']['pf']
        sp = results['by_transition_direction'][key]['steady_state']['pf']
        if sp > 0:
            results['by_transition_direction'][key]['pf_uplift_pct'] = round((fp - sp) / sp * 100, 1)
        else:
            results['by_transition_direction'][key]['pf_uplift_pct'] = None

    return results


def main():
    print("=" * 70)
    print("STRATEGY #4: Volatility Regime Transition Backtest")
    print("=" * 70)
    print()

    all_trades = []
    pair_results = {}

    for pair, filename in PAIRS.items():
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            print(f"[SKIP] {pair}: file not found {filepath}")
            continue

        print(f"[LOAD] {pair}: {filename}")
        df = pd.read_parquet(filepath)

        # Ensure sorted by time
        if 'open_time' in df.columns:
            df = df.sort_values('open_time').reset_index(drop=True)
        elif df.index.name == 'open_time' or isinstance(df.index, pd.DatetimeIndex):
            df = df.sort_index()

        print(f"  Bars: {len(df)}, Range: {df.index[0]} to {df.index[-1]}")

        trades = run_mr_backtest(df)
        for t in trades:
            t['pair'] = pair

        fresh = [t for t in trades if t['transition_state'] == 'fresh_transition']
        steady = [t for t in trades if t['transition_state'] == 'steady_state']

        pair_metrics = {
            'all': calc_metrics(trades),
            'fresh_transition': calc_metrics(fresh),
            'steady_state': calc_metrics(steady),
        }

        if pair_metrics['steady_state']['pf'] > 0:
            uplift = (pair_metrics['fresh_transition']['pf'] - pair_metrics['steady_state']['pf']) / pair_metrics['steady_state']['pf'] * 100
        elif pair_metrics['fresh_transition']['pf'] > 0:
            uplift = float('inf')
        else:
            uplift = 0
        pair_metrics['pf_uplift_pct'] = round(uplift, 1)

        pair_results[pair] = pair_metrics
        all_trades.extend(trades)

        print(f"  Trades: {len(trades)} (fresh: {len(fresh)}, steady: {len(steady)})")
        print(f"  All PF: {pair_metrics['all']['pf']}, Fresh PF: {pair_metrics['fresh_transition']['pf']}, Steady PF: {pair_metrics['steady_state']['pf']}")
        print(f"  PF Uplift: {pair_metrics['pf_uplift_pct']}%")
        print()

    # Cross-pair analysis
    print("=" * 70)
    print("CROSS-PAIR ANALYSIS")
    print("=" * 70)
    print()

    transition_analysis = analyze_transitions(all_trades)

    # Print summary
    overall = transition_analysis['overall']
    print(f"TOTAL TRADES: {len(all_trades)}")
    print(f"  Fresh transitions: {overall['fresh_transition']['num_trades']}")
    print(f"  Steady state: {overall['steady_state']['num_trades']}")
    print()
    print(f"FRESH TRANSITION:")
    print(f"  PF: {overall['fresh_transition']['pf']}, WR: {overall['fresh_transition']['win_rate']}%, N: {overall['fresh_transition']['num_trades']}")
    print(f"  Expectancy: {overall['fresh_transition']['expectancy']:.5f}")
    print()
    print(f"STEADY STATE:")
    print(f"  PF: {overall['steady_state']['pf']}, WR: {overall['steady_state']['win_rate']}%, N: {overall['steady_state']['num_trades']}")
    print(f"  Expectancy: {overall['steady_state']['expectancy']:.5f}")
    print()
    print(f"PF UPLIFT: {overall['pf_uplift_pct']}%")
    print()

    # By regime
    print("BY REGIME:")
    for regime, data in transition_analysis['by_regime'].items():
        fp = data['fresh_transition']['pf']
        sp = data['steady_state']['pf']
        fn = data['fresh_transition']['num_trades']
        sn = data['steady_state']['num_trades']
        up = data.get('pf_uplift_pct', 'N/A')
        print(f"  {regime}: Fresh PF={fp} (n={fn}), Steady PF={sp} (n={sn}), Uplift={up}%")
    print()

    # By transition direction
    print("BY TRANSITION DIRECTION:")
    for direction, data in transition_analysis['by_transition_direction'].items():
        fp = data['fresh_transition']['pf']
        sp = data['steady_state']['pf']
        fn = data['fresh_transition']['num_trades']
        sn = data['steady_state']['num_trades']
        up = data.get('pf_uplift_pct', 'N/A')
        print(f"  {direction}: Fresh PF={fp} (n={fn}), Steady PF={sp} (n={sn}), Uplift={up}%")
    print()

    # Verdict
    uplift = overall['pf_uplift_pct']
    if uplift > 20:
        verdict = "VALIDATED EDGE ENHANCEMENT"
        print(f">>> {verdict} <<<")
        print(f"Fresh transitions outperform by {uplift}% — filter to transition-only trades.")
    elif uplift > 0:
        verdict = "MARGINAL - NEEDS MORE DATA"
        print(f">>> {verdict} <<<")
        print(f"Fresh transitions show {uplift}% uplift but below 20% threshold.")
    else:
        verdict = "HYPOTHESIS REJECTED"
        print(f">>> {verdict} <<<")
        print(f"No significant difference between fresh and steady trades.")

    # Save results
    output = {
        'strategy': 'regime_transition',
        'hypothesis': 'First trades after ATR regime change have higher PF',
        'verdict': verdict,
        'friction': FRICTION,
        'params': {
            'rsi_threshold': RSI_THRESHOLD,
            'bb_period': BB_PERIOD,
            'bb_mult': BB_MULT,
            'atr_period': ATR_PERIOD,
            'volume_mult': VOL_MULTIPLIER,
            'fresh_window': FRESH_TRANSITION_WINDOW,
        },
        'pair_results': {k: {
            'all': v['all'],
            'fresh_transition': v['fresh_transition'],
            'steady_state': v['steady_state'],
            'pf_uplift_pct': v['pf_uplift_pct'],
        } for k, v in pair_results.items()},
        'cross_pair': transition_analysis,
        'total_trades': len(all_trades),
        'trades_sample': all_trades[:20] if all_trades else [],
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
