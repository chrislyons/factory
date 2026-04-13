"""
Debug: Check if overbought signals exist
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'SOL', 'NEAR', 'ATOM']

for pair in PAIRS:
    df = pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # BB
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_upper = sma20 + std20 * 2
    
    # Vol
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    # Count overbought signals
    ob_rsi = (rsi > 70).sum()
    ob_bb = (c > bb_upper).sum()
    ob_both = (rsi > 70) & (c > bb_upper) & (vol_ratio > 1.3)
    
    print(f"{pair:<8} RSI>70: {ob_rsi}  BB>2.0: {ob_bb}  BOTH+Vol: {ob_both.sum()}")
