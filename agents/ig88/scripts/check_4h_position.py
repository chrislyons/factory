#!/usr/bin/env python3
import pandas as pd, numpy as np
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
pairs = ["SOLUSDT","BTCUSDT","ETHUSDT","AVAXUSDT","ARBUSDT","OPUSDT",
         "LINKUSDT","RENDERUSDT","NEARUSDT","AAVEUSDT","DOGEUSDT","LTCUSDT"]
print("Pair | Price | 4H SMA100 | Above? | Dist | 4H DC20 Above?")
print("-" * 70)
for pair in pairs:
    f = DATA_DIR / f"binance_{pair}_60m.parquet"
    if not f.exists(): f = DATA_DIR / f"binance_{pair}_1h.parquet"
    if not f.exists(): continue
    df = pd.read_parquet(f)
    if 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.set_index('time').sort_index()
    df4h = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    c = df4h['close'].values
    sma100 = pd.Series(c).rolling(100).mean().values
    upper_dc = pd.Series(df4h['high'].values).rolling(20).max().values
    if len(c) > 100:
        above = c[-1] > sma100[-1]
        dist = (c[-1]/sma100[-1]-1)*100
        above_dc = c[-1] > upper_dc[-2]
        print(f"{pair:>12s} | {c[-1]:>10.4f} | {sma100[-1]:>10.4f} | {'YES' if above else 'NO':>3s} | {dist:>+5.1f}% | {'YES' if above_dc else 'NO'}")
