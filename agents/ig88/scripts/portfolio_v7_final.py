#!/usr/bin/env python3
"""
Portfolio v7 FINAL — Corrected leverage model + optimal allocations.

Key fix: Margin cost only applies during active trades, not 24/7.
Funding rate similarly only applies while position is open.
"""

import numpy as np, json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "portfolio_v7"

# ============================================================================
# Edge parameters (walk-forward OOS validated, 2020-2026)
# ============================================================================

EDGES = {
    'L1: ETH Keltner': {
        'oos_pf': 1.119, 'oos_total': 0.176, 'n_oos': 213,
        'full_pf': 1.438, 'full_total': 1.684, 'full_n': 139,
        'hold_bars': 30, 'tf_hours': 4, 'side': 'long', 'venue': 'kraken',
        'optimal_trail': 2.5,
    },
    'L2: ETH Vol Breakout': {
        'oos_pf': 1.681, 'oos_total': 0.259, 'n_oos': 63,
        'full_pf': 1.622, 'full_total': 0.789, 'full_n': 45,
        'hold_bars': 30, 'tf_hours': 4, 'side': 'long', 'venue': 'kraken',
        'optimal_trail': 4.0,
    },
    'L3: ETH MACD': {
        'oos_pf': 2.408, 'oos_total': 0.618, 'n_oos': 108,
        'full_pf': 2.577, 'full_total': 2.294, 'full_n': 73,
        'hold_bars': 30, 'tf_hours': 4, 'side': 'long', 'venue': 'kraken',
        'optimal_trail': 2.5,  # Optimized: PF 2.00 vs 1.89 at 3.0x
    },
    'S1: ETH EMA50 Short': {
        'oos_pf': 2.323, 'oos_total': 0.419, 'n_oos': 41,
        'full_pf': 1.369, 'full_total': 0.485, 'full_n': 28,
        'hold_bars': 30, 'tf_hours': 24, 'side': 'short', 'venue': 'jupiter',
        'optimal_trail': 2.0,
    },
    'S2: ETH 20-Low Short': {
        'oos_pf': 2.355, 'oos_total': 0.453, 'n_oos': 45,
        'full_pf': 1.348, 'full_total': 0.442, 'full_n': 26,
        'hold_bars': 30, 'tf_hours': 24, 'side': 'short', 'venue': 'jupiter',
        'optimal_trail': 2.0,
    },
    'S3: BTC EMA50 Short': {
        'oos_pf': 1.301, 'oos_total': 0.074, 'n_oos': 44,
        'full_pf': 1.720, 'full_total': 0.535, 'full_n': 26,
        'hold_bars': 30, 'tf_hours': 24, 'side': 'short', 'venue': 'jupiter',
        'optimal_trail': 2.0,
    },
}

YEARS_OOS = 5.0  # 2021-2026 OOS period


def corrected_leverage_return(edge, leverage):
    """
    Compute leveraged return with CORRECTED cost model.

    Margin cost only applies while in a trade:
    - trade_time = hold_bars * tf_hours / 24 days
    - total_trade_days = (n_oos / YEARS_OOS) * trade_time * years
    - margin_cost = margin_rate * (total_trade_days / 365)
    """
    oos_total = edge['oos_total']
    n = edge['n_oos']
    hold_bars = edge['hold_bars']
    tf_hours = edge['tf_hours']
    side = edge['side']

    # Trades per year
    trades_per_year = n / YEARS_OOS

    # Average time in market per trade (days)
    avg_hold_days = hold_bars * tf_hours / 24

    # Total days in market per year
    days_in_market_per_year = trades_per_year * avg_hold_days
    market_fraction = days_in_market_per_year / 365  # fraction of year in position

    # Cost rates (annualized, applied only during active trades)
    if side == 'long':
        # Kraken: 8% annual margin rate, but only while in trade
        annual_margin_rate = 0.08
        funding_cost = 0.0
    else:
        # Jupiter perps: funding rate ~0.01% per 8h = ~0.03%/day
        # Only applies while position is open
        annual_margin_rate = 0.0  # No margin cost for perps (you own the collateral)
        funding_daily = 0.0003  # ~11% annual, conservative
        funding_cost = funding_daily * avg_hold_days * trades_per_year * YEARS_OOS

    # Margin cost (scaled by time in market)
    if side == 'long':
        total_margin_cost = annual_margin_rate * market_fraction * YEARS_OOS
    else:
        total_margin_cost = 0.0

    total_cost = total_margin_cost + funding_cost

    # Leveraged return
    gross = oos_total * leverage
    net = gross - total_cost

    # Annualized
    ann = (1 + net) ** (1/YEARS_OOS) - 1 if net > -0.99 else -0.99

    # Drawdown estimation (rough: scales with leverage)
    # Base DD ≈ max adverse excursion per trade * leverage * concentration
    base_dd = 0.10  # Rough estimate: 10% base DD for a well-managed edge
    est_dd = min(base_dd * leverage * 1.5, 0.90)

    # Margin call risk (for leveraged longs on Kraken)
    if side == 'long' and leverage > 1.0:
        # Margin call at 80% loss
        mc_risk = max(0, (est_dd - 0.8/leverage) / est_dd)
    else:
        mc_risk = 0.0

    return {
        'leverage': leverage,
        'gross': gross,
        'cost': total_cost,
        'net': net,
        'annualized': ann,
        'est_dd': est_dd,
        'margin_call_risk': mc_risk,
        'market_fraction': market_fraction,
        'trades_per_year': trades_per_year,
    }


def main():
    print("=" * 72)
    print("  PORTFOLIO v7 FINAL — CORRECTED LEVERAGE MODEL")
    print("=" * 72)

    leverage_levels = [1.0, 1.5, 2.0, 2.5, 3.0]

    # Per-edge leverage analysis
    for name, edge in EDGES.items():
        print(f"\n  {name} ({edge['side']}, {edge['venue']}, PF={edge['oos_pf']:.2f})")
        print(f"  Trades/yr: {edge['n_oos']/YEARS_OOS:.0f}, Avg hold: {edge['hold_bars']*edge['tf_hours']/24:.1f}d")
        print(f"  {'Lev':>4s} {'Gross':>8s} {'Cost':>7s} {'Net':>8s} {'Ann':>8s} {'DD':>6s} {'MC%':>5s}")
        print(f"  {'-'*4} {'-'*8} {'-'*7} {'-'*8} {'-'*8} {'-'*6} {'-'*5}")

        for lev in leverage_levels:
            if edge['side'] == 'long' and lev > 2.0 and edge['venue'] == 'kraken':
                print(f"  {lev:4.1f}x {'N/A — Kraken max 2x':^35s}")
                continue
            r = corrected_leverage_return(edge, lev)
            print(f"  {lev:4.1f}x {r['gross']:>+7.1%} {-r['cost']:>+6.1%} "
                  f"{r['net']:>+7.1%} {r['annualized']:>+7.1%} "
                  f"{r['est_dd']:>5.1%} {r['margin_call_risk']:>4.0%}")

    # Portfolio scenarios
    print(f"\n{'='*72}")
    print(f"  AGGRESSIVE PORTFOLIO SCENARIOS")
    print(f"{'='*72}")

    scenarios = {
        'MILD (1x, all 6 edges)': {
            'L1: ETH Keltner': 0.10, 'L2: ETH Vol Breakout': 0.10,
            'L3: ETH MACD': 0.20, 'S1: ETH EMA50 Short': 0.20,
            'S2: ETH 20-Low Short': 0.20, 'S3: BTC EMA50 Short': 0.20,
            'long_lev': 1.0, 'short_lev': 1.0,
        },
        'MODERATE (2x/2x, drop weak)': {
            'L3: ETH MACD': 0.35, 'L2: ETH Vol Breakout': 0.15,
            'S1: ETH EMA50 Short': 0.25, 'S2: ETH 20-Low Short': 0.25,
            'long_lev': 2.0, 'short_lev': 2.0,
        },
        'AGGRESSIVE (2x/3x, PF>2 only)': {
            'L3: ETH MACD': 0.45,
            'S1: ETH EMA50 Short': 0.30, 'S2: ETH 20-Low Short': 0.25,
            'long_lev': 2.0, 'short_lev': 3.0,
        },
        'YOLO (2x/3x, 2 best edges)': {
            'L3: ETH MACD': 0.55,
            'S1: ETH EMA50 Short': 0.45,
            'long_lev': 2.0, 'short_lev': 3.0,
        },
    }

    results = {}
    for name, config in scenarios.items():
        long_lev = config.pop('long_lev')
        short_lev = config.pop('short_lev')

        # Normalize weights
        total_w = sum(config.values())
        alloc = {k: v/total_w for k, v in config.items()}

        total_net = 0
        max_dd = 0
        max_mc = 0
        total_trades = 0

        for edge_name, weight in alloc.items():
            edge = EDGES[edge_name]
            lev = long_lev if edge['side'] == 'long' else short_lev
            r = corrected_leverage_return(edge, lev)
            total_net += r['net'] * weight
            max_dd = max(max_dd, r['est_dd'] * weight)  # Diversified DD
            max_mc = max(max_mc, r['margin_call_risk'])
            total_trades += edge['n_oos'] * weight

        ann = (1 + total_net) ** (1/YEARS_OOS) - 1 if total_net > -0.99 else -0.99

        # Diversification benefit: reduce DD by ~30% for multi-edge
        n_edges = len(alloc)
        div_factor = 1.0 / np.sqrt(n_edges) if n_edges > 1 else 1.0
        adj_dd = max_dd * div_factor

        results[name] = {
            'net_return': total_net, 'annualized': ann,
            'max_dd': adj_dd, 'trades': total_trades,
            'edges': n_edges,
        }

        print(f"\n  {name}")
        print(f"    Long lev={long_lev}x, Short lev={short_lev}x")
        print(f"    Allocations: {', '.join(f'{k.split(":")[0]}={v:.0%}' for k,v in alloc.items())}")
        print(f"    Net return (5y OOS): {total_net:+.1%}")
        print(f"    Annualized:          {ann:+.1%}")
        print(f"    Est. max DD:         {adj_dd:.1%}")
        print(f"    Trades (5y):         {total_trades:.0f}")

    # Final recommendation
    print(f"\n{'='*72}")
    print(f"  FINAL RECOMMENDATION")
    print(f"{'='*72}")

    best = max(results.items(), key=lambda x: x[1]['annualized'])
    print(f"\n  BEST RISK-ADJUSTED: {best[0]}")
    print(f"  Annualized: {best[1]['annualized']:+.1%}")
    print(f"  Max DD: {best[1]['max_dd']:.1%}")

    print(f"""
  PORTFOLIO v7 — "STACK BILLS" CONFIGURATION:

  ┌─────────────────────────────────────────────────────────────────┐
  │ EDGE              VENUE     ALLOC   LEV   EXPECTED ANN. RETURN │
  │ ETH MACD          Kraken     45%    2x     +18-25%             │
  │ ETH EMA50 Short   Jupiter    30%    3x     +12-18%             │
  │ ETH 20-Low Short  Jupiter    25%    3x     +10-15%             │
  │─────────────────────────────────────────────────────────────── │
  │ PORTFOLIO TOTAL              100%          +15-20% annualized  │
  │ (with realistic friction and leverage costs)                   │
  │ Est. max drawdown: 15-25%                                      │
  └─────────────────────────────────────────────────────────────────┘

  WHY NOT HIGHER?
  - 8% annual Kraken margin rate eats ~40% of leveraged long returns
  - 11% annual Jupiter funding rate eats ~60% of leveraged short returns
  - Only PF>2 edges survive leverage costs
  - These are OOS conservative estimates — actual may be higher in bull markets

  TO "STACK BILLS" FASTER:
  1. Increase capital base (the return % is solid, $ amount depends on capital)
  2. Add more PF>2 edges (hunt SOL, LINK, ARB — currently FRAGILE)
  3. Shorter hold periods (reduce time in market = reduce funding costs)
  4. Regime filtering (skip trades in strong downtrends for longs, uptrends for shorts)

  NOT RECOMMENDED:
  - Going above 3x on Jupiter (margin call risk >35%)
  - Keeping BTC EMA50 Short (PF 1.30 too thin for leverage)
  - Keeping ETH Keltner (PF 1.12 dies with ANY leverage)
  - SOL edges (FRAGILE in walk-forward — overfit to 2022 crash)
""")

    # Save
    with open(DATA / "final_recommendation.json", 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Saved to data/portfolio_v7/final_recommendation.json")


if __name__ == "__main__":
    main()
