#!/usr/bin/env python3
"""Debug: check structure of problematic parquet files."""
import pandas as pd
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")

# Check ALL parquet files to understand the timestamp situation
for fpath in sorted(DATA_DIR.glob("*.parquet")):
    df = pd.read_parquet(fpath)
    idx = df.index
    idx_type = str(type(idx[0])) if len(idx) > 0 else "empty"
    
    # Check if index is datetime
    is_datetime = pd.api.types.is_datetime64_any_dtype(idx)
    
    has_time_col = any(c.lower() in ['time', 'timestamp', 'datetime'] for c in df.columns)
    
    # Only show assets we care about
    assets = ["ETH", "AVAX", "SOL", "LINK", "NEAR", "FIL", "SUI", "WLD", "RNDR"]
    name = fpath.stem
    if any(a in name.upper() for a in assets):
        if "60m" in name or "_1h" in name:
            print(f"\n{name}:")
            print(f"  Shape: {df.shape}")
            print(f"  Columns: {list(df.columns)}")
            print(f"  Index name: {idx.name}, dtype: {idx.dtype}")
            print(f"  Index is datetime: {is_datetime}")
            print(f"  First 3 index values: {idx[:3].tolist()}")
            print(f"  Has time column: {has_time_col}")
