#!/usr/bin/env python3
"""
Kelly Criterion Optimal Leverage Computation
Uses walk-forward validation trade data to compute optimal position sizing.
"""
import json
import math
from pathlib import Path

BASE = Path("/Users/nesbitt/dev/factory/agents/ig88")

def load_json(path):
    with open(path) as f:
        return json.load(f)

def compute_kelly(win_rate, avg_win, avg_loss):
    """
    Compute Kelly fraction given:
    - win_rate (p): probability of winning
    - avg_win: average winning trade return (positive)
    - avg_loss: average losing trade return (negative, will use absolute)
    
    Returns: (b_ratio, kelly_fraction, half_kelly, kelly_leverage)
    b = avg_win / abs(avg_loss)  (win/loss ratio)
    f* = p - (1-p) / b
    """
    p = win_rate
    b = avg_win / abs(avg_loss)  # win-to-loss ratio
    q = 1 - p
    
    # Kelly fraction: f* = p - q/b
    f_star = p - (q / b)
    
    # Half-Kelly for safety
    half_kelly = f_star / 2.0
    
    # Kelly leverage multiplier: if f* > 0, optimal leverage = 1/f* for full Kelly
    # But typically we report f* directly as the fraction of capital to bet
    # Optimal leverage = f* / friction_factor... but simpler: leverage = f* / base_bet
    # For a base 1x bet, the Kelly-optimal leverage multiplier is just f* (if > 1, you lever up)
    
    return {
        "win_rate_p": round(p, 6),
        "avg_win": round(avg_win, 6),
        "avg_loss": round(avg_loss, 6),
        "win_loss_ratio_b": round(b, 6),
        "kelly_fraction_f_star": round(f_star, 6),
        "half_kelly": round(half_kelly, 6),
        "kelly_leverage_multiplier": round(max(f_star, 0), 6),
        "half_kelly_leverage": round(max(half_kelly, 0), 6),
        "expected_growth_rate_full_kelly": round(p * math.log(1 + f_star * avg_win) + q * math.log(1 + f_star * avg_loss), 6) if f_star > 0 else 0,
        "expected_growth_rate_half_kelly": round(p * math.log(1 + half_kelly * avg_win) + q * math.log(1 + half_kelly * avg_loss), 6) if half_kelly > 0 else 0,
    }

def main():
    # Load validation data
    original_data = load_json(BASE / "data" / "atr_leverage_validation.json")
    new_data = load_json(BASE / "data" / "atr_new_assets_leverage.json")
    
    # Collect all assets: use 1x leverage, 50_50 split (most trades)
    assets = {}
    
    # Original assets (ETH, AVAX, LINK, NEAR, SOL)
    for symbol in ["ETH", "AVAX", "LINK", "NEAR", "SOL"]:
        if symbol in original_data["results"]:
            d = original_data["results"][symbol]["1x"]["50_50"]
            assets[symbol] = {
                "source": "atr_leverage_validation",
                "trade_count": d["trade_count"],
                "total_return": d["total_return"],
                "annualized_return": d["annualized_return"],
                "max_drawdown": d["max_drawdown"],
                "sharpe_ratio": d["sharpe_ratio"],
                **compute_kelly(d["win_rate"], d["avg_win"], d["avg_loss"])
            }
    
    # New assets (RNDR, WLD, SUI, FIL)
    for symbol in ["RNDR", "WLD", "SUI", "FIL"]:
        if symbol in new_data["results"]:
            d = new_data["results"][symbol]["1x"]["50_50"]
            assets[symbol] = {
                "source": "atr_new_assets_leverage",
                "trade_count": d["trade_count"],
                "total_return": d["total_return"],
                "annualized_return": d["annualized_return"],
                "max_drawdown": d["max_drawdown"],
                "sharpe_ratio": d["sharpe_ratio"],
                **compute_kelly(d["win_rate"], d["avg_win"], d["avg_loss"])
            }
    
    # Print per-asset results
    print("=" * 90)
    print("KELLY CRITERION OPTIMAL LEVERAGE - PER ASSET (1x, 50/50 split)")
    print("=" * 90)
    print(f"{'Asset':<8} {'WinRate':>8} {'b_ratio':>8} {'Kelly f*':>10} {'HalfKelly':>10} {'Leverage':>10} {'Trades':>8}")
    print("-" * 90)
    
    for sym, d in assets.items():
        print(f"{sym:<8} {d['win_rate_p']:>8.4f} {d['win_loss_ratio_b']:>8.4f} "
              f"{d['kelly_fraction_f_star']:>10.4f} {d['half_kelly']:>10.4f} "
              f"{d['half_kelly_leverage']:>10.4f} {d['trade_count']:>8}")
    
    # Portfolio allocation: normalize half-Kelly fractions to sum to 1.0
    # Use half-Kelly for safety
    half_kellys = {sym: max(d["half_kelly"], 0) for sym, d in assets.items()}
    total_half_kelly = sum(half_kellys.values())
    
    portfolio = {}
    if total_half_kelly > 0:
        for sym, hk in half_kellys.items():
            portfolio[sym] = {
                "half_kelly_fraction": round(hk, 6),
                "portfolio_weight": round(hk / total_half_kelly, 6),
                "effective_leverage": round(hk, 6),  # fraction of capital allocated
            }
    
    # Portfolio-level expected growth rate
    # Weight each asset's half-Kelly growth rate by its portfolio weight
    portfolio_growth_rate = 0
    for sym, d in assets.items():
        w = portfolio[sym]["portfolio_weight"]
        portfolio_growth_rate += w * d["expected_growth_rate_half_kelly"]
    
    # Aggregate leverage: sum of all half-Kelly fractions (total capital deployment)
    aggregate_leverage_half_kelly = sum(d["half_kelly"] for d in assets.values())
    aggregate_leverage_full_kelly = sum(max(d["kelly_fraction_f_star"], 0) for d in assets.values())
    
    print("\n" + "=" * 90)
    print("PORTFOLIO ALLOCATION (Half-Kelly weighted)")
    print("=" * 90)
    print(f"{'Asset':<8} {'HalfKelly':>10} {'Weight':>10} {'Eff.Lev':>10} {'GrowthRate':>12}")
    print("-" * 60)
    for sym in portfolio:
        gr = assets[sym]["expected_growth_rate_half_kelly"]
        print(f"{sym:<8} {portfolio[sym]['half_kelly_fraction']:>10.4f} "
              f"{portfolio[sym]['portfolio_weight']:>10.4f} "
              f"{portfolio[sym]['effective_leverage']:>10.4f} {gr:>12.6f}")
    
    print(f"\nAggregate Leverage (Half-Kelly): {aggregate_leverage_half_kelly:.4f}x")
    print(f"Aggregate Leverage (Full Kelly): {aggregate_leverage_full_kelly:.4f}x")
    print(f"Portfolio Expected Growth Rate (Half-Kelly): {portfolio_growth_rate:.6f}")
    print(f"Portfolio Expected Growth Rate Annualized: {portfolio_growth_rate * 365 * 4:.4f}")  # ~4 trades/day avg
    
    # Build output
    output = {
        "metadata": {
            "method": "Kelly Criterion with Half-Kelly safety factor",
            "data_sources": [
                str(BASE / "data" / "atr_leverage_validation.json"),
                str(BASE / "data" / "atr_new_assets_leverage.json")
            ],
            "leverage_level_used": "1x",
            "split_used": "50_50",
            "note": "Using 50/50 train/test split for maximum trade count and statistical robustness"
        },
        "per_asset_kelly": assets,
        "portfolio_allocation": portfolio,
        "portfolio_summary": {
            "aggregate_leverage_half_kelly": round(aggregate_leverage_half_kelly, 6),
            "aggregate_leverage_full_kelly": round(aggregate_leverage_full_kelly, 6),
            "portfolio_expected_growth_rate_per_trade": round(portfolio_growth_rate, 6),
            "portfolio_expected_growth_rate_annualized_est": round(portfolio_growth_rate * 365 * 4, 6),
            "num_assets": len(assets),
            "assets_with_positive_kelly": sum(1 for d in assets.values() if d["kelly_fraction_f_star"] > 0)
        }
    }
    
    # Save
    out_path = BASE / "data" / "kelly_optimization.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\nSaved to {out_path}")

if __name__ == "__main__":
    main()
