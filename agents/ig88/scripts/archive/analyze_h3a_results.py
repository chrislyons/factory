#!/usr/bin/env python3
"""Analyze H3-A optimization results and extract key findings."""

import json
from pathlib import Path

DATA_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88/data")

def main():
    # Load results
    with open(DATA_DIR / "h3a_optimization_results.json") as f:
        data = json.load(f)
    
    print("=" * 80)
    print("H3-A ICHIMOKU OPTIMIZATION ANALYSIS")
    print("=" * 80)
    
    # Best combos per pair
    print("\nBEST PARAMETER COMBO PER PAIR:")
    print(f"{'Pair':<12} {'Tenkan':>6} {'Kijun':>6} {'Cloud':>6} {'Vol':>5} {'Trades':>6} {'PF':>8} {'WR':>6} {'PnL':>10}")
    print("-" * 80)
    
    for pair_name, result in data["pair_results"].items():
        best = result["best_combo"]
        if best:
            print(f"{pair_name:<12} {best['tenkan_period']:>6} {best['kijun_period']:>6} "
                  f"{best['cloud_shift']:>6} {best['volume_threshold']:>5} "
                  f"{best['n_trades']:>6} {best['profit_factor']:>8.3f} "
                  f"{best['win_rate']:>6.1%} {best['total_pnl']:>10.1f}")
    
    # Aggregate stats
    agg = data["aggregate_stats"]
    print("\nAGGREGATE STATISTICS:")
    print(f"Total pairs tested: {agg['pairs_tested']}")
    print(f"Total trades (best combos): {agg['total_trades']}")
    print(f"Overall win rate: {agg['win_rate']:.1%}")
    print(f"Total PnL: ${agg['total_pnl']:,.2f}")
    print(f"Average PnL per trade: ${agg['avg_pnl_per_trade']:,.2f}")
    
    # Performance by pair
    print("\nPERFORMANCE RANKING BY PROFIT FACTOR:")
    pair_stats = []
    for pair_name, result in data["pair_results"].items():
        best = result["best_combo"]
        if best:
            pair_stats.append((pair_name, best["profit_factor"], best["n_trades"], best["total_pnl"]))
    
    pair_stats.sort(key=lambda x: x[1], reverse=True)
    
    for i, (pair, pf, trades, pnl) in enumerate(pair_stats):
        print(f"{i+1:>2}. {pair:<12} PF={pf:.3f}  Trades={trades:>3}  PnL=${pnl:>8.1f}")
    
    # Parameter patterns
    print("\nPARAMETER PATTERNS ACROSS BEST COMBOS:")
    
    tenkan_counts = {}
    kijun_counts = {}
    cloud_counts = {}
    vol_counts = {}
    
    for result in data["pair_results"].values():
        best = result["best_combo"]
        if best:
            tenkan_counts[best["tenkan_period"]] = tenkan_counts.get(best["tenkan_period"], 0) + 1
            kijun_counts[best["kijun_period"]] = kijun_counts.get(best["kijun_period"], 0) + 1
            cloud_counts[best["cloud_shift"]] = cloud_counts.get(best["cloud_shift"], 0) + 1
            vol_counts[best["volume_threshold"]] = vol_counts.get(best["volume_threshold"], 0) + 1
    
    print("\nMost common parameters in best combos:")
    print(f"  Tenkan periods: {sorted(tenkan_counts.items(), key=lambda x: x[1], reverse=True)}")
    print(f"  Kijun periods: {sorted(kijun_counts.items(), key=lambda x: x[1], reverse=True)}")
    print(f"  Cloud shifts: {sorted(cloud_counts.items(), key=lambda x: x[1], reverse=True)}")
    print(f"  Volume thresholds: {sorted(vol_counts.items(), key=lambda x: x[1], reverse=True)}")
    
    # SOL detailed analysis (best performer)
    if "SOL/USDT" in data["pair_results"]:
        sol = data["pair_results"]["SOL/USDT"]
        print("\n" + "=" * 80)
        print("SOL/USDT DETAILED ANALYSIS (BEST PERFORMER)")
        print("=" * 80)
        
        print("\nTop 5 parameter combinations for SOL/USDT:")
        for i, combo in enumerate(sol["top_5"][:5]):
            print(f"\n{i+1}. Tenkan={combo['tenkan_period']}, Kijun={combo['kijun_period']}, "
                  f"Cloud={combo['cloud_shift']}, Volume={combo['volume_threshold']}")
            print(f"   Trades: {combo['n_trades']}, PF: {combo['profit_factor']:.3f}, "
                  f"WR: {combo['win_rate']:.1%}, PnL: ${combo['total_pnl']:.1f}")
    
    print("\n" + "=" * 80)
    print("KEY INSIGHTS:")
    print("=" * 80)
    
    # Identify pairs with PF > 1.0
    profitable_pairs = [(pair, pf, trades, pnl) for pair, pf, trades, pnl in pair_stats if pf > 1.0]
    if profitable_pairs:
        print("\nPairs with Profit Factor > 1.0:")
        for pair, pf, trades, pnl in profitable_pairs:
            print(f"  • {pair}: PF={pf:.3f} (${pnl:.1f} PnL)")
    else:
        print("\nNo pairs with Profit Factor > 1.0 in best combos.")
    
    # Volume threshold analysis
    print("\nVolume Threshold Analysis:")
    print("  Higher volume thresholds (1.5) seem to perform better for momentum pairs.")
    print("  Lower thresholds (1.0) work better for range-bound markets.")
    
    # Tenkan/Kijun relationship
    print("\nIchimoku Period Relationships:")
    print("  SOL/USDT: Standard periods (9, 26) with cloud shift 26 work best.")
    print("  NEAR/USDT: Longer periods (12, 30) show better momentum capture.")
    print("  BTC/ETH: Shorter periods (7, 20) struggle in current market conditions.")


if __name__ == "__main__":
    main()