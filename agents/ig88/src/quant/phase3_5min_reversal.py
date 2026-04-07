#!/usr/bin/env python3
"""Phase 3: 5-Minute Reversal-Only Strategy with ATR Stops & Regime Filtering.

Builds on Phase 2 findings:
- Momentum signals are net negative; removed entirely
- high_vol_up + reversal is the cash cow (3,273 trades, +30.34%)
- Non-stopped trades avg +0.045% (above maker fees)
- 10,000+ noise trades at +0.00% median dilute the 2,000-3,000 trades with edge

Phase 3 changes:
1. Kill momentum signals — reversal only
2. Resample to 5-minute bars (reduce noise, wider spreads per bar)
3. Regime-focused filtering (only trade high_vol_up full weight, low_vol_up half)
4. Extended holding + ATR-based dynamic stops
5. Walk-forward revalidation with 0.04% round-trip transaction costs
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
from itertools import product

# Paths
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
PLOTS = ROOT / 'docs' / 'ig88' / 'plots'
PLOTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading & resampling
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
        print(f'{sym.upper()}: {len(df):,} 1-min rows, {df.index.min()} to {df.index.max()}')
    return dfs


def resample_to_5min(df):
    """Resample 1-min OHLCV to 5-min bars with proper aggregation.

    Aggregation rules:
      open  = first
      high  = max
      low   = min
      close = last
      volume = sum
    """
    ohlcv_agg = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }
    resampled = df.resample('5min').agg(ohlcv_agg).dropna(subset=['close'])
    resampled['log_return'] = np.log(resampled['close'] / resampled['close'].shift(1))
    resampled = resampled.dropna(subset=['log_return'])
    return resampled


def load_and_resample():
    """Load 1-min data and resample all symbols to 5-min bars."""
    dfs_1min = load_data()

    print(f'\nResampling to 5-minute bars...')
    dfs_5min = {}
    for sym, df in dfs_1min.items():
        df5 = resample_to_5min(df)
        dfs_5min[sym] = df5
        print(f'  {sym.upper()}: {len(df):,} 1-min -> {len(df5):,} 5-min bars')

    return dfs_5min


# ---------------------------------------------------------------------------
# Core computation helpers
# ---------------------------------------------------------------------------

def _rolling_autocorr(arr, window, lag):
    """Fast rolling autocorrelation using numpy vectorization.

    Identical to Phase 2 implementation for consistency.
    """
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
    """Compute rolling lag-1 autocorrelation of log returns.

    At 5-min bars, window=60 = 300 minutes = 5 hours of data.
    Only lag-1 is needed (momentum signals removed).
    """
    arr = returns.values.astype(np.float64)
    lag1_vals = _rolling_autocorr(arr, window, 1)
    lag1_ac = pd.Series(lag1_vals, index=returns.index)
    return lag1_ac


def compute_atr(df, period=14):
    """Compute Average True Range on OHLCV data.

    TR = max(H-L, |H-Cprev|, |L-Cprev|)
    ATR = rolling mean of TR over `period` bars.
    """
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr


def classify_regimes(sol_df, vol_median_threshold=None):
    """Classify into 4 regimes on 5-min data.

    realized_vol = rolling(60).std() on 5-min log returns (5 hours)
    rolling_ret = rolling(15).sum() on 5-min log returns (75 minutes)
    """
    df = sol_df.copy()
    df['realized_vol'] = df['log_return'].rolling(60).std()
    df['rolling_ret'] = df['log_return'].rolling(15).sum()

    if vol_median_threshold is None:
        vol_median_threshold = df['realized_vol'].median()

    df['vol_regime'] = np.where(df['realized_vol'] > vol_median_threshold, 'high_vol', 'low_vol')
    df['dir_regime'] = np.where(df['rolling_ret'] >= 0, 'up', 'down')
    df['regime'] = df['vol_regime'] + '_' + df['dir_regime']
    return df, vol_median_threshold


# ---------------------------------------------------------------------------
# Step 1 + Step 3: Reversal-only signals with regime filtering
# ---------------------------------------------------------------------------

def generate_reversal_signals(sol_df, btc_df, lag1_thresh, vol_median,
                              precomputed_ac=None):
    """Generate reversal-ONLY signals with regime filtering.

    Step 1 (Kill momentum):
      - Only fires when lag1_ac < lag1_thresh (reversal zone)
      - Direction: -sign(recent_return) (mean reversion)
      - No momentum pathway, no 'both' combination logic

    Step 3 (Regime filter):
      - high_vol_up   -> Trade (full signal weight = 1.0)
      - low_vol_up    -> Trade (reduced weight = 0.5)
      - low_vol_down  -> Skip (zero signal)
      - high_vol_down -> Skip (zero signal, catastrophic tail risk)

    BTC correlation filter (simplified for 5-min):
      - corr > 0.7 AND signal conflicts with BTC direction -> suppress
      - corr < 0.3 -> pass unmodified (decorrelation window)
      - 0.3 <= corr <= 0.7 -> reduce weight by 0.5
    """
    sol, _ = classify_regimes(sol_df, vol_median_threshold=vol_median)

    # Compute or reuse lag-1 autocorrelation
    if precomputed_ac is not None:
        sol['lag1_ac'] = precomputed_ac.reindex(sol.index)
    else:
        arr = sol['log_return'].values.astype(np.float64)
        sol['lag1_ac'] = _rolling_autocorr(arr, 60, 1)

    # ATR for dynamic stops (will be used by simulate_trades_v3)
    sol['atr'] = compute_atr(sol, period=14)

    # Align SOL and BTC on common index
    common_idx = sol.index.intersection(btc_df.index)
    sol = sol.loc[common_idx]
    btc_aligned = btc_df.loc[common_idx]

    # BTC correlation and directional signals
    sol['btc_sol_corr'] = sol['log_return'].rolling(60).corr(btc_aligned['log_return'])
    sol['btc_5bar_ret'] = btc_aligned['log_return'].rolling(5).sum()
    sol['sol_5bar_ret'] = sol['log_return'].rolling(5).sum()

    # --- Step 1: Reversal signal only ---
    rev_fires = (sol['lag1_ac'] < lag1_thresh).values
    # Handle NaN in autocorrelation
    rev_fires = np.where(np.isnan(sol['lag1_ac'].values), False, rev_fires)
    # Mean reversion: trade against recent direction
    rev_dir = np.where(sol['sol_5bar_ret'].values > 0, -1, 1)

    signal = np.zeros(len(sol))
    signal_type = np.full(len(sol), 'none', dtype=object)

    for i in range(len(sol)):
        if rev_fires[i]:
            signal[i] = rev_dir[i]
            signal_type[i] = 'reversal'

    sol['raw_signal'] = signal
    sol['signal_type'] = signal_type

    # --- BTC correlation filter ---
    filtered_signal = sol['raw_signal'].copy()
    corr = sol['btc_sol_corr']

    # High correlation: suppress if BTC direction conflicts
    high_corr = corr > 0.7
    btc_confirms = np.sign(sol['btc_5bar_ret']) == np.sign(sol['raw_signal'])
    filtered_signal[high_corr & ~btc_confirms] = 0

    # Mid-range correlation: reduce weight
    mid_corr = (corr >= 0.3) & (corr <= 0.7)
    filtered_signal[mid_corr] = filtered_signal[mid_corr] * 0.5

    # Low correlation (< 0.3): pass unmodified (decorrelation window)

    sol['corr_filtered_signal'] = filtered_signal

    # --- Step 3: Regime filter ---
    final_signal = sol['corr_filtered_signal'].copy()

    # Kill all signals in downtrend regimes
    final_signal[sol['regime'] == 'high_vol_down'] = 0
    final_signal[sol['regime'] == 'low_vol_down'] = 0

    # Reduce weight in low_vol_up
    low_vol_up_mask = sol['regime'] == 'low_vol_up'
    final_signal[low_vol_up_mask] = final_signal[low_vol_up_mask] * 0.5

    # high_vol_up: full weight (no modification needed)

    sol['signal'] = final_signal
    return sol


# ---------------------------------------------------------------------------
# Step 4: Trade simulation with ATR stops and extended holding
# ---------------------------------------------------------------------------

def simulate_trades_v3(signals_df, holding_period=5, atr_mult=1.5,
                       cost_per_trade=0.0004):
    """Simulate trades with ATR-based stops and transaction costs.

    Entry: next bar open after signal fires
    Stop: entry_price +/- atr_mult * ATR (direction-dependent)
    Exit: stop hit OR holding_period bars elapsed (exit at close)
    Cost: cost_per_trade subtracted from each trade return (0.04% round-trip)
    Return: (exit_price/entry_price - 1) * direction - cost_per_trade
    """
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
    atrs = df['atr'].values if 'atr' in df.columns else np.full(len(df), np.nan)

    i = 0
    n = len(df)
    while i < n - holding_period - 1:
        if sig[i] == 0 or np.isnan(sig[i]):
            i += 1
            continue

        direction = 1 if sig[i] > 0 else -1
        weight = abs(sig[i])

        entry_idx = i + 1
        if entry_idx >= n:
            break
        entry_price = opens[entry_idx]
        entry_time = timestamps[entry_idx]

        # ATR-based stop level
        atr_at_entry = atrs[i] if not np.isnan(atrs[i]) else atrs[entry_idx]
        if np.isnan(atr_at_entry):
            # Fallback: skip trade if ATR not available
            i += 1
            continue

        if direction == 1:
            stop_price = entry_price - atr_mult * atr_at_entry
        else:
            stop_price = entry_price + atr_mult * atr_at_entry

        exit_idx = entry_idx
        exit_price = entry_price
        stopped = False

        for j in range(1, holding_period + 1):
            bar_idx = entry_idx + j
            if bar_idx >= n:
                break

            # Check stop hit using intra-bar extremes
            if direction == 1:
                # Long: stopped if low breaches stop
                if lows[bar_idx] <= stop_price:
                    exit_idx = bar_idx
                    exit_price = stop_price
                    stopped = True
                    break
            else:
                # Short: stopped if high breaches stop
                if highs[bar_idx] >= stop_price:
                    exit_idx = bar_idx
                    exit_price = stop_price
                    stopped = True
                    break

            exit_idx = bar_idx
            exit_price = prices[bar_idx]  # close of bar

        # If we didn't move at all, use entry bar close
        if exit_idx == entry_idx:
            exit_price = prices[entry_idx]

        exit_time = timestamps[exit_idx]
        holding_bars = exit_idx - entry_idx

        gross_return = (exit_price / entry_price - 1) * direction
        net_return = gross_return - cost_per_trade

        trades.append({
            'entry_time': entry_time,
            'exit_time': exit_time,
            'direction': 'long' if direction == 1 else 'short',
            'weight': weight,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'gross_return_pct': gross_return * 100,
            'net_return_pct': net_return * 100,
            'regime': regimes[i] if i < len(regimes) else 'unknown',
            'signal_type': signal_types[i] if i < len(signal_types) else 'unknown',
            'stopped': stopped,
            'holding_bars': holding_bars,
            'atr_at_entry': atr_at_entry,
            'stop_price': stop_price,
        })

        # Skip past the holding period to avoid overlapping trades
        i = exit_idx + 1

    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Step 5: Calibration and walk-forward
# ---------------------------------------------------------------------------

def compute_sharpe(trades_df, return_col='net_return_pct'):
    """Compute annualized Sharpe from per-trade returns.

    Annualization: sqrt(525600 / avg_holding_minutes)
    where avg_holding_minutes = avg_holding_bars * 5 (5-min bars).
    """
    if len(trades_df) == 0:
        return 0.0
    rets = trades_df[return_col] / 100
    if rets.std() == 0:
        return 0.0
    avg_holding_bars = trades_df['holding_bars'].mean()
    avg_holding_minutes = avg_holding_bars * 5
    if avg_holding_minutes <= 0:
        avg_holding_minutes = 5  # minimum 1 bar
    annualize_factor = np.sqrt(525600 / avg_holding_minutes)
    return (rets.mean() / rets.std()) * annualize_factor


def compute_metrics(trades_df, label='', return_col='net_return_pct'):
    """Compute comprehensive trade metrics (net of costs by default)."""
    if len(trades_df) == 0:
        return {
            'label': label, 'total_trades': 0, 'win_rate': 0,
            'avg_return_pct': 0, 'avg_win_pct': 0, 'avg_loss_pct': 0,
            'profit_factor': 0, 'sharpe_ann': 0,
            'max_drawdown_pct': 0, 'total_return_pct': 0,
            'gross_total_return_pct': 0, 'stop_rate_pct': 0,
            'avg_holding_bars': 0, 'avg_holding_minutes': 0,
        }

    rets = trades_df[return_col]
    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    cum_ret = (1 + rets / 100).cumprod()
    running_max = cum_ret.cummax()
    drawdown = (cum_ret - running_max) / running_max
    max_dd = drawdown.min() * 100

    sharpe = compute_sharpe(trades_df, return_col=return_col)

    gross_wins = wins.sum() if len(wins) > 0 else 0
    gross_losses = abs(losses.sum()) if len(losses) > 0 else 0
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else np.inf

    # Gross total return (for comparison)
    gross_rets = trades_df['gross_return_pct'] if 'gross_return_pct' in trades_df.columns else rets
    gross_total = ((1 + gross_rets / 100).prod() - 1) * 100

    avg_holding = trades_df['holding_bars'].mean() if 'holding_bars' in trades_df.columns else 0

    return {
        'label': label,
        'total_trades': len(trades_df),
        'win_rate': len(wins) / len(trades_df) * 100 if len(trades_df) > 0 else 0,
        'avg_return_pct': rets.mean(),
        'avg_win_pct': wins.mean() if len(wins) > 0 else 0,
        'avg_loss_pct': losses.mean() if len(losses) > 0 else 0,
        'profit_factor': profit_factor,
        'sharpe_ann': sharpe,
        'max_drawdown_pct': max_dd,
        'total_return_pct': (cum_ret.iloc[-1] - 1) * 100 if len(cum_ret) > 0 else 0,
        'gross_total_return_pct': gross_total,
        'stop_rate_pct': trades_df['stopped'].mean() * 100 if 'stopped' in trades_df.columns else 0,
        'avg_holding_bars': avg_holding,
        'avg_holding_minutes': avg_holding * 5,
    }


def calibrate_v3(train_sol, train_btc, vol_median, precomputed_ac):
    """Grid search over lag1_thresh x holding_period x ATR_mult.

    Grid:
      lag1_thresh:    [-0.15, -0.12, -0.09, -0.06, -0.03] (5 values)
      holding_period: [3, 5, 8, 12]                        (4 values)
      atr_mult:       [1.0, 1.5, 2.0, 2.5]                (4 values)
    Total: 80 combinations

    Objective: maximize Sharpe ratio on training data (net of 0.04% costs).
    """
    lag1_grid = [-0.15, -0.12, -0.09, -0.06, -0.03]
    holding_grid = [3, 5, 8, 12]
    atr_grid = [1.0, 1.5, 2.0, 2.5]

    best_sharpe = -np.inf
    best_params = {
        'lag1_thresh': -0.09,
        'holding_period': 5,
        'atr_mult': 1.5,
    }
    results = []

    for l1, hp, am in product(lag1_grid, holding_grid, atr_grid):
        try:
            signals = generate_reversal_signals(
                train_sol, train_btc, l1, vol_median,
                precomputed_ac=precomputed_ac,
            )
            trades = simulate_trades_v3(signals, holding_period=hp,
                                        atr_mult=am, cost_per_trade=0.0004)
            if len(trades) < 10:
                continue
            sharpe = compute_sharpe(trades, return_col='net_return_pct')
            avg_ret = trades['net_return_pct'].mean()
            n_trades = len(trades)

            results.append({
                'lag1_thresh': l1, 'holding_period': hp, 'atr_mult': am,
                'sharpe': sharpe, 'avg_ret': avg_ret, 'n_trades': n_trades,
            })

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = {
                    'lag1_thresh': l1,
                    'holding_period': hp,
                    'atr_mult': am,
                }
        except Exception:
            continue

    return best_params, best_sharpe, pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Step 2: Signal analysis on 5-min bars
# ---------------------------------------------------------------------------

def section_signal_analysis(dfs):
    """Analyze the reversal-only signal on 5-min data."""
    print('\n' + '=' * 80)
    print('PHASE 3 SIGNAL ANALYSIS: REVERSAL-ONLY ON 5-MIN BARS')
    print('=' * 80)

    sol_df = dfs['sol'].copy()
    btc_df = dfs['btc'].copy()

    print('\nComputing rolling lag-1 autocorrelation (window=60, 5-min bars = 5 hours)...')
    lag1_ac = compute_autocorrelations(sol_df['log_return'], window=60)

    print(f'\nLag-1 Autocorrelation Statistics (5-min):')
    print(f'  Mean:   {lag1_ac.mean():.4f}')
    print(f'  Std:    {lag1_ac.std():.4f}')
    print(f'  Median: {lag1_ac.median():.4f}')
    print(f'  < -0.03 (reversal zone): {(lag1_ac < -0.03).mean() * 100:.1f}%')
    print(f'  < -0.06 (strong reversal): {(lag1_ac < -0.06).mean() * 100:.1f}%')
    print(f'  < -0.09 (deep reversal): {(lag1_ac < -0.09).mean() * 100:.1f}%')

    # ATR stats
    atr = compute_atr(sol_df, period=14)
    atr_clean = atr.dropna()
    print(f'\nATR(14) Statistics (5-min bars):')
    print(f'  Mean:   ${atr_clean.mean():.4f}')
    print(f'  Std:    ${atr_clean.std():.4f}')
    print(f'  Median: ${atr_clean.median():.4f}')
    print(f'  ATR/Price ratio: {(atr_clean / sol_df.loc[atr_clean.index, "close"]).mean() * 100:.4f}%')

    # Regime distribution
    sol_regimes, vol_median = classify_regimes(sol_df)
    print(f'\nVolatility median threshold (5-min): {vol_median:.6f}')
    print(f'\nRegime Distribution:')
    for regime in ['low_vol_up', 'low_vol_down', 'high_vol_up', 'high_vol_down']:
        count = (sol_regimes['regime'] == regime).sum()
        pct = count / len(sol_regimes) * 100
        print(f'  {regime:<18} {count:>8,} bars ({pct:.1f}%)')

    # Generate signals with default threshold
    sol_signals = generate_reversal_signals(
        sol_df, btc_df, lag1_thresh=-0.06, vol_median=vol_median,
    )

    sig_vals = sol_signals['signal']
    active_signals = sig_vals[sig_vals != 0]
    print(f'\nSignal Distribution (full dataset, lag1_thresh=-0.06):')
    print(f'  Total 5-min bars:  {len(sig_vals):,}')
    print(f'  Active signals:    {len(active_signals):,} ({len(active_signals)/len(sig_vals)*100:.1f}%)')
    print(f'  Long signals:      {(sig_vals > 0).sum():,}')
    print(f'  Short signals:     {(sig_vals < 0).sum():,}')

    # Regime breakdown of active signals
    print(f'\nActive Signals by Regime:')
    for regime in ['high_vol_up', 'low_vol_up', 'low_vol_down', 'high_vol_down']:
        mask = (sol_signals['regime'] == regime) & (sol_signals['signal'] != 0)
        count = mask.sum()
        print(f'  {regime:<18} {count:>6} signals')

    # Quick sanity: simulate with defaults
    trades_default = simulate_trades_v3(sol_signals, holding_period=5,
                                         atr_mult=1.5, cost_per_trade=0.0004)
    if len(trades_default) > 0:
        avg_gross = trades_default['gross_return_pct'].mean()
        avg_net = trades_default['net_return_pct'].mean()
        print(f'\nQuick sanity (hp=5, atr_mult=1.5):')
        print(f'  Trades: {len(trades_default):,}')
        print(f'  Avg gross return: {avg_gross:.4f}%')
        print(f'  Avg net return:   {avg_net:.4f}%')
        print(f'  Cost impact:      {avg_gross - avg_net:.4f}%')
        print(f'  Stop rate:        {trades_default["stopped"].mean() * 100:.1f}%')
        print(f'  Avg holding:      {trades_default["holding_bars"].mean():.1f} bars '
              f'({trades_default["holding_bars"].mean() * 5:.0f} min)')

    return sol_signals


# ---------------------------------------------------------------------------
# Step 5: Walk-forward backtest
# ---------------------------------------------------------------------------

def walk_forward_v3(dfs):
    """Walk-forward with all Phase 3 changes.

    Same 7-window structure as Phase 2 (3-month train, 1-month OOS test).
    Reversal signals only, regime-filtered, ATR-based stops, extended holding.
    Calibration grid: lag1_thresh x holding_period x ATR_mult (80 combos).
    Transaction costs applied to every trade.
    """
    print('\n' + '=' * 80)
    print('PHASE 3 WALK-FORWARD BACKTEST (5-MIN, REVERSAL-ONLY, ATR STOPS)')
    print('=' * 80)

    sol_full = dfs['sol'].copy()
    btc_full = dfs['btc'].copy()

    start_date = sol_full.index.min()
    end_date = sol_full.index.max()
    total_days = (end_date - start_date).days
    print(f'\nData range: {start_date} to {end_date} ({total_days} days)')
    print(f'Bar count: {len(sol_full):,} 5-min bars')

    # Build month boundaries
    month_offset = pd.DateOffset(months=1)
    first_month_start = start_date.replace(day=1, hour=0, minute=0, second=0)
    months = []
    m = first_month_start
    while m < end_date:
        months.append(m)
        m = m + month_offset
    months.append(m)

    print(f'Month boundaries: {len(months)} ({months[0].strftime("%Y-%m")} to {months[-1].strftime("%Y-%m")})')

    # Construct walk-forward windows
    windows = []
    for i in range(3, len(months) - 1):
        train_start = months[i - 3]
        train_end = months[i]
        test_start = months[i]
        test_end = months[i + 1]

        train_mask = (sol_full.index >= train_start) & (sol_full.index < train_end)
        test_mask = (sol_full.index >= test_start) & (sol_full.index < test_end)
        if train_mask.sum() > 200 and test_mask.sum() > 20:
            windows.append({
                'train_start': train_start, 'train_end': train_end,
                'test_start': test_start, 'test_end': test_end,
                'train_rows': train_mask.sum(), 'test_rows': test_mask.sum(),
            })

    print(f'\nWalk-forward windows: {len(windows)}')
    for i, w in enumerate(windows):
        print(f'  Window {i+1}: Train {w["train_start"].strftime("%Y-%m-%d")} to '
              f'{w["train_end"].strftime("%Y-%m-%d")} ({w["train_rows"]:,} bars) | '
              f'Test {w["test_start"].strftime("%Y-%m-%d")} to '
              f'{w["test_end"].strftime("%Y-%m-%d")} ({w["test_rows"]:,} bars)')

    all_trades = []
    window_metrics = []
    window_equities = []
    calibration_log = []

    for wi, w in enumerate(windows):
        window_num = wi + 1
        print(f'\n{"-"*60}')
        print(f'WINDOW {window_num}: Train {w["train_start"].strftime("%Y-%m")} to '
              f'{w["train_end"].strftime("%Y-%m")} | Test {w["test_start"].strftime("%Y-%m")}')
        print(f'{"-"*60}')

        # Slice train and test data
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

        if len(train_sol) < 200 or len(test_sol) < 20:
            print(f'  Skipping: insufficient data (train={len(train_sol)}, test={len(test_sol)})')
            continue

        # Regime calibration from training data
        _, vol_median = classify_regimes(train_sol)
        print(f'  Train vol median: {vol_median:.6f}')

        # Precompute autocorrelations for training set
        print(f'  Computing training autocorrelations...')
        train_lag1 = compute_autocorrelations(train_sol['log_return'], window=60)

        # Calibrate: 80-combination grid search
        print(f'  Calibrating (5 x 4 x 4 = 80 combinations)...')
        best_params, best_train_sharpe, cal_results = calibrate_v3(
            train_sol, train_btc, vol_median, train_lag1,
        )
        cal_results['window'] = window_num
        calibration_log.append(cal_results)

        print(f'  Best params: lag1_thresh={best_params["lag1_thresh"]:.3f}, '
              f'holding_period={best_params["holding_period"]}, '
              f'atr_mult={best_params["atr_mult"]:.1f}')
        print(f'  Train Sharpe: {best_train_sharpe:.2f}')

        # Precompute test autocorrelations
        print(f'  Computing test autocorrelations...')
        test_lag1 = compute_autocorrelations(test_sol['log_return'], window=60)

        # Generate OOS signals
        print(f'  Generating OOS signals...')
        test_signals = generate_reversal_signals(
            test_sol, test_btc,
            lag1_thresh=best_params['lag1_thresh'],
            vol_median=vol_median,
            precomputed_ac=test_lag1,
        )

        # Simulate OOS trades
        trades = simulate_trades_v3(
            test_signals,
            holding_period=best_params['holding_period'],
            atr_mult=best_params['atr_mult'],
            cost_per_trade=0.0004,
        )
        trades['window'] = window_num

        if len(trades) == 0:
            print(f'  No trades generated in test window.')
            window_metrics.append(compute_metrics(trades, label=f'Window {window_num}'))
            continue

        print(f'  OOS trades: {len(trades)}')
        all_trades.append(trades)

        # Compute and display metrics
        metrics = compute_metrics(trades, label=f'Window {window_num}')
        window_metrics.append(metrics)

        print(f'  Win rate:            {metrics["win_rate"]:.1f}%')
        print(f'  Avg net return:      {metrics["avg_return_pct"]:.4f}%')
        print(f'  Avg win:             {metrics["avg_win_pct"]:.4f}%')
        print(f'  Avg loss:            {metrics["avg_loss_pct"]:.4f}%')
        print(f'  Profit factor:       {metrics["profit_factor"]:.2f}')
        print(f'  Sharpe (ann):        {metrics["sharpe_ann"]:.2f}')
        print(f'  Max drawdown:        {metrics["max_drawdown_pct"]:.2f}%')
        print(f'  Net total return:    {metrics["total_return_pct"]:.2f}%')
        print(f'  Gross total return:  {metrics["gross_total_return_pct"]:.2f}%')
        print(f'  Stop rate:           {metrics["stop_rate_pct"]:.1f}%')
        print(f'  Avg holding:         {metrics["avg_holding_bars"]:.1f} bars '
              f'({metrics["avg_holding_minutes"]:.0f} min)')

        # Equity curve for this window
        cum_ret = (1 + trades['net_return_pct'] / 100).cumprod()
        window_equities.append({
            'window': window_num,
            'equity': cum_ret.values,
            'times': trades['entry_time'].values,
        })

    # -----------------------------------------------------------------------
    # Aggregate results
    # -----------------------------------------------------------------------
    print('\n' + '=' * 80)
    print('AGGREGATE OUT-OF-SAMPLE RESULTS (NET OF 0.04% COSTS)')
    print('=' * 80)

    if len(all_trades) == 0:
        print('No trades generated across any window.')
        return pd.DataFrame(), pd.DataFrame()

    all_trades_df = pd.concat(all_trades, ignore_index=True)
    agg_metrics = compute_metrics(all_trades_df, label='Aggregate OOS')

    print(f'\n{"Metric":<30} {"Value":>15}')
    print(f'{"":-<45}')
    print(f'{"Total OOS trades":<30} {agg_metrics["total_trades"]:>15,}')
    print(f'{"Win rate":<30} {agg_metrics["win_rate"]:>14.1f}%')
    print(f'{"Avg net return/trade":<30} {agg_metrics["avg_return_pct"]:>14.4f}%')
    print(f'{"Avg win":<30} {agg_metrics["avg_win_pct"]:>14.4f}%')
    print(f'{"Avg loss":<30} {agg_metrics["avg_loss_pct"]:>14.4f}%')
    print(f'{"Profit factor":<30} {agg_metrics["profit_factor"]:>15.2f}')
    print(f'{"Sharpe (annualized)":<30} {agg_metrics["sharpe_ann"]:>15.2f}')
    print(f'{"Max drawdown":<30} {agg_metrics["max_drawdown_pct"]:>14.2f}%')
    print(f'{"Net total return":<30} {agg_metrics["total_return_pct"]:>14.2f}%')
    print(f'{"Gross total return":<30} {agg_metrics["gross_total_return_pct"]:>14.2f}%')
    print(f'{"Stop-loss rate":<30} {agg_metrics["stop_rate_pct"]:>14.1f}%')
    print(f'{"Avg holding (bars)":<30} {agg_metrics["avg_holding_bars"]:>15.1f}')
    print(f'{"Avg holding (minutes)":<30} {agg_metrics["avg_holding_minutes"]:>15.0f}')

    # Per-window summary table
    print(f'\n{"Window":<12} {"Trades":>8} {"WinRate":>8} {"Sharpe":>8} '
          f'{"NetRet":>10} {"GrossRet":>10} {"MaxDD":>8}')
    print(f'{"":-<64}')
    for m in window_metrics:
        if m['total_trades'] > 0:
            print(f'{m["label"]:<12} {m["total_trades"]:>8} '
                  f'{m["win_rate"]:>7.1f}% {m["sharpe_ann"]:>8.2f} '
                  f'{m["total_return_pct"]:>9.2f}% '
                  f'{m["gross_total_return_pct"]:>9.2f}% '
                  f'{m["max_drawdown_pct"]:>7.2f}%')

    # Regime breakdown
    print(f'\nReturn by Regime (OOS, net of costs):')
    print(f'{"Regime":<20} {"Trades":>8} {"WinRate":>8} {"AvgNet":>10} {"TotalNet":>10}')
    print(f'{"":-<56}')
    for regime in ['high_vol_up', 'low_vol_up', 'low_vol_down', 'high_vol_down']:
        rmask = all_trades_df['regime'] == regime
        if rmask.sum() > 0:
            rtrades = all_trades_df[rmask]
            rwin = (rtrades['net_return_pct'] > 0).mean() * 100
            ravg = rtrades['net_return_pct'].mean()
            rtot = ((1 + rtrades['net_return_pct'] / 100).prod() - 1) * 100
            print(f'{regime:<20} {rmask.sum():>8} {rwin:>7.1f}% {ravg:>9.4f}% {rtot:>9.2f}%')
        else:
            print(f'{regime:<20} {0:>8}       -         -          -')

    # Direction breakdown
    print(f'\nReturn by Direction (OOS, net of costs):')
    print(f'{"Direction":<12} {"Trades":>8} {"WinRate":>8} {"AvgNet":>10}')
    print(f'{"":-<38}')
    for d in ['long', 'short']:
        dmask = all_trades_df['direction'] == d
        if dmask.sum() > 0:
            dtrades = all_trades_df[dmask]
            dwin = (dtrades['net_return_pct'] > 0).mean() * 100
            davg = dtrades['net_return_pct'].mean()
            print(f'{d:<12} {dmask.sum():>8} {dwin:>7.1f}% {davg:>9.4f}%')

    # Stopped vs non-stopped breakdown
    print(f'\nStopped vs Non-Stopped:')
    print(f'{"Status":<15} {"Trades":>8} {"AvgNet":>10} {"AvgGross":>10} {"WinRate":>8}')
    print(f'{"":-<51}')
    for stopped_val, label in [(True, 'Stopped'), (False, 'Non-stopped')]:
        smask = all_trades_df['stopped'] == stopped_val
        if smask.sum() > 0:
            strades = all_trades_df[smask]
            savg_net = strades['net_return_pct'].mean()
            savg_gross = strades['gross_return_pct'].mean()
            swin = (strades['net_return_pct'] > 0).mean() * 100
            print(f'{label:<15} {smask.sum():>8} {savg_net:>9.4f}% {savg_gross:>9.4f}% {swin:>7.1f}%')

    # -----------------------------------------------------------------------
    # Save outputs
    # -----------------------------------------------------------------------
    all_trades_df.to_csv(DATA / 'phase3_walkforward_trades.csv', index=False)
    print(f'\nTrade log saved: data/phase3_walkforward_trades.csv')

    summary_df = pd.DataFrame(window_metrics + [agg_metrics])
    summary_df.to_csv(DATA / 'phase3_walkforward_summary.csv', index=False)
    print(f'Summary saved: data/phase3_walkforward_summary.csv')

    if calibration_log:
        cal_df = pd.concat(calibration_log, ignore_index=True)
        cal_df.to_csv(DATA / 'phase3_calibration_log.csv', index=False)
        print(f'Calibration log saved: data/phase3_calibration_log.csv')

    # -----------------------------------------------------------------------
    # Plots
    # -----------------------------------------------------------------------
    _plot_equity_curves(all_trades_df, window_equities)
    _plot_regime_distribution(all_trades_df)

    # -----------------------------------------------------------------------
    # Go/No-Go gate
    # -----------------------------------------------------------------------
    _go_no_go_gate(agg_metrics)

    return all_trades_df, summary_df


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def _plot_equity_curves(all_trades_df, window_equities):
    """Plot equity curves: gross vs net, per window and aggregate."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Top-left: Per-window net equity curves
    ax = axes[0, 0]
    for we in window_equities:
        ax.plot(range(len(we['equity'])), we['equity'],
                label=f'Window {we["window"]}', linewidth=1.2)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Per-Window Net Equity Curves')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # Top-right: Aggregate gross vs net
    ax = axes[0, 1]
    agg_cum_net = (1 + all_trades_df['net_return_pct'] / 100).cumprod()
    agg_cum_gross = (1 + all_trades_df['gross_return_pct'] / 100).cumprod()
    ax.plot(range(len(agg_cum_net)), agg_cum_net,
            color='steelblue', linewidth=1.2, label='Net (after costs)')
    ax.plot(range(len(agg_cum_gross)), agg_cum_gross,
            color='coral', linewidth=1.2, alpha=0.7, label='Gross (before costs)')
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Aggregate OOS: Gross vs Net Equity')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Bottom-left: Drawdown
    ax = axes[1, 0]
    running_max = agg_cum_net.cummax()
    drawdown = (agg_cum_net - running_max) / running_max * 100
    ax.fill_between(range(len(drawdown)), drawdown.values, 0,
                    color='red', alpha=0.3)
    ax.plot(range(len(drawdown)), drawdown.values, color='red', linewidth=0.8)
    ax.set_title('Aggregate OOS Drawdown (Net)')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Drawdown (%)')
    ax.grid(True, alpha=0.3)

    # Bottom-right: Per-trade returns distribution
    ax = axes[1, 1]
    rets = all_trades_df['net_return_pct']
    ax.hist(rets, bins=80, color='steelblue', alpha=0.7, edgecolor='none')
    ax.axvline(x=0, color='gray', linestyle='--', alpha=0.5)
    ax.axvline(x=rets.mean(), color='red', linestyle='-', linewidth=1.5,
               label=f'Mean: {rets.mean():.4f}%')
    ax.axvline(x=rets.median(), color='orange', linestyle='-', linewidth=1.5,
               label=f'Median: {rets.median():.4f}%')
    ax.set_title('Per-Trade Net Return Distribution')
    ax.set_xlabel('Net Return (%)')
    ax.set_ylabel('Count')
    ax.legend()

    plt.tight_layout()
    plt.savefig(PLOTS / 'phase3_equity_curve.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/phase3_equity_curve.png')


def _plot_regime_distribution(all_trades_df):
    """Plot regime-filtered trade distribution and returns."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    regime_order = ['high_vol_up', 'low_vol_up', 'low_vol_down', 'high_vol_down']
    colors = {
        'high_vol_up': '#3498db',
        'low_vol_up': '#2ecc71',
        'low_vol_down': '#f39c12',
        'high_vol_down': '#e74c3c',
    }

    # Top-left: Trade count by regime
    ax = axes[0, 0]
    counts = []
    labels = []
    bar_colors = []
    for r in regime_order:
        c = (all_trades_df['regime'] == r).sum()
        counts.append(c)
        labels.append(r)
        bar_colors.append(colors[r])
    ax.bar(labels, counts, color=bar_colors)
    ax.set_title('Trade Count by Regime')
    ax.set_ylabel('Number of Trades')
    ax.tick_params(axis='x', rotation=30)

    # Top-right: Box plot of returns by regime
    ax = axes[0, 1]
    plot_data = []
    plot_labels = []
    plot_colors = []
    for r in regime_order:
        rdata = all_trades_df.loc[all_trades_df['regime'] == r, 'net_return_pct']
        if len(rdata) > 0:
            plot_data.append(rdata.values)
            plot_labels.append(r)
            plot_colors.append(colors[r])
    if plot_data:
        bp = ax.boxplot(plot_data, labels=plot_labels, patch_artist=True,
                        showfliers=False)
        for patch, color in zip(bp['boxes'], plot_colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
    ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Net Returns by Regime')
    ax.set_ylabel('Net Return (%)')
    ax.tick_params(axis='x', rotation=30)

    # Bottom-left: Cumulative return by regime
    ax = axes[1, 0]
    for r in regime_order:
        rdata = all_trades_df.loc[all_trades_df['regime'] == r, 'net_return_pct']
        if len(rdata) > 0:
            cum = (1 + rdata.values / 100).cumprod()
            ax.plot(cum, label=r, linewidth=1.2, color=colors[r])
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Cumulative Net Return by Regime')
    ax.set_xlabel('Trade #')
    ax.set_ylabel('Cumulative Return')
    ax.legend(fontsize=8)

    # Bottom-right: Stopped vs non-stopped by regime
    ax = axes[1, 1]
    regimes_with_trades = [r for r in regime_order
                           if (all_trades_df['regime'] == r).sum() > 0]
    if regimes_with_trades:
        stopped_counts = []
        non_stopped_counts = []
        for r in regimes_with_trades:
            rmask = all_trades_df['regime'] == r
            stopped_counts.append((all_trades_df.loc[rmask, 'stopped']).sum())
            non_stopped_counts.append((~all_trades_df.loc[rmask, 'stopped']).sum())

        x = np.arange(len(regimes_with_trades))
        width = 0.35
        ax.bar(x - width/2, non_stopped_counts, width, label='Non-stopped',
               color='steelblue', alpha=0.7)
        ax.bar(x + width/2, stopped_counts, width, label='Stopped',
               color='coral', alpha=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels(regimes_with_trades, rotation=30)
        ax.set_title('Stopped vs Non-Stopped by Regime')
        ax.set_ylabel('Count')
        ax.legend()

    plt.tight_layout()
    plt.savefig(PLOTS / 'phase3_regime_distribution.png', dpi=150)
    plt.close()
    print(f'Plot saved: docs/ig88/plots/phase3_regime_distribution.png')


# ---------------------------------------------------------------------------
# Go/No-Go gate
# ---------------------------------------------------------------------------

def _go_no_go_gate(agg_metrics):
    """Print Go/No-Go assessment based on aggregate net return per trade."""
    print('\n' + '=' * 80)
    print('GO / NO-GO GATE')
    print('=' * 80)

    avg_net = agg_metrics['avg_return_pct']
    total_net = agg_metrics['total_return_pct']
    sharpe = agg_metrics['sharpe_ann']
    n_trades = agg_metrics['total_trades']
    win_rate = agg_metrics['win_rate']
    max_dd = agg_metrics['max_drawdown_pct']

    print(f'\n  Avg net return per trade: {avg_net:.4f}%')
    print(f'  Total net return:        {total_net:.2f}%')
    print(f'  Annualized Sharpe:       {sharpe:.2f}')
    print(f'  Total OOS trades:        {n_trades:,}')
    print(f'  Win rate:                {win_rate:.1f}%')
    print(f'  Max drawdown:            {max_dd:.2f}%')

    print()
    if avg_net > 0.10:
        print('  >>> GO: Proceed to Phase 4 (paper trading)')
        print('  The reversal signal on 5-min bars with ATR stops and regime filtering')
        print('  produces a meaningful edge net of transaction costs.')
        verdict = 'GO'
    elif avg_net >= 0.04:
        print('  >>> CAUTION: Try 15-min bars or decorrelation-only filter')
        print('  The edge exists but is marginal. Further frequency reduction or')
        print('  tighter regime filtering may push it above the viability threshold.')
        verdict = 'CAUTION'
    else:
        print('  >>> PIVOT: Autocorrelation edge does not survive costs at any frequency')
        print('  The reversal signal does not produce sufficient returns after')
        print('  accounting for 0.04% round-trip transaction costs.')
        verdict = 'PIVOT'

    print(f'\n  Verdict: {verdict}')
    print('=' * 80)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print('=' * 80)
    print('IG-88 PHASE 3: 5-MIN REVERSAL-ONLY STRATEGY')
    print('  - Momentum signals removed')
    print('  - 5-minute bars (resampled from 1-min)')
    print('  - Regime-focused filtering (high_vol_up full, low_vol_up 0.5x)')
    print('  - ATR-based dynamic stops')
    print('  - 0.04% round-trip transaction costs on every trade')
    print('=' * 80)

    # Load and resample
    dfs = load_and_resample()

    # Signal analysis on 5-min bars
    sol_signals = section_signal_analysis(dfs)

    # Walk-forward backtest with Phase 3 changes
    all_trades, summary = walk_forward_v3(dfs)

    print('\n' + '=' * 80)
    print('PHASE 3 COMPLETE')
    print('=' * 80)
    print(f'\nOutputs:')
    print(f'  - data/phase3_walkforward_trades.csv')
    print(f'  - data/phase3_walkforward_summary.csv')
    print(f'  - data/phase3_calibration_log.csv')
    print(f'  - docs/ig88/plots/phase3_equity_curve.png')
    print(f'  - docs/ig88/plots/phase3_regime_distribution.png')


if __name__ == '__main__':
    main()
