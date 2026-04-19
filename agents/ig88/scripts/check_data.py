#!/usr/bin/env python3
"""Quick data availability check with exact filenames."""
import os
DATA_DIR = "/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h"
pairs = ["DOT_USDT", "DOGEUSDT", "MATIC_USDT", "ALGO_USDT", "UNI_USDT", "TAOUSDT"]
for sym in pairs:
    sym_clean = sym.replace("_", "")
    patterns = [f"binance_{sym}_60m", f"binance_{sym_clean}_60m", f"binance_{sym}_1h", f"binance_{sym_clean}_1h"]
    for p in patterns:
        fpath = os.path.join(DATA_DIR, p + ".parquet")
        exists = os.path.exists(fpath)
        if exists:
            import pandas as pd
            df = pd.read_parquet(fpath)
            print(f"{sym}: {p}.parquet OK ({len(df)} bars)")
            break
    else:
        # Try partial match
        matches = [f for f in os.listdir(DATA_DIR) if sym_clean.lower() in f.lower() and ("60m" in f or "1h" in f)]
        print(f"{sym}: NOT FOUND by patterns. Directory has: {matches}")
