#!/usr/bin/env python3
"""Quick test: does relaxing RSI from <35 to <40 give us more trades without losing quality?"""
import pandas as pd
import numpy as np
from pathlib import Path

def load_binance(pair, tf='240m'):
    path = Path(f"/Users/nesbitt/dev/factory/agents/ig88/data/binance_{pair}_{tf}.parquet")
    df = pd.read_parquet(path)
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp')
    return df

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def backtest_mr(df, rsi_threshold=35, bb_period=20, bb_std=1.0, vol_mult=1.2, friction=0.0032):
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    rsi_val = rsi(close)
    sma = close.rolling(bb_period).mean()
    std = close.rolling(bb_period).std()
    lower_bb = sma - bb_std * std
    vol_sma = volume.rolling(20).mean()
    
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = atr / close * 100
    
    entry_signal = (
        (rsi_val < rsi_threshold) &
        (close < lower_bb) &
        (close > df['open']) &
        (volume > vol_mult * vol_sma)
    )
    
    trades = []
    in_trade = False
    entry_price = 0
    entry_atr_pct = 0
    
    for i in range(1, len(close)):
        if not in_trade and entry_signal.iloc[i-1]:
            in_trade = True
            entry_price = close.iloc[i]
            entry_atr_pct = atr_pct.iloc[i]
        elif in_trade:
            if entry_atr_pct < 2.0:
                stop_pct = 0.015
                target_pct = 0.03
            elif entry_atr_pct < 4.0:
                stop_pct = 0.01
                target_pct = 0.075
            else:
                stop_pct = 0.005
                target_pct = 0.075
            
            stop_price = entry_price * (1 - stop_pct)
            target_price = entry_price * (1 + target_pct)
            
            if low.iloc[i] <= stop_price:
                exit_price = stop_price
                pnl_pct = (exit_price - entry_price) / entry_price - friction
                trades.append({'pnl_pct': pnl_pct, 'reason': 'stop'})
                in_trade = False
            elif high.iloc[i] >= target_price:
                exit_price = target_price
                pnl_pct = (exit_price - entry_price) / entry_price - friction
                trades.append({'pnl_pct': pnl_pct, 'reason': 'target'})
                in_trade = False
            
            if i > 10 and in_trade:
                pnl_pct = (close.iloc[i] - entry_price) / entry_price - friction
                trades.append({'pnl_pct': pnl_pct, 'reason': 'time'})
                in_trade = False
    
    if not trades:
        return {'n': 0, 'pf': 0, 'wr': 0, 'expectancy': 0, 'gross_win': 0, 'gross_loss': 0.001}
    
    pnls = [t['pnl_pct'] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    gross_win = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0.001
    
    return {
        'n': len(trades),
        'pf': gross_win / gross_loss,
        'wr': len(wins) / len(trades) * 100,
        'expectancy': np.mean(pnls) * 100,
        'gross_win': gross_win * 100,
        'gross_loss': gross_loss * 100,
    }

pairs = ['SOLUSDT', 'AVAXUSDT', 'ETHUSDT', 'LINKUSDT', 'BTCUSDT']
results = []

for pair in pairs:
    df = load_binance(pair)
    for rsi_thresh in [30, 35, 40, 45, 50]:
        r = backtest_mr(df, rsi_threshold=rsi_thresh)
        results.append({'pair': pair.replace('USDT', ''), 'rsi_threshold': rsi_thresh, **r})

results_df = pd.DataFrame(results)
print("=== RSI Threshold Analysis ===\n")
for pair in ['SOL', 'AVAX', 'ETH', 'LINK', 'BTC']:
    pair_df = results_df[results_df['pair'] == pair]
    print(f"\n{pair}:")
    for _, row in pair_df.iterrows():
        print(f"  RSI<{row['rsi_threshold']:2.0f}: n={row['n']:3d}  PF={row['pf']:5.2f}  WR={row['wr']:5.1f}%  EXP={row['expectancy']:6.3f}%")

print("\n\n=== AGGREGATE ===")
for rsi_thresh in [30, 35, 40, 45, 50]:
    subset = results_df[results_df['rsi_threshold'] == rsi_thresh]
    total_n = subset['n'].sum()
    total_win = subset['gross_win'].sum()
    total_loss = subset['gross_loss'].sum()
    agg_pf = total_win / total_loss if total_loss > 0 else 0
    avg_wr = (subset['n'] * subset['wr']).sum() / total_n if total_n > 0 else 0
    avg_exp = subset['expectancy'].mean()
    print(f"RSI<{rsi_thresh}: total_n={total_n:3d}  agg_PF={agg_pf:5.2f}  avg_WR={avg_wr:5.1f}%  avg_EXP={avg_exp:6.3f}%")
