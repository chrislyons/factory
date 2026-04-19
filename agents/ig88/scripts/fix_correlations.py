#!/usr/bin/env python3
"""
Fix correlation data alignment — v2.
All parquet files have datetime INDEX (not columns).
Use the deepest file per asset, align on timestamps, compute real correlations.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
OUT_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

# Use the deepest 60m file per asset (most history)
# All files have datetime INDEX, not columns
ASSET_FILES = {
    "ETH": "binance_ETHUSDT_60m.parquet",      # 43788 rows, 2021-04-13 start
    "AVAX": "binance_AVAXUSDT_60m.parquet",    # 43788 rows, 2021-04-13 start
    "SOL": "binance_SOLUSDT_60m.parquet",       # 43788 rows, 2021-04-13 start
    "LINK": "binance_LINKUSDT_60m.parquet",     # 43788 rows, 2021-04-13 start
    "NEAR": "binance_NEARUSDT_60m.parquet",     # 43788 rows, 2021-04-13 start
    "FIL": "binance_FILUSDT_60m.parquet",       # 17520 rows, 2024-03-27 start
    "SUI": "binance_SUIUSDT_60m.parquet",       # 18000 rows, 2024-03-27 start
    "WLD": "binance_WLDUSDT_60m.parquet",       # 18000 rows, 2024-03-27 start
    "RNDR": "binance_RNDRUSDT_60m.parquet",     # 17520 rows, 2022-07-03 start
}

def load_and_align():
    """Load all asset close prices, align on timestamps."""
    series = {}
    
    for asset, filename in ASSET_FILES.items():
        fpath = DATA_DIR / filename
        if not fpath.exists():
            print(f"WARN: {fpath} not found, searching...")
            matches = list(DATA_DIR.glob(f"*{asset}*60m.parquet"))
            if not matches:
                matches = list(DATA_DIR.glob(f"*{asset}*_1h.parquet"))
            if matches:
                # Pick the largest file
                fpath = max(matches, key=lambda f: f.stat().st_size)
                print(f"  {asset}: using {fpath.name}")
            else:
                print(f"  {asset}: NOT FOUND")
                continue
        
        df = pd.read_parquet(fpath)
        
        # Index is already datetime
        idx = df.index
        if not pd.api.types.is_datetime64_any_dtype(idx):
            print(f"WARN: {asset} index is not datetime: {idx.dtype}")
            continue
        
        # Normalize timezone (some files are UTC, some naive)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        df.index = idx
        
        # Get close price
        close_col = None
        for c in ['close', 'Close', 'CLOSE']:
            if c in df.columns:
                close_col = c
                break
        if close_col is None:
            print(f"WARN: {asset} has no close column")
            continue
        
        n_rows = len(df)
        start = df.index.min().strftime('%Y-%m-%d')
        end = df.index.max().strftime('%Y-%m-%d')
        print(f"  {asset:>5}: {n_rows:>6} rows, {start} to {end}")
        
        series[asset] = df[close_col].rename(asset)
    
    if not series:
        print("ERROR: No assets loaded")
        sys.exit(1)
    
    # Concatenate into aligned panel
    panel = pd.DataFrame(series)
    
    print(f"\nPanel: {panel.shape[0]} rows x {panel.shape[1]} assets")
    print(f"NaN counts:")
    for col in panel.columns:
        n_nan = panel[col].isna().sum()
        pct = n_nan / len(panel) * 100
        if n_nan > 0:
            print(f"  {col}: {n_nan} ({pct:.1f}%)")
    
    # Strategy: compute correlations on the OVERLAPPING period only
    # First, find the common date range (where all assets have data)
    first_valid = panel.apply(lambda s: s.first_valid_index())
    last_valid = panel.apply(lambda s: s.last_valid_index())
    common_start = first_valid.max()  # Latest start
    common_end = last_valid.min()     # Earliest end
    
    print(f"\nCommon date range (all assets): {common_start} to {common_end}")
    print(f"  Duration: {(common_end - common_start).days} days")
    
    panel_common = panel.loc[common_start:common_end].dropna()
    print(f"  Rows in common range: {len(panel_common)}")
    
    # Also compute on extended range (allow partial overlap)
    # Forward-fill small gaps (up to 4 hours)
    panel_filled = panel.ffill(limit=4)
    panel_filled = panel_filled.dropna()
    print(f"\nExtended range (ffill 4h): {panel_filled.index.min()} to {panel_filled.index.max()}")
    print(f"  Rows: {len(panel_filled)}")
    
    return panel_common, panel_filled


def compute_correlations(panel, label=""):
    """Compute log returns and correlation matrix."""
    returns = np.log(panel / panel.shift(1)).dropna()
    
    print(f"\n{'='*60}")
    print(f"CORRELATION MATRIX {label}")
    print(f"{'='*60}")
    print(f"Observations: {len(returns)} hours ({(returns.index[-1]-returns.index[0]).days} days)")
    print(f"Range: {returns.index.min()} to {returns.index.max()}")
    
    corr = returns.corr()
    
    assets = corr.columns.tolist()
    print(f"\n{'':>8}", end="")
    for a in assets:
        print(f"{a:>8}", end="")
    print()
    
    for a1 in assets:
        print(f"{a1:>8}", end="")
        for a2 in assets:
            print(f"{corr.loc[a1, a2]:>8.3f}", end="")
        print()
    
    return corr, returns


def portfolio_simulation(returns, label=""):
    """Simulate equal-weight portfolio returns."""
    n_assets = returns.shape[1]
    weights = np.ones(n_assets) / n_assets
    port_returns = (returns * weights).sum(axis=1)
    equity = (1 + port_returns).cumprod()
    
    total_return = equity.iloc[-1] - 1
    n_days = (returns.index[-1] - returns.index[0]).days
    ann_return = (1 + total_return) ** (365.25 / n_days) - 1 if n_days > 0 else 0
    
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    max_dd = dd.min()
    
    sharpe = port_returns.mean() / port_returns.std() * np.sqrt(8760) if port_returns.std() > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"PORTFOLIO SIMULATION {label}")
    print(f"{'='*60}")
    print(f"Assets: {n_assets}, Observations: {len(returns)}h ({n_days}d)")
    print(f"Total return: {total_return*100:.1f}%")
    print(f"Annualized:   {ann_return*100:.1f}%")
    print(f"Max DD:       {max_dd*100:.1f}%")
    print(f"Sharpe:       {sharpe:.2f}")
    
    print(f"\nPer-asset:")
    for col in returns.columns:
        eq = (1 + returns[col]).cumprod()
        ret = eq.iloc[-1] - 1
        ann = (1 + ret) ** (365.25 / n_days) - 1 if n_days > 0 else 0
        asset_dd = (eq / eq.expanding().max() - 1).min()
        wr = (returns[col] > 0).mean() * 100
        print(f"  {col:>5}: {ann*100:>8.1f}% ann, DD={asset_dd*100:>6.1f}%, WR={wr:.0f}%")
    
    return {
        "label": label,
        "total_return": float(total_return),
        "ann_return": float(ann_return),
        "max_dd": float(max_dd),
        "sharpe": float(sharpe),
        "n_days": int(n_days),
        "n_assets": n_assets
    }


if __name__ == "__main__":
    print("Loading and aligning asset data...")
    panel_common, panel_filled = load_and_align()
    
    # Common range correlation (most reliable)
    corr_common, ret_common = compute_correlations(panel_common, "(common range — all assets)")
    metrics_common = portfolio_simulation(ret_common, "(common range)")
    
    # Extended range correlation
    corr_ext, ret_ext = compute_correlations(panel_filled, "(extended — ffill 4h)")
    metrics_ext = portfolio_simulation(ret_ext, "(extended)")
    
    # Save results
    def corr_to_dict(corr):
        return {a1: {a2: float(corr.loc[a1, a2]) for a2 in corr.columns} for a1 in corr.index}
    
    output = {
        "common_range": {
            "correlation_matrix": corr_to_dict(corr_common),
            "portfolio_metrics": metrics_common,
            "assets": list(corr_common.columns),
        },
        "extended_range": {
            "correlation_matrix": corr_to_dict(corr_ext),
            "portfolio_metrics": metrics_ext,
            "assets": list(corr_ext.columns),
        },
        "note": "FIXED: All parquet indices are datetime. Aligned on timestamps, ffill(4h), dropna. Before fix ETH-AVAX showed 0.00."
    }
    
    out_path = OUT_DIR / "correlation_matrix_fixed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {out_path}")
