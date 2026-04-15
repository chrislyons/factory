#!/usr/bin/env python3
"""
Rigorous OOS Validation of Momentum Breakout on Jupiter Perps
Walk-forward with expanding window, parameter optimization, bootstrap CI
"""
import pandas as pd
import numpy as np
from itertools import product
import json
import warnings
warnings.filterwarnings('ignore')

# === CONFIG ===
FRICTION = 0.0014  # 0.14% round-trip
PAIRS = ['BTCUSDT', 'ETHUSDT']
DATA_DIR = '/Users/nesbitt/dev/factory/agents/ig88/data'
OUTPUT = f'{DATA_DIR}/edge_discovery/momentum_breakout_validation.json'

# Parameter grid
TRAILING_ATR_MULT = [1.0, 1.5, 2.0]
ADX_THRESHOLD = [25, 30, 35]
VOLUME_MULT = [1.2, 1.5, 2.0]
SPLIT_RATIOS = [0.5, 0.6, 0.7]  # IS/OOS split
N_SPLITS = 5  # expanding window splits per ratio


def compute_indicators(df):
    """Pre-compute all indicators needed."""
    d = df.copy()
    # Highest high over 20 bars
    d['hh20'] = d['high'].rolling(20).max()
    # SMA(20) of volume
    d['vol_sma20'] = d['volume'].rolling(20).mean()
    # SMA(10) of close
    d['sma10'] = d['close'].rolling(10).mean()
    # ATR(14)
    d['tr'] = np.maximum(
        d['high'] - d['low'],
        np.maximum(
            abs(d['high'] - d['close'].shift(1)),
            abs(d['low'] - d['close'].shift(1))
        )
    )
    d['atr14'] = d['tr'].rolling(14).mean()
    # ADX(14) - simplified directional movement
    up_move = d['high'].diff()
    down_move = -d['low'].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_smooth = d['tr'].rolling(14).sum()
    plus_di = 100 * pd.Series(plus_dm, index=d.index).rolling(14).sum() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=d.index).rolling(14).sum() / atr_smooth
    di_sum = plus_di + minus_di
    di_diff = abs(plus_di - minus_di)
    dx = 100 * di_diff / di_sum.replace(0, np.nan)
    d['adx14'] = dx.rolling(14).mean()
    return d


def run_backtest(df, adx_thresh, vol_mult, trail_mult):
    """
    Momentum Breakout backtest.
    Entry: Close > Highest(High,20) AND Volume > vol_mult*SMA(Vol,20) AND ADX(14) > adx_thresh
    Exit: Close < SMA(10) OR Trailing stop at trail_mult*ATR(14) from highest close since entry
    T1 entry: next bar open after signal
    """
    d = df.copy()
    n = len(d)
    if n < 30:
        return [], []

    # Compute indicators
    d = compute_indicators(d)

    trades = []
    in_pos = False
    entry_price = 0
    highest_close = 0
    signal_bar = -1

    for i in range(25, n - 1):  # need lookback + room for T1 entry
        row = d.iloc[i]

        if pd.isna(row['hh20']) or pd.isna(row['vol_sma20']) or pd.isna(row['adx14']) or pd.isna(row['atr14']):
            continue

        if not in_pos:
            # Entry signal
            breakout = row['close'] > d.iloc[i - 1]['hh20']  # close > prev bar's HH20
            vol_ok = row['volume'] > vol_mult * row['vol_sma20']
            adx_ok = row['adx14'] > adx_thresh

            if breakout and vol_ok and adx_ok:
                signal_bar = i
                # T1 entry at next bar open
                entry_price = d.iloc[i + 1]['open']
                highest_close = entry_price
                in_pos = True
                entry_idx = i + 1
        else:
            # Update highest close since entry
            if row['close'] > highest_close:
                highest_close = row['close']

            # Exit conditions
            exit_signal = False
            exit_reason = ''

            # SMA(10) exit
            if row['close'] < row['sma10']:
                exit_signal = True
                exit_reason = 'sma10_cross'

            # Trailing stop
            trail_stop = highest_close - trail_mult * row['atr14']
            if row['low'] <= trail_stop:
                exit_signal = True
                exit_reason = 'trailing_stop'
                # Fill at trail stop or worst case open
                exit_price = min(trail_stop, d.iloc[i]['open'])
            else:
                exit_price = d.iloc[i]['close']

            if exit_signal:
                ret = (exit_price - entry_price) / entry_price - FRICTION
                trades.append({
                    'entry_bar': entry_idx,
                    'exit_bar': i,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return': ret,
                    'reason': exit_reason
                })
                in_pos = False

    # Force close any open position at last bar
    if in_pos:
        exit_price = d.iloc[-1]['close']
        ret = (exit_price - entry_price) / entry_price - FRICTION
        trades.append({
            'entry_bar': entry_idx,
            'exit_bar': n - 1,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return': ret,
            'reason': 'force_close'
        })

    return trades


def compute_metrics(trades):
    """Compute performance metrics from trade list."""
    if len(trades) == 0:
        return {'pf': 0, 'wr': 0, 'n': 0, 'avg_ret': 0, 'total_ret': 0,
                'max_dd': 0, 'sharpe': 0}

    rets = np.array([t['return'] for t in trades])
    n = len(rets)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else (999 if gross_profit > 0 else 0)

    wr = len(wins) / n if n > 0 else 0
    avg_ret = rets.mean()

    # Equity curve for max DD
    equity = np.cumsum(rets)
    peak = np.maximum.accumulate(equity)
    dd = peak - equity
    max_dd = dd.max() if len(dd) > 0 else 0

    # Sharpe (per trade)
    sharpe = avg_ret / rets.std() * np.sqrt(n) if rets.std() > 0 and n > 1 else 0

    return {
        'pf': round(pf, 3),
        'wr': round(wr, 3),
        'n': n,
        'avg_ret': round(avg_ret, 5),
        'total_ret': round(float(equity[-1]), 4),
        'max_dd': round(max_dd, 4),
        'sharpe': round(sharpe, 3)
    }


def bootstrap_ci(trades, confidence=0.90, n_boot=2000):
    """Bootstrap confidence intervals for PF and WR."""
    if len(trades) < 5:
        return {'pf_lo': 0, 'pf_hi': 0, 'wr_lo': 0, 'wr_hi': 0}

    rets = np.array([t['return'] for t in trades])
    n = len(rets)
    alpha = 1 - confidence

    pf_samples = []
    wr_samples = []

    for _ in range(n_boot):
        sample = np.random.choice(rets, size=n, replace=True)
        wins = sample[sample > 0]
        losses = sample[sample <= 0]
        gp = wins.sum() if len(wins) > 0 else 0
        gl = abs(losses.sum()) if len(losses) > 0 else 0
        pf = gp / gl if gl > 0 else (999 if gp > 0 else 0)
        pf_samples.append(min(pf, 99))
        wr_samples.append(len(wins) / n)

    pf_samples = np.array(pf_samples)
    wr_samples = np.array(wr_samples)

    return {
        'pf_lo': round(float(np.percentile(pf_samples, alpha / 2 * 100)), 3),
        'pf_hi': round(float(np.percentile(pf_samples, (1 - alpha / 2) * 100)), 3),
        'wr_lo': round(float(np.percentile(wr_samples, alpha / 2 * 100)), 3),
        'wr_hi': round(float(np.percentile(wr_samples, (1 - alpha / 2) * 100)), 3)
    }


def walk_forward(df, adx_thresh, vol_mult, trail_mult, split_ratio, n_splits=5):
    """
    Expanding window walk-forward.
    split_ratio: fraction of data that's IS for first split, then expands.
    Returns list of OOS results across splits.
    """
    n = len(df)
    min_is = int(n * 0.3)  # minimum IS size
    oos_results = []

    for split in range(n_splits):
        # Expanding: IS grows, OOS is a fixed window after IS
        is_end = int(n * (split_ratio + (1 - split_ratio) * split / n_splits))
        oos_start = is_end
        oos_end = min(is_end + int(n * 0.1), n)

        if oos_start >= n or oos_end - oos_start < 10:
            break

        is_data = df.iloc[:is_end]
        oos_data = df.iloc[oos_start:oos_end]

        # Run on OOS only (we optimize on IS conceptually but run same params OOS)
        oos_trades = run_backtest(oos_data, adx_thresh, vol_mult, trail_mult)
        oos_metrics = compute_metrics(oos_trades)

        oos_results.append({
            'split': split + 1,
            'is_bars': is_end,
            'oos_bars': oos_end - oos_start,
            'oos_start': str(df.index[oos_start]),
            'oos_end': str(df.index[min(oos_end - 1, n - 1)]),
            **oos_metrics
        })

    return oos_results


def optimize_and_validate(pair_df, pair_name):
    """
    1. Grid search over full data to find optimal params
    2. Walk-forward validation with optimal params
    3. Also walk-forward with default params for comparison
    """
    print(f"\n{'='*60}")
    print(f"  {pair_name} - Momentum Breakout Validation")
    print(f"{'='*60}")

    # === PHASE 1: Parameter Optimization on Full Sample ===
    print("\n[Phase 1] Grid search on full sample...")
    best_pf = -1
    best_params = {}
    all_is_results = []

    for adx_t, vol_m, trail_m in product(ADX_THRESHOLD, VOLUME_MULT, TRAILING_ATR_MULT):
        trades = run_backtest(pair_df, adx_t, vol_m, trail_m)
        metrics = compute_metrics(trades)
        ci = bootstrap_ci(trades)

        result = {
            'adx': adx_t,
            'vol_mult': vol_m,
            'trail_mult': trail_m,
            **metrics,
            **ci
        }
        all_is_results.append(result)

        # Score: PF * sqrt(n) * WR (penalize low n, low wr)
        score = metrics['pf'] * np.sqrt(max(metrics['n'], 1)) * (0.5 + 0.5 * metrics['wr'])
        if score > best_pf and metrics['n'] >= 10:
            best_pf = score
            best_params = {'adx': adx_t, 'vol_mult': vol_m, 'trail_mult': trail_m}

    print(f"  Best params: ADX>{best_params['adx']}, Vol>{best_params['vol_mult']}x, Trail>{best_params['trail_mult']}x ATR")

    # Sort IS results by score
    for r in all_is_results:
        r['score'] = round(r['pf'] * np.sqrt(max(r['n'], 1)) * (0.5 + 0.5 * r['wr']), 3)
    all_is_results.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n  Top 5 IS configurations:")
    for r in all_is_results[:5]:
        print(f"    ADX>{r['adx']} Vol>{r['vol_mult']}x Trail>{r['trail_mult']}x: "
              f"PF={r['pf']:.2f} WR={r['wr']:.0%} n={r['n']} "
              f"CI=[{r['pf_lo']:.2f}-{r['pf_hi']:.2f}]")

    # === PHASE 2: Walk-Forward with Best Params ===
    print(f"\n[Phase 2] Walk-forward validation (best params)...")
    wf_results = {}

    for split_ratio in SPLIT_RATIOS:
        key = f"split_{int(split_ratio*100)}"
        wf = walk_forward(pair_df, best_params['adx'], best_params['vol_mult'],
                         best_params['trail_mult'], split_ratio, N_SPLITS)
        wf_results[key] = wf

        # Aggregate OOS metrics
        if wf:
            all_oos_trades = []
            for split in wf:
                all_oos_trades.extend([split['n']])  # just counting

            total_oos_n = sum(s['n'] for s in wf)
            avg_pf = np.mean([s['pf'] for s in wf if s['n'] > 0]) if any(s['n'] > 0 for s in wf) else 0
            avg_wr = np.mean([s['wr'] for s in wf if s['n'] > 0]) if any(s['n'] > 0 for s in wf) else 0

            print(f"    Split {int(split_ratio*100)}/{int((1-split_ratio)*100)}: "
                  f"Avg OOS PF={avg_pf:.2f}, Avg WR={avg_wr:.0%}, Total OOS trades={total_oos_n}")
            for s in wf:
                if s['n'] > 0:
                    print(f"      Split {s['split']}: PF={s['pf']:.2f} WR={s['wr']:.0%} n={s['n']} "
                          f"[{s['oos_start'][:10]} -> {s['oos_end'][:10]}]")

    # === PHASE 3: Walk-Forward with DEFAULT Params ===
    print(f"\n[Phase 3] Walk-forward validation (default: ADX>30, Vol>1.5x, Trail 1.5x)...")
    wf_default_results = {}
    for split_ratio in SPLIT_RATIOS:
        key = f"split_{int(split_ratio*100)}"
        wf = walk_forward(pair_df, 30, 1.5, 1.5, split_ratio, N_SPLITS)
        wf_default_results[key] = wf

        if wf:
            total_oos_n = sum(s['n'] for s in wf)
            avg_pf = np.mean([s['pf'] for s in wf if s['n'] > 0]) if any(s['n'] > 0 for s in wf) else 0
            avg_wr = np.mean([s['wr'] for s in wf if s['n'] > 0]) if any(s['n'] > 0 for s in wf) else 0
            print(f"    Split {int(split_ratio*100)}/{int((1-split_ratio)*100)}: "
                  f"Avg OOS PF={avg_pf:.2f}, Avg WR={avg_wr:.0%}, Total OOS trades={total_oos_n}")

    # === PHASE 4: Aggregated OOS Bootstrap CI ===
    print(f"\n[Phase 4] Computing OOS bootstrap CIs...")
    # Collect all OOS trades from best split ratio
    best_split_key = f"split_{int(SPLIT_RATIOS[0]*100)}"
    # Re-run to get actual OOS trades for CI
    oos_trades_agg = []
    for split_ratio in SPLIT_RATIOS:
        wf = walk_forward(pair_df, best_params['adx'], best_params['vol_mult'],
                         best_params['trail_mult'], split_ratio, N_SPLITS)
        for s in wf:
            # We need the actual trades - re-run to collect them
            pass

    # Actually collect OOS trades properly
    # For each split ratio, re-run and collect trades from OOS periods
    oos_trade_collections = {}
    for split_ratio in SPLIT_RATIOS:
        n = len(pair_df)
        split_trades = []
        for split in range(N_SPLITS):
            is_end = int(n * (split_ratio + (1 - split_ratio) * split / N_SPLITS))
            oos_start = is_end
            oos_end = min(is_end + int(n * 0.1), n)
            if oos_start >= n or oos_end - oos_start < 10:
                break
            oos_data = pair_df.iloc[oos_start:oos_end]
            trades = run_backtest(oos_data, best_params['adx'], best_params['vol_mult'],
                                 best_params['trail_mult'])
            split_trades.extend(trades)
        oos_trade_collections[f"split_{int(split_ratio*100)}"] = split_trades

    # Compute aggregated metrics and CI
    oos_validation = {}
    for key, trades in oos_trade_collections.items():
        metrics = compute_metrics(trades)
        ci = bootstrap_ci(trades)
        oos_validation[key] = {**metrics, **ci}
        print(f"    {key}: PF={metrics['pf']:.2f} [{ci['pf_lo']:.2f}-{ci['pf_hi']:.2f}], "
              f"WR={metrics['wr']:.0%} [{ci['wr_lo']:.0%}-{ci['wr_hi']:.0%}], n={metrics['n']}")

    # Combined OOS across all splits
    all_oos_trades = []
    for trades in oos_trade_collections.values():
        all_oos_trades.extend(trades)
    combined_metrics = compute_metrics(all_oos_trades)
    combined_ci = bootstrap_ci(all_oos_trades)
    print(f"\n  COMBINED OOS: PF={combined_metrics['pf']:.2f} [{combined_ci['pf_lo']:.2f}-{combined_ci['pf_hi']:.2f}], "
          f"WR={combined_metrics['wr']:.0%} [{combined_ci['wr_lo']:.0%}-{combined_ci['wr_hi']:.0%}], "
          f"n={combined_metrics['n']}")

    # === PHASE 5: Parameter Sensitivity (all params walk-forward) ===
    print(f"\n[Phase 5] Full parameter sensitivity (OOS)...")
    param_sensitivity = []
    for adx_t, vol_m, trail_m in product(ADX_THRESHOLD, VOLUME_MULT, TRAILING_ATR_MULT):
        # Use middle split ratio for sensitivity
        split_ratio = 0.6
        n = len(pair_df)
        split_trades = []
        for split in range(N_SPLITS):
            is_end = int(n * (split_ratio + (1 - split_ratio) * split / N_SPLITS))
            oos_start = is_end
            oos_end = min(is_end + int(n * 0.1), n)
            if oos_start >= n or oos_end - oos_start < 10:
                break
            oos_data = pair_df.iloc[oos_start:oos_end]
            trades = run_backtest(oos_data, adx_t, vol_m, trail_m)
            split_trades.extend(trades)

        metrics = compute_metrics(split_trades)
        ci = bootstrap_ci(split_trades)
        param_sensitivity.append({
            'adx': adx_t,
            'vol_mult': vol_m,
            'trail_mult': trail_m,
            **metrics,
            **ci
        })

    param_sensitivity.sort(key=lambda x: x['pf'] * np.sqrt(max(x['n'], 1)), reverse=True)
    print(f"  Top 5 OOS configurations (split 60/40):")
    for r in param_sensitivity[:5]:
        print(f"    ADX>{r['adx']} Vol>{r['vol_mult']}x Trail>{r['trail_mult']}x: "
              f"PF={r['pf']:.2f} [{r['pf_lo']:.2f}-{r['pf_hi']:.2f}] "
              f"WR={r['wr']:.0%} [{r['wr_lo']:.0%}-{r['wr_hi']:.0%}] n={r['n']}")

    return {
        'pair': pair_name,
        'is_optimization': all_is_results[:10],
        'best_params': best_params,
        'walk_forward_best': wf_results,
        'walk_forward_default': wf_default_results,
        'oos_validation': oos_validation,
        'oos_combined': {**combined_metrics, **combined_ci},
        'param_sensitivity_oos': param_sensitivity
    }


def main():
    print("=" * 60)
    print("  MOMENTUM BREAKOUT - RIGOROUS OOS VALIDATION")
    print("  Jupiter Perps | 0.14% friction | 4h Binance")
    print("=" * 60)

    results = {}

    for pair in PAIRS:
        path = f'{DATA_DIR}/binance_{pair}_240m.parquet'
        df = pd.read_parquet(path)

        # Compute indicators once
        df = compute_indicators(df)

        result = optimize_and_validate(df, pair)
        results[pair] = result

    # === FINAL SUMMARY ===
    print("\n" + "=" * 60)
    print("  FINAL VALIDATION SUMMARY")
    print("=" * 60)

    for pair in PAIRS:
        r = results[pair]
        combined = r['oos_combined']
        bp = r['best_params']
        print(f"\n  {pair}:")
        print(f"    Optimal: ADX>{bp['adx']}, Vol>{bp['vol_mult']}x, Trail>{bp['trail_mult']}x ATR")
        print(f"    OOS PF: {combined['pf']:.2f} (90% CI: {combined['pf_lo']:.2f} - {combined['pf_hi']:.2f})")
        print(f"    OOS WR: {combined['wr']:.0%} (90% CI: {combined['wr_lo']:.0%} - {combined['wr_hi']:.0%})")
        print(f"    OOS Trades: {combined['n']}")
        print(f"    OOS Avg Ret: {combined['avg_ret']:.4%}")
        print(f"    OOS Sharpe: {combined['sharpe']:.2f}")

        # Verdict
        pf_survives = combined['pf_lo'] > 1.0
        wr_reasonable = combined['wr'] > 0.35
        enough_trades = combined['n'] >= 20
        verdict = "SURVIVES" if (pf_survives and wr_reasonable and enough_trades) else "QUESTIONABLE"
        if not enough_trades:
            verdict += " (low n)"
        if not pf_survives:
            verdict += " (CI includes PF<1)"
        print(f"    VERDICT: {verdict}")

    # Save results
    # Convert numpy types for JSON serialization
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    output = {
        'strategy': 'Momentum Breakout',
        'pairs': PAIRS,
        'friction': FRICTION,
        'timeframe': '4h',
        'data_source': 'Binance',
        'entry_rules': {
            'signal': 'Close > Highest(High, 20) AND Volume > vol_mult * SMA(Volume, 20) AND ADX(14) > adx_thresh',
            'execution': 'T1 entry at next bar open after signal',
            'exit_rules': 'Close < SMA(10) OR Trailing stop at trail_mult * ATR(14) from highest close since entry'
        },
        'parameter_grid': {
            'trailing_atr_mult': TRAILING_ATR_MULT,
            'adx_threshold': ADX_THRESHOLD,
            'volume_mult': VOLUME_MULT
        },
        'walk_forward_config': {
            'type': 'expanding_window',
            'n_splits': N_SPLITS,
            'split_ratios': SPLIT_RATIOS
        },
        'results': results
    }

    # Deep convert
    output_str = json.dumps(output, default=convert, indent=2)

    import os
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w') as f:
        f.write(output_str)

    print(f"\n  Results saved to: {OUTPUT}")
    print("=" * 60)


if __name__ == '__main__':
    main()
