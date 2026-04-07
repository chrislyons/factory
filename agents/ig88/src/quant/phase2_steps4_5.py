#!/usr/bin/env python3
"""Phase 2, Steps 4-5: Momentum-Reversal Hybrid Signal & Walk-Forward Backtest.

Implements:
4. Autocorrelation-based momentum/reversal hybrid signal with BTC correlation
   and regime filters
5. Walk-forward out-of-sample backtest with per-window parameter calibration
"""

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
PLOTS = ROOT / 'docs' / 'ig88' / 'plots'
PLOTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data():
    """Load SOL, BTC, ETH parquet files and compute log returns."""
    dfs = {}
    for sym in ['sol', 'btc', 'eth']:
        path = DATA / f'{sym}_usdt_1min.parquet'
        df = pd.read_parquet(path)
        df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
        df = df.sort_values('datetime').set_index('datetime')
        df.index = df.index.tz_localize(None)
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        df = df.dropna(subset=['log_return'])
        dfs[sym] = df
        print(f'{sym.upper()}: {len(df):,} rows, {df.index.min()} to {df.index.max()}')
    return dfs


# ---------------------------------------------------------------------------
# Step 4: Signal construction helpers
# ---------------------------------------------------------------------------

def _rolling_autocorr(arr, window, lag):
    """Fast rolling autocorrelation using numpy vectorization."""
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(window + lag - 1, n):
        chunk = arr[i - window + 1:i + 1]
        if np.any(np.isnan(chunk)):
            continue
        m = np.mean(chunk)
        demeaned = chunk - m
        var = np.sum(demeaned ** 2)
        if var == 0:
            result[i] = 0.0
            continue
        cov = np.sum(demeaned[lag:] * demeaned[:-lag])
        result[i] = cov / var
    return result


def compute_autocorrelations(returns, window=60):
    """Compute rolling lag-1 and lag-5 autocorrelations of log returns."""
    arr = returns.values.astype(np.float64)
    lag1_vals = _rolling_autocorr(arr, window, 1)
    lag5_vals = _rolling_autocorr(arr, window, 5)
    lag1_ac = pd.Series(lag1_vals, index=returns.index)
    lag5_ac = pd.Series(lag5_vals, index=returns.index)
    return lag1_ac, lag5_ac


def classify_regimes(sol_df, vol_median_threshold=None):
    """Classify into 4 regimes. If vol_median_threshold is None, compute from data."""
    df = sol_df.copy()
    df['realized_vol'] = df['log_return'].rolling(60).std()
    df['rolling_ret'] = df['log_return'].rolling(15).sum()

    if vol_median_threshold is None:
        vol_median_threshold = df['realized_vol'].median()

    df['vol_regime'] = np.where(df['realized_vol'] > vol_median_threshold, 'high_vol', 'low_vol')
    df['dir_regime'] = np.where(df['rolling_ret'] >= 0, 'up', 'down')
    df['regime'] = df['vol_regime'] + '_' + df['dir_regime']
    return df, vol_median_threshold


def generate_signals(sol_df, btc_df, lag1_thresh, lag5_thresh, vol_median,
                     precomputed_ac=None):
    """Generate momentum-reversal hybrid signals with BTC and regime filters."""
    sol, _ = classify_regimes(sol_df, vol_median_threshold=vol_median)

    if precomputed_ac is not None:
        sol['lag1_ac'] = precomputed_ac[0].reindex(sol.index)
        sol['lag5_ac'] = precomputed_ac[1].reindex(sol.index)
    else:
        arr = sol['log_return'].values.astype(np.float64)
        sol['lag1_ac'] = _rolling_autocorr(arr, 60, 1)
        sol['lag5_ac'] = _rolling_autocorr(arr, 60, 5)

    common_idx = sol.index.intersection(btc_df.index)
    sol = sol.loc[common_idx]
    btc_aligned = btc_df.loc[common_idx]

    sol['btc_sol_corr'] = sol['log_return'].rolling(60).corr(btc_aligned['log_return'])
    sol['btc_5m_ret'] = btc_aligned['log_return'].rolling(5).sum()
    sol['sol_5m_ret'] = sol['log_return'].rolling(5).sum()

    rev_fires = (sol['lag1_ac'] < lag1_thresh).values
    rev_dir = np.where(sol['sol_5m_ret'].values > 0, -1, 1)

    mom_fires = (sol['lag5_ac'] > lag5_thresh).values
    mom_dir = np.where(sol['sol_5m_ret'].values > 0, 1, -1)

    # Handle NaN
    rev_fires = np.where(np.isnan(sol['lag1_ac'].values), False, rev_fires)
    mom_fires = np.where(np.isnan(sol['lag5_ac'].values), False, mom_fires)

    signal = np.zeros(len(sol))
    signal_type = np.full(len(sol), 'none', dtype=object)

    for i in range(len(sol)):
        rev_on = rev_fires[i]
        mom_on = mom_fires[i]

        if rev_on and mom_on:
            rev_d = rev_dir[i]
            mom_d = mom_dir[i]
            if rev_d == mom_d:
                signal[i] = rev_d * 2
                signal_type[i] = 'both'
            else:
                signal[i] = 0
                signal_type[i] = 'conflict'
        elif rev_on:
            signal[i] = rev_dir[i]
            signal_type[i] = 'reversal'
        elif mom_on:
            signal[i] = mom_dir[i]
            signal_type[i] = 'momentum'

    sol['raw_signal'] = signal
    sol['signal_type'] = signal_type

    # BTC correlation filter
    filtered_signal = sol['raw_signal'].copy()
    high_corr = sol['btc_sol_corr'] > 0.7
    btc_confirms = np.sign(sol['btc_5m_ret']) == np.sign(sol['raw_signal'])
    filtered_signal[high_corr & ~btc_confirms] = 0

    mid_corr = (sol['btc_sol_corr'] >= 0.3) & (sol['btc_sol_corr'] <= 0.7)
    filtered_signal[mid_corr] = filtered_signal[mid_corr] * 0.5

    sol['corr_filtered_signal'] = filtered_signal

    # Regime filter
    final_signal = sol['corr_filtered_signal'].copy()
    final_signal[sol['regime'] == 'high_vol_down'] = 0

    low_vol_down_mask = sol['regime'] == 'low_vol_down'
    non_reversal = sol['signal_type'] != 'reversal'
    final_signal[low_vol_down_mask & non_reversal] = 0

    sol['signal'] = final_signal
    return sol


# ---------------------------------------------------------------------------
# Step 4: Signal analysis & plotting
# ---------------------------------------------------------------------------

def section_signal_analysis(dfs):
    """Analyze the momentum-reversal hybrid signal."""
    print('\n' + '=' * 80)
    print('STEP 4: MOMENTUM-REVERSAL HYBRID SIGNAL ANALYSIS')
    print('=' * 80)

    sol_df = dfs['sol'].copy()
    btc_df = dfs['btc'].copy()

    print('\nComputing rolling autocorrelations...')
    arr = sol_df['log_return'].values.astype(np.float64)
    lag1_ac = pd.Series(_rolling_autocorr(arr, 60, 1), index=sol_df.index)
    lag5_ac = pd.Series(_rolling_autocorr(arr, 60, 5), index=sol_df.index)

    print(f'\nLag-1 Autocorrelation Statistics:')
    print(f'  Mean:   {lag1_ac.mean():.4f}')
    print(f'  Std:    {lag1_ac.std():.4f}')
    print(f'  Median: {lag1_ac.median():.4f}')
    print(f'  < -0.05 (reversal zone): {(lag1_ac < -0.05).mean() * 100:.1f}%')

    print(f'\nLag-5 Autocorrelation Statistics:')
    print(f'  Mean:   {lag5_ac.mean():.4f}')
    print(f'  Std:    {lag5_ac.std():.4f}')
    print(f'  Median: {lag5_ac.median():.4f}')
    print(f'  > 0.05 (momentum zone):  {(lag5_ac > 0.05).mean() * 100:.1f}%')

    sol_regimes, vol_median = classify_regimes(sol_df)
    print(f'\nVolatility median threshold: {vol_median:.6f}')

    sol_signals = generate_signals(sol_df, btc_df, lag1_thresh=-0.05,
                                   lag5_thresh=0.05, vol_median=vol_median)

    sig_vals = sol_signals['signal']
    active_signals = sig_vals[sig_vals != 0]
    print(f'\nSignal Distribution (full dataset, default thresholds):')
    print(f'  Total candles:    {len(sig_vals):,}')
    print(f'  Active signals:   {len(active_signals):,} ({len(active_signals)/len(sig_vals)*100:.1f}%)')
    print(f'  Long signals:     {(sig_vals > 0).sum():,}')
    print(f'  Short signals:    {(sig_vals < 0).sum():,}')
    print(f'  Strong (weight=2): {(sig_vals.abs() == 2).sum():,}')

    print(f'\nSignal Type Breakdown:')
    for stype in ['reversal', 'momentum', 'both', 'conflict', 'none']:
        count = (sol_signals['signal_type'] == stype).sum()
        pct = count / len(sol_signals) * 100
        print(f'  {stype:<12} {count:>8,} ({pct:.1f}%)')

    # Plot
    fig, axes = plt.subplots(3, 2, figsize=(16, 12))

    ax = axes[0, 0]
    lag1_clean = lag1_ac.dropna()
    ax.hist(lag1_clean, bins=100, color='steelblue', alpha=0.7, edgecolor='none')
    ax.axvline(x=-0.05, color='red', linestyle='--', label='Reversal threshold')
    ax.axvline(x=0, color='gray', linestyle='-', alpha=0.5)
    ax.set_title('Lag-1 Autocorrelation Distribution')
    ax.set_xlabel('Lag-1 AC')
    ax.legend()

    ax = axes[0, 1]
    lag5_clean = lag5_ac.dropna()
    ax.hist(lag5_clean, bins=100, color='coral', alpha=0.7, edgecolor='none')
    ax.axvline(x=0.05, color='red', linestyle='--', label='Momentum threshold')
    ax.axvline(x=0, color='gray', linestyle='-', alpha=0.5)
    ax.set_title('Lag-5 Autocorrelation Distribution')
    ax.set_xlabel('Lag-5 AC')
    ax.legend()

    ax = axes[1, 0]
    n_plot = min(20000, len(lag1_clean))
    ax.plot(lag1_clean.index[-n_plot:], lag1_clean.iloc[-n_plot:], linewidth=0.3, color='steelblue')
    ax.axhline(y=-0.05, color='red', linestyle='--', alpha=0.7)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_title('Rolling Lag-1 Autocorrelation (last 20k candles)')
    ax.set_ylabel('AC')

    ax = axes[1, 1]
    ax.plot(lag5_clean.index[-n_plot:], lag5_clean.iloc[-n_plot:], linewidth=0.3, color='coral')
    ax.axhline(y=0.05, color='red', linestyle='--', alpha=0.7)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_title('Rolling Lag-5 Autocorrelation (last 20k candles)')
    ax.set_ylabel('AC')

    ax = axes[2, 0]
    sig_nonzero = sol_signals.loc[sol_signals['signal'] != 0, 'signal']
    n_sig_plot = min(5000, len(sig_nonzero))
    if n_sig_plot > 0:
        ax.scatter(sig_nonzero.index[-n_sig_plot:], sig_nonzero.iloc[-n_sig_plot:],
                   s=1, alpha=0.5, c=np.where(sig_nonzero.iloc[-n_sig_plot:] > 0, 'green', 'red'))
    ax.set_title(f'Signal Values (last {n_sig_plot} active signals)')
    ax.set_ylabel('Signal')
    ax.set_yticks([-2, -1, 0, 1, 2])

    ax = axes[2, 1]
    regime_signal_counts = sol_signals.groupby('regime')['signal'].apply(lambda x: (x != 0).sum())
    colors = {'low_vol_up': '#2ecc71', 'low_vol_down': '#f39c12',
              'high_vol_up': '#3498db', 'high_vol_down': '#e74c3c'}
    regime_order = ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']
    bars = [regime_signal_counts.get(r, 0) for r in regime_order]
    bar_colors = [colors[r] for r in regime_order]
    ax.bar(regime_order, bars, color=bar_colors)
    ax.set_title('Active Signals by Regime')
    ax.set_ylabel('Count')
    ax.tick_params(axis='x', rotation=30)

    plt.tight_layout()
    plt.savefig(PLOTS / 'momentum_reversal_signal.png', dpi=150)
    plt.close()
    print(f'\nPlot saved: docs/ig88/plots/momentum_reversal_signal.png')

    return sol_signals


# ---------------------------------------------------------------------------
# Step 5: Walk-forward backtest
# ---------------------------------------------------------------------------

def calibrate_thresholds(train_sol, train_btc, vol_median, precomputed_ac,
                         grid_points=5):
    """Grid search for optimal thresholds using precomputed autocorrelations."""
    lag1_grid = np.linspace(-0.15, -0.02, grid_points)
    lag5_grid = np.linspace(0.02, 0.15, grid_points)

    best_sharpe = -np.inf
    best_params = (-0.05, 0.05)

    for l1 in lag1_grid:
        for l5 in lag5_grid:
            try:
                signals = generate_signals(train_sol, train_btc, l1, l5, vol_median,
                                           precomputed_ac=precomputed_ac)
                trades = simulate_trades(signals)
                if len(trades) < 10:
                    continue
                sharpe = compute_sharpe(trades)
                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = (l1, l5)
            except Exception:
                continue

    return best_params, best_sharpe


def simulate_trades(signals_df, holding_period=5, stop_loss_pct=0.003):
    """Simulate trades from signal DataFrame."""
    trades = []
    df = signals_df.reset_index()
    time_col = df.columns[0]
    prices = df['close'].values
    opens = df['open'].values if 'open' in df.columns else prices
    timestamps = df[time_col].values
    sig = df['signal'].values
    regimes = df['regime'].values if 'regime' in df.columns else np.full(len(df), 'unknown')
    signal_types = df['signal_type'].values if 'signal_type' in df.columns else np.full(len(df), 'unknown')
    highs = df['high'].values if 'high' in df.columns else prices
    lows = df['low'].values if 'low' in df.columns else prices

    i = 0
    n = len(df)
    while i < n - holding_period - 1:
        if sig[i] == 0 or np.isnan(sig[i]):
            i += 1
            continue

        direction = 1 if sig[i] > 0 else -1
        weight = abs(sig[i])

        entry_idx = i + 1
        entry_price = opens[entry_idx]
        entry_time = timestamps[entry_idx]

        exit_idx = entry_idx
        exit_price = entry_price
        stopped = False

        for j in range(1, holding_period + 1):
            if entry_idx + j >= n:
                break
            if direction == 1:
                adverse_price = lows[entry_idx + j]
            else:
                adverse_price = highs[entry_idx + j]

            adverse_move = (adverse_price / entry_price - 1) * direction
            if adverse_move < -stop_loss_pct:
                exit_idx = entry_idx + j
                exit_price = entry_price * (1 - direction * stop_loss_pct)
                stopped = True
                break
            exit_idx = entry_idx + j
            exit_price = prices[exit_idx]

        exit_time = timestamps[exit_idx]
        ret = (exit_price / entry_price - 1) * direction

        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'long' if direction == 1 else 'short',
            'weight': weight,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'return_pct': ret * 100,
            'regime': regimes[i] if i < len(regimes) else 'unknown',
            'signal_type': signal_types[i] if i < len(signal_types) else 'unknown',
            'stopped': stopped,
            'holding_candles': exit_idx - entry_idx,
        })

        i = exit_idx + 1

    return pd.DataFrame(trades)


def compute_sharpe(trades_df, annualize_factor=np.sqrt(525600 / 5)):
    """Compute annualized Sharpe from trade returns."""
    if len(trades_df) == 0:
        return 0.0
    rets = trades_df['return_pct'] / 100
    if rets.std() == 0:
        return 0.0
    return (rets.mean() / rets.std()) * annualize_factor


def compute_metrics(trades_df, label=''):
    """Compute comprehensive trade metrics."""
    if len(trades_df) == 0:
        return {'label': label, 'total_trades': 0, 'win_rate': 0, 'avg_win_pct': 0,
                'avg_loss_pct': 0, 'profit_factor': 0, 'sharpe_ann': 0,
                'max_drawdown_pct': 0, 'total_return_pct': 0, 'stop_rate_pct': 0,
                'avg_holding': 0}

    rets = trades_df['return_pct']
    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    cum_ret = (1 + rets / 100).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min() * 100

    sharpe = compute_sharpe(trades_df)

    gross_wins = wins.sum() if len(wins) > 0 else 0
    gross_losses = abs(losses.sum()) if len(losses) > 0 else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else np.inf

    return {
        'label': label,
        'total_trades': len(trades_df),
        'win_rate': len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0,
        'avg_win_pct': wins.mean() if len(wins) > 0 else 0,
        'avg_loss_pct': losses.mean() if len(losses) > 0 else 0,
        'profit_factor': profit_factor,
        'sharpe_ann': sharpe,
        'max_drawdown_pct': max_dd,
        'total_return_pct': (cum_ret.iloc[-1] - 1) * 100 if len(cum_ret) > 0 else 0,
        'stop_rate_pct': trades_df['stopped'].mean() * 100 if 'stopped' in trades_df.columns else 0,
        'avg_holding': trades_df['holding_candles'].mean() if 'holding_candles' in trades_df.columns else 0,
    }


def walk_forward_backtest(dfs):
    """Execute walk-forward out-of-sample backtest."""
    print('\n' + '=' * 80)
    print('STEP 5: WALK-FORWARD OUT-OF-SAMPLE BACKTEST')
    print('=' * 80)

    sol_full = dfs['sol'].copy()
    btc_full = dfs['btc'].copy()

    start_date = sol_full.index.min()
    end_date = sol_full.index.max()
    total_days = (end_date - start_date).days
    print(f'\nData range: {start_date} to {end_date} ({total_days} days)')

    month_offset = pd.DateOffset(months=1)
    first_month_start = start_date.replace(day=1, hour=0, minute=0, second=0)
    months = []
    m = first_month_start
    while m < end_date:
        months.append(m)
        m = m + month_offset
    months.append(m)

    print(f'Month boundaries: {len(months)} ({months[0].strftime("%Y-%m")} to {months[-1].strftime("%Y-%m")})')

    windows = []
    for i in range(3, len(months) - 1):
        train_start = months[i - 3]
        train_end = months[i]
        test_start = months[i]
        test_end = months[i + 1]

        train_mask = (sol_full.index >= train_start) & (sol_full.index < train_end)
        test_mask = (sol_full.index >= test_start) & (sol_full.index < test_end)
        if train_mask.sum() > 1000 and test_mask.sum() > 100:
            windows.append({
                'train_start': train_start, 'train_end': train_end,
                'test_start': test_start, 'test_end': test_end,
                'train_rows': train_mask.sum(), 'test_rows': test_mask.sum(),
            })

    print(f'\nWalk-forward windows: {len(windows)}')
    for i, w in enumerate(windows):
        print(f'  Window {i+1}: Train {w["train_start"].strftime("%Y-%m-%d")} to '
              f'{w["train_end"].strftime("%Y-%m-%d")} ({w["train_rows"]:,} rows) | '
              f'Test {w["test_start"].strftime("%Y-%m-%d")} to '
              f'{w["test_end"].strftime("%Y-%m-%d")} ({w["test_rows"]:,} rows)')

    all_trades = []
    window_metrics = []
    window_equities = []

    for wi, w in enumerate(windows):
        window_num = wi + 1
        print(f'\n{"-"*60}')
        print(f'WINDOW {window_num}: Train {w["train_start"].strftime("%Y-%m")} to '
              f'{w["train_end"].strftime("%Y-%m")} | Test {w["test_start"].strftime("%Y-%m")}')
        print(f'{"-"*60}')

        train_sol = sol_full.loc[
            (sol_full.index >= w['train_start']) & (sol_full.index < w['train_end'])
        ].copy()
        train_btc = btc_full.loc[
            (btc_full.index >= w['train_start']) & (btc_full.index < w['train_end'])
        ].copy()
        test_sol = sol_full.loc[
            (sol_full.index >= w['test_start']) & (sol_full.index < w['test_end'])
        ].copy()
        test_btc = btc_full.loc[
            (btc_full.index >= w['test_start']) & (btc_full.index < w['test_end'])
        ].copy()

        if len(train_sol) < 1000 or len(test_sol) < 100:
            print(f'  Skipping: insufficient data (train={len(train_sol)}, test={len(test_sol)})')
            continue

        train_regimes, vol_median = classify_regimes(train_sol)
        print(f'  Train vol median: {vol_median:.6f}')

        # Precompute autocorrelations for training set
        print(f'  Computing training autocorrelations...')
        ta = train_sol['log_return'].values.astype(np.float64)
        train_lag1 = pd.Series(_rolling_autocorr(ta, 60, 1), index=train_sol.index)
        train_lag5 = pd.Series(_rolling_autocorr(ta, 60, 5), index=train_sol.index)

        print(f'  Calibrating thresholds (5x5 grid)...')
        best_params, best_train_sharpe = calibrate_thresholds(
            train_sol, train_btc, vol_median, (train_lag1, train_lag5), grid_points=5
        )
        print(f'  Best lag1_thresh={best_params[0]:.3f}, lag5_thresh={best_params[1]:.3f}, '
              f'train Sharpe={best_train_sharpe:.2f}')

        # Precompute test autocorrelations
        print(f'  Computing test autocorrelations...')
        xa = test_sol['log_return'].values.astype(np.float64)
        test_lag1 = pd.Series(_rolling_autocorr(xa, 60, 1), index=test_sol.index)
        test_lag5 = pd.Series(_rolling_autocorr(xa, 60, 5), index=test_sol.index)

        print(f'  Generating OOS signals...')
        test_signals = generate_signals(test_sol, test_btc,
                                        lag1_thresh=best_params[0],
                                        lag5_thresh=best_params[1],
                                        vol_median=vol_median,
                                        precomputed_ac=(test_lag1, test_lag5))

        trades = simulate_trades(test_signals)
        trades['window'] = window_num

        if len(trades) == 0:
            print(f'  No trades generated in test window.')
            window_metrics.append(compute_metrics(trades, label=f'Window {window_num}'))
            continue

        print(f'  OOS trades: {len(trades)}')
        all_trades.append(trades)

        metrics = compute_metrics(trades, label=f'Window {window_num}')
        window_metrics.append(metrics)

        print(f'  Win rate:       {metrics["win_rate"]:.1f}%')
        print(f'  Avg win:        {metrics["avg_win_pct"]:.4f}%')
        print(f'  Avg loss:       {metrics["avg_loss_pct"]:.4f}%')
        print(f'  Profit factor:  {metrics["profit_factor"]:.2f}')
        print(f'  Sharpe (ann):   {metrics["sharpe_ann"]:.2f}')
        print(f'  Max drawdown:   {metrics["max_drawdown_pct"]:.2f}%')
        print(f'  Total return:   {metrics["total_return_pct"]:.2f}%')
        print(f'  Stop rate:      {metrics["stop_rate_pct"]:.1f}%')

        cum_ret = (1 + trades['return_pct'] / 100).cumprod()
        window_equities.append({
            'window': window_num,
            'equity': cum_ret.values,
            'times': trades['entry_time'].values,
        })

    # Aggregate results
    print('\n' + '=' * 80)
    print('AGGREGATE OUT-OF-SAMPLE RESULTS')
    print('=' * 80)

    if len(all_trades) == 0:
        print('No trades generated across any window.')
        return pd.DataFrame(), pd.DataFrame()

    all_trades_df = pd.concat(all_trades, ignore_index=True)
    agg_metrics = compute_metrics(all_trades_df, label='Aggregate OOS')

    print(f'\n{"Metric":<25} {"Value":>15}')
    print(f'{"":-<40}')
    print(f'{"Total OOS trades":<25} {agg_metrics["total_trades"]:>15,}')
    print(f'{"Win rate":<25} {agg_metrics["win_rate"]:>14.1f}%')
    print(f'{"Avg win":<25} {agg_metrics["avg_win_pct"]:>14.4f}%')
    print(f'{"Avg loss":<25} {agg_metrics["avg_loss_pct"]:>14.4f}%')
    print(f'{"Profit factor":<25} {agg_metrics["profit_factor"]:>15.2f}')
    print(f'{"Sharpe (annualized)":<25} {agg_metrics["sharpe_ann"]:>15.2f}')
    print(f'{"Max drawdown":<25} {agg_metrics["max_drawdown_pct"]:>14.2f}%')
    print(f'{"Total return":<25} {agg_metrics["total_return_pct"]:>14.2f}%')
    print(f'{"Stop-loss rate":<25} {agg_metrics["stop_rate_pct"]:>14.1f}%')
    print(f'{"Avg holding (candles)":<25} {agg_metrics["avg_holding"]:>15.1f}')

    print(f'\n{"Window":<12} {"Trades":>8} {"WinRate":>8} {"Sharpe":>8} {"Return":>10} {"MaxDD":>8}')
    print(f'{"":-<54}')
    for m in window_metrics:
        if m['total_trades'] > 0:
            print(f'{m["label"]:<12} {m["total_trades"]:>8} '
                  f'{m["win_rate"]:>7.1f}% {m["sharpe_ann"]:>8.2f} '
                  f'{m["total_return_pct"]:>9.2f}% {m["max_drawdown_pct"]:>7.2f}%')

    print(f'\nReturn by Regime (OOS):')
    print(f'{"Regime":<20} {"Trades":>8} {"WinRate":>8} {"AvgRet":>10} {"TotalRet":>10}')
    print(f'{"":-<56}')
    for regime in ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']:
        rmask = all_trades_df['regime'] == regime
        if rmask.sum() > 0:
            rtrades = all_trades_df[rmask]
            rwin = (rtrades['return_pct'] > 0).mean() * 100
            ravg = rtrades['return_pct'].mean()
            rtot = ((1 + rtrades['return_pct'] / 100).prod() - 1) * 100
            print(f'{regime:<20} {rmask.sum():>8} {rwin:>7.1f}% {ravg:>9.4f}% {rtot:>9.2f}%')
        else:
            print(f'{regime:<20} {0:>8}       -         -          -')

    print(f'\nReturn by Signal Type (OOS):')
    print(f'{"Type":<12} {"Trades":>8} {"WinRate":>8} {"AvgRet":>10}')
    print(f'{"":-<38}')
    for stype in ['reversal', 'momentum', 'both']:
        smask = all_trades_df['signal_type'] == stype
        if smask.sum() > 0:
            strades = all_trades_df[smask]
            swin = (strades['return_pct'] > 0).mean() * 100
            savg = strades['return_pct'].mean()
            print(f'{stype:<12} {smask.sum():>8} {swin:>7.1f}% {savg:>9.4f}%')

    # Save outputs
    all_trades_df.to_csv(DATA / 'walkforward_trades.csv', index=False)
    print(f'\nTrade log saved: data/walkforward_trades.csv')

    summary_df = pd.DataFrame(window_metrics + [agg_metrics])
    summary_df.to_csv(DATA / 'walkforward_summary.csv', index=False)
    print(f'Summary stats saved: data/walkforward_summary.csv')

    # Plots
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))

    ax = axes[0]
    for we in window_equities:
        ax.plot(range(len(we['equity'])), we['equity'],
                label=f'Window {we["window"]}', linewidth=1.2)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Walk-Forward Equity Curves (per window)')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.legend()
    ax.grid(True, alpha=0.3)

    ax = axes[1]
    agg_cum = (1 + all_trades_df['return_pct'] / 100).cumprod()
    ax.plot(range(len(agg_cum)), agg_cum, color='steelblue', linewidth=1.2)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Aggregate OOS Equity Curve')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.grid(True, alpha=0.3)

    trade_counts = [0]
    for we in window_equities:
        trade_counts.append(trade_counts[-1] + len(we['equity']))
    for i in range(0, len(trade_counts) - 1, 2):
        ax.axvspan(trade_counts[i], trade_counts[i + 1], alpha=0.05, color='blue')

    plt.tight_layout()
    plt.savefig(PLOTS / 'walkforward_equity.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/walkforward_equity.png')

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    ax = axes[0]
    regime_order = ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']
    plot_data = []
    plot_labels = []
    for r in regime_order:
        rdata = all_trades_df.loc[all_trades_df['regime'] == r, 'return_pct']
        if len(rdata) > 0:
            plot_data.append(rdata.values)
            plot_labels.append(r)
    if plot_data:
        bp = ax.boxplot(plot_data, labels=plot_labels, patch_artist=True)
        colors_list = ['#2ecc71', '#f39c12', '#3498db', '#e74c3c']
        for patch, color in zip(bp['boxes'], colors_list[:len(plot_data)]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Trade Returns by Regime')
    ax.set_ylabel('Return (%)')
    ax.tick_params(axis='x', rotation=30)

    ax = axes[1]
    for r in regime_order:
        rdata = all_trades_df.loc[all_trades_df['regime'] == r, 'return_pct']
        if len(rdata) > 0:
            cum = (1 + rdata.values / 100).cumprod()
            ax.plot(cum, label=r, linewidth=1.2)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Cumulative Return by Regime')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.legend(fontsize=8)

    ax = axes[2]
    stype_order = ['reversal', 'momentum', 'both']
    stype_data = []
    stype_labels = []
    for s in stype_order:
        sdata = all_trades_df.loc[all_trades_df['signal_type'] == s, 'return_pct']
        if len(sdata) > 0:
            stype_data.append(sdata.values)
            stype_labels.append(s)
    if stype_data:
        bp2 = ax.boxplot(stype_data, labels=stype_labels, patch_artist=True)
        scolors = ['#9b59b6', '#e67e22', '#1abc9c']
        for patch, color in zip(bp2['boxes'], scolors[:len(stype_data)]):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Trade Returns by Signal Type')
    ax.set_ylabel('Return (%)')

    plt.tight_layout()
    plt.savefig(PLOTS / 'regime_returns.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/regime_returns.png')

    return all_trades_df, summary_df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print('=' * 80)
    print('IG-88 PHASE 2, STEPS 4-5: SIGNAL & WALK-FORWARD BACKTEST')
    print('=' * 80)

    dfs = load_data()

    # Step 4: Signal analysis
    sol_signals = section_signal_analysis(dfs)

    # Step 5: Walk-forward backtest
    all_trades, summary = walk_forward_backtest(dfs)

    print('\n' + '=' * 80)
    print('PHASE 2 STEPS 4-5 COMPLETE')
    print('=' * 80)
    print(f'\nOutputs:')
    print(f'  - data/walkforward_trades.csv')
    print(f'  - data/walkforward_summary.csv')
    print(f'  - docs/ig88/plots/momentum_reversal_signal.png')
    print(f'  - docs/ig88/plots/walkforward_equity.png')
    print(f'  - docs/ig88/plots/regime_returns.png')


if __name__ == '__main__':
    main()
