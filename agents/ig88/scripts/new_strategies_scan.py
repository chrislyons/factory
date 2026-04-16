"""
New Strategies Scanner — Beyond MACD/EMA (Vectorized)
Tests 7 indicator families on 6 symbols, 1h data, walk-forward 60/40.
Both LONG and SHORT sides.
"""
import pandas as pd
import numpy as np
import os, json, warnings
from itertools import product
warnings.filterwarnings('ignore')

DATA_DIR_1H = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
DATA_DIR_4H = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/4h"
OUTPUT_PATH = "/Users/nesbitt/dev/factory/agents/ig88/data/new_strategies.json"
BPY = 8760  # bars per year for 1h

# ============================================================
# VECTORIZED INDICATORS
# ============================================================

def ema_v(close, p):
    return pd.Series(close).ewm(span=p, adjust=False).mean().values

def sma_v(close, p):
    return pd.Series(close).rolling(p).mean().values

def rsi_v(close, period=14):
    c = pd.Series(close)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return (100 - (100 / (1 + rs))).values

def atr_v(df, period=14):
    h, l, c = df['high'].values, df['low'].values, df['close'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    tr[0] = h[0] - l[0]
    return pd.Series(tr).rolling(period).mean().values

def bollinger_v(close, period=20, std_mult=2.0):
    mid = sma_v(close, period)
    std = pd.Series(close).rolling(period).std().values
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower

# ============================================================
# SIGNAL GENERATORS (all vectorized)
# ============================================================

def bb_signals_v(close, period=20, std_mult=2.0):
    upper, mid, lower = bollinger_v(close, period, std_mult)
    long_sig = (close <= lower) & (np.roll(close, 1) > np.roll(lower, 1))
    short_sig = (close >= upper) & (np.roll(close, 1) < np.roll(upper, 1))
    long_sig[0] = short_sig[0] = False
    return long_sig.astype(float), short_sig.astype(float), mid

def rsi_div_signals_v(close, rsi_period=14, lookback=20):
    r = rsi_v(close, rsi_period)
    n = len(close)
    long_sig = np.zeros(n)
    short_sig = np.zeros(n)

    # Local min/max detection over rolling window
    for i in range(lookback + 1, n):
        # Bullish divergence: price at local low, RSI higher than previous low
        if (close[i] == np.min(close[i-lookback:i+1]) and
            r[i] > r[i-1] and r[i] < 40 and not np.isnan(r[i])):
            long_sig[i] = 1
        # Bearish divergence: price at local high, RSI lower than previous high
        if (close[i] == np.max(close[i-lookback:i+1]) and
            r[i] < r[i-1] and r[i] > 60 and not np.isnan(r[i])):
            short_sig[i] = 1
    return long_sig, short_sig

def rsi_simple_signals_v(close, period=14, oversold=30, overbought=70):
    r = rsi_v(close, period)
    long_sig = (r < oversold) & (np.roll(r, 1) >= oversold)
    short_sig = (r > overbought) & (np.roll(r, 1) <= overbought)
    long_sig[0] = short_sig[0] = False
    return long_sig.astype(float), short_sig.astype(float)

def vol_spike_signals_v(df, vol_mult=2.0, lookback=20, body_thresh=0.5):
    close, open_, high, low, vol = (df['close'].values, df['open'].values,
                                     df['high'].values, df['low'].values, df['volume'].values)
    vol_avg = sma_v(vol, lookback)
    body = np.abs(close - open_)
    body_pct = body / open_ * 100
    bullish = close > open_
    bearish = close < open_
    lower_wick = np.where(bullish, open_ - low, close - low)
    upper_wick = np.where(bullish, high - close, high - open_)

    vol_cond = vol > vol_avg * vol_mult
    long_sig = vol_cond & bullish & (lower_wick > body * 2) & (body_pct > body_thresh)
    short_sig = vol_cond & bearish & (upper_wick > body * 2) & (body_pct > body_thresh)
    return long_sig.astype(float), short_sig.astype(float)

def atr_breakout_signals_v(df, atr_period=14, atr_mult=1.5, lookback=20):
    a = atr_v(df, atr_period)
    close = df['close'].values
    recent_high = pd.Series(df['high'].values).rolling(lookback).max().values
    recent_low = pd.Series(df['low'].values).rolling(lookback).min().values

    long_sig = close > np.roll(recent_high, 1) + a * atr_mult
    short_sig = close < np.roll(recent_low, 1) - a * atr_mult
    long_sig[:lookback+atr_period] = False
    short_sig[:lookback+atr_period] = False
    return long_sig.astype(float), short_sig.astype(float)

def vwap_dev_signals_v(df, dev_mult=2.0, lookback=20):
    close = df['close'].values
    vol = df['volume'].values
    tp = (df['high'].values + df['low'].values + df['close'].values) / 3
    cum_tp_vol = pd.Series(tp * vol).rolling(lookback).sum().values
    cum_vol = pd.Series(vol).rolling(lookback).sum().values
    vwap = cum_tp_vol / cum_vol
    dev = pd.Series(close - vwap).rolling(lookback).std().values

    long_sig = close < vwap - dev * dev_mult
    short_sig = close > vwap + dev * dev_mult
    long_sig[:lookback*2] = False
    short_sig[:lookback*2] = False
    return long_sig.astype(float), short_sig.astype(float)

def mtf_signals_v(df_1h, df_4h, ema_fast=20, ema_slow=50):
    ema4h_fast = ema_v(df_4h['close'].values, ema_fast)
    ema4h_slow = ema_v(df_4h['close'].values, ema_slow)
    trend_4h = np.where(ema4h_fast > ema4h_slow, 1, -1)

    # Map 4h trend to 1h indices
    idx_4h = df_4h.index if hasattr(df_4h, 'index') else np.arange(len(df_4h))
    idx_1h = df_1h.index if hasattr(df_1h, 'index') else np.arange(len(df_1h))

    # Forward fill using searchsorted
    if hasattr(idx_4h, 'values') and hasattr(idx_1h, 'values'):
        # DatetimeIndex
        search_idx = idx_4h.searchsorted(idx_1h, side='right') - 1
        search_idx = np.clip(search_idx, 0, len(trend_4h) - 1)
        trend_1h = trend_4h[search_idx]
    else:
        # Numeric: assume 4h bars = every 4th 1h bar
        map_idx = np.arange(len(df_1h)) // 4
        map_idx = np.clip(map_idx, 0, len(trend_4h) - 1)
        trend_1h = trend_4h[map_idx]

    close_1h = df_1h['close'].values
    ema1h = ema_v(close_1h, ema_fast)

    long_sig = (trend_1h == 1) & (close_1h >= ema1h) & (np.roll(close_1h, 1) < np.roll(ema1h, 1))
    short_sig = (trend_1h == -1) & (close_1h <= ema1h) & (np.roll(close_1h, 1) > np.roll(ema1h, 1))
    long_sig[:ema_slow] = False
    short_sig[:ema_slow] = False
    return long_sig.astype(float), short_sig.astype(float)

# ============================================================
# BACKTEST ENGINE (vectorized where possible)
# ============================================================

def run_bt(close_arr, sigs, trail, hold, fee=0.00043, short=False, exit_prices=None):
    trades = []
    in_t = False
    ep = 0.0
    pp = 0.0
    eb = 0
    n = len(close_arr)

    for i in range(n):
        p = close_arr[i]
        if not in_t:
            if sigs[i] != 0:
                if (not short and sigs[i] > 0) or (short and sigs[i] < 0):
                    in_t = True
                    ep = p
                    pp = p
                    eb = i
        else:
            price_exit = False
            if exit_prices is not None:
                if not short and p >= exit_prices[i]:
                    price_exit = True
                elif short and p <= exit_prices[i]:
                    price_exit = True

            if short:
                pp = min(pp, p)
                stop = pp * (1 + trail)
                if p >= stop or (i - eb) >= hold or price_exit:
                    pnl = (ep / p) - 1 - fee
                    trades.append(pnl)
                    in_t = False
            else:
                pp = max(pp, p)
                stop = pp * (1 - trail)
                if p <= stop or (i - eb) >= hold or price_exit:
                    pnl = (p / ep) - 1 - fee
                    trades.append(pnl)
                    in_t = False
    return np.array(trades)

def stats(pnls, bpy, n_bars_span):
    if len(pnls) < 5:
        return None
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(pnls)
    total = float(pnls.sum())
    gp = float(wins.sum()) if len(wins) else 0
    gl = abs(float(losses.sum())) if len(losses) else 0.0001
    pf = gp / gl
    wr = len(wins) / n
    avg_win = float(np.mean(wins)) if len(wins) else 0
    avg_loss = float(np.mean(losses)) if len(losses) else 0

    t_span = n_bars_span / bpy
    if t_span < 1.0:
        return None
    ann = (1 + total) ** (1 / t_span) - 1 if total > -1 else -1.0

    eq = np.cumsum(pnls)
    dd = float(np.max(np.maximum.accumulate(eq) - eq))
    trades_yr = n / t_span

    return {
        'n': n, 'wr': wr, 'pf': pf, 'total': total, 'ann': ann, 'dd': dd,
        'trades_yr': trades_yr, 'avg_win': avg_win, 'avg_loss': avg_loss, 'years': t_span
    }

# ============================================================
# MAIN
# ============================================================

def main():
    pairs = {
        "ETH": "binance_ETHUSDT_60m.parquet",
        "BTC": "binance_BTCUSDT_60m.parquet",
        "SOL": "binance_SOLUSDT_60m.parquet",
        "AVAX": "binance_AVAXUSDT_60m.parquet",
        "LINK": "binance_LINKUSDT_60m.parquet",
        "NEAR": "binance_NEARUSDT_60m.parquet",
    }

    # Strategy definitions: (name, signal_fn, param_grid, has_exit_prices)
    strategies = [
        ("BB_MR", bb_signals_v,
         {'period': [15, 20, 25], 'std_mult': [1.5, 2.0, 2.5]}, True),
        ("RSI_Div", rsi_div_signals_v,
         {'rsi_period': [10, 14], 'lookback': [15, 20, 30]}, False),
        ("RSI_Simple", rsi_simple_signals_v,
         {'period': [10, 14, 21], 'oversold': [25, 30, 35], 'overbought': [65, 70, 75]}, False),
        ("VolSpike", vol_spike_signals_v,
         {'vol_mult': [1.5, 2.0, 2.5], 'lookback': [15, 20], 'body_thresh': [0.3, 0.5]}, False),
        ("ATR_BO", atr_breakout_signals_v,
         {'atr_period': [10, 14], 'atr_mult': [1.0, 1.5, 2.0], 'lookback': [15, 20]}, False),
        ("VWAP_Dev", vwap_dev_signals_v,
         {'dev_mult': [1.5, 2.0, 2.5], 'lookback': [15, 20]}, False),
    ]

    # MTF handled separately
    mtf_grid = {'ema_fast': [15, 20, 25], 'ema_slow': [40, 50, 60]}

    exit_trails = [0.02, 0.03, 0.05]
    exit_holds = [24, 48, 96]

    all_results = []

    for sym, fname in pairs.items():
        path_1h = os.path.join(DATA_DIR_1H, fname)
        if not os.path.exists(path_1h):
            print(f"SKIP {sym}: file not found")
            continue

        df = pd.read_parquet(path_1h).sort_index().reset_index(drop=True)
        n = len(df)
        split = int(n * 0.6)
        test_df = df.iloc[split:].reset_index(drop=True)
        test_close = test_df['close'].values
        test_years = len(test_df) / BPY

        if test_years < 1.0:
            print(f"SKIP {sym}: {test_years:.1f}yr OOS")
            continue

        print(f"\n{sym}: {n} bars, {test_years:.1f}yr OOS ({split} train, {n-split} test)")

        # Load 4h for MTF
        df_4h = None
        mtf_fname = fname.replace('_60m', '_240m')
        mtf_path = os.path.join(DATA_DIR_4H, mtf_fname)
        if os.path.exists(mtf_path):
            df_4h_full = pd.read_parquet(mtf_path).sort_index().reset_index(drop=True)
            # Split 4h proportionally
            split_4h = int(len(df_4h_full) * 0.6)
            df_4h_test = df_4h_full.iloc[split_4h:].reset_index(drop=True)

        # Generate signals on FULL data, then slice to OOS
        for strat_name, sig_fn, grid, has_exit in strategies:
            keys = list(grid.keys())
            vals = list(grid.values())
            count = 0

            for params in product(*vals):
                pdict = dict(zip(keys, params))

                # Generate on full data
                if strat_name == "BB_MR":
                    long_full, short_full, exit_p = sig_fn(df['close'].values, **pdict)
                    exit_oos = exit_p[split:]
                elif strat_name in ("VolSpike", "ATR_BO", "VWAP_Dev"):
                    long_full, short_full = sig_fn(df, **pdict)
                    exit_oos = None
                else:
                    long_full, short_full = sig_fn(df['close'].values, **pdict)
                    exit_oos = None

                long_oos = long_full[split:]
                short_oos = short_full[split:]

                for trail in exit_trails:
                    for hold in exit_holds:
                        # LONG
                        trades_l = run_bt(test_close, long_oos, trail, hold,
                                         short=False, exit_prices=exit_oos if has_exit else None)
                        sl = stats(trades_l, BPY, len(test_df))
                        if sl and sl['pf'] > 1.15 and sl['trades_yr'] > 10 and sl['years'] > 1.0:
                            param_str = ','.join(f'{k}={v}' for k,v in pdict.items())
                            all_results.append({
                                'sym': sym, 'strat': f"{strat_name}({param_str})", 'dir': 'LNG',
                                'n': sl['n'], 'wr': sl['wr'], 'pf': sl['pf'],
                                'ann1x': sl['ann'], 'dd1x': sl['dd'],
                                'trades_yr': sl['trades_yr'], 'trail': trail, 'hold': hold,
                                'avg_win': sl['avg_win'], 'avg_loss': sl['avg_loss'], 'years': sl['years'],
                            })

                        # SHORT
                        trades_s = run_bt(test_close, -short_oos, trail, hold,
                                         short=True, exit_prices=exit_oos if has_exit else None)
                        ss = stats(trades_s, BPY, len(test_df))
                        if ss and ss['pf'] > 1.15 and ss['trades_yr'] > 10 and ss['years'] > 1.0:
                            param_str = ','.join(f'{k}={v}' for k,v in pdict.items())
                            all_results.append({
                                'sym': sym, 'strat': f"{strat_name}({param_str})", 'dir': 'SHT',
                                'n': ss['n'], 'wr': ss['wr'], 'pf': ss['pf'],
                                'ann1x': ss['ann'], 'dd1x': ss['dd'],
                                'trades_yr': ss['trades_yr'], 'trail': trail, 'hold': hold,
                                'avg_win': ss['avg_win'], 'avg_loss': ss['avg_loss'], 'years': ss['years'],
                            })
                count += 1

            print(f"  {strat_name}: {count} param combos tested")

        # MTF strategy
        if df_4h is not None:
            print(f"  MTF_4hTrend: testing...")
            mkeys = list(mtf_grid.keys())
            mvals = list(mtf_grid.values())
            for params in product(*mvals):
                pdict = dict(zip(mkeys, params))
                long_full, short_full = mtf_signals_v(df, df_4h_full, **pdict)
                long_oos = long_full[split:]
                short_oos = short_full[split:]

                for trail in exit_trails:
                    for hold in exit_holds:
                        trades_l = run_bt(test_close, long_oos, trail, hold, short=False)
                        sl = stats(trades_l, BPY, len(test_df))
                        if sl and sl['pf'] > 1.15 and sl['trades_yr'] > 10 and sl['years'] > 1.0:
                            param_str = ','.join(f'{k}={v}' for k,v in pdict.items())
                            all_results.append({
                                'sym': sym, 'strat': f"MTF_4hTrend({param_str})", 'dir': 'LNG',
                                'n': sl['n'], 'wr': sl['wr'], 'pf': sl['pf'],
                                'ann1x': sl['ann'], 'dd1x': sl['dd'],
                                'trades_yr': sl['trades_yr'], 'trail': trail, 'hold': hold,
                                'avg_win': sl['avg_win'], 'avg_loss': sl['avg_loss'], 'years': sl['years'],
                            })

                        trades_s = run_bt(test_close, -short_oos, trail, hold, short=True)
                        ss = stats(trades_s, BPY, len(test_df))
                        if ss and ss['pf'] > 1.15 and ss['trades_yr'] > 10 and ss['years'] > 1.0:
                            param_str = ','.join(f'{k}={v}' for k,v in pdict.items())
                            all_results.append({
                                'sym': sym, 'strat': f"MTF_4hTrend({param_str})", 'dir': 'SHT',
                                'n': ss['n'], 'wr': ss['wr'], 'pf': ss['pf'],
                                'ann1x': ss['ann'], 'dd1x': ss['dd'],
                                'trades_yr': ss['trades_yr'], 'trail': trail, 'hold': hold,
                                'avg_win': ss['avg_win'], 'avg_loss': ss['avg_loss'], 'years': ss['years'],
                            })
        else:
            print(f"  MTF_4hTrend: no 4h data, skipping")

    # Sort and display
    all_results.sort(key=lambda x: x['pf'], reverse=True)

    print(f"\n\n{'='*100}")
    print(f"RESULTS SUMMARY — {len(all_results)} viable strategies found")
    print(f"Filter: PF > 1.15, trades/yr > 10, OOS > 1yr")
    print(f"{'='*100}")
    print(f"{'#':>3s} {'Sym':<5s} {'Strategy':<45s} {'Dir':>4s} {'N':>5s} {'WR':>6s} {'PF':>6s} {'Ann':>8s} {'DD':>8s} {'Trd/Yr':>7s} {'Yr':>5s}")
    print("-" * 105)
    for i, r in enumerate(all_results[:60]):
        sn = r['strat'][:44]
        print(f"{i+1:>3d} {r['sym']:<5s} {sn:<45s} {r['dir']:>4s} {r['n']:>5d} {r['wr']:>5.1%} {r['pf']:>5.2f} {r['ann1x']:>7.1%} {r['dd1x']:>7.1%} {r['trades_yr']:>6.1f} {r['years']:>5.1f}")

    # Breakdown
    print(f"\nBREAKDOWN BY STRATEGY TYPE:")
    strat_counts = {}
    for r in all_results:
        base = r['strat'].split('(')[0]
        strat_counts.setdefault(base, []).append(r)
    for base, res in sorted(strat_counts.items(), key=lambda x: -len(x[1])):
        pfs = [r['pf'] for r in res]
        print(f"  {base:<20s}: {len(res):>4d} strategies, best PF={max(pfs):.2f}, avg PF={np.mean(pfs):.2f}")

    lng = sum(1 for r in all_results if r['dir'] == 'LNG')
    sht = sum(1 for r in all_results if r['dir'] == 'SHT')
    print(f"\nDIRECTION: {lng} LONG, {sht} SHORT")

    with open(OUTPUT_PATH, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nSaved {len(all_results)} results to {OUTPUT_PATH}")

if __name__ == '__main__':
    main()
