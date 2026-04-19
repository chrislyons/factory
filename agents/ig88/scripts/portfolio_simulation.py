#!/usr/bin/env python3
"""
Full portfolio simulation with ATR Breakout strategy returns.
Uses properly aligned correlation data to compute REAL portfolio DD.

Approach:
1. Run ATR Breakout on each asset's FULL history (not just common range)
2. Compute hourly strategy returns per asset
3. Align all strategy return series on timestamps
4. Compute portfolio returns with proper correlations embedded
5. Report portfolio-level metrics (ann return, max DD, Sharpe)
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import sys

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data/ohlcv/1h")
OUT_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

# Deep 60m files
ASSET_FILES = {
    "ETH": "binance_ETHUSDT_60m.parquet",
    "AVAX": "binance_AVAXUSDT_60m.parquet",
    "SOL": "binance_SOLUSDT_60m.parquet",
    "LINK": "binance_LINKUSDT_60m.parquet",
    "NEAR": "binance_NEARUSDT_60m.parquet",
    "FIL": "binance_FILUSDT_60m.parquet",
    "SUI": "binance_SUIUSDT_60m.parquet",
    "WLD": "binance_WLDUSDT_60m.parquet",
    "RNDR": "binance_RNDRUSDT_60m.parquet",
}

# Strategy parameters (from registry v5, IG88077 optimized)
PARAMS = {
    "lookback": 20,
    "atr_period": 10,
    "atr_mult": 1.5,
    "trail_pct": 0.01,
    "hold_hours": 96,
    "friction_rt": 0.0014,  # Jupiter perps
}


def compute_atr(df, period=10):
    """Compute ATR."""
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def backtest_atr_breakout(df, params):
    """
    ATR Breakout LONG strategy.
    Entry: close breaks above upper channel (highest high of lookback + ATR*mult)
    Exit: trailing stop (1% from highest close since entry) OR max hold
    Returns: Series of hourly returns (0 when flat)
    """
    close = df['close']
    atr = compute_atr(df, params['atr_period'])
    
    # Channel
    highest_high = df['high'].rolling(params['lookback']).max()
    upper = highest_high + atr * params['atr_mult']
    
    # Signals
    breakout = close > upper.shift(1)
    
    # Simulate trades
    returns = pd.Series(0.0, index=df.index)
    in_trade = False
    entry_price = 0.0
    highest_since_entry = 0.0
    hours_held = 0
    
    for i in range(len(df)):
        if not in_trade:
            if breakout.iloc[i] and not np.isnan(upper.iloc[i-1] if i > 0 else np.nan):
                # Enter at next bar open (use current close as proxy)
                in_trade = True
                entry_price = close.iloc[i]
                highest_since_entry = entry_price
                hours_held = 0
                # Apply entry friction (half of round-trip)
                returns.iloc[i] = -params['friction_rt'] / 2
        else:
            hours_held += 1
            highest_since_entry = max(highest_since_entry, close.iloc[i])
            
            # Trailing stop
            trail_stop = highest_since_entry * (1 - params['trail_pct'])
            
            # Check exits
            hit_stop = close.iloc[i] <= trail_stop
            hit_max_hold = hours_held >= params['hold_hours']
            
            if hit_stop or hit_max_hold:
                # Exit
                pnl = (close.iloc[i] - entry_price) / entry_price
                returns.iloc[i] = pnl - params['friction_rt'] / 2  # exit friction
                in_trade = False
            else:
                # Mark to market
                returns.iloc[i] = (close.iloc[i] - close.iloc[i-1]) / close.iloc[i-1] if i > 0 else 0
    
    return returns


def run_portfolio():
    """Run ATR Breakout on all assets, compute portfolio metrics."""
    
    strategy_returns = {}
    asset_info = {}
    
    for asset, filename in ASSET_FILES.items():
        fpath = DATA_DIR / filename
        if not fpath.exists():
            print(f"WARN: {asset} file not found")
            continue
        
        df = pd.read_parquet(fpath)
        
        # Normalize index
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        
        # Need OHLCV
        required = ['open', 'high', 'low', 'close', 'volume']
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"WARN: {asset} missing columns: {missing}")
            continue
        
        print(f"\n{'='*50}")
        print(f"Backtesting {asset}: {len(df)} bars, {df.index.min()} to {df.index.max()}")
        
        ret = backtest_atr_breakout(df, PARAMS)
        
        # Compute stats
        total_ret = (1 + ret).prod() - 1
        n_days = (ret.index[-1] - ret.index[0]).days
        ann_ret = (1 + total_ret) ** (365.25 / n_days) - 1 if n_days > 0 else 0
        
        # Count trades
        entries = (ret < -PARAMS['friction_rt']/2 * 0.5)  # rough detection
        # Better: count sign changes from 0 to non-zero
        active = ret != 0
        trade_starts = active & (~active.shift(1).fillna(True))
        n_trades = trade_starts.sum()
        
        # Max DD on equity curve
        equity = (1 + ret).cumprod()
        peak = equity.expanding().max()
        dd = (equity - peak) / peak
        max_dd = dd.min()
        
        # Win rate (on completed trades only)
        # Simplified: count hours where return is negative vs positive while in trade
        in_trade = ret != 0
        if in_trade.sum() > 0:
            wr = (ret[in_trade] > 0).mean() * 100
        else:
            wr = 0
        
        print(f"  Total return: {total_ret*100:.1f}%")
        print(f"  Annualized:   {ann_ret*100:.1f}%")
        print(f"  Max DD:       {max_dd*100:.1f}%")
        print(f"  Trades:       {n_trades}")
        print(f"  Win rate:     {wr:.1f}%")
        
        strategy_returns[asset] = ret
        asset_info[asset] = {
            "ann_return": float(ann_ret),
            "max_dd": float(max_dd),
            "trades": int(n_trades),
            "win_rate": float(wr),
            "n_days": int(n_days)
        }
    
    # Align all strategy returns on timestamps
    returns_df = pd.DataFrame(strategy_returns)
    
    # Fill NaN with 0 (asset not listed yet = flat)
    returns_df = returns_df.fillna(0)
    
    print(f"\n{'='*60}")
    print(f"PORTFOLIO CONSTRUCTION")
    print(f"{'='*60}")
    print(f"Assets: {len(returns_df.columns)}")
    print(f"Date range: {returns_df.index.min()} to {returns_df.index.max()}")
    print(f"Total hours: {len(returns_df)}")
    
    # Correlation of strategy returns (not price returns)
    # This captures the REAL correlation of our strategy PnL across assets
    # Only compute on hours where at least one asset is in a trade
    active_mask = (returns_df != 0).any(axis=1)
    active_returns = returns_df[active_mask]
    
    if len(active_returns) > 100:
        strat_corr = active_returns.corr()
        print(f"\nStrategy return correlations (hours in trade: {len(active_returns)}):")
        assets = strat_corr.columns.tolist()
        print(f"{'':>8}", end="")
        for a in assets:
            print(f"{a:>8}", end="")
        print()
        for a1 in assets:
            print(f"{a1:>8}", end="")
            for a2 in assets:
                print(f"{strat_corr.loc[a1, a2]:>8.3f}", end="")
            print()
    
    # Equal-weight portfolio
    n_assets = len(returns_df.columns)
    weights = np.ones(n_assets) / n_assets
    port_returns = (returns_df * weights).sum(axis=1)
    
    # Portfolio equity
    equity = (1 + port_returns).cumprod()
    total_ret = equity.iloc[-1] - 1
    n_days = (returns_df.index[-1] - returns_df.index[0]).days
    ann_ret = (1 + total_ret) ** (365.25 / n_days) - 1 if n_days > 0 else 0
    
    # Max DD
    peak = equity.expanding().max()
    dd = (equity - peak) / peak
    max_dd = dd.min()
    
    # Sharpe
    sharpe = port_returns.mean() / port_returns.std() * np.sqrt(8760) if port_returns.std() > 0 else 0
    
    # Trade frequency
    port_active = port_returns != 0
    pct_active = port_active.mean() * 100
    
    print(f"\n{'='*60}")
    print(f"PORTFOLIO RESULTS (Equal Weight, {n_assets} Assets)")
    print(f"{'='*60}")
    print(f"Total return:  {total_ret*100:.1f}%")
    print(f"Annualized:    {ann_ret*100:.1f}%")
    print(f"Max DD:        {max_dd*100:.1f}%")
    print(f"Sharpe:        {sharpe:.2f}")
    print(f"Days:          {n_days}")
    print(f"Hours active:  {pct_active:.1f}%")
    
    # 2x leverage scenario
    leveraged_returns = port_returns * 2
    # Subtract borrowing cost (~5% ann = 0.000057 per hour)
    borrow_cost = 0.05 / 8760
    leveraged_returns = leveraged_returns - borrow_cost
    
    lev_equity = (1 + leveraged_returns).cumprod()
    lev_ret = lev_equity.iloc[-1] - 1
    lev_ann = (1 + lev_ret) ** (365.25 / n_days) - 1 if n_days > 0 else 0
    lev_peak = lev_equity.expanding().max()
    lev_dd = (lev_equity - lev_peak) / lev_peak
    lev_max_dd = lev_dd.min()
    
    print(f"\n--- 2x LEVERAGE ---")
    print(f"Annualized:    {lev_ann*100:.1f}%")
    print(f"Max DD:        {lev_max_dd*100:.1f}%")
    
    # Monthly breakdown
    monthly = port_returns.resample('ME').apply(lambda x: (1+x).prod()-1)
    print(f"\nMonthly returns:")
    for date, ret in monthly.items():
        print(f"  {date.strftime('%Y-%m')}: {ret*100:>8.1f}%")
    
    # Save
    output = {
        "portfolio": {
            "ann_return_1x": float(ann_ret),
            "max_dd_1x": float(max_dd),
            "ann_return_2x": float(lev_ann),
            "max_dd_2x": float(lev_max_dd),
            "sharpe": float(sharpe),
            "n_days": int(n_days),
            "n_assets": n_assets,
        },
        "per_asset": asset_info,
        "params": PARAMS,
    }
    
    out_path = OUT_DIR / "portfolio_simulation_fixed.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run_portfolio()
