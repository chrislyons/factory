#!/usr/bin/env python3
"""Check current SMA100 regime and MR signals for all assets."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

pairs = [
    ("ETHUSDT", "binance_ETHUSDT_60m.parquet"),
    ("AVAXUSDT", "binance_AVAXUSDT_60m.parquet"),
    ("LINKUSDT", "binance_LINKUSDT_60m.parquet"),
    ("SOLUSDT", "binance_SOLUSDT_60m.parquet"),
    ("NEARUSDT", "binance_NEARUSDT_60m.parquet"),
    ("FILUSDT", "binance_FILUSDT_60m.parquet"),
    ("SUIUSDT", "binance_SUIUSDT_60m.parquet"),
    ("DOGEUSDT", "binance_DOGEUSDT_60m.parquet"),
    ("AAVEUSDT", "binance_AAVEUSDT_60m.parquet"),
    ("LTCUSDT", "binance_LTCUSDT_60m.parquet"),
    ("XRPUSDT", "binance_XRPUSDT_60m.parquet"),
    ("BNBUSDT", "binance_BNBUSDT_60m.parquet"),
    ("ZECUSDT", "binance_ZECUSDT_60m.parquet"),
    ("ATOMUSDT", "binance_ATOMUSDT_60m.parquet"),
    ("INJUSDT", "binance_INJUSDT_60m.parquet"),
    ("OPUSDT", "binance_OPUSDT_60m.parquet"),
    ("DOTUSDT", "binance_DOTUSDT_60m.parquet"),
    ("UNIUSDT", "binance_UNIUSDT_60m.parquet"),
    ("ALGOUSDT", "binance_ALGOUSDT_60m.parquet"),
    ("APTUSDT", "binance_APTUSDT_60m.parquet"),
]

print("SMA100 REGIME CHECK — ATR Breakout Long Entry Availability")
print("="*75)
for name, fname in pairs:
    f = DATA_DIR / fname
    if not f.exists():
        print(f"  {name:12s}: NO DATA ({fname})")
        continue
    df = pd.read_parquet(f)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time').sort_index()
    close = df['close'].values
    sma100 = pd.Series(close).rolling(100).mean().values
    last_close = close[-1]
    last_sma = sma100[-1]
    pct_above = (last_close - last_sma) / last_sma * 100
    above = last_close > last_sma
    
    # Donchian 20 breakout check
    upper_20 = pd.Series(df['high'].values).rolling(20).max().values
    prev_upper = upper_20[-2]
    broke_out = last_close > prev_upper
    
    status = "ABOVE" if above else "BLOCKED"
    bo = " | BO!" if broke_out else ""
    print(f"  {name:12s}: close={last_close:>10.4f} SMA100={last_sma:>10.4f} ({pct_above:+.1f}%) {status}{bo}")

print("\n\nMean Reversion 4h SIGNAL CHECK — RSI<35 + Below BB Lower(2σ)")
print("="*75)
for name, fname in pairs:
    f = DATA_DIR / fname
    if not f.exists():
        continue
    df = pd.read_parquet(f)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time').sort_index()
    
    # 4h resample
    df4h = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum'}).dropna()
    close = df4h['close'].values
    
    # RSI(14)
    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gains).rolling(14).mean().values
    avg_loss = pd.Series(losses).rolling(14).mean().values
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    rsi = 100 - (100 / (1 + rs))
    
    # BB(20, 2σ)
    sma20 = pd.Series(close).rolling(20).mean().values
    std20 = pd.Series(close).rolling(20).std().values
    bb_lower = sma20 - 2 * std20
    bb_upper = sma20 + 2 * std20
    
    last_rsi = rsi[-1]
    last_close = close[-1]
    below_bb = last_close < bb_lower[-1]
    rsi_low = last_rsi < 35
    
    signal = "LONG SIGNAL!" if (below_bb and rsi_low) else "---"
    print(f"  {name:12s}: close={last_close:>10.4f} RSI={last_rsi:>5.1f} BB_low={bb_lower[-1]:>10.4f} {'BELOW' if below_bb else 'above':>5s} → {signal}")

# Also check if the current regime is RISK_OFF using BTC as proxy
print("\n\nREGIME PROXY (BTC)")
print("="*75)
f = DATA_DIR / "binance_BTCUSDT_60m.parquet"
if f.exists():
    df = pd.read_parquet(f)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time').sort_index()
    close = df['close'].values
    sma50 = pd.Series(close).rolling(50).mean().values
    sma100 = pd.Series(close).rolling(100).mean().values
    sma200 = pd.Series(close).rolling(200).mean().values
    last = close[-1]
    print(f"  BTC close: {last:.2f}")
    print(f"  SMA50:  {sma50[-1]:.2f} ({'above' if last > sma50[-1] else 'BELOW'})")
    print(f"  SMA100: {sma100[-1]:.2f} ({'above' if last > sma100[-1] else 'BELOW'})")
    print(f"  SMA200: {sma200[-1]:.2f} ({'above' if last > sma200[-1] else 'BELOW'})")
    
    # 7d trend
    bars_7d = 7 * 24
    if len(close) > bars_7d:
        pct_7d = (close[-1] - close[-bars_7d]) / close[-bars_7d] * 100
        print(f"  7d trend: {pct_7d:+.1f}%")
