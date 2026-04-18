#!/usr/bin/env python3
"""
Portfolio Monte Carlo Simulation for ATR BO LONG assets with 2x leverage.
Uses real trade return distributions from walk-forward validation results.
Simulates geometric compounding of trades within each year.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path

np.random.seed(42)  # reproducibility

# Configuration
ITERATIONS = 10000
TRADING_DAYS_PER_YEAR = 365
HOURS_PER_YEAR = TRADING_DAYS_PER_YEAR * 24
# Data rows per symbol (4-hour bars)
DATA_ROWS_PER_SYMBOL = 43788
TOTAL_HOURS = DATA_ROWS_PER_SYMBOL * 4  # 4-hour bars

# Split percentages and test period years
SPLITS = {
    "50_50": 0.5,
    "60_40": 0.4,
    "70_30": 0.3,
}
TEST_YEARS = {split: (frac * TOTAL_HOURS) / HOURS_PER_YEAR for split, frac in SPLITS.items()}

# Load validation data
data_dir = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

with open(data_dir / "atr_leverage_validation.json") as f:
    leverage_data = json.load(f)

with open(data_dir / "atr_new_assets_validation.json") as f:
    new_assets_data = json.load(f)

# Extract 2x leverage stats for each asset
asset_stats = {}

# Original assets from leverage validation (AVAX, ETH, LINK, NEAR, SOL, BTC)
orig_symbols = ["AVAX", "ETH", "LINK", "NEAR", "SOL"]
for sym in orig_symbols:
    if sym not in leverage_data["results"]:
        continue
    sym_data = leverage_data["results"][sym]["2x"]
    # collect splits 50_50, 60_40, 70_30
    splits_to_use = ["50_50", "60_40", "70_30"]
    win_rates = []
    avg_wins = []
    avg_losses = []
    trade_counts = []
    profit_factors = []
    annual_returns = []
    for split in splits_to_use:
        if split not in sym_data:
            continue
        d = sym_data[split]
        win_rates.append(d["win_rate"])
        avg_wins.append(d["avg_win"])
        avg_losses.append(d["avg_loss"])
        trade_counts.append(d["trade_count"])
        profit_factors.append(d["profit_factor"])
        annual_returns.append(d["annualized_return"])
    # average across splits
    avg_wr = np.mean(win_rates)
    avg_aw = np.mean(avg_wins)
    avg_al = np.mean(avg_losses)
    avg_tc = np.mean(trade_counts)
    avg_pf = np.mean(profit_factors)
    avg_ar = np.mean(annual_returns)
    # trades per year
    # test period years for each split varies, compute weighted average? Simpler: use average trade count and average test years across splits
    # Compute average test years across splits used
    test_years_list = [TEST_YEARS[split] for split in splits_to_use if split in sym_data]
    avg_test_years = np.mean(test_years_list)
    trades_per_year = avg_tc / avg_test_years
    asset_stats[sym] = {
        "win_rate": avg_wr,
        "avg_win": avg_aw,
        "avg_loss": avg_al,
        "trades_per_year": trades_per_year,
        "profit_factor": avg_pf,
        "annualized_return": avg_ar,
    }

# New assets from new assets validation (RNDR, WLD, SUI, FIL)
new_symbols = ["RNDRUSDT", "WLDUSDT", "SUIUSDT", "FILUSDT"]
# mapping to shorter names
name_map = {
    "RNDRUSDT": "RNDR",
    "WLDUSDT": "WLD",
    "SUIUSDT": "SUI",
    "FILUSDT": "FIL",
}
for sym_full in new_symbols:
    if sym_full not in new_assets_data["results"]:
        continue
    sym_data = new_assets_data["results"][sym_full]["2x"]
    splits_to_use = ["50_50", "60_40", "70_30"]  # ignore 80_19
    win_rates = []
    avg_wins = []
    avg_losses = []
    trade_counts = []
    profit_factors = []
    annual_returns = []
    for split in splits_to_use:
        if split not in sym_data:
            continue
        d = sym_data[split]
        win_rates.append(d["win_rate"])
        avg_wins.append(d["avg_win"])
        avg_losses.append(d["avg_loss"])
        trade_counts.append(d["trade_count"])
        profit_factors.append(d["profit_factor"])
        annual_returns.append(d["annualized_return"])
    avg_wr = np.mean(win_rates)
    avg_aw = np.mean(avg_wins)
    avg_al = np.mean(avg_losses)
    avg_tc = np.mean(trade_counts)
    avg_pf = np.mean(profit_factors)
    avg_ar = np.mean(annual_returns)
    test_years_list = [TEST_YEARS[split] for split in splits_to_use if split in sym_data]
    avg_test_years = np.mean(test_years_list)
    trades_per_year = avg_tc / avg_test_years
    short_name = name_map.get(sym_full, sym_full)
    asset_stats[short_name] = {
        "win_rate": avg_wr,
        "avg_win": avg_aw,
        "avg_loss": avg_al,
        "trades_per_year": trades_per_year,
        "profit_factor": avg_pf,
        "annualized_return": avg_ar,
    }

print("Asset statistics (2x leverage, averaged across splits 50/50, 60/40, 70/30):")
for sym, stats in asset_stats.items():
    print(f"{sym}: WR {stats['win_rate']:.3f}, AvgWin {stats['avg_win']:.4f}, AvgLoss {stats['avg_loss']:.4f}, Trades/yr {stats['trades_per_year']:.1f}, PF {stats['profit_factor']:.3f}, AnnRet {stats['annualized_return']:.3f}")

# Ensure we have exactly the 9 assets
expected_assets = ["AVAX", "ETH", "LINK", "NEAR", "SOL", "RNDR", "WLD", "SUI", "FIL"]
for asset in expected_assets:
    if asset not in asset_stats:
        print(f"WARNING: Missing asset {asset}")

# Monte Carlo simulation for a single asset
def simulate_asset_annual_returns(stats, n_iter=ITERATIONS, seed=None):
    """Simulate annual returns for a single asset using trade return distribution with compounding."""
    if seed is not None:
        np.random.seed(seed)
    win_rate = stats["win_rate"]
    avg_win = stats["avg_win"]
    avg_loss = stats["avg_loss"]
    trades_per_year = stats["trades_per_year"]
    
    # Coefficient of variation for win and loss distributions
    CV = 0.5  # arbitrary but reasonable
    std_win = avg_win * CV
    std_loss = abs(avg_loss) * CV
    
    annual_returns = []
    for _ in range(n_iter):
        # Determine number of trades this year (Poisson)
        n_trades = np.random.poisson(trades_per_year)
        if n_trades == 0:
            annual_returns.append(0.0)
            continue
        # Simulate equity curve
        equity = 1.0
        for _ in range(n_trades):
            if np.random.rand() < win_rate:
                # winning trade
                trade_ret = np.random.normal(avg_win, std_win)
            else:
                # losing trade
                trade_ret = np.random.normal(avg_loss, std_loss)
            equity *= (1 + trade_ret)
        annual_ret = equity - 1.0
        annual_returns.append(annual_ret)
    return np.array(annual_returns)

# Simulate annual returns for each asset
asset_annual_returns = {}
for asset in expected_assets:
    if asset in asset_stats:
        returns = simulate_asset_annual_returns(asset_stats[asset])
        asset_annual_returns[asset] = returns
        print(f"{asset}: median annual return {np.median(returns):.3f}, P5 {np.percentile(returns,5):.3f}, P95 {np.percentile(returns,95):.3f}")

# Portfolio allocation strategies
allocations = {
    "equal_weight_9": {asset: 1/9 for asset in expected_assets},
    "top4_by_PF": {},  # will fill
    "top5_by_PF": {},
}

# Sort assets by profit factor descending
sorted_assets = sorted(asset_stats.items(), key=lambda x: x[1]["profit_factor"], reverse=True)
print("\nAssets sorted by profit factor:")
for sym, stats in sorted_assets:
    print(f"  {sym}: PF {stats['profit_factor']:.3f}")

top4 = [sym for sym, _ in sorted_assets[:4]]
top5 = [sym for sym, _ in sorted_assets[:5]]
print(f"Top 4: {top4}")
print(f"Top 5: {top5}")

allocations["top4_by_PF"] = {asset: 1/4 for asset in top4}
allocations["top5_by_PF"] = {asset: 1/5 for asset in top5}

# Monte Carlo for portfolios
def simulate_portfolio(alloc, n_iter=ITERATIONS):
    """Simulate portfolio annual returns given allocation weights.
    Assumes assets are independent and each asset's annual returns are already simulated.
    Portfolio return = weighted sum of asset returns (simple additive across assets).
    """
    portfolio_returns = np.zeros(n_iter)
    for asset, weight in alloc.items():
        if asset in asset_annual_returns:
            asset_returns = asset_annual_returns[asset]
            portfolio_returns += weight * asset_returns
        else:
            print(f"Warning: asset {asset} not in simulated returns")
    return portfolio_results(portfolio_returns)

def portfolio_results(returns):
    """Compute summary statistics for a series of annual returns."""
    median = np.median(returns)
    p5 = np.percentile(returns, 5)
    p95 = np.percentile(returns, 95)
    # Sharpe ratio: assume risk-free rate = 0 (crypto)
    sharpe = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    # Max drawdown: simulate 5-year paths of annual returns (assuming independence across years)
    n_years = 5
    n_paths = 2000
    max_dd_samples = []
    for _ in range(n_paths):
        # sample n_years returns with replacement from the simulated annual returns
        path_returns = np.random.choice(returns, size=n_years, replace=True)
        # compute cumulative equity
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in path_returns:
            equity *= (1 + r)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
        max_dd_samples.append(max_dd)
    median_max_dd = np.median(max_dd_samples)
    p5_max_dd = np.percentile(max_dd_samples, 5)
    p95_max_dd = np.percentile(max_dd_samples, 95)
    return {
        "median_annual_return": float(median),
        "p5_annual_return": float(p5),
        "p95_annual_return": float(p95),
        "sharpe_ratio": float(sharpe),
        "median_max_drawdown_5yr": float(median_max_dd),
        "p5_max_drawdown_5yr": float(p5_max_dd),
        "p95_max_drawdown_5yr": float(p95_max_dd),
        "mean_annual_return": float(np.mean(returns)),
        "std_annual_return": float(np.std(returns)),
    }

# Run portfolio simulations
results = {}
for name, alloc in allocations.items():
    print(f"\nSimulating portfolio: {name}")
    res = simulate_portfolio(alloc)
    results[name] = res
    print(f"  Median annual return: {res['median_annual_return']*100:.1f}%")
    print(f"  P5 worst case: {res['p5_annual_return']*100:.1f}%")
    print(f"  P95 best case: {res['p95_annual_return']*100:.1f}%")
    print(f"  Sharpe ratio: {res['sharpe_ratio']:.2f}")
    print(f"  Median max drawdown (5yr): {res['median_max_drawdown_5yr']*100:.1f}%")

# Save results to JSON
output_path = data_dir / "portfolio_optimization.json"
output = {
    "metadata": {
        "iterations": ITERATIONS,
        "assets": expected_assets,
        "asset_stats": asset_stats,
        "allocation_strategies": {k: v for k, v in allocations.items()},
        "notes": "Monte Carlo simulation using trade return distributions from walk-forward validation. Assumes CV=0.5 for win/loss distributions, independence across assets, Poisson-distributed trade counts, geometric compounding within year.",
    },
    "results": results,
}
with open(output_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to {output_path}")