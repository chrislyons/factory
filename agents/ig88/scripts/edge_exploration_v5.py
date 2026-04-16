#!/usr/bin/env python3
"""
IG88 Portfolio v5 Edge Exploration
Test 5 hypotheses for new edges beyond current long-only 4h strategies.

Hypotheses:
1. Short-side edges on ETH 4h
2. Higher timeframe edges (daily, weekly)
3. New assets (SOL, AVAX, NEAR) on daily
4. Funding rate arbitrage (Jupiter perps)
5. Stablecoin yield for unused capital
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
import requests
import warnings
warnings.filterwarnings('ignore')

# Paths
BASE_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88')
DATA_DIR = BASE_DIR / 'data'
OUTPUT_DIR = DATA_DIR / 'edge_discovery'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# === UTILITY FUNCTIONS ===

def load_data(pair, timeframe='240m'):
    """Load OHLCV data for a pair."""
    # Try multiple filename patterns
    patterns = [
        f'binance_{pair}_USDT_{timeframe}.parquet',
        f'binance_{pair}USDT_{timeframe}.parquet',
        f'binance_{pair}USDT_{timeframe}_resampled.parquet',
    ]
    for pat in patterns:
        path = DATA_DIR / pat
        if path.exists():
            df = pd.read_parquet(path)
            df = df.sort_index()
            return df
    return None

def fetch_binance_klines(symbol, interval='4h', limit=1000):
    """Fetch klines from Binance public API."""
    url = 'https://api.binance.com/api/v3/klines'
    params = {'symbol': symbol, 'interval': interval, 'limit': limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
        df.set_index('open_time', inplace=True)
        df = df[['open', 'high', 'low', 'close', 'volume']]
        return df
    except Exception as e:
        print(f"Error fetching {symbol}: {e}", file=sys.stderr)
        return None

def compute_atr(highs, lows, closes, period=14):
    """Compute Average True Range."""
    high = pd.Series(highs)
    low = pd.Series(lows)
    close = pd.Series(closes)
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    return atr.values

def compute_ema(closes, period=20):
    """Compute Exponential Moving Average."""
    return pd.Series(closes).ewm(span=period, adjust=False).mean().values

def compute_rsi(closes, period=14):
    """Compute RSI."""
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.values

def compute_bollinger(closes, period=20, n_std=2):
    """Compute Bollinger Bands."""
    s = pd.Series(closes)
    sma = s.rolling(period).mean()
    std = s.rolling(period).std()
    upper = sma + n_std * std
    lower = sma - n_std * std
    return upper.values, lower.values, sma.values

def compute_macd(closes, fast=12, slow=26, signal=9):
    """Compute MACD and histogram."""
    s = pd.Series(closes)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.values, signal_line.values, histogram.values

def compute_keltner(closes, highs, lows, ema_period=20, atr_period=10, atr_mult=2):
    """Compute Keltner Channels."""
    ema = compute_ema(closes, ema_period)
    atr = compute_atr(highs, lows, closes, atr_period)
    upper = ema + atr_mult * atr
    lower = ema - atr_mult * atr
    return upper, lower, ema

def compute_metrics(trades, initial_capital=10000):
    """Compute performance metrics."""
    if len(trades) == 0:
        return {
            'pf': 0, 'wr': 0, 'n_trades': 0,
            'avg_net_pnl_pct': 0, 'total_return_pct': 0,
            'max_dd_pct': 0, 'final_capital': initial_capital,
            'avg_win_pct': 0, 'avg_loss_pct': 0,
        }
    
    net_pnls = np.array([t['net_pnl_pct'] / 100.0 for t in trades])
    wins = net_pnls[net_pnls > 0]
    losses = net_pnls[net_pnls <= 0]
    
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0)
    wr = len(wins) / len(net_pnls)
    
    equity = [initial_capital]
    for pnl in net_pnls:
        equity.append(equity[-1] * (1 + pnl))
    equity = np.array(equity)
    
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    max_dd_pct = dd.max() * 100
    
    final_capital = equity[-1]
    total_return_pct = (final_capital / initial_capital - 1) * 100
    
    return {
        'pf': round(pf, 3),
        'wr': round(wr, 3),
        'n_trades': len(trades),
        'avg_net_pnl_pct': round(np.mean([t['net_pnl_pct'] for t in trades]), 4),
        'total_return_pct': round(total_return_pct, 2),
        'max_dd_pct': round(max_dd_pct, 2),
        'final_capital': round(final_capital, 2),
        'avg_win_pct': round(wins.mean() * 100, 4) if len(wins) > 0 else 0,
        'avg_loss_pct': round(losses.mean() * 100, 4) if len(losses) > 0 else 0,
    }

def walk_forward_test(df, run_backtest_func, n_splits=5):
    """Run walk-forward validation."""
    n = len(df)
    segment_size = n // n_splits
    results = []
    
    for split in range(n_splits):
        split_start = split * segment_size
        split_end = (split + 1) * segment_size if split < n_splits - 1 else n
        
        split_data = df.iloc[split_start:split_end].copy()
        split_n = len(split_data)
        
        is_end = int(split_n * 0.7)
        df_is = split_data.iloc[:is_end]
        df_oos = split_data.iloc[is_end:]
        
        is_trades = run_backtest_func(df_is)
        is_metrics = compute_metrics(is_trades)
        
        oos_trades = run_backtest_func(df_oos)
        oos_metrics = compute_metrics(oos_trades)
        
        results.append({
            'split': split + 1,
            'is_period': f"{df_is.index[0]} to {df_is.index[-1]}",
            'oos_period': f"{df_oos.index[0]} to {df_oos.index[-1]}",
            'is_metrics': is_metrics,
            'oos_metrics': oos_metrics,
        })
    
    return results


# === HYPOTHESIS 1: SHORT-SIDE EDGES ===

def test_short_edge_eth_4h():
    """Test short signals on ETH 4h: close < EMA20 - 2*ATR with volume spike."""
    print("\n" + "="*70)
    print("HYPOTHESIS 1: SHORT-SIDE EDGES ON ETH 4H")
    print("="*70)
    
    df = load_data('ETH', '240m')
    if df is None:
        print("ERROR: ETH 4h data not found")
        return None
    
    print(f"Data: {len(df)} candles, {df.index[0]} to {df.index[-1]}")
    
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    volumes = df['volume'].values
    
    # Compute indicators
    ema20 = compute_ema(closes, 20)
    atr14 = compute_atr(highs, lows, closes, 14)
    vol_avg = pd.Series(volumes).rolling(20).mean().values
    
    # Short signal: close < EMA20 - 2*ATR, volume > 1.5x avg
    short_threshold = ema20 - 2 * atr14
    vol_spike = volumes > 1.5 * vol_avg
    
    # Also test with regime filter
    rsi = compute_rsi(closes, 14)
    
    FRICTION = 0.0014
    LEVERAGE = 1
    TP_PCT = 0.02
    SL_PCT = 0.01
    TIME_EXIT_BARS = 6  # 24 hours
    
    def run_short_backtest(df_sub):
        opens = df_sub['open'].values
        highs = df_sub['high'].values
        lows = df_sub['low'].values
        closes = df_sub['close'].values
        volumes = df_sub['volume'].values
        
        ema20 = compute_ema(closes, 20)
        atr14 = compute_atr(highs, lows, closes, 14)
        vol_avg = pd.Series(volumes).rolling(20).mean().values
        short_threshold = ema20 - 2 * atr14
        vol_spike = volumes > 1.5 * vol_avg
        rsi = compute_rsi(closes, 14)
        
        trades = []
        i = 25
        
        while i < len(df_sub):
            if (not np.isnan(ema20[i]) and 
                not np.isnan(atr14[i]) and
                not np.isnan(vol_avg[i]) and
                closes[i] < short_threshold[i] and
                vol_spike[i]):
                
                entry_price = closes[i]
                entry_idx = i
                # SHORT: profit when price drops
                tp_price = entry_price * (1 - TP_PCT)
                sl_price = entry_price * (1 + SL_PCT)
                
                exit_price = None
                exit_reason = None
                bars_held = 0
                
                for j in range(i + 1, min(i + 1 + TIME_EXIT_BARS, len(df_sub))):
                    bars_held = j - entry_idx
                    # For short: SL hits when price goes UP
                    if highs[j] >= sl_price:
                        exit_price = sl_price
                        exit_reason = 'SL'
                        i = j + 1
                        break
                    # For short: TP hits when price goes DOWN
                    if lows[j] <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TP'
                        i = j + 1
                        break
                else:
                    exit_idx = min(i + TIME_EXIT_BARS, len(df_sub) - 1)
                    bars_held = exit_idx - entry_idx
                    exit_price = closes[exit_idx]
                    exit_reason = 'TIME'
                    i = exit_idx + 1
                
                if exit_price is not None:
                    # SHORT PnL: (entry - exit) / entry
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = raw_pnl - FRICTION
                    
                    trades.append({
                        'entry_idx': entry_idx,
                        'entry_price': round(entry_price, 4),
                        'exit_price': round(exit_price, 4),
                        'raw_pnl_pct': round(raw_pnl * 100, 4),
                        'net_pnl_pct': round(net_pnl * 100, 4),
                        'exit_reason': exit_reason,
                        'bars_held': bars_held,
                    })
                    continue
            i += 1
        
        return trades
    
    # Run walk-forward
    wf_results = walk_forward_test(df, run_short_backtest, n_splits=5)
    
    # Aggregate OOS results
    all_oos_trades = []
    for r in wf_results:
        om = r['oos_metrics']
        print(f"  Split {r['split']}: IS PF={r['is_metrics']['pf']:.2f} WR={r['is_metrics']['wr']:.2f} N={r['is_metrics']['n_trades']} | "
              f"OOS PF={om['pf']:.2f} WR={om['wr']:.2f} N={om['n_trades']}")
        all_oos_trades.extend(run_short_backtest(df))
    
    agg_metrics = compute_metrics(all_oos_trades)
    print(f"\n  AGGREGATE: PF={agg_metrics['pf']:.3f}, WR={agg_metrics['wr']:.3f}, "
          f"N={agg_metrics['n_trades']}, Return={agg_metrics['total_return_pct']:.1f}%")
    
    # Test with regime filter (only short in high RSI / overbought)
    print("\n  Testing with RSI > 60 filter (overbought regime)...")
    
    def run_short_backtest_regime(df_sub):
        opens = df_sub['open'].values
        highs = df_sub['high'].values
        lows = df_sub['low'].values
        closes = df_sub['close'].values
        volumes = df_sub['volume'].values
        
        ema20 = compute_ema(closes, 20)
        atr14 = compute_atr(highs, lows, closes, 14)
        vol_avg = pd.Series(volumes).rolling(20).mean().values
        short_threshold = ema20 - 2 * atr14
        vol_spike = volumes > 1.5 * vol_avg
        rsi = compute_rsi(closes, 14)
        
        trades = []
        i = 25
        
        while i < len(df_sub):
            if (not np.isnan(ema20[i]) and 
                not np.isnan(atr14[i]) and
                not np.isnan(vol_avg[i]) and
                not np.isnan(rsi[i]) and
                closes[i] < short_threshold[i] and
                vol_spike[i] and
                rsi[i] > 60):  # Overbought regime
                
                entry_price = closes[i]
                entry_idx = i
                tp_price = entry_price * (1 - TP_PCT)
                sl_price = entry_price * (1 + SL_PCT)
                
                exit_price = None
                exit_reason = None
                bars_held = 0
                
                for j in range(i + 1, min(i + 1 + TIME_EXIT_BARS, len(df_sub))):
                    bars_held = j - entry_idx
                    if highs[j] >= sl_price:
                        exit_price = sl_price
                        exit_reason = 'SL'
                        i = j + 1
                        break
                    if lows[j] <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'TP'
                        i = j + 1
                        break
                else:
                    exit_idx = min(i + TIME_EXIT_BARS, len(df_sub) - 1)
                    bars_held = exit_idx - entry_idx
                    exit_price = closes[exit_idx]
                    exit_reason = 'TIME'
                    i = exit_idx + 1
                
                if exit_price is not None:
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = raw_pnl - FRICTION
                    
                    trades.append({
                        'net_pnl_pct': round(net_pnl * 100, 4),
                        'exit_reason': exit_reason,
                    })
                    continue
            i += 1
        
        return trades
    
    regime_trades = run_short_backtest_regime(df)
    regime_metrics = compute_metrics(regime_trades)
    print(f"  Regime-filtered: PF={regime_metrics['pf']:.3f}, WR={regime_metrics['wr']:.3f}, "
          f"N={regime_metrics['n_trades']}")
    
    verdict = "KILL"
    if agg_metrics['pf'] >= 1.3 and agg_metrics['n_trades'] >= 20:
        verdict = "VALIDATE"
    elif agg_metrics['pf'] >= 1.1:
        verdict = "MARGINAL"
    
    return {
        'hypothesis': 'Short-side edges on ETH 4h',
        'signal': 'close < EMA20 - 2*ATR, volume > 1.5x avg',
        'aggregate_metrics': agg_metrics,
        'regime_filtered_metrics': regime_metrics,
        'walk_forward': wf_results,
        'verdict': verdict,
    }


# === HYPOTHESIS 2: HIGHER TIMEFRAME EDGES ===

def test_higher_timeframes():
    """Test daily Keltner breakout and weekly MACD on ETH."""
    print("\n" + "="*70)
    print("HYPOTHESIS 2: HIGHER TIMEFRAME EDGES")
    print("="*70)
    
    results = {}
    
    # Test 1: ETH Daily Keltner breakout
    print("\n  --- ETH Daily Keltner Breakout ---")
    df_daily = load_data('ETH', '1440m')
    if df_daily is None:
        print("  Fetching ETH daily data...")
        df_daily = fetch_binance_klines('ETHUSDT', '1d', 1000)
        if df_daily is not None:
            df_daily.to_parquet(DATA_DIR / 'binance_ETHUSDT_1440m.parquet')
    
    if df_daily is not None:
        print(f"  Data: {len(df_daily)} candles")
        
        def run_daily_keltner(df_sub):
            opens = df_sub['open'].values
            highs = df_sub['high'].values
            lows = df_sub['low'].values
            closes = df_sub['close'].values
            volumes = df_sub['volume'].values
            
            ema20 = compute_ema(closes, 20)
            atr10 = compute_atr(highs, lows, closes, 10)
            upper = ema20 + 2 * atr10
            lower = ema20 - 2 * atr10
            vol_avg = pd.Series(volumes).rolling(20).mean().values
            
            trades = []
            i = 25
            
            while i < len(df_sub):
                if (not np.isnan(ema20[i]) and
                    not np.isnan(upper[i]) and
                    not np.isnan(vol_avg[i]) and
                    closes[i] > upper[i] and
                    volumes[i] > vol_avg[i]):
                    
                    entry_price = closes[i]
                    entry_idx = i
                    tp_price = entry_price * 1.03  # 3% TP for daily
                    sl_price = entry_price * 0.98  # 2% SL
                    
                    exit_price = None
                    exit_reason = None
                    bars_held = 0
                    
                    for j in range(i + 1, min(i + 1 + 5, len(df_sub))):  # 5 days max
                        bars_held = j - entry_idx
                        if lows[j] <= sl_price:
                            exit_price = sl_price
                            exit_reason = 'SL'
                            i = j + 1
                            break
                        if highs[j] >= tp_price:
                            exit_price = tp_price
                            exit_reason = 'TP'
                            i = j + 1
                            break
                    else:
                        exit_idx = min(i + 5, len(df_sub) - 1)
                        bars_held = exit_idx - entry_idx
                        exit_price = closes[exit_idx]
                        exit_reason = 'TIME'
                        i = exit_idx + 1
                    
                    if exit_price is not None:
                        raw_pnl = (exit_price - entry_price) / entry_price
                        net_pnl = raw_pnl - 0.0014
                        
                        trades.append({
                            'net_pnl_pct': round(net_pnl * 100, 4),
                            'exit_reason': exit_reason,
                        })
                        continue
                i += 1
            
            return trades
        
        wf_results = walk_forward_test(df_daily, run_daily_keltner, n_splits=5)
        all_trades = run_daily_keltner(df_daily)
        metrics = compute_metrics(all_trades)
        
        for r in wf_results:
            print(f"    Split {r['split']}: OOS PF={r['oos_metrics']['pf']:.2f} N={r['oos_metrics']['n_trades']}")
        
        print(f"  Aggregate: PF={metrics['pf']:.3f}, WR={metrics['wr']:.3f}, N={metrics['n_trades']}")
        results['eth_daily_keltner'] = {
            'metrics': metrics,
            'walk_forward': wf_results,
            'verdict': 'VALIDATE' if metrics['pf'] >= 1.3 else 'KILL'
        }
    
    # Test 2: ETH Weekly MACD histogram
    print("\n  --- ETH Weekly MACD Histogram ---")
    df_weekly = fetch_binance_klines('ETHUSDT', '1w', 500)
    if df_weekly is not None:
        print(f"  Data: {len(df_weekly)} candles")
        
        def run_weekly_macd(df_sub):
            closes = df_sub['close'].values
            
            macd_line, signal_line, histogram = compute_macd(closes)
            
            trades = []
            i = 30
            
            while i < len(df_sub):
                if (not np.isnan(histogram[i]) and
                    not np.isnan(histogram[i-1]) and
                    histogram[i] > 0 and
                    histogram[i-1] <= 0):  # MACD histogram crosses above zero
                    
                    entry_price = closes[i]
                    entry_idx = i
                    tp_price = entry_price * 1.05  # 5% TP for weekly
                    sl_price = entry_price * 0.97  # 3% SL
                    
                    exit_price = None
                    exit_reason = None
                    bars_held = 0
                    
                    for j in range(i + 1, min(i + 1 + 4, len(df_sub))):  # 4 weeks max
                        bars_held = j - entry_idx
                        if closes[j] <= sl_price:
                            exit_price = sl_price
                            exit_reason = 'SL'
                            i = j + 1
                            break
                        if closes[j] >= tp_price:
                            exit_price = tp_price
                            exit_reason = 'TP'
                            i = j + 1
                            break
                    else:
                        exit_idx = min(i + 4, len(df_sub) - 1)
                        bars_held = exit_idx - entry_idx
                        exit_price = closes[exit_idx]
                        exit_reason = 'TIME'
                        i = exit_idx + 1
                    
                    if exit_price is not None:
                        raw_pnl = (exit_price - entry_price) / entry_price
                        net_pnl = raw_pnl - 0.0014
                        
                        trades.append({
                            'net_pnl_pct': round(net_pnl * 100, 4),
                            exit_reason: exit_reason,
                        })
                        continue
                i += 1
            
            return trades
        
        wf_results = walk_forward_test(df_weekly, run_weekly_macd, n_splits=4)
        all_trades = run_weekly_macd(df_weekly)
        metrics = compute_metrics(all_trades)
        
        for r in wf_results:
            print(f"    Split {r['split']}: OOS PF={r['oos_metrics']['pf']:.2f} N={r['oos_metrics']['n_trades']}")
        
        print(f"  Aggregate: PF={metrics['pf']:.3f}, WR={metrics['wr']:.3f}, N={metrics['n_trades']}")
        results['eth_weekly_macd'] = {
            'metrics': metrics,
            'walk_forward': wf_results,
            'verdict': 'VALIDATE' if metrics['pf'] >= 1.3 else 'KILL'
        }
    
    return results


# === HYPOTHESIS 3: NEW ASSETS ===

def test_new_assets():
    """Test SOL, AVAX, NEAR on daily timeframe for Keltner breakout."""
    print("\n" + "="*70)
    print("HYPOTHESIS 3: NEW ASSETS (SOL, AVAX, NEAR) - DAILY KELTNER")
    print("="*70)
    
    assets = ['SOL', 'AVAX', 'NEAR']
    results = {}
    
    for asset in assets:
        print(f"\n  --- {asset} Daily Keltner Breakout ---")
        df = load_data(asset, '1440m')
        if df is None:
            print(f"  Fetching {asset} daily data...")
            df = fetch_binance_klines(f'{asset}USDT', '1d', 1000)
            if df is not None:
                df.to_parquet(DATA_DIR / f'binance_{asset}USDT_1440m.parquet')
        
        if df is None:
            print(f"  SKIP {asset}: no data available")
            continue
        
        print(f"  Data: {len(df)} candles")
        
        def run_keltner_breakout(df_sub):
            opens = df_sub['open'].values
            highs = df_sub['high'].values
            lows = df_sub['low'].values
            closes = df_sub['close'].values
            volumes = df_sub['volume'].values
            
            ema20 = compute_ema(closes, 20)
            atr10 = compute_atr(highs, lows, closes, 10)
            upper = ema20 + 2 * atr10
            vol_avg = pd.Series(volumes).rolling(20).mean().values
            
            trades = []
            i = 25
            
            while i < len(df_sub):
                if (not np.isnan(ema20[i]) and
                    not np.isnan(upper[i]) and
                    not np.isnan(vol_avg[i]) and
                    closes[i] > upper[i] and
                    volumes[i] > vol_avg[i]):
                    
                    entry_price = closes[i]
                    entry_idx = i
                    tp_price = entry_price * 1.03
                    sl_price = entry_price * 0.98
                    
                    exit_price = None
                    exit_reason = None
                    bars_held = 0
                    
                    for j in range(i + 1, min(i + 1 + 5, len(df_sub))):
                        bars_held = j - entry_idx
                        if lows[j] <= sl_price:
                            exit_price = sl_price
                            exit_reason = 'SL'
                            i = j + 1
                            break
                        if highs[j] >= tp_price:
                            exit_price = tp_price
                            exit_reason = 'TP'
                            i = j + 1
                            break
                    else:
                        exit_idx = min(i + 5, len(df_sub) - 1)
                        bars_held = exit_idx - entry_idx
                        exit_price = closes[exit_idx]
                        exit_reason = 'TIME'
                        i = exit_idx + 1
                    
                    if exit_price is not None:
                        raw_pnl = (exit_price - entry_price) / entry_price
                        net_pnl = raw_pnl - 0.0014
                        
                        trades.append({
                            'net_pnl_pct': round(net_pnl * 100, 4),
                            'exit_reason': exit_reason,
                        })
                        continue
                i += 1
            
            return trades
        
        wf_results = walk_forward_test(df, run_keltner_breakout, n_splits=5)
        all_trades = run_keltner_breakout(df)
        metrics = compute_metrics(all_trades)
        
        for r in wf_results:
            print(f"    Split {r['split']}: OOS PF={r['oos_metrics']['pf']:.2f} N={r['oos_metrics']['n_trades']}")
        
        print(f"  Aggregate: PF={metrics['pf']:.3f}, WR={metrics['wr']:.3f}, N={metrics['n_trades']}")
        
        oos_pfs = [r['oos_metrics']['pf'] for r in wf_results if r['oos_metrics']['n_trades'] > 0]
        avg_oos_pf = np.mean(oos_pfs) if oos_pfs else 0
        
        verdict = "KILL"
        if metrics['pf'] >= 1.3 and avg_oos_pf >= 1.2:
            verdict = "VALIDATE"
        elif metrics['pf'] >= 1.1:
            verdict = "MARGINAL"
        
        results[asset] = {
            'metrics': metrics,
            'avg_oos_pf': round(avg_oos_pf, 3),
            'walk_forward': wf_results,
            'verdict': verdict,
        }
    
    return results


# === HYPOTHESIS 4: FUNDING RATE ARBITRAGE ===

def test_funding_rate_arb():
    """Analyze funding rate distribution on ETH/SOL perps."""
    print("\n" + "="*70)
    print("HYPOTHESIS 4: FUNDING RATE ARBITRAGE")
    print("="*70)
    
    # Fetch Binance funding rates (proxy for Jupiter)
    results = {}
    
    for symbol in ['ETHUSDT', 'SOLUSDT']:
        print(f"\n  --- {symbol} Funding Rates ---")
        try:
            url = f'https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&limit=1000'
            req = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            data = req.json()
            
            if not data:
                print(f"  No data for {symbol}")
                continue
            
            funding_rates = [float(r['fundingRate']) for r in data]
            total = len(funding_rates)
            
            # Statistics
            avg_rate = np.mean(funding_rates)
            median_rate = np.median(funding_rates)
            p90 = np.percentile(funding_rates, 90)
            p95 = np.percentile(funding_rates, 95)
            p99 = np.percentile(funding_rates, 99)
            
            # Frequency analysis
            above_5bps = sum(1 for r in funding_rates if r > 0.0005)
            above_10bps = sum(1 for r in funding_rates if r > 0.0010)
            above_20bps = sum(1 for r in funding_rates if r > 0.0020)
            below_neg5bps = sum(1 for r in funding_rates if r < -0.0005)
            
            # Consecutive high periods
            consecutive = 0
            max_consecutive = 0
            for r in funding_rates:
                if r > 0.0005:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0
            
            # Expected yield from basis trade
            # When funding > 0.05%, short perp + long spot
            # Expected return = average funding rate * periods in trade
            high_rate_periods = [r for r in funding_rates if r > 0.0005]
            expected_yield_per_period = np.mean(high_rate_periods) if high_rate_periods else 0
            
            # Annualized: 3 periods per day * 365 days
            annual_yield = expected_yield_per_period * 3 * 365 * 100
            
            print(f"  Periods: {total}")
            print(f"  Avg rate: {avg_rate*100:.4f}% (per 8h)")
            print(f"  Median: {median_rate*100:.4f}%")
            print(f"  P90: {p90*100:.4f}%, P95: {p95*100:.4f}%, P99: {p99*100:.4f}%")
            print(f"  Above 5bps: {above_5bps} ({100*above_5bps/total:.1f}%)")
            print(f"  Above 10bps: {above_10bps} ({100*above_10bps/total:.1f}%)")
            print(f"  Above 20bps: {above_20bps} ({100*above_20bps/total:.1f}%)")
            print(f"  Below -5bps: {below_neg5bps} ({100*below_neg5bps/total:.1f}%)")
            print(f"  Max consecutive high: {max_consecutive}")
            print(f"  Expected yield when active: {annual_yield:.1f}% annualized")
            
            results[symbol] = {
                'total_periods': total,
                'avg_rate_pct': round(avg_rate * 100, 4),
                'median_rate_pct': round(median_rate * 100, 4),
                'p90_pct': round(p90 * 100, 4),
                'p95_pct': round(p95 * 100, 4),
                'p99_pct': round(p99 * 100, 4),
                'above_5bps_count': above_5bps,
                'above_5bps_pct': round(100 * above_5bps / total, 2),
                'above_10bps_count': above_10bps,
                'above_10bps_pct': round(100 * above_10bps / total, 2),
                'max_consecutive_high': max_consecutive,
                'expected_annual_yield_pct': round(annual_yield, 2),
                'verdict': 'VALIDATE' if annual_yield > 10 else 'KILL'
            }
            
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")
    
    return results


# === HYPOTHESIS 5: STABLECOIN YIELD ===

def research_stablecoin_yield():
    """Research current DeFi yield opportunities for stablecoins."""
    print("\n" + "="*70)
    print("HYPOTHESIS 5: STABLECOIN YIELD OPPORTUNITIES")
    print("="*70)
    
    # Note: This is a research summary, not a live test
    # Real yields change constantly, so we document known protocols and typical ranges
    
    protocols = {
        'Aave V3 (Ethereum)': {
            'assets': ['USDC', 'USDT'],
            'typical_apy': '3-8%',
            'risk': 'Low-Medium',
            'notes': 'Battle-tested, high TVL, variable rates'
        },
        'Compound V3': {
            'assets': ['USDC'],
            'typical_apy': '3-6%',
            'risk': 'Low-Medium',
            'notes': 'Similar to Aave, COMP rewards'
        },
        'Maker DSR': {
            'assets': ['DAI'],
            'typical_apy': '5-8%',
            'risk': 'Low',
            'notes': 'DAI Savings Rate, very stable'
        },
        'Curve (3pool)': {
            'assets': ['USDC', 'USDT', 'DAI'],
            'typical_apy': '2-5% + CRV',
            'risk': 'Medium',
            'notes': 'Low IL, CRV boost possible'
        },
        'Lido stETH': {
            'assets': ['ETH'],
            'typical_apy': '3-5%',
            'risk': 'Low-Medium',
            'notes': 'Liquid staking, not stablecoin but good for idle ETH'
        },
        'Jupiter Perps (JLP)': {
            'assets': ['SOL', 'ETH', 'BTC', 'USDC'],
            'typical_apy': '20-40%',
            'risk': 'High',
            'notes': 'Liquidity provider for perps, earns fees + funding'
        },
    }
    
    print("\n  Known DeFi Yield Protocols (as of early 2026):")
    print("  " + "-"*60)
    
    for name, info in protocols.items():
        print(f"\n  {name}:")
        print(f"    Assets: {', '.join(info['assets'])}")
        print(f"    Typical APY: {info['typical_apy']}")
        print(f"    Risk: {info['risk']}")
        print(f"    Notes: {info['notes']}")
    
    # Calculate potential improvement
    print("\n  --- Yield Impact Analysis ---")
    idle_capital = 49.18  # Current Kraken balance in CAD
    print(f"  Current idle capital: ${idle_capital:.2f} CAD")
    
    for yield_pct in [3, 5, 8]:
        annual_yield = idle_capital * yield_pct / 100
        print(f"  At {yield_pct}% APY: ${annual_yield:.2f} CAD/year = ${annual_yield/12:.2f}/month")
    
    print("\n  RECOMMENDATION:")
    print("  For small capital ($50 CAD), gas costs make DeFi yield impractical.")
    print("  Better to keep as trading margin. Revisit when capital > $1000 CAD.")
    
    return {
        'protocols': protocols,
        'current_idle_capital_cad': idle_capital,
        'verdict': 'KILL (too small for DeFi gas costs)',
        'recommendation': 'Keep as trading margin. Revisit at $1000+ capital.'
    }


# === MAIN ===

def main():
    print("="*70)
    print("IG88 PORTFOLIO v5 — EDGE EXPLORATION")
    print("Testing 5 hypotheses for new trading edges")
    print("="*70)
    
    all_results = {}
    
    # Hypothesis 1: Short-side edges
    all_results['h1_short_edges'] = test_short_edge_eth_4h()
    
    # Hypothesis 2: Higher timeframe edges
    all_results['h2_higher_timeframes'] = test_higher_timeframes()
    
    # Hypothesis 3: New assets
    all_results['h3_new_assets'] = test_new_assets()
    
    # Hypothesis 4: Funding rate arb
    all_results['h4_funding_rate_arb'] = test_funding_rate_arb()
    
    # Hypothesis 5: Stablecoin yield
    all_results['h5_stablecoin_yield'] = research_stablecoin_yield()
    
    # Summary
    print("\n" + "="*70)
    print("EDGE EXPLORATION SUMMARY")
    print("="*70)
    
    validated_edges = []
    
    for key, result in all_results.items():
        if result is None:
            continue
        
        if isinstance(result, dict):
            verdict = result.get('verdict', 'UNKNOWN')
            if verdict == 'VALIDATE':
                validated_edges.append(key)
            print(f"\n{key}: {verdict}")
            
            if 'metrics' in result:
                m = result['metrics']
                print(f"  PF={m.get('pf', 'N/A')}, WR={m.get('wr', 'N/A')}, N={m.get('n_trades', 'N/A')}")
    
    # Save results
    output_path = OUTPUT_DIR / 'edge_exploration_v5.json'
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    
    print(f"\nResults saved to {output_path}")
    
    # Generate IG88 doc if substantive edges found
    if validated_edges:
        doc_path = BASE_DIR / 'docs' / 'ig88_edge_report_v5.md'
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(doc_path, 'w') as f:
            f.write("# IG88 Portfolio v5 — New Edge Report\n\n")
            f.write(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n")
            f.write("## Validated Edges\n\n")
            
            for edge in validated_edges:
                f.write(f"### {edge}\n")
                result = all_results[edge]
                if 'metrics' in result:
                    m = result['metrics']
                    f.write(f"- Profit Factor: {m.get('pf', 'N/A')}\n")
                    f.write(f"- Win Rate: {m.get('wr', 'N/A')}\n")
                    f.write(f"- Trades: {m.get('n_trades', 'N/A')}\n")
                    f.write(f"- Return: {m.get('total_return_pct', 'N/A')}%\n")
                f.write("\n")
        
        print(f"\nIG88 report saved to {doc_path}")
    
    print("\n" + "="*70)
    print("EDGE EXPLORATION COMPLETE")
    print("="*70)

if __name__ == '__main__':
    main()